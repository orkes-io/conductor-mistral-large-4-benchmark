"""Conductor workers for the Mistral Large 4 benchmark.

Run:  .venv/bin/python workers/main.py  (or scripts/workers.sh start)
with CONDUCTOR_SERVER_URL / CONDUCTOR_AUTH_KEY / CONDUCTOR_AUTH_SECRET set, or CONDUCTOR_ENV_FILE pointing at a
file that sets them. For a local OSS server set only CONDUCTOR_SERVER_URL=http://localhost:8080/api."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from conductor.client.automator.task_handler import TaskHandler  # noqa: E402
from conductor.client.configuration.configuration import Configuration  # noqa: E402
from conductor.client.worker.worker_task import worker_task  # noqa: E402

import bench  # noqa: E402
import model_io  # noqa: E402
from conductor_api import _load_env_file  # noqa: E402


@worker_task(task_definition_name="ml4_prepare_run")
def prepare_run(dataset: str = None, categories: list[str] = None, item_ids: list[str] = None, repeats: int = 1,
                batch_size: int = 6, limit_per_category: int = None) -> dict:
    return bench.prepare_run(dataset, categories, item_ids, repeats or 1, batch_size or 6, limit_per_category)


@worker_task(task_definition_name="ml4_plan_batch_fork")
def plan_batch_fork(batches: list[list], index: int, configs: list[dict], dataset: str = None, run_id: str = None,
                    judge: dict = None) -> dict:
    batch = batches[int(index) - 1]
    plan = bench.plan_batch_fork(batch, configs, dataset, run_id)
    for v in plan["inputs"].values():
        v["judge"] = judge
    plan["batch"] = batch
    return plan


@worker_task(task_definition_name="ml4_plan_item_fork")
def plan_item_fork(item_id: str, repeat: int, configs: list[dict], dataset: str = None, run_id: str = None,
                   judge: dict = None) -> dict:
    plan = bench.plan_item_fork(item_id, repeat, configs, dataset, run_id)
    for v in plan["inputs"].values():
        v["judge"] = judge
    return plan


@worker_task(task_definition_name="ml4_prepare_eval", thread_count=8)
def prepare_eval(item_id: str, config: dict, dataset: str = None) -> dict:
    return bench.prepare_eval(item_id, config, dataset)


@worker_task(task_definition_name="ml4_normalize", thread_count=8)
def normalize(route: str, mistral: dict = None, openai: dict = None) -> dict:
    h = (mistral or {}) if (mistral or {}).get("status") else (openai or {})
    return {"result": model_io.normalize(route, h.get("response"), task_status=h.get("status"), reason=h.get("reason"),
                                         start_time=h.get("start"), end_time=h.get("end"),
                                         scheduled_time=h.get("scheduled"), retry_count=h.get("retries"))}


@worker_task(task_definition_name="ml4_agent_step", thread_count=6)
def agent_step(item_id: str, config: dict, route: str, state: dict, result: dict, dataset: str = None) -> dict:
    return bench.agent_step(item_id, config, route, state, result or {}, dataset)


@worker_task(task_definition_name="ml4_prepare_judge", thread_count=4)
def prepare_judge(item_id: str, candidate_text: str, judge: dict, dataset: str = None) -> dict:
    return {"request": bench.prepare_judge(item_id, candidate_text, judge, dataset)}


@worker_task(task_definition_name="ml4_run_code", thread_count=2)
def run_code(item_id: str, result: dict, dataset: str = None) -> dict:
    return {"result": bench.run_code(item_id, result or {}, dataset)}


@worker_task(task_definition_name="ml4_score", thread_count=6)
def score(item_id: str, result: dict = None, dataset: str = None, code_result: dict = None,
          agent_state: dict = None, judge_result: dict = None) -> dict:
    return bench.score(item_id, result, dataset, code_result, agent_state, judge_result)


@worker_task(task_definition_name="ml4_record", thread_count=2)
def record(run_id: str, item_id: str, repeat: int, config: dict, category: str, result: dict = None,
           score_out: dict = None, agent_state: dict = None, workflow_id: str = None,
           parent_workflow_id: str = None, title: str = None, difficulty: str = None) -> dict:
    return bench.record(run_id, item_id, repeat, config, category, result, score_out, agent_state, workflow_id,
                        parent_workflow_id, title, difficulty)


@worker_task(task_definition_name="ml4_summarize")
def summarize(run_id: str) -> dict:
    return bench.summarize(run_id)


def main():
    env_file = os.environ.get("CONDUCTOR_ENV_FILE")
    for k, v in (_load_env_file(env_file) if env_file else {}).items():
        os.environ.setdefault(k, v)
    if not os.environ.get("CONDUCTOR_SERVER_URL"):
        sys.exit("Set CONDUCTOR_SERVER_URL (plus CONDUCTOR_AUTH_KEY / CONDUCTOR_AUTH_SECRET for Orkes), "
                 "or point CONDUCTOR_ENV_FILE at a file that sets them.")
    url = os.environ["CONDUCTOR_SERVER_URL"].rstrip("/")
    if not url.endswith("/api"):
        url += "/api"
    os.environ["CONDUCTOR_SERVER_URL"] = url
    cfg = Configuration()  # reads CONDUCTOR_SERVER_URL / CONDUCTOR_AUTH_KEY / CONDUCTOR_AUTH_SECRET
    handler = TaskHandler(configuration=cfg, scan_for_annotated_workers=True)
    handler.start_processes()
    handler.join_processes()


if __name__ == "__main__":
    main()
