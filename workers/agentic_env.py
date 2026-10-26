"""Deterministic tool environment and trace scoring for the agentic eval set.

Implements the agentic rules in evals/SCHEMA.md:
- tool calls are answered from per-tool `cases` (first match wins) or the tool's `default`
- argument matching is a subset match after normalization (strings trimmed and casefolded,
  numbers compared numerically, lists compared as unordered multisets, dicts as subsets)
- a trace passes when every required call was made, no forbidden call was made, the final
  answer passes the include/exclude checks and the agent finished within max_turns
Pure stdlib so the harness worker and the verify script share one implementation."""
import json
import re


def normalize(v):
    """Strings trimmed and casefolded, numbers as float, lists/dicts recursively."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        return v.strip().casefold()
    if isinstance(v, (list, tuple)):
        return [normalize(x) for x in v]
    if isinstance(v, dict):
        return {str(k).strip().casefold(): normalize(x) for k, x in v.items()}
    return v


def _as_number(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, float):
        return v
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").strip())
        except ValueError:
            return None
    return None


def _value_matches(expected, actual):
    """Compare two already-normalized values. Dicts: subset. Lists: unordered multiset."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(k in actual and _value_matches(v, actual[k]) for k, v in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        remaining = list(actual)
        for item in expected:
            for i, cand in enumerate(remaining):
                if _value_matches(item, cand):
                    del remaining[i]
                    break
            else:
                return False
        return True
    if expected == actual:
        return True
    # numbers compared numerically, including numeric strings such as "200" vs 200
    a, b = _as_number(expected), _as_number(actual)
    return a is not None and b is not None and a == b


def match_args(expected: dict, actual: dict) -> bool:
    """True when every key in `expected` is present in `actual` with a matching value."""
    if isinstance(actual, str):
        actual = _parse_args(actual)
        if actual is None:
            return False
    return _value_matches(normalize(expected or {}), normalize(actual or {}))


def _parse_args(args):
    if isinstance(args, dict):
        return args
    if args is None or args == "":
        return {}
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _tool_spec(environment: dict, name: str):
    if name in environment:
        return environment[name]
    folded = {k.casefold(): k for k in environment}
    key = folded.get((name or "").strip().casefold())
    return environment[key] if key else None


def run_tool(environment: dict, name: str, args: dict) -> dict:
    """Answer one tool call from the scenario environment."""
    spec = _tool_spec(environment, name)
    if spec is None:
        return {"result": {"error": f"unknown tool {name}"}, "side_effect": False, "known_tool": False}
    side_effect = bool(spec.get("side_effect", False))
    parsed = _parse_args(args)
    if parsed is None:
        return {"result": {"error": "arguments must be a JSON object"}, "side_effect": side_effect,
                "known_tool": True}
    for case in spec.get("cases", []):
        if match_args(case.get("match", {}), parsed):
            return {"result": case["result"], "side_effect": side_effect, "known_tool": True}
    return {"result": spec.get("default", {"error": "no matching record"}), "side_effect": side_effect,
            "known_tool": True}


def _text_check(text: str, check: str) -> bool:
    if check.startswith("re:"):
        return re.search(check[3:], text, re.IGNORECASE | re.DOTALL) is not None
    return check.casefold() in text.casefold()


def _call_matches(rule: dict, call: dict) -> bool:
    if (call.get("tool") or "").strip().casefold() != (rule.get("tool") or "").strip().casefold():
        return False
    return match_args(rule.get("args", {}), call.get("args") or {})


def score_trace(scoring: dict, calls: list, final_text: str, turns: int) -> dict:
    """Score an agent run. calls = [{"tool": name, "args": {...}}] in the order made."""
    calls = calls or []
    text = final_text or ""
    missing = [r for r in scoring.get("required_calls", []) if not any(_call_matches(r, c) for c in calls)]
    forbidden = [f for f in scoring.get("forbidden_calls", []) if any(_call_matches(f, c) for c in calls)]
    include_failed = [chk for chk in scoring.get("final_must_include", []) if not _text_check(text, chk)]
    exclude_failed = [chk for chk in scoring.get("final_must_not_include", []) if _text_check(text, chk)]
    within = turns <= int(scoring.get("max_turns", 10))
    return {
        "pass": not missing and not forbidden and not include_failed and not exclude_failed and within,
        "missing_required": missing,
        "forbidden_made": forbidden,
        "final_include_failed": include_failed,
        "final_exclude_failed": exclude_failed,
        "within_max_turns": within,
    }
