"""Watch benchmark runs until they all finish; requeue worker tasks stuck far past their timeout.

Usage: watch_runs.py <run_id> [<run_id> ...]"""
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workers"))
from conductor_api import Conductor  # noqa: E402

runs = sys.argv[1:]
c = Conductor()
ids = {r: json.loads((ROOT / "results" / r / "run.json").read_text())["workflow_id"] for r in runs}
last_requeue = 0
while True:
    states = {}
    for r, wid in ids.items():
        try:
            states[r] = c.execution(wid, include_tasks=False)["status"]
        except Exception as e:  # transient API errors: try again next round
            states[r] = f"?({type(e).__name__})"
    counts = {}
    for r in runs:
        p = ROOT / "results" / r / "results.jsonl"
        counts[r] = sum(1 for _ in open(p)) if p.exists() else 0
    print(time.strftime("%H:%M:%S"), " | ".join(f"{r} {states[r]} {counts[r]}" for r in runs), flush=True)
    if all(s in ("COMPLETED", "FAILED", "TERMINATED", "TIMED_OUT") for s in states.values()):
        break
    if time.time() - last_requeue > 300:
        last_requeue = time.time()
        for r in runs:
            if states[r] == "RUNNING":
                out = subprocess.run([sys.executable, str(ROOT / "scripts" / "requeue_stale.py"), r, "--min-age", "300"],
                                     capture_output=True, text=True)
                lines = [l for l in out.stdout.splitlines() if l.startswith(("stale", "   ->"))]
                for l in lines:
                    print("   ", r, l, flush=True)
    time.sleep(60)
print("ALL DONE", states, counts, flush=True)
