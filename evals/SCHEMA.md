# Eval set format

Each category is one JSONL file in this folder (`reasoning.jsonl`, `coding.jsonl`, `agentic.jsonl`,
`grounding.jsonl`, `your_data.jsonl`), one item per line. The harness sends `system` (if any) and
`prompt` to every model config unchanged, then scores the reply with the rule in `scoring`.

Nothing in an item except `system`, `prompt` and (agentic) `tools` is ever sent to a model.

## Common fields

| field | type | notes |
|---|---|---|
| `id` | string | `<category>-NNN`, e.g. `reasoning-007` |
| `category` | string | `reasoning` \| `coding` \| `agentic` \| `grounding` \| `your_data` |
| `title` | string | short human-readable name, ≤ 60 chars |
| `system` | string, optional | system message |
| `prompt` | string | the user message |
| `scoring` | object | per-category rules below |
| `difficulty` | string | `easy` \| `medium` \| `hard` (author's estimate) |
| `provenance` | string | one sentence on how the expected answer was produced and verified |
| `tags` | list of strings, optional | |

## reasoning

Fresh, checkable problems (not famous puzzles), each verified by code.

- `prompt` must end with an instruction like
  `End your reply with a final line of the form 'ANSWER: <number>'.` (exact format spelled out).
- `scoring`:
  ```json
  {"type": "final_answer", "answer": "5929", "match": "number", "accept": []}
  ```
  `match` is one of:
  - `number`: numeric equality after stripping commas, spaces, `$`, `%`
  - `exact_ci`: case-insensitive, whitespace-collapsed string equality (also accepts any string in `accept`)
  - `set`: comma-separated items, order-insensitive, case-insensitive
  - `sequence`: comma-separated items, order-sensitive, case-insensitive
  - `regex`: Python regex in `pattern`, matched case-insensitively against the final answer
- The harness reads the LAST line that starts with `ANSWER:` (markdown bold/backticks stripped).

## coding

- `prompt`: specify one Python 3.13 function (exact name and signature), its behavior and edge cases. End with:
  `Return only the complete function (plus any imports or helpers it needs) in a single python code block.`
  Do not show the tests.
- `scoring`:
  ```json
  {"type": "unit_tests", "entrypoint": "parse_duration", "tests": "assert parse_duration('PT1M') == 60\n...", "timeout_s": 10}
  ```
  `tests` is Python source using plain `assert` statements, stdlib only, deterministic, no network or files,
  8 to 20 asserts. The harness runs `<model code>\n\n<tests>` in a sandbox; pass = exit code 0.
  The harness also reports how many asserts passed, so put one assert per line.
- `reference_solution`: Python source that passes all tests (verified). Never sent to models.

## agentic

A multi-step tool-use task. The model gets `system`, `prompt` and `tools`; the harness executes tool calls
against the deterministic `environment` and feeds results back until the model answers without tool calls
or `max_turns` is reached.

- `tools`: list of function tools in OpenAI/Mistral chat format:
  `{"type": "function", "function": {"name": "...", "description": "...", "parameters": {JSON schema}}}`
- `environment`: per tool name
  ```json
  {"get_service_status": {"cases": [{"match": {"service": "checkout"}, "result": {"error_rate": 0.18}}],
                          "default": {"error": "unknown service"}}}
  ```
  Matching: every key in `match` must equal the call's argument after normalization (strings trimmed and
  compared case-insensitively; numbers compared numerically; lists/objects compared after the same
  normalization). First matching case wins; `"match": {}` matches anything. Results are stateless.
  Mark write/action tools with `"side_effect": true` at the tool level in `environment`
  (e.g. `{"rollback": {"side_effect": true, "cases": [...], "default": {...}}}`).
- `scoring`:
  ```json
  {"type": "agentic_trace",
   "required_calls": [{"tool": "rollback", "args": {"service": "checkout", "deploy_id": "d-482"}}],
   "forbidden_calls": [{"tool": "rollback", "args": {"service": "search"}}],
   "final_must_include": ["checkout", "re:search .*(not|wasn't|was not) rolled back"],
   "final_must_not_include": [],
   "max_turns": 8}
  ```
  `args` is a subset match with the same normalization. A forbidden call with `"args": {}` forbids any call
  to that tool. `final_must_include` entries are case-insensitive substrings, or Python regexes when
  prefixed with `re:`. Pass = all required calls made, no forbidden call made, final answer checks pass,
  finished within `max_turns`.
- `reference_trace`: the tool calls an ideal agent makes, in order (used to verify the scenario is solvable).

## grounding

Questions that need live web search: facts from roughly Aug to Oct 2026 that are unambiguous and stable
(past events, dated releases), unlikely to be in either model's training data.

- `prompt` asks the question, asks for sources, and ends with an `ANSWER:` format line.
- `scoring`:
  ```json
  {"type": "grounded_answer", "answer": "v3.32.5", "patterns": ["3\\.32\\.5"], "require_citation": true}
  ```
  Pass = every regex in `patterns` matches the final answer (case-insensitive) and, if `require_citation`,
  the reply cites at least one source URL.
- `sources`: URLs that confirm the answer, checked on 2026-10-24/25.

## your_data

Questions over a private document the models have never seen. The document lives in
`evals/your_data/` and the harness injects it as the system message (the item's `system` is ignored).

- `doc`: file name of the document in `evals/your_data/`
- `scoring`:
  ```json
  {"type": "doc_qa", "answerable": true, "answer": "reference answer",
   "key_facts": ["4 hours", "re:sev(erity)?[- ]?1"], "judge_rubric": "what a correct, faithful answer must contain"}
  ```
  For unanswerable questions set `"answerable": false`; a correct reply says the document doesn't contain it.
  Programmatic pass = all `key_facts` present (answerable) or an explicit "not in the document" (unanswerable);
  an LLM judge also grades faithfulness against `judge_rubric` and the document.
