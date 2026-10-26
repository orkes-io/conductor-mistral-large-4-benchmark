"""Re-score stored web-grounded results with the broadened citation rule (no new model calls).

The first scoring counted a citation only for a full URL or a structured API reference, which marked Large 4
answers that list sources by title and website (e.g. 'usopen.org') as uncited. This re-applies
scoring.score_grounded to the stored answers and keeps the original file as results.jsonl.orig."""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workers"))
import bench  # noqa: E402
import scoring  # noqa: E402

for rid in sys.argv[1:]:
    p = ROOT / "results" / rid / "results.jsonl"
    orig = p.with_suffix(".jsonl.orig")
    if not orig.exists():
        shutil.copy(p, orig)
    rows = [json.loads(line) for line in orig.read_text().splitlines() if line.strip()]
    changed = 0
    for r in rows:
        if r["category"] != "grounding" or not r["api_ok"]:
            continue
        item = bench.Dataset().item(r["item_id"])
        d = r.get("detail") or {}
        n_refs = d.get("citation_count") or 0
        if r.get("answer_chars", 0) > 4000:          # stored answer truncated: only update the citation flag
            cited = bool(n_refs) or scoring.names_a_source(r["answer"])
            new = {**d, "cited": cited, "pass": (not d.get("pattern_misses")) and cited}
        else:
            new = scoring.score_grounded(item["scoring"], r["answer"], ["ref"] * n_refs)
            new["citation_count"] = n_refs
        if bool(new["pass"]) != bool(r["pass"]):
            changed += 1
        r["pass"], r["score"], r["detail"] = bool(new["pass"]), 1.0 if new["pass"] else 0.0, new
        r["rescored"] = "grounding citation rule v3 (URL, website or provider reference link)"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with open(ROOT / "results" / rid / "notes.md", "a") as f:
        f.write(f"- re-scored web-grounded answers with the broadened citation rule (URL, website or API reference); "
                f"{changed} result(s) changed. Original file kept as results.jsonl.orig.\n")
    print(rid, "changed:", changed)
