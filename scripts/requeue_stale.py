"""Fail worker tasks that have been IN_PROGRESS far past their response timeout so Conductor retries them.

Happens when a worker process dies (or is restarted) after polling a task: the server keeps the task
IN_PROGRESS until its response timeout is enforced, which on Developer Edition can take much longer
than the configured value. Failing the task triggers a normal retry (the task defs allow 3).

Usage: requeue_stale.py <run_id> [--min-age 180] [--dry-run]"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workers"))
from conductor_api import Conductor  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("run_id")
ap.add_argument("--min-age", type=int, default=180, help="seconds since the worker picked the task up")
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()

c = Conductor()
run_wf = json.loads((ROOT / "results" / a.run_id / "run.json").read_text())["workflow_id"]
now = time.time() * 1000
stale = []


def walk(wid):
    for t in c.execution(wid)["tasks"]:
        if t["status"] not in ("IN_PROGRESS", "SCHEDULED"):
            continue
        if t["taskType"] == "SUB_WORKFLOW" and t.get("subWorkflowId"):
            walk(t["subWorkflowId"])
        elif t["taskType"] == "SIMPLE" and t["status"] == "IN_PROGRESS":
            age = (now - (t.get("updateTime") or t.get("startTime") or now)) / 1000
            if age >= a.min_age:
                stale.append((wid, t, age))


walk(run_wf)
for wid, t, age in stale:
    print(f"stale {t['referenceTaskName']} ({t['taskDefName']}) {age:.0f}s in {wid}")
    if not a.dry_run:
        r = c.post("/tasks", json={"workflowInstanceId": wid, "taskId": t["taskId"], "status": "FAILED",
                                   "reasonForIncompletion": "worker restarted while holding the task; retrying",
                                   "workerId": "requeue_stale.py"})
        print("   -> FAILED for retry:", r.status_code)
        with open(ROOT / "results" / a.run_id / "notes.md", "a") as f:
            f.write(f"- {time.strftime('%H:%M')} requeued stale {t['taskDefName']} {t['taskId']} "
                    f"({age:.0f}s IN_PROGRESS after a worker restart); Conductor retried it normally.\n")
print(f"{len(stale)} stale task(s)")
