"""Register and run ml4_native_connector_check, then save a per-task summary.

Usage: run_native_check.py [env-label]   (default: developer-edition)
Targets Developer Edition unless CONDUCTOR_SERVER_URL points at a local server."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "workers"))
from conductor_api import Conductor  # noqa: E402

label = sys.argv[1] if len(sys.argv) > 1 else "developer-edition"
mistral_provider = sys.argv[2] if len(sys.argv) > 2 else "ml4_mistral"
openai_provider = sys.argv[3] if len(sys.argv) > 3 else "openai"
openai_model = sys.argv[4] if len(sys.argv) > 4 else "gpt-4.1"

c = Conductor()
wf = json.loads((ROOT / "workflows" / "ml4_native_connector_check.json").read_text())
c.register_workflow(wf)
version = c.get("/version").text.strip()
wid = c.start(wf["name"], {
    "prompt": "In one sentence, what does a workflow orchestration engine do?",
    "mistralProvider": mistral_provider, "openaiProvider": openai_provider, "openaiModel": openai_model,
})
print("started", wid, "on", c.ui, "version", version)
ex = c.wait(wid, timeout=300)
rows = []
for t in ex["tasks"]:
    if t["taskType"] != "LLM_CHAT_COMPLETE":
        continue
    rows.append({
        "task": t["referenceTaskName"],
        "model": t["inputData"].get("model"),
        "status": t["status"],
        "reason": (t.get("reasonForIncompletion") or "")[:600],
        "result": str((t.get("outputData") or {}).get("result", ""))[:200],
        "tokens": {k: (t.get("outputData") or {}).get(k) for k in ("promptTokens", "completionTokens", "tokenUsed")},
        "duration_ms": (t.get("endTime") or 0) - (t.get("startTime") or 0),
    })
out = {"env": label, "server": c.ui, "server_version": version, "workflow_id": wid,
       "workflow_status": ex["status"], "checked_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "tasks": rows}
dest = ROOT / "integration" / f"native_check_{label}.json"
dest.write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
