# Results

One folder per run. Each has `results.jsonl` (one line per model call), `run.json` (the run's input and
Conductor workflow id) and `summary.json`.

## Which files hold the final numbers

- `full-r1`, `full-r2` and `full-r3` are the three runs behind the report: 76 tasks × 5 configs each, 1,140
  calls in total.
- One call in `full-r1` (task `agentic-010`, Large 3) failed on a rate limit and was re-run in
  `repair-full-r1-1`. `scripts/analyze.py` swaps the re-run in; do the same if you recompute anything.
- `report/data/all_results_flat.csv` has every call from the three runs in one table, with the re-run already
  swapped in.
- `results.jsonl.orig` and `results.jsonl.pre-rejudge` are copies from before the scoring corrections described
  in `report/REPORT.md`, kept as a record. Don't take numbers from them. Each run's `notes.md` lists what
  changed.

Other runs, not part of the headline numbers:

- `followup-l4-128k`: Large 4 (reasoning high) with a 128k output cap on the 9 coding tasks where it ran out of
  budget
- `oss-sample-r1`: 10 tasks × 5 configs on Conductor OSS 3.32.5, to check the harness runs there
- `pilot-1`: a 5-task pilot before the full runs

## Fields in results.jsonl

- `item_id`, `category`, `config_id` (`l4_off`, `l4_high`, `sol_low`, `sol_high`, `l3`), `repeat`
- `pass` and `score`, and `detail`, which shows how the call was scored
- `answer`: the model's final answer
- `latency_ms`: Conductor's HTTP task time, summed over turns for agentic tasks
- `usage`: `input_tokens`, `output_tokens`, `reasoning_tokens`, `cached_input_tokens`, `search_calls`,
  `search_tokens`
- `finish_reason`: `length` means the call hit the output cap
- `workflow_id`, `parent_workflow_id`: the Conductor executions that produced the row
