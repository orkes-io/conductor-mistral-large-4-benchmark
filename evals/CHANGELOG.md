# Eval set changes

- **2026-10-25, your_data-008 (Friday deploy with the standard canary).** The handbook says a Friday change must reach
  100% of traffic *before* 16:00 UTC, so a 14:30 start (100% at exactly 16:00) is only allowed under a loose reading.
  v1 accepted only "14:30", which marked GPT-6.1 Sol's strictly correct "start before 14:30" as wrong in every run.
  The rubric now accepts either boundary reading if the answer is consistent; the stored answers were re-judged
  (`scripts/rejudge.py`). The v1 file is kept as `your_data.jsonl.v1`.
