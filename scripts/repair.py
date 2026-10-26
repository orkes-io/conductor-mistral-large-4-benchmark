"""Re-run (item, config) pairs that failed at the API level (rate limit after retries, 5xx, timeouts).

Each pair runs as its own small run, results/repair-<run_id>-<n>/. scripts/analyze.py swaps a repaired
result in for the failed original (same run, item and config) and marks it `repaired`.

Usage: repair.py <run_id> [--dry-run]"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
run_id = sys.argv[1]
dry = "--dry-run" in sys.argv
rows = [json.loads(line) for line in open(ROOT / "results" / run_id / "results.jsonl")]
failed = [(r["item_id"], r["config_id"]) for r in rows if not r["api_ok"]]
done = {p.name for p in (ROOT / "results").glob(f"repair-{run_id}-*")}
print(f"{run_id}: {len(failed)} API-level failure(s)")
for n, (item, cfg) in enumerate(failed, 1):
    rid = f"repair-{run_id}-{n}"
    if rid in done:
        print("  already repaired:", rid, item, cfg)
        continue
    print("  ", rid, item, cfg)
    if not dry:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "run_bench.py"), "--run-id", rid, "--items", item,
                        "--configs", cfg, "--batch-size", "1"], check=True)
        with open(ROOT / "results" / run_id / "notes.md", "a") as f:
            f.write(f"- re-ran {item} / {cfg} as {rid} after an API-level failure; analyze.py uses the repaired result.\n")
