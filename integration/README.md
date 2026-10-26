# Conductor's built-in Mistral connector and Mistral Large 4

Tested 2026-10-24 with `workflows/ml4_native_connector_check.json`: one prompt sent through Conductor's
built-in `LLM_CHAT_COMPLETE` task to Mistral Large 4, Mistral Large 3 and an OpenAI control model, in a
FORK so all three run side by side. Raw results are in `native_check_*.json`, screenshots in `screenshots/`.

## Results

| Platform | Large 3 (`mistral-large-2512`) | Large 4 (`mistral-large-4`) | OpenAI control | Evidence |
|---|---|---|---|---|
| Orkes Developer Edition 5.6.0-rc2 | completed | **failed**: `The content is not a string!` | completed | `native_check_developer-edition.json`, `de_0*.png` |
| Orkes standalone 6.0.0 (local image built 2026-09-21) | **failed**: `Error while extracting response for type [...MistralAiApi$ChatCompletion]` | **failed** (same) | completed | `native_check_orkes-local-6.0.0.json`, `orkes600_0*.png` |
| Conductor OSS 3.32.5 | **failed**: `Illegal character ((CTRL-CHAR, code 31))` | **failed** (same) | completed | `native_check_oss-3.32.5.json`, `oss_0[12].png` |
| Conductor OSS 3.32.5, `litellm` provider + LiteLLM proxy | not tested | completed (thinking on and off) | completed | `native_check_oss-3.32.5_litellm.json`, `oss_0[345].png` |

A newer Orkes standalone image wasn't available for this test, so Developer Edition 5.6.0-rc2 stands in for the
latest Orkes build.

## Root causes

**1. Thinking replies, Large 4 only (all platforms).** Large 4 reasons unless the request sets
`reasoning_effort: "none"`, and then returns `choices[0].message.content` as a list of chunks:
`[{"type": "thinking", ...}, {"type": "text", "text": "..."}]`. Replies that call tools carry a thinking chunk
too. Conductor's Mistral provider (`ai/src/main/java/org/conductoross/conductor/ai/providers/mistral/MistralAI.java`
in conductor-oss) uses Spring AI's `MistralAiChatModel`, which builds the reply from
`ChatCompletionMessage.content()`. In Spring AI 1.0.x and 1.1.x that method throws
`IllegalStateException("The content is not a string!")` for anything but a string. The provider also has no
way to send `reasoning_effort`. Spring AI added thinking chunks and `reasoning_effort` in 2.0.0
(spring-projects/spring-ai#5019 tracked the same failure for Magistral), but Spring AI 2.x requires Spring
Boot 4, and Conductor is on Spring Boot 3 (OSS pins Spring AI 1.1.6).
Mistral's other current models (Large 3, Medium 3.5, Small 4) return plain strings unless reasoning is
requested, which is why this didn't surface before Large 4. No conductor-oss issue or PR mentioned it as of
2026-10-24.

**2. Gzip, every Mistral model (open-source releases and Orkes builds before 5.5.7).** The provider sets
`Accept-Encoding: gzip, deflate` by hand on its HTTP client. OkHttp only decompresses transparently when it
adds that header itself, so Mistral's gzipped body reaches Jackson as raw bytes (`0x1F 0x8B`, hence
"CTRL-CHAR, code 31"). Orkes fixed it in release 5.5.7 (Oct 8) with an
interceptor that strips the header. The open-source fix, conductor-oss/conductor#1198,
was approved on 2026-06-22 and is still open.

## What works today

1. **HTTP task to Mistral's API** (what the benchmark uses): works on every platform, keeps the key in a
   Conductor secret, and lets you set `reasoning_effort` per call. You parse the reply yourself (the
   benchmark's `ml4_normalize` worker handles string and chunked content).
2. **Conductor OSS `litellm` provider** with a LiteLLM proxy in front of Mistral (`env/litellm/config.yaml`):
   built-in `LLM_CHAT_COMPLETE` tasks work because LiteLLM moves the thinking text to `reasoning_content` and
   returns the answer as a string. Define two aliases to choose the reasoning mode, e.g. `mistral-large-4`
   (thinking on) and `mistral-large-4-fast` (`reasoning_effort: none`). Conductor's `reasoningTokens` output
   isn't populated on this path. The Orkes server doesn't include the `litellm` provider.

## Reproduce

```bash
# Developer Edition / any Orkes cluster (Mistral integration "ml4_mistral" with both models)
.venv/bin/python scripts/run_native_check.py developer-edition ml4_mistral openai gpt-4.1

# Conductor OSS (keys from env vars MISTRAL_API_KEY / OPENAI_API_KEY)
CONDUCTOR_ENV_FILE=/dev/null CONDUCTOR_SERVER_URL=http://localhost:8080/api \
  .venv/bin/python scripts/run_native_check.py oss-3.32.5 mistral openai gpt-4.1
```
