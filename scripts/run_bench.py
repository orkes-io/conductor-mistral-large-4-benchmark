"""Start a benchmark run (ml4_bench_run) and optionally wait for it.

Examples:
  run_bench.py --run-id pilot-1 --items reasoning-003,coding-001 --wait
  run_bench.py --run-id full-1 --repeats 3 --batch-size 6
  run_bench.py --run-id byo-1 --dataset https://example.com/my-evals --categories your_data
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workers"))
from conductor_api import Conductor  # noqa: E402
from configs import CONFIGS, EXTRA_CONFIGS, JUDGE  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--run-id", required=True)
ap.add_argument("--items", default=None, help="comma-separated item ids")
ap.add_argument("--categories", default=None, help="comma-separated categories")
ap.add_argument("--limit-per-category", type=int, default=None)
ap.add_argument("--configs", default=None, help="comma-separated config ids (default: all)")
ap.add_argument("--repeats", type=int, default=1)
ap.add_argument("--batch-size", type=int, default=6)
ap.add_argument("--dataset", default=None, help="folder or http(s) base URL (default: ./evals)")
ap.add_argument("--wait", action="store_true")
a = ap.parse_args()

configs = [c for c in CONFIGS + EXTRA_CONFIGS if (c in CONFIGS and not a.configs) or (a.configs and c["id"] in a.configs.split(","))]
inp = {"run_id": a.run_id, "dataset": a.dataset, "configs": configs, "repeats": a.repeats,
       "batch_size": a.batch_size, "judge": JUDGE,
       "categories": a.categories.split(",") if a.categories else None,
       "item_ids": a.items.split(",") if a.items else None, "limit_per_category": a.limit_per_category}
c = Conductor()
wid = c.start("ml4_bench_run", inp, correlation_id=a.run_id)
meta = ROOT / "results" / a.run_id
meta.mkdir(parents=True, exist_ok=True)
(meta / "run.json").write_text(json.dumps({"workflow_id": wid, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                           "server": c.ui, "input": inp}, indent=2))
print("started", wid, f"{c.ui}/execution/{wid}")
if a.wait:
    ex = c.wait(wid, timeout=6 * 3600, poll=15)
    print("status", ex["status"])
    print(json.dumps(ex.get("output"), indent=1)[:4000])
