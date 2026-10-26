"""Programmatic scoring rules from evals/SCHEMA.md, plus the judge prompt and code sandbox."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from fractions import Fraction
from pathlib import Path

ANSWER_RE = re.compile(r"^\s*(?:[*_`>#\s]*)ANSWER\s*[:：]\s*(.+?)\s*$", re.I | re.M)


def final_answer_line(text):
    """Last 'ANSWER: ...' line, with markdown emphasis/backticks/quotes stripped."""
    m = ANSWER_RE.findall(text or "")
    if not m:
        return None
    ans = m[-1]
    ans = re.sub(r"[*_`]", "", ans).strip()
    ans = ans.strip(" '\"“”‘’").rstrip(".").strip()
    return ans


def _collapse(s):
    return re.sub(r"\s+", " ", s or "").strip().casefold()


def _num(s):
    s = re.sub(r"[,\s$%]", "", s or "")
    s = s.replace("−", "-")
    try:
        return Fraction(s)
    except (ValueError, ZeroDivisionError):
        m = re.search(r"-?\d+(?:\.\d+)?(?:/\d+)?", s)
        if not m:
            return None
        try:
            return Fraction(m.group(0))
        except (ValueError, ZeroDivisionError):
            return None


def _items(s):
    return [_collapse(x) for x in (s or "").split(",") if x.strip()]


def match_final(scoring, ans):
    if ans is None:
        return False
    mode = scoring.get("match", "exact_ci")
    expected = scoring.get("answer", "")
    accept = [expected] + list(scoring.get("accept") or [])
    if mode == "number":
        got = _num(ans)
        return got is not None and any(got == _num(a) for a in accept)
    if mode == "exact_ci":
        return any(_collapse(ans) == _collapse(a) for a in accept)
    if mode == "set":
        return any(sorted(_items(ans)) == sorted(_items(a)) for a in accept)
    if mode == "sequence":
        return any(_items(ans) == _items(a) for a in accept)
    if mode == "regex":
        return re.search(scoring["pattern"], ans, re.I) is not None
    raise ValueError(f"unknown match {mode}")


def score_final_answer(scoring, text):
    ans = final_answer_line(text)
    ok = match_final(scoring, ans)
    return {"pass": ok, "score": 1.0 if ok else 0.0, "extracted": ans, "expected": scoring.get("answer"),
            "answer_line_found": ans is not None}


DOMAIN_RE = re.compile(
    r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:com|org|net|gov|edu|int|io|ai|co|uk|de|fr|eu|info|news|tv|us|ca|au)\b"
    r"(?:/[\w./%-]*)?", re.I)


def names_a_source(text):
    """True when the answer itself points at a source: a URL, a website domain (e.g. 'usopen.org'), or a
    provider reference link such as Mistral's 'search-result://FH7lpTBD' to a retrieved search result."""
    t = text or ""
    return bool(re.search(r"\b[a-z][a-z0-9+.-]*://\S+", t, re.I) or DOMAIN_RE.search(t))


def score_grounded(scoring, text, citations):
    ans = final_answer_line(text)
    target = ans if ans is not None else (text or "")
    misses = [p for p in scoring.get("patterns", []) if not re.search(p, target, re.I)]
    # cited = structured references from the API, or a URL / website named in the answer text
    cited = bool(citations) or names_a_source(text)
    ok = not misses and (cited or not scoring.get("require_citation"))
    return {"pass": ok, "score": 1.0 if ok else 0.0, "extracted": ans, "expected": scoring.get("answer"),
            "answer_line_found": ans is not None, "pattern_misses": misses, "cited": cited,
            "citation_count": len(citations or [])}


_NOT_IN_DOC = re.compile(
    r"(not|n't)\s+(?:\w+\s+){0,4}(mention|specif|cover|state|say|contain|include|address|provide|list|describe|document)"
    r"|no (information|mention|details?|guidance|section|policy)"
    r"|(isn't|is not|aren't|are not) (in|covered|addressed|specified|documented)"
    r"|doesn't (say|specify|cover|mention)|does not (say|specify|cover|mention)|silent on"
    r"|outside (the )?(scope|document)", re.I)


def _fact_present(fact, text):
    if fact.startswith("re:"):
        return re.search(fact[3:], text or "", re.I) is not None
    return fact.casefold() in (text or "").casefold()


def score_doc_qa_programmatic(scoring, text):
    if scoring.get("answerable", True):
        missing = [f for f in scoring.get("key_facts", []) if not _fact_present(f, text)]
        return {"pass": not missing, "missing_facts": missing}
    said_absent = bool(_NOT_IN_DOC.search(text or ""))
    return {"pass": said_absent, "said_not_in_doc": said_absent}


JUDGE_SYSTEM = (
    "You are a strict, impartial grader for questions answered from an internal document. "
    "You never see which model wrote the answer. Grade only against the document, the reference answer "
    "and the rubric. Respond with a JSON object only."
)


def judge_messages(doc_text, item, candidate_text):
    s = item["scoring"]
    user = (
        "Grade the candidate answer. Return JSON with keys: "
        "\"correct\" (bool: matches the reference answer and rubric), "
        "\"faithful\" (bool: every factual claim is supported by the document; for unanswerable questions, "
        "the answer must say the document does not cover it and must not invent a policy), "
        "\"score\" (integer 1-5), \"hallucinations\" (list of unsupported claims, may be empty), "
        "\"reason\" (one sentence).\n\n"
        f"<document>\n{doc_text}\n</document>\n\n"
        f"<question>\n{item['prompt']}\n</question>\n\n"
        f"<answerable>{str(s.get('answerable', True)).lower()}</answerable>\n"
        f"<reference_answer>\n{s.get('answer', '')}\n</reference_answer>\n"
        f"<rubric>\n{s.get('judge_rubric', '')}\n</rubric>\n\n"
        f"<candidate_answer>\n{candidate_text}\n</candidate_answer>\n\nReturn the JSON object now."
    )
    return [{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": user}]


def parse_judge(text):
    try:
        m = re.search(r"\{.*\}", text or "", re.S)
        v = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        v = {}
    return {"correct": bool(v.get("correct")), "faithful": bool(v.get("faithful")),
            "score": v.get("score"), "hallucinations": v.get("hallucinations") or [],
            "reason": v.get("reason"), "parsed": bool(v)}


# ---------------------------------------------------------------- code sandbox

CODE_BLOCK = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S | re.I)

RUNNER = r'''
import ast, json
ns = {"__name__": "candidate"}
out = {"loaded": False, "passed": 0, "total": 0, "failures": []}
try:
    exec(compile(open("/work/solution.py").read(), "solution.py", "exec"), ns)
    out["loaded"] = True
except BaseException as e:
    out["load_error"] = f"{type(e).__name__}: {e}"[:500]
if out["loaded"]:
    src = open("/work/tests.py").read()
    for node in ast.parse(src).body:          # one top-level statement at a time
        is_assert = isinstance(node, ast.Assert)
        if is_assert:
            out["total"] += 1
        try:
            exec(compile(ast.Module(body=[node], type_ignores=[]), f"tests.py:{node.lineno}", "exec"), ns)
            if is_assert:
                out["passed"] += 1
        except BaseException as e:
            seg = (ast.get_source_segment(src, node) or "")[:160]
            key = "error" if is_assert else "setup_error"
            out["failures"].append({"line": node.lineno, "test": seg, key: f"{type(e).__name__}: {e}"[:200]})
print("__RESULT__" + json.dumps(out))
'''

RD_BIN, RD_SOCK = os.path.expanduser("~/.rd/bin"), os.path.expanduser("~/.rd/docker.sock")  # Rancher Desktop
DOCKER = shutil.which("docker") or os.path.join(RD_BIN, "docker")
DOCKER_ENV = {**os.environ, "PATH": RD_BIN + ":" + os.environ.get("PATH", "")}
if "DOCKER_HOST" not in os.environ and os.path.exists(RD_SOCK):
    DOCKER_ENV["DOCKER_HOST"] = "unix://" + RD_SOCK
SANDBOX_IMAGE = "python:3.13-slim"


def extract_code(text):
    blocks = CODE_BLOCK.findall(text or "")
    if blocks:
        # prefer the longest block that defines something
        defs = [b for b in blocks if re.search(r"^\s*(def|class|import|from)\s", b, re.M)]
        return max(defs or blocks, key=len)
    if re.search(r"^\s*def\s", text or "", re.M):
        return text
    return None


def run_unit_tests(model_text, tests, timeout_s=10):
    code = extract_code(model_text)
    if code is None:
        return {"pass": False, "score": 0.0, "passed": 0, "total": tests.count("assert"), "error": "no code block found"}
    tmp = Path(tempfile.mkdtemp(prefix="ml4code_"))
    try:
        (tmp / "solution.py").write_text(code)
        (tmp / "tests.py").write_text(tests)
        (tmp / "runner.py").write_text(RUNNER)
        name = "ml4sbx_" + uuid.uuid4().hex[:10]
        cmd = [DOCKER, "run", "--rm", "--name", name, "--network", "none", "--memory", "256m", "--cpus", "0.5",
               "--pids-limit", "64", "--read-only", "--tmpfs", "/tmp:size=16m", "-v", f"{tmp}:/work:ro",
               SANDBOX_IMAGE, "timeout", "-s", "KILL", str(int(timeout_s)), "python", "-I", "/work/runner.py"]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s + 30, env=DOCKER_ENV)
        except subprocess.TimeoutExpired:
            subprocess.run([DOCKER, "rm", "-f", name], capture_output=True, env=DOCKER_ENV)
            return {"pass": False, "score": 0.0, "passed": 0, "total": tests.count("assert"), "error": "timeout"}
        m = re.search(r"__RESULT__(\{.*\})", p.stdout)
        if not m and p.returncode == 137:
            return {"pass": False, "score": 0.0, "passed": 0, "total": tests.count("assert"), "error": "timeout"}
        if not m:
            return {"pass": False, "score": 0.0, "passed": 0, "total": tests.count("assert"),
                    "error": ("no result; " + (p.stderr or p.stdout)[-400:]).strip()}
        r = json.loads(m.group(1))
        total = r["total"] or 1
        ok = r["loaded"] and r["passed"] == r["total"] and r["total"] > 0 and not any("setup_error" in f for f in r["failures"])
        return {"pass": ok, "score": round(r["passed"] / total, 4), "passed": r["passed"], "total": r["total"],
                "load_error": r.get("load_error"), "failures": r["failures"][:5]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
