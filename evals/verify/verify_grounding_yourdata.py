"""Verify evals/grounding.jsonl and evals/your_data.jsonl against evals/SCHEMA.md.

Checks
- common fields, ids, categories, title length, difficulty values
- grounding: every `patterns` regex compiles and matches the canonical `answer`; prompt asks for sources and
  ends with an ANSWER format line; sources are URLs
- your_data: document exists, is marked fictional and is 2,500-5,000 words; answerable items' `key_facts`
  appear in the document (or are listed as computed in `verify.computed_facts`) and match the reference answer;
  `verify.doc_evidence` snippets appear in the document; `verify.calc` reproduces `verify.calc_result`;
  unanswerable items' `verify.absent_terms` do not appear in the document

Usage: python3 evals/verify/verify_grounding_yourdata.py   (exit code 0 = all checks pass)
"""
import json
import re
import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent.parent
DIFFICULTIES = {"easy", "medium", "hard"}
errors, warnings = [], []


def err(msg):
    errors.append(msg)


def load(name):
    path = EVALS / name
    items = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if line.strip():
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as e:
                err(f"{name}:{n}: invalid JSON ({e})")
    return items


def check_common(items, category, count):
    if len(items) != count:
        err(f"{category}: expected {count} items, found {len(items)}")
    ids = [i.get("id") for i in items]
    expected = [f"{category}-{n:03d}" for n in range(1, count + 1)]
    if ids != expected:
        err(f"{category}: ids {ids} != {expected}")
    for it in items:
        iid = it.get("id")
        for field in ("id", "category", "title", "prompt", "scoring", "difficulty", "provenance"):
            if not it.get(field):
                err(f"{iid}: missing {field}")
        if it.get("category") != category:
            err(f"{iid}: category {it.get('category')!r} != {category!r}")
        if len(it.get("title", "")) > 60:
            err(f"{iid}: title longer than 60 chars")
        if it.get("difficulty") not in DIFFICULTIES:
            err(f"{iid}: difficulty {it.get('difficulty')!r}")
        if "tags" in it and not isinstance(it["tags"], list):
            err(f"{iid}: tags must be a list")


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def fact_in(fact, text):
    """SCHEMA rule: case-insensitive substring, or Python regex when prefixed with 're:'."""
    if fact.startswith("re:"):
        return re.search(fact[3:], text, re.IGNORECASE) is not None
    return fact.lower() in text.lower()


def check_grounding():
    items = load("grounding.jsonl")
    check_common(items, "grounding", 12)
    for it in items:
        iid, sc = it["id"], it.get("scoring", {})
        if sc.get("type") != "grounded_answer":
            err(f"{iid}: scoring.type must be grounded_answer")
        answer = sc.get("answer", "")
        if not answer:
            err(f"{iid}: missing scoring.answer")
        pats = sc.get("patterns") or []
        if not pats:
            err(f"{iid}: no patterns")
        for p in pats:
            try:
                rx = re.compile(p, re.IGNORECASE)
            except re.error as e:
                err(f"{iid}: pattern {p!r} does not compile ({e})")
                continue
            if not rx.search(answer):
                err(f"{iid}: pattern {p!r} does not match canonical answer {answer!r}")
        if sc.get("require_citation") is not True:
            err(f"{iid}: require_citation should be true")
        prompt = it.get("prompt", "")
        if not re.search(r"\b(cite|sources?)\b", prompt, re.IGNORECASE):
            err(f"{iid}: prompt doesn't ask for sources")
        if not re.search(r"ANSWER: [^']+'\.\s*$", prompt):
            err(f"{iid}: prompt must end with an ANSWER format line")
        srcs = it.get("sources") or []
        if not srcs or not all(isinstance(s, str) and s.startswith(("http://", "https://")) for s in srcs):
            err(f"{iid}: sources must be a non-empty list of URLs")
        elif len(srcs) < 2:
            warnings.append(f"{iid}: only {len(srcs)} source")
    return items


def check_your_data():
    items = load("your_data.jsonl")
    check_common(items, "your_data", 12)
    docs = {it.get("doc") for it in items}
    if len(docs) != 1:
        err(f"your_data: expected exactly one document, got {docs}")
    doc_name = next(iter(docs))
    doc_path = EVALS / "your_data" / str(doc_name)
    if not doc_path.exists():
        err(f"your_data: document {doc_path} missing")
        return items
    doc = doc_path.read_text()
    words = len(doc.split())
    if not 2500 <= words <= 5000:
        err(f"your_data: document has {words} words (want 2,500-5,000)")
    if "fictional" not in doc[:400].lower():
        err("your_data: document must be marked fictional at the top")
    ndoc = norm(doc)

    answerable = [it for it in items if it.get("scoring", {}).get("answerable") is True]
    unanswerable = [it for it in items if it.get("scoring", {}).get("answerable") is False]
    if (len(answerable), len(unanswerable)) != (9, 3):
        err(f"your_data: want 9 answerable + 3 unanswerable, got {len(answerable)} + {len(unanswerable)}")
    combined = [it["id"] for it in answerable
                if it.get("verify", {}).get("multi_section") or it.get("verify", {}).get("computed_facts")]
    if len(combined) < 4:
        err(f"your_data: only {len(combined)} items combine sections or need arithmetic (want >= 4)")

    for it in items:
        iid, sc, vf = it["id"], it.get("scoring", {}), it.get("verify", {})
        if sc.get("type") != "doc_qa":
            err(f"{iid}: scoring.type must be doc_qa")
        if not sc.get("judge_rubric"):
            err(f"{iid}: missing judge_rubric")
        answer = sc.get("answer", "")
        if not answer:
            err(f"{iid}: missing scoring.answer")
        if sc.get("answerable"):
            facts = sc.get("key_facts") or []
            if not facts:
                err(f"{iid}: answerable item needs key_facts")
            computed = set(vf.get("computed_facts") or [])
            for f in facts:
                if f.startswith("re:"):
                    try:
                        re.compile(f[3:])
                    except re.error as e:
                        err(f"{iid}: key_fact {f!r} does not compile ({e})")
                        continue
                if f not in computed and not fact_in(f, doc):
                    err(f"{iid}: key_fact {f!r} not found in the document (and not marked computed)")
                if not fact_in(f, answer):
                    err(f"{iid}: key_fact {f!r} not present in the reference answer")
            for snip in vf.get("doc_evidence") or []:
                if norm(snip) not in ndoc:
                    err(f"{iid}: doc_evidence not in document: {snip!r}")
            if not vf.get("doc_evidence"):
                err(f"{iid}: answerable item needs verify.doc_evidence")
            if "calc" in vf:
                got = eval(vf["calc"], {"__builtins__": {"round": round, "sum": sum, "max": max, "divmod": divmod}})
                if str(got) != str(vf.get("calc_result")):
                    err(f"{iid}: calc {vf['calc']!r} = {got!r}, expected {vf.get('calc_result')!r}")
                for part in str(vf.get("calc_result")).split(","):
                    if part not in answer:
                        err(f"{iid}: calc_result part {part!r} missing from the reference answer")
        else:
            if sc.get("key_facts"):
                err(f"{iid}: unanswerable item should have empty key_facts")
            terms = vf.get("absent_terms") or []
            if not terms:
                err(f"{iid}: unanswerable item needs verify.absent_terms")
            for t in terms:
                if t.lower() in doc.lower():
                    err(f"{iid}: absent term {t!r} appears in the document")
            if not re.search(r"doesn't|does not|not (in|covered|specified)|no ", answer, re.IGNORECASE):
                err(f"{iid}: unanswerable reference answer should say the document doesn't cover it")
    return items, words


def main():
    g = check_grounding()
    y = check_your_data()
    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("FAIL ", e)
    if errors:
        print(f"\n{len(errors)} problem(s)")
        sys.exit(1)
    items, words = y
    print(f"OK grounding: {len(g)} items, {sum(len(i['scoring']['patterns']) for i in g)} patterns checked")
    print(f"OK your_data: {len(items)} items "
          f"({sum(1 for i in items if i['scoring']['answerable'])} answerable), document {words} words")


if __name__ == "__main__":
    main()
