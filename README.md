# Mistral Large 4 benchmark on Conductor

A reproducible eval harness, built as Conductor workflows, that runs the same prompts against
Mistral Large 4 and comparison models side by side and scores the answers with code checks or an
LLM judge. It runs on Orkes Developer Edition (where the published numbers come from) and on
Conductor OSS.

Everything here was built and run on 2026-10-24/25. Mistral Large 4 is in public preview, so
results can change as Mistral updates the model.

Full results and caveats are in `report/REPORT.md`. `results/README.md` explains the data files and which ones
hold the final numbers.

## Results at a glance

1,140 scored calls (76 tasks × 5 configs × 3 runs) on Orkes Developer Edition, 2026-10-24/25. Full write-up in
`report/REPORT.md`.

| Config | Pass rate (95% CI) | Median time to answer | Avg output tokens |
|---|---|---|---|
| Large 4 · reasoning off | 92% (87–96%) | 5.9 s | 1,274 |
| Large 4 · reasoning high | 82% (74–89%) | 17.6 s | 9,289 |
| GPT-6.1 Sol · low | 100% (99–100%) | 5.4 s | 301 |
| GPT-6.1 Sol · high | 100% (100–100%) | 7.4 s | 585 |
| Large 3 | 68% (58–77%) | 5.4 s | 851 |

## What's in this folder

| Path | What it is |
|---|---|
| `workflows/` | Conductor workflow definitions (JSON) |
| `workers/` | Python workers (conductor-python 2.0) plus the request, scoring and agent-loop logic |
| `evals/` | The eval set: 76 items in 5 categories, the schema, and scripts that verify every expected answer |
| `results/<run_id>/` | Raw per-call results (`results.jsonl`), run metadata, summaries; see `results/README.md` |
| `report/` | Findings (`REPORT.md`), generated tables and CSVs, charts, screenshots |
| `integration/` | Tests of Conductor's built-in Mistral connector on each platform, with screenshots |
| `env/litellm/` | LiteLLM proxy config for reaching Mistral Large 4 through Conductor OSS's built-in LLM tasks |
| `scripts/` | Setup (`setup_de.py`), registration (`register.py`), runs (`run_bench.py`, `watch_runs.py`), recovery (`requeue_stale.py`, `repair.py`), scoring fixes (`rescore_grounding.py`, `rejudge.py`), analysis (`analyze.py`) and the connector test (`run_native_check.py`) |

## How the harness works

```
ml4_bench_run            load eval set → loop over batches → summarize
 └─ ml4_bench_item       FORK_JOIN_DYNAMIC: the same item goes to every model config in parallel
     └─ ml4_eval_one     build request → call model (loop over tool calls for agentic items)
         │                → run hidden unit tests (coding) or LLM judge (your-documents) → score → record
         └─ ml4_call_model   SWITCH provider → HTTP task (API key from a Conductor secret) → normalize reply
```

- **Model calls are plain HTTP tasks.** Conductor's built-in Mistral connector can't read Large 4's
  replies yet (see `integration/`), so the harness calls Mistral's and OpenAI's REST APIs directly. Keys
  live in Conductor secrets (`ml4_mistral_api_key`, `ml4_openai_api_key`) and show as `***` in the UI.
- **Latency is Conductor's own task timing** (HTTP task start → end, successful attempt only), so it
  includes network time from the Conductor server to the provider.
- **Scoring is programmatic wherever possible:** exact answers for reasoning, hidden unit tests in a
  network-less Docker sandbox for coding, tool-call traces for agentic scenarios, regex plus citation
  checks for web-grounded questions. Only the your-documents questions use an LLM judge (GPT-6 Astra,
  blind to which model answered), alongside a key-facts check.
- **Bring your own data:** pass `--dataset /path/to/folder` or `--dataset https://host/path` with files
  in the `evals/` format (see `evals/SCHEMA.md`). Items are loaded by the workers, so private data stays
  where the workers run.

## Model configs

| id | Model | Reasoning setting |
|---|---|---|
| `l4_off` | `mistral-large-4` | `reasoning_effort: none` |
| `l4_high` | `mistral-large-4` | `reasoning_effort: high` (Large 4 accepts only `none` and `high`) |
| `sol_low` | `gpt-6.1-sol` | `reasoning_effort: low` (Sol's lowest setting) |
| `sol_high` | `gpt-6.1-sol` | `reasoning_effort: high` |
| `l3` | `mistral-large-2512` (Large 3) | none (not a reasoning model) |

All configs get the same prompts and a 32,000-token output cap (8,000 for web search). Sampling uses
each provider's defaults. GPT-6.1 Sol was chosen as the comparison because it's OpenAI's tier closest
to Large 4 in price ($2/$10 vs $1.36/$4.18 per 1M tokens) and positioning (agents and coding).

## Running it

Prereqs: Python 3.13, Docker (for the coding sandbox), a Mistral API key with paid access, an OpenAI key.

```bash
python3.13 -m venv .venv && .venv/bin/pip install requests conductor-python pandas matplotlib playwright==1.63.0
docker pull python:3.13-slim

# Orkes Developer Edition (or any Orkes cluster). Instead of exporting these you can put them in a file
# and set CONDUCTOR_ENV_FILE to its path.
export CONDUCTOR_SERVER_URL=https://developer.orkescloud.com/api CONDUCTOR_AUTH_KEY=... CONDUCTOR_AUTH_SECRET=...
export MISTRAL_API_KEY=... OPENAI_API_KEY=...
.venv/bin/python scripts/setup_de.py      # secrets + a Mistral integration (for the connector test)
.venv/bin/python scripts/register.py      # task definitions + workflows
scripts/workers.sh start                  # workers (one process group; `stop` kills all of them)
.venv/bin/python scripts/run_bench.py --run-id my-run --repeats 1 --batch-size 8
.venv/bin/python scripts/analyze.py my-run

# Conductor OSS (local Docker). Secrets come from env vars named CONDUCTOR_SECRET_<secret name>, and the
# name is case-sensitive.
docker run -d --name conductor -p 8080:8080 -p 5000:5000 \
  -e CONDUCTOR_SECRET_ml4_mistral_api_key=... -e CONDUCTOR_SECRET_ml4_openai_api_key=... \
  -e CONDUCTOR_APP_SYSTEMTASKWORKERTHREADCOUNT=32 \
  conductoross/conductor:3.32.5
unset CONDUCTOR_AUTH_KEY CONDUCTOR_AUTH_SECRET CONDUCTOR_ENV_FILE
export CONDUCTOR_SERVER_URL=http://localhost:8080/api
.venv/bin/python scripts/register.py
TARGET=oss scripts/workers.sh start
.venv/bin/python scripts/run_bench.py --run-id oss-run
```

Useful flags: `--items reasoning-001,coding-002`, `--categories coding,agentic`, `--limit-per-category 2`,
`--configs l4_high,sol_high`.

## Operational notes (learned the hard way)

- **Developer Edition caps AI integrations at 5 models per account.** The harness doesn't need any
  (it uses HTTP tasks); the built-in connector test uses two.
- **Secrets on Developer Edition:** `PUT /api/secrets/{name}` stores the request body verbatim, so send the
  bare value as `text/plain`. Overwriting didn't always stick; `scripts/setup_de.py` deletes first.
- **GPT-6.1 Sol rejects function tools with reasoning on `/v1/chat/completions`.** Agentic runs for Sol
  use the Responses API (`/v1/responses`) and pass back the encrypted reasoning items between turns.
- **Workers:** the SDK forks one process per worker, so stop them by process group (`scripts/workers.sh stop`).
  Run with `CONDUCTOR_HTTP2_ENABLED=false`: on HTTP/2 the server closes connections every ~2,000 streams
  and a task update in flight can be lost, leaving the task IN_PROGRESS until its response timeout.
- **Conductor OSS runs HTTP tasks on a shared system-task pool of CPU × 2 threads.** A Large 4 call with
  reasoning on can hold a thread for minutes, so raise `conductor.app.systemTaskWorkerThreadCount`
  (env `CONDUCTOR_APP_SYSTEMTASKWORKERTHREADCOUNT`) for LLM-heavy workloads.
- **Developer Edition enforced task response timeouts several minutes late** in these runs, so a task orphaned by a
  restarted worker can block a batch; `scripts/requeue_stale.py` fails such tasks so Conductor retries them, and
  `scripts/watch_runs.py` runs it automatically.
- **HTTP-task capacity is shared.** With three runs in parallel, long Large 4 calls held Developer Edition's HTTP capacity and
  new calls queued for minutes (latency numbers exclude queue time; each call records `queue_ms`).
- **Large 4 with `reasoning_effort: high` can spend the entire output budget thinking** and return no answer
  (`finish_reason: length`). Budget for it, or use `none` for tasks that don't need deep reasoning.
