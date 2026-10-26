"""Re-run the LLM judge on stored your_data answers after a rubric change (see evals/CHANGELOG.md).

Each verdict goes through the same Conductor workflow as the benchmark (ml4_call_model, route openai_chat,
GPT-6 Astra). Results files are backed up as results.jsonl.pre-rejudge before they're updated.

Usage: rejudge.py <item_id>[,<item_id>...] <run_id> [<run_id> ...]"""
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workers"))
import bench  # noqa: E402
from conductor_api import Conductor  # noqa: E402
from configs import JUDGE  # noqa: E402

items = set(sys.argv[1].split(","))
runs = sys.argv[2:]
c = Conductor()


def judge(row):
    req = bench.prepare_judge(row["item_id"], row["answer"], JUDGE)
    wid = c.start("ml4_call_model", {"route": "openai_chat", "request": req}, correlation_id=f"rejudge-{row['run_id']}")
    ex = c.wait(wid, timeout=600, poll=3)
    result = (ex.get("output") or {}).get("result") or {}
    new = bench.score(row["item_id"], {"ok": True, "text": row["answer"]}, None, None, None, result)
    return row, new, wid


for rid in runs:
    p = ROOT / "results" / rid / "results.jsonl"
    backup = p.with_suffix(".jsonl.pre-rejudge")
    if not backup.exists():
        shutil.copy(p, backup)
    rows = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    targets = [r for r in rows if r["item_id"] in items and r["api_ok"]]
    with ThreadPoolExecutor(8) as ex:
        done = list(ex.map(judge, targets))
    changed = 0
    for row, new, wid in done:
        if bool(new["pass"]) != bool(row["pass"]):
            changed += 1
        row["pass"], row["score"], row["detail"] = bool(new["pass"]), new["score"], new["detail"]
        row["rejudged"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "judge_workflow_id": wid}
        print(f"{rid} {row['item_id']} {row['config_id']:9} pass={row['pass']}")
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with open(ROOT / "results" / rid / "notes.md", "a") as f:
        f.write(f"- re-judged {sorted(items)} after the rubric fix in evals/CHANGELOG.md; {changed} result(s) changed. "
                f"Pre-rejudge file kept as results.jsonl.pre-rejudge.\n")
    print(rid, "changed:", changed)
