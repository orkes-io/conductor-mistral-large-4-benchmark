"""Register the benchmark's task definitions and workflows on a Conductor server.

Targets the server in CONDUCTOR_SERVER_URL (see workers/conductor_api.py). CONDUCTOR_OWNER_EMAIL sets the owner
email on the definitions."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workers"))
from conductor_api import Conductor  # noqa: E402

OWNER = os.environ.get("CONDUCTOR_OWNER_EMAIL", "nicholas.lotz@orkes.io")

SIMPLE = {
    "ml4_prepare_run": "Load the eval set (local folder or URL) and split the run into batches",
    "ml4_plan_batch_fork": "Plan the dynamic fork for one batch of eval items",
    "ml4_plan_item_fork": "Plan the dynamic fork across model configs for one eval item",
    "ml4_prepare_eval": "Build the model request for one eval item and config",
    "ml4_normalize": "Normalize a Mistral or OpenAI API reply (text, tool calls, citations, tokens, latency)",
    "ml4_agent_step": "Execute the model's tool calls against the scenario environment and build the next turn",
    "ml4_prepare_judge": "Build the blind LLM-as-judge request for a document question",
    "ml4_run_code": "Run the model's code against hidden unit tests in a network-less Docker sandbox",
    "ml4_score": "Score one result (answer match, unit tests, tool-call trace, grounding, judge verdict)",
    "ml4_record": "Append one scored result to the run's results file",
    "ml4_summarize": "Summarize pass rates, latency and token usage for a run",
}
HTTP = {
    "ml4_http_mistral": "HTTP call to the Mistral API (key from the ml4_mistral_api_key secret)",
    "ml4_http_openai": "HTTP call to the OpenAI API (key from the ml4_openai_api_key secret)",
}
WORKFLOWS = ["ml4_call_model", "ml4_eval_one", "ml4_bench_item", "ml4_bench_run", "ml4_native_connector_check"]


def taskdefs():
    defs = []
    for name, desc in SIMPLE.items():
        defs.append({"name": name, "description": desc, "ownerEmail": OWNER, "retryCount": 2,
                     "retryLogic": "FIXED", "retryDelaySeconds": 5, "timeoutSeconds": 1800,
                     "responseTimeoutSeconds": 900, "timeoutPolicy": "RETRY", "inputKeys": [], "outputKeys": []})
    for name, desc in HTTP.items():
        # 429s and 5xx get retried with exponential backoff (20s, 40s, 80s)
        defs.append({"name": name, "description": desc, "ownerEmail": OWNER, "retryCount": 3,
                     "retryLogic": "EXPONENTIAL_BACKOFF", "retryDelaySeconds": 20, "timeoutSeconds": 1200,
                     "responseTimeoutSeconds": 1200, "timeoutPolicy": "RETRY", "inputKeys": [], "outputKeys": []})
    return defs


def main():
    c = Conductor()
    for d in taskdefs():
        r = c.put("/metadata/taskdefs", json=d)
        if not r.ok:
            r = c.post("/metadata/taskdefs", json=[d])
        print("taskdef", d["name"], r.status_code)
    for name in WORKFLOWS:
        wf = json.loads((ROOT / "workflows" / f"{name}.json").read_text())
        c.register_workflow(wf)
        print("workflow", name, "ok")


if __name__ == "__main__":
    main()
