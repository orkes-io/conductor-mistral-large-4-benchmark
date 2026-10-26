"""Model configurations compared in the benchmark, and the judge."""

CONFIGS = [
    {"id": "l4_off", "label": "Mistral Large 4 (reasoning off)", "provider": "mistral",
     "model": "mistral-large-4", "reasoning_effort": "none"},
    {"id": "l4_high", "label": "Mistral Large 4 (reasoning high)", "provider": "mistral",
     "model": "mistral-large-4", "reasoning_effort": "high"},
    {"id": "sol_low", "label": "GPT-6.1 Sol (reasoning low)", "provider": "openai",
     "model": "gpt-6.1-sol", "reasoning_effort": "low"},
    {"id": "sol_high", "label": "GPT-6.1 Sol (reasoning high)", "provider": "openai",
     "model": "gpt-6.1-sol", "reasoning_effort": "high"},
    {"id": "l3", "label": "Mistral Large 3 (baseline)", "provider": "mistral",
     "model": "mistral-large-2512", "reasoning_effort": None},
]
for c in CONFIGS:
    c.setdefault("max_tokens", 32000)
    c.setdefault("max_tokens_search", 8000)

# Blind grader for the your_data answers; never one of the contestants.
JUDGE = {"model": "gpt-6-astra", "reasoning_effort": "low", "max_tokens": 4000}

# Follow-up experiments, selectable by id with run_bench.py --configs (not part of the default five)
EXTRA_CONFIGS = [
    {"id": "l4_high_128k", "label": "Mistral Large 4 (reasoning high, 128k output cap)", "provider": "mistral",
     "model": "mistral-large-4", "reasoning_effort": "high", "max_tokens": 131072, "max_tokens_search": 8000},
]
