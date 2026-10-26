"""Idempotent Developer Edition setup for the benchmark.

- secrets ml4_mistral_api_key / ml4_openai_api_key (used by HTTP tasks)
- AI integrations ml4_mistral (built-in Mistral connector) and ml4_openai, with models
Never prints key material."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "workers"))
from conductor_api import Conductor  # noqa: E402

MISTRAL_KEY = os.environ.get("MISTRAL_API_KEY", "").strip()
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
if not (MISTRAL_KEY and OPENAI_KEY):
    sys.exit("Set MISTRAL_API_KEY and OPENAI_API_KEY")

MISTRAL_MODELS = ["mistral-large-4", "mistral-large-2512", "mistral-medium-latest", "mistral-small-latest"]
OPENAI_MODELS = ["gpt-6.1-sol", "gpt-6-astra"]


def mask(o):
    if isinstance(o, dict):
        return {k: ("***" if k in ("api_key", "configuration") else mask(v)) for k, v in o.items()}
    if isinstance(o, list):
        return [mask(x) for x in o]
    return o


def main():
    c = Conductor()
    for name, val in (("ml4_mistral_api_key", MISTRAL_KEY), ("ml4_openai_api_key", OPENAI_KEY)):
        # Developer Edition stores the request body verbatim, so send the bare value (no JSON quotes).
        # Overwriting an existing secret didn't always stick, so delete it first.
        c.delete(f"/secrets/{name}")
        r = c.s.put(c.api + f"/secrets/{name}", data=val.encode(),
                    headers={**c._headers(), "Content-Type": "text/plain"}, timeout=30)
        print("secret", name, r.status_code, r.text[:120] if not r.ok else "ok")

    providers = {
        "ml4_mistral": ("mistral", MISTRAL_KEY, MISTRAL_MODELS, "Mistral (built-in connector) for the Large 4 benchmark"),
        "ml4_openai": ("openai", OPENAI_KEY, OPENAI_MODELS, "OpenAI for the Mistral Large 4 benchmark"),
    }
    for name, (ptype, key, models, desc) in providers.items():
        body = {"type": ptype, "category": "AI_MODEL", "description": desc, "enabled": True,
                "configuration": {"api_key": key}}
        r = c.post(f"/integrations/provider/{name}", json=body)
        print("integration", name, r.status_code, "ok" if r.ok else r.text[:200])
        for m in models:
            r = c.post(f"/integrations/provider/{name}/integration/{m}",
                       json={"description": m, "enabled": True})
            print("   model", m, r.status_code, "ok" if r.ok else r.text[:200])
        r = c.get(f"/integrations/provider/{name}/integration")
        print("   now:", [x.get("api") for x in r.json()] if r.ok else r.text[:200])
    print("secrets now:", c.get("/secrets").json())


if __name__ == "__main__":
    main()
