"""Verify evals/coding.jsonl.

For every item:
- schema checks (fields, ids, prompt ending, entrypoint, 8-20 asserts with one assert per line, stdlib-only imports)
- reference_solution + tests runs in a fresh Python subprocess within the item timeout and exits 0 (twice, for determinism)
- the same check with each assert wrapped separately, so per-assert counting works and every assert passes
- a stored plausible-but-wrong variant + tests must FAIL (non-zero exit or timeout)

Run with Python 3.13: /opt/homebrew/bin/python3.13 evals/verify/verify_coding.py
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE = HERE.parent / "coding.jsonl"
PYTHON = sys.executable
ENDING = "Return only the complete function (plus any imports or helpers it needs) in a single python code block."
REQUIRED = ("id", "category", "title", "prompt", "scoring", "difficulty", "provenance", "reference_solution")

# Plausible-but-wrong variants. "replace" edits the reference solution (each old string must be present);
# "code" is a full replacement implementation.
WRONG = {
    "coding-001": {"why": "months counted as 31 days",
                   "replace": [("30 * 86400", "31 * 86400")]},
    "coding-002": {"why": "numeric pre-release identifiers compared as strings",
                   "replace": [("return -1 if int(x) < int(y) else 1", "return -1 if x < y else 1")]},
    "coding-003": {"why": "touching intervals not merged",
                   "replace": [("if merged and start <= merged[-1][1]:", "if merged and start < merged[-1][1]:")]},
    "coding-004": {"why": "day-of-month AND day-of-week instead of OR",
                   "replace": [("ok = dom_ok or dow_ok", "ok = dom_ok and dow_ok")]},
    "coding-005": {"why": "lenient csv module",
                   "code": r'''
import csv


def parse_csv_line(line: str, delimiter: str = ",") -> list[str]:
    if len(delimiter) != 1 or delimiter == '"':
        raise ValueError("bad delimiter")
    rows = list(csv.reader([line], delimiter=delimiter))
    return rows[0] if rows else [""]
'''},
    "coding-006": {"why": "~0 decoded before ~1",
                   "replace": [('.replace("~1", "/").replace("~0", "~")', '.replace("~0", "~").replace("~1", "/")')]},
    "coding-007": {"why": "fnmatch semantics (* crosses /, no ^ negation, no escapes)",
                   "code": r'''
import fnmatch


def glob_match(pattern: str, name: str) -> bool:
    return fnmatch.fnmatchcase(name, pattern)
'''},
    "coding-008": {"why": "removal blocks that contain the remaining piece are ignored",
                   "replace": [("            if p.subnet_of(r):\n                continue\n", "")]},
    "coding-009": {"why": "left-associative ** with an atom exponent",
                   "replace": [('if peek() == ("op", "**"):', 'while peek() == ("op", "**"):'),
                               ("exponent = parse_unary()", "exponent = parse_atom()"),
                               ("return base ** int(exponent)", "base = base ** int(exponent)")]},
    "coding-010": {"why": "unrestricted Damerau-Levenshtein instead of OSA",
                   "code": r'''
def osa_distance(a: str, b: str) -> int:
    inf = len(a) + len(b)
    d = [[0] * (len(b) + 2) for _ in range(len(a) + 2)]
    d[0][0] = inf
    for i in range(len(a) + 1):
        d[i + 1][0] = inf
        d[i + 1][1] = i
    for j in range(len(b) + 1):
        d[0][j + 1] = inf
        d[1][j + 1] = j
    last_row = {}
    for i in range(1, len(a) + 1):
        last_col = 0
        for j in range(1, len(b) + 1):
            k = last_row.get(b[j - 1], 0)
            l = last_col
            if a[i - 1] == b[j - 1]:
                cost = 0
                last_col = j
            else:
                cost = 1
            d[i + 1][j + 1] = min(d[i][j] + cost, d[i + 1][j] + 1, d[i][j + 1] + 1,
                                  d[k][l] + (i - k - 1) + 1 + (j - l - 1))
        last_row[a[i - 1]] = i
    return d[len(a) + 1][len(b) + 1]
'''},
    "coding-011": {"why": "days == 0 returns start even on a weekend",
                   "replace": [("        while not is_business(current):\n            current += timedelta(days=1)\n"
                                "        return current.isoformat()", "        return current.isoformat()")]},
    "coding-012": {"why": "bucket starts empty",
                   "replace": [("tokens = full", "tokens = Fraction(0)")]},
    "coding-013": {"why": "FIFO Kahn order instead of smallest available node",
                   "replace": [("heapq.heapify(heap)", "pass"),
                               ("heapq.heappop(heap)", "heap.pop(0)"),
                               ("heapq.heappush(heap, m)", "heap.append(m)")]},
    "coding-014": {"why": "textwrap.wrap fills the current line with part of a long word",
                   "code": r'''
import textwrap


def wrap_text(text: str, width: int) -> list[str]:
    if width < 1:
        raise ValueError("width must be >= 1")
    return textwrap.wrap(text, width)
'''},
    "coding-015": {"why": "plain string prefix match without the '-' boundary",
                   "replace": [('elif lowered == rng or lowered.startswith(rng + "-"):', "elif lowered.startswith(rng):")]},
    "coding-016": {"why": "case-sensitive comparison of non-digit runs",
                   "replace": [("xl, yl = x.lower(), y.lower()", "xl, yl = x, y")]},
    "coding-017": {"why": "plain LRU eviction (ignores use counts)",
                   "replace": [("victim = min(store, key=lambda k: (store[k][1], store[k][2]))",
                                "victim = min(store, key=lambda k: store[k][2])")]},
    "coding-018": {"why": "quote-aware split that ignores comments",
                   "code": r'''
def split_sql(script: str) -> list[str]:
    statements, buf = [], []
    quote = None
    i = 0
    while i < len(script):
        c = script[i]
        if quote:
            buf.append(c)
            if c == quote:
                if i + 1 < len(script) and script[i + 1] == quote:
                    buf.append(quote)
                    i += 2
                    continue
                quote = None
        elif c in "'\"":
            quote = c
            buf.append(c)
        elif c == ";":
            text = "".join(buf).strip()
            if text:
                statements.append(text)
            buf = []
        else:
            buf.append(c)
        i += 1
    if quote:
        raise ValueError("unterminated quoted text")
    text = "".join(buf).strip()
    if text:
        statements.append(text)
    return statements
'''},
    "coding-019": {"why": "free time measured from the previous interval's end, not the latest busy end",
                   "replace": [("        if b <= t:\n            continue\n", ""),
                               ("t = max(t, b)", "t = max(start, b)")]},
    "coding-020": {"why": "binary float rounding",
                   "replace": [("value = Decimal(amount).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_EVEN)",
                                "value = float(amount)")]},
}


def run(code, timeout):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "case.py"
        path.write_text(code)
        try:
            p = subprocess.run([PYTHON, "-I", str(path)], cwd=tmp, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, "timeout"
        return p.returncode, (p.stderr or p.stdout)[-600:]


def per_assert_script(code, tests):
    """Wrap each top-level assert line separately and print passed/total."""
    out = [code, "", "_passed = 0", "_total = 0"]
    for line in tests.splitlines():
        if line.startswith("assert "):
            out += ["_total += 1", "try:", "    " + line, "    _passed += 1", "except Exception:", "    pass"]
        else:
            out.append(line)
    out.append('print(f"{_passed}/{_total}")')
    return "\n".join(out) + "\n"


def imports_ok(src):
    mods = re.findall(r"^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))", src, re.M)
    return all((a or b).split(".")[0] in sys.stdlib_module_names for a, b in mods)


def check(item, n):
    errors = []
    iid = item.get("id", "?")
    for k in REQUIRED:
        if k not in item:
            errors.append(f"missing field {k}")
    if errors:
        return errors
    if iid != f"coding-{n:03d}":
        errors.append(f"id {iid} out of sequence")
    if item["category"] != "coding":
        errors.append("category must be coding")
    if len(item["title"]) > 60:
        errors.append("title longer than 60 chars")
    if item["difficulty"] not in ("easy", "medium", "hard"):
        errors.append("bad difficulty")
    sc = item["scoring"]
    if sc.get("type") != "unit_tests":
        errors.append("scoring.type must be unit_tests")
    entry, tests, timeout = sc.get("entrypoint"), sc.get("tests", ""), sc.get("timeout_s")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        errors.append("bad timeout_s")
        timeout = 10
    if not item["prompt"].endswith(ENDING):
        errors.append("prompt does not end with the required sentence")
    if f"`{entry}(" not in item["prompt"]:
        errors.append("prompt does not name the entrypoint with its signature")
    if not re.search(rf"^def {re.escape(entry)}\(", item["reference_solution"], re.M):
        errors.append("reference_solution does not define the entrypoint")
    assert_lines = [ln for ln in tests.splitlines() if re.search(r"\bassert\b", ln)]
    if any(not ln.startswith("assert ") for ln in assert_lines):
        errors.append("every assert must start a line at column 0")
    if not 8 <= len(assert_lines) <= 20:
        errors.append(f"{len(assert_lines)} asserts (need 8-20)")
    if any(ln[len('assert '):].strip() in item["prompt"] for ln in assert_lines):
        errors.append("a test assert appears verbatim in the prompt")
    if not imports_ok(tests) or not imports_ok(item["reference_solution"]):
        errors.append("non-stdlib import")
    if re.search(r"\b(open|input)\(|socket|urllib|requests", tests):
        errors.append("tests must not do I/O")

    full = item["reference_solution"] + "\n\n" + tests
    for attempt in (1, 2):
        rc, out = run(full, timeout)
        if rc != 0:
            errors.append(f"reference run {attempt} failed ({rc}): {out}")
            break
    rc, out = run(per_assert_script(item["reference_solution"], tests), timeout)
    counts = out.strip().splitlines()[-1] if rc == 0 and out.strip() else out
    if rc != 0 or counts != f"{len(assert_lines)}/{len(assert_lines)}":
        errors.append(f"per-assert run: {counts}")

    wrong = WRONG.get(iid)
    if not wrong:
        errors.append("no wrong variant stored")
    else:
        if "code" in wrong:
            code = wrong["code"]
        else:
            code = item["reference_solution"]
            for old, new in wrong["replace"]:
                if old not in code:
                    errors.append(f"wrong-variant edit not applicable: {old!r}")
                code = code.replace(old, new)
        rc, out = run(code + "\n\n" + tests, timeout)
        if rc == 0:
            errors.append(f"tests did not catch the wrong variant ({wrong['why']})")
        wrong["result"] = "timeout" if rc is None else f"exit {rc}"
    return errors


def main():
    items = [json.loads(line) for line in FILE.read_text().splitlines() if line.strip()]
    failures = 0
    if len(items) != 20:
        print(f"expected 20 items, found {len(items)}")
        failures += 1
    if len({it.get("id") for it in items}) != len(items):
        print("duplicate ids")
        failures += 1
    for n, item in enumerate(items, 1):
        errs = check(item, n)
        iid = item.get("id", f"#{n}")
        if errs:
            failures += 1
            print(f"FAIL {iid}: " + " | ".join(errs))
        else:
            asserts = sum(1 for ln in item["scoring"]["tests"].splitlines() if ln.startswith("assert "))
            w = WRONG[iid]
            print(f"ok   {iid} {item['title']:<48} {asserts:2d} asserts  wrong variant caught "
                  f"({w['why']}; {w['result']})")
    print(f"\n{len(items) - failures if failures <= len(items) else 0}/{len(items)} items verified")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
