"""Benchmark logic used by the Conductor workers (plain functions, testable offline)."""
import json
import os
import statistics
import threading
import time
from collections import defaultdict
from pathlib import Path

import requests

import agentic_env
import model_io
import scoring

ROOT = Path(__file__).resolve().parent.parent
CATEGORY_MODE = {"reasoning": "chat", "coding": "chat", "your_data": "chat", "agentic": "agentic", "grounding": "search"}

DOC_SYSTEM = (
    "You answer employees' questions using only the internal document below. "
    "If the document does not contain the answer, say clearly that the document doesn't cover it; "
    "do not guess or fill gaps from general knowledge. Be concise.\n\n<document>\n{doc}\n</document>"
)

# ------------------------------------------------------------------ dataset


class Dataset:
    """Eval items from a local folder (default: ./evals) or an http(s) base URL."""
    _cache = {}

    def __init__(self, location=None):
        self.location = location or str(ROOT / "evals")

    def _read(self, rel):
        loc = self.location
        if loc.startswith("http://") or loc.startswith("https://"):
            r = requests.get(loc.rstrip("/") + "/" + rel, timeout=30)
            r.raise_for_status()
            return r.text
        p = Path(os.path.expanduser(loc))
        if not p.is_absolute():
            p = ROOT / p
        return (p / rel).read_text()

    def items(self, categories=None):
        key = (self.location, tuple(categories or []))
        if key not in Dataset._cache:
            out = []
            for cat in categories or ["reasoning", "coding", "agentic", "grounding", "your_data"]:
                try:
                    txt = self._read(f"{cat}.jsonl")
                except (FileNotFoundError, requests.HTTPError):
                    continue
                out += [json.loads(line) for line in txt.splitlines() if line.strip()]
            Dataset._cache[key] = out
        return Dataset._cache[key]

    def item(self, item_id):
        cat = item_id.rsplit("-", 1)[0]
        for it in self.items([cat]):
            if it["id"] == item_id:
                return it
        raise KeyError(item_id)

    def doc(self, name):
        return self._read(f"your_data/{name}")


# ------------------------------------------------------------------ run planning

def prepare_run(dataset=None, categories=None, item_ids=None, repeats=1, batch_size=6, limit_per_category=None):
    ds = Dataset(dataset)
    items = ds.items(categories)
    if item_ids:
        wanted = set(item_ids)
        items = [i for i in items if i["id"] in wanted]
    if limit_per_category:
        seen = defaultdict(int)
        kept = []
        for i in items:
            if seen[i["category"]] < int(limit_per_category):
                kept.append(i)
                seen[i["category"]] += 1
        items = kept
    units = [{"item_id": i["id"], "repeat": r} for r in range(1, int(repeats) + 1) for i in items]
    batches = [units[k:k + int(batch_size)] for k in range(0, len(units), int(batch_size))]
    return {"item_count": len(items), "unit_count": len(units), "batch_count": len(batches), "batches": batches,
            "categories": sorted({i["category"] for i in items})}


def plan_item_fork(item_id, repeat, configs, dataset, run_id):
    """Dynamic fork: one ml4_eval_one sub-workflow per model config."""
    tasks, inputs = [], {}
    for cfg in configs:
        ref = f"eval_{cfg['id']}"
        tasks.append({"name": "ml4_eval_one", "taskReferenceName": ref, "type": "SUB_WORKFLOW",
                      "subWorkflowParam": {"name": "ml4_eval_one", "version": 1}})
        inputs[ref] = {"item_id": item_id, "repeat": repeat, "config": cfg, "dataset": dataset, "run_id": run_id}
    return {"tasks": tasks, "inputs": inputs}


def plan_batch_fork(batch, configs, dataset, run_id):
    """Dynamic fork: one ml4_bench_item sub-workflow per (item, repeat) in the batch."""
    tasks, inputs = [], {}
    for u in batch:
        ref = f"item_{u['item_id'].replace('-', '_')}_r{u['repeat']}"
        tasks.append({"name": "ml4_bench_item", "taskReferenceName": ref, "type": "SUB_WORKFLOW",
                      "subWorkflowParam": {"name": "ml4_bench_item", "version": 1}})
        inputs[ref] = {"item_id": u["item_id"], "repeat": u["repeat"], "configs": configs, "dataset": dataset,
                       "run_id": run_id}
    return {"tasks": tasks, "inputs": inputs}


# ------------------------------------------------------------------ one eval

def _initial_messages(ds, item):
    msgs = []
    if item["category"] == "your_data":
        msgs.append({"role": "system", "content": DOC_SYSTEM.format(doc=ds.doc(item["doc"]))})
    elif item.get("system"):
        msgs.append({"role": "system", "content": item["system"]})
    msgs.append({"role": "user", "content": item["prompt"]})
    return msgs


def prepare_eval(item_id, config, dataset=None):
    ds = Dataset(dataset)
    item = ds.item(item_id)
    mode = CATEGORY_MODE[item["category"]]
    route = model_io.route_for(config, mode)
    msgs = _initial_messages(ds, item)
    max_tokens = config.get("max_tokens_search", 8000) if mode == "search" else config.get("max_tokens", 32000)
    tools = item.get("tools") if mode == "agentic" else None
    req = model_io.build_request(route, config["model"], msgs, reasoning_effort=config.get("reasoning_effort"),
                                 max_tokens=max_tokens, tools=tools)
    out = {"category": item["category"], "mode": mode, "route": route, "request": req, "title": item.get("title"),
           "difficulty": item.get("difficulty")}
    if mode == "agentic":
        out["agent_state"] = {"messages": msgs, "calls": [], "turns": 0, "done": False, "final_text": "",
                              "max_turns": item["scoring"].get("max_turns", 8), "errors": [],
                              "usage": _zero_usage(), "latency_ms": 0, "steps": []}
    return out


def _zero_usage():
    return {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "cached_input_tokens": 0,
            "search_calls": 0, "search_tokens": 0}


def _add_usage(total, u):
    for k in total:
        total[k] += (u or {}).get(k) or 0
    return total


def agent_step(item_id, config, route, state, result, dataset=None):
    """Execute the model's tool calls against the scenario environment and build the next request."""
    ds = Dataset(dataset)
    item = ds.item(item_id)
    state = json.loads(json.dumps(state))  # detach from the task payload
    state["turns"] += 1
    state["usage"] = _add_usage(state.get("usage") or _zero_usage(), result.get("usage"))
    state["latency_ms"] = (state.get("latency_ms") or 0) + (result.get("latency_ms") or 0)
    step = {"turn": state["turns"], "latency_ms": result.get("latency_ms"), "tool_calls": [],
            "usage": result.get("usage")}
    if not result.get("ok"):
        state["errors"].append(result.get("error"))
        state["done"] = True
        state["steps"].append(step)
        return {"state": state, "done": True, "request": None}
    calls = result.get("tool_calls") or []
    if not calls:
        state["final_text"] = result.get("text") or ""
        state["done"] = True
        state["steps"].append(step)
        return {"state": state, "done": True, "request": None}
    if route == "openai_agent":
        state["messages"].extend(result["assistant_message"]["items"])
    else:
        state["messages"].append(result["assistant_message"])
    for tc in calls:
        r = agentic_env.run_tool(item["environment"], tc["name"], tc["arguments"])
        state["calls"].append({"tool": tc["name"], "args": tc["arguments"]})
        step["tool_calls"].append({"tool": tc["name"], "args": tc["arguments"], "result": r["result"]})
        if route == "openai_agent":
            msg = {"type": "function_call_output", "call_id": tc["id"], "output": json.dumps(r["result"])}
        else:
            msg = {"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(r["result"])}
            if config["provider"] == "mistral":
                msg["name"] = tc["name"]
        state["messages"].append(msg)
    state["steps"].append(step)
    if state["turns"] >= state["max_turns"]:
        state["done"] = True
        state["final_text"] = result.get("text") or ""
        return {"state": state, "done": True, "request": None}
    req = model_io.build_request(route, config["model"], state["messages"],
                                 reasoning_effort=config.get("reasoning_effort"),
                                 max_tokens=config.get("max_tokens", 32000), tools=item.get("tools"))
    return {"state": state, "done": False, "request": req}


def prepare_judge(item_id, candidate_text, judge, dataset=None):
    ds = Dataset(dataset)
    item = ds.item(item_id)
    msgs = scoring.judge_messages(ds.doc(item["doc"]), item, candidate_text or "")
    return model_io.build_request("openai_chat", judge["model"], msgs, reasoning_effort=judge.get("reasoning_effort"),
                                  max_tokens=judge.get("max_tokens", 4000), response_format={"type": "json_object"})


def run_code(item_id, result, dataset=None):
    item = Dataset(dataset).item(item_id)
    s = item["scoring"]
    return scoring.run_unit_tests(result.get("text") or "", s["tests"], s.get("timeout_s", 10))


def score(item_id, result, dataset=None, code_result=None, agent_state=None, judge_result=None):
    item = Dataset(dataset).item(item_id)
    s = item["scoring"]
    t = s["type"]
    if t == "agentic_trace":
        st = agent_state or {}
        tr = agentic_env.score_trace(s, st.get("calls", []), st.get("final_text", ""), st.get("turns", 0))
        ok = bool(tr["pass"]) and not st.get("errors")
        return {"pass": ok, "score": 1.0 if ok else 0.0, "detail": tr, "errors": st.get("errors")}
    if not (result or {}).get("ok"):
        return {"pass": False, "score": 0.0, "detail": {"error": (result or {}).get("error")}}
    text = result.get("text") or ""
    if t == "final_answer":
        d = scoring.score_final_answer(s, text)
    elif t == "grounded_answer":
        d = scoring.score_grounded(s, text, result.get("citations"))
    elif t == "unit_tests":
        d = code_result or {"pass": False, "score": 0.0, "error": "no code result"}
    elif t == "doc_qa":
        prog = scoring.score_doc_qa_programmatic(s, text)
        jr = scoring.parse_judge((judge_result or {}).get("text")) if judge_result and judge_result.get("ok") else None
        judge_pass = bool(jr and jr["correct"] and jr["faithful"])
        d = {"pass": judge_pass if jr and jr["parsed"] else prog["pass"], "programmatic": prog, "judge": jr,
             "judge_usage": (judge_result or {}).get("usage")}
        d["score"] = 1.0 if d["pass"] else 0.0
    else:
        raise ValueError(t)
    return {"pass": bool(d.get("pass")), "score": d.get("score", 1.0 if d.get("pass") else 0.0), "detail": d}


# ------------------------------------------------------------------ recording

_lock = threading.Lock()


def record(run_id, item_id, repeat, config, category, result, score_out, agent_state=None, workflow_id=None,
           parent_workflow_id=None, title=None, difficulty=None):
    if agent_state:
        usage, latency, turns = agent_state.get("usage"), agent_state.get("latency_ms"), agent_state.get("turns")
        text = agent_state.get("final_text", "")
        ok = not agent_state.get("errors")
        err = "; ".join(e for e in agent_state.get("errors") or [] if e) or None
    else:
        usage, latency, turns = (result or {}).get("usage"), (result or {}).get("latency_ms"), 1
        text, ok, err = (result or {}).get("text", ""), (result or {}).get("ok"), (result or {}).get("error")
    rec = {
        "run_id": run_id, "item_id": item_id, "category": category, "title": title, "difficulty": difficulty,
        "repeat": repeat, "config_id": config["id"], "config_label": config.get("label"),
        "model": config["model"], "reasoning_effort": config.get("reasoning_effort"),
        "pass": bool((score_out or {}).get("pass")), "score": (score_out or {}).get("score"),
        "api_ok": bool(ok), "error": err, "latency_ms": latency, "turns": turns,
        "retries": (result or {}).get("retries"), "usage": usage, "answer_chars": len(text or ""),
        "finish_reason": (result or {}).get("finish_reason"),
        "thinking_chars": (result or {}).get("thinking_chars"), "detail": (score_out or {}).get("detail"),
        "workflow_id": workflow_id, "parent_workflow_id": parent_workflow_id,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "answer": (text or "")[:4000],
    }
    out = ROOT / "results" / run_id
    out.mkdir(parents=True, exist_ok=True)
    with _lock, open(out / "results.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")
    return {k: rec[k] for k in ("item_id", "config_id", "repeat", "pass", "score", "latency_ms", "api_ok")} | {
        "output_tokens": (usage or {}).get("output_tokens"), "reasoning_tokens": (usage or {}).get("reasoning_tokens")}


def summarize(run_id):
    path = ROOT / "results" / run_id / "results.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    by = defaultdict(list)
    for r in rows:
        by[r["config_id"]].append(r)
    configs = {}
    for cid, rs in sorted(by.items()):
        lat = [r["latency_ms"] for r in rs if r.get("latency_ms")]
        outt = [(r.get("usage") or {}).get("output_tokens") or 0 for r in rs]
        rea = [(r.get("usage") or {}).get("reasoning_tokens") or 0 for r in rs]
        cats = defaultdict(list)
        for r in rs:
            cats[r["category"]].append(r["pass"])
        configs[cid] = {
            "label": rs[0].get("config_label"), "runs": len(rs), "pass_rate": round(sum(r["pass"] for r in rs) / len(rs), 3),
            "api_errors": sum(not r["api_ok"] for r in rs),
            "pass_rate_by_category": {c: round(sum(v) / len(v), 3) for c, v in sorted(cats.items())},
            "latency_ms_median": int(statistics.median(lat)) if lat else None,
            "latency_ms_p90": int(sorted(lat)[int(0.9 * (len(lat) - 1))]) if lat else None,
            "output_tokens_total": sum(outt), "reasoning_tokens_total": sum(rea),
            "output_tokens_median": int(statistics.median(outt)) if outt else None,
        }
    summary = {"run_id": run_id, "rows": len(rows), "configs": configs, "written": str(path.parent)}
    (path.parent / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary
