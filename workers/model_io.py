"""Request bodies and response normalization for the four model routes.

Routes:
  mistral_chat   POST https://api.mistral.ai/v1/chat/completions
  openai_chat    POST https://api.openai.com/v1/chat/completions
  mistral_search POST https://api.mistral.ai/v1/conversations   (built-in web_search tool)
  openai_search  POST https://api.openai.com/v1/responses       (built-in web_search tool)

The HTTP call itself is a Conductor HTTP task; these functions only shape the request
and turn whatever came back into one common result shape."""
import json
import re

MISTRAL = "https://api.mistral.ai"
OPENAI = "https://api.openai.com"

ROUTES = {
    "mistral_chat": ("mistral", MISTRAL + "/v1/chat/completions"),
    "openai_chat": ("openai", OPENAI + "/v1/chat/completions"),
    "mistral_search": ("mistral", MISTRAL + "/v1/conversations"),
    "openai_search": ("openai", OPENAI + "/v1/responses"),
    # GPT-6.1 Sol only accepts function tools together with reasoning on the Responses API
    "openai_agent": ("openai", OPENAI + "/v1/responses"),
}

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")


def route_for(config, mode):
    """mode: 'chat', 'search' or 'agentic'."""
    if mode == "agentic":
        return "openai_agent" if config["provider"] == "openai" else "mistral_chat"
    return f"{config['provider']}_{mode}"


def _responses_tools(tools):
    """Chat-format function tools -> Responses API function tools."""
    out = []
    for t in tools or []:
        f = t.get("function", t)
        out.append({"type": "function", "name": f["name"], "description": f.get("description", ""),
                    "parameters": f.get("parameters", {"type": "object", "properties": {}})})
    return out


def _split_system(messages):
    system = [m["content"] for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    return ("\n\n".join(system) if system else None), rest


def build_request(route, model, messages, reasoning_effort=None, max_tokens=None, tools=None,
                  response_format=None):
    provider, uri = ROUTES[route]
    if route == "mistral_chat":
        body = {"model": model, "messages": messages}
        if max_tokens:
            body["max_tokens"] = max_tokens
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
            body["parallel_tool_calls"] = True
        if response_format:
            body["response_format"] = response_format
    elif route == "openai_chat":
        body = {"model": model, "messages": messages, "store": False}
        if max_tokens:
            body["max_completion_tokens"] = max_tokens
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        if tools:
            body["tools"] = tools
            body["parallel_tool_calls"] = True
        if response_format:
            body["response_format"] = response_format
    elif route == "mistral_search":
        system, rest = _split_system(messages)
        inputs = rest[0]["content"] if len(rest) == 1 and rest[0]["role"] == "user" else \
            [{"role": m["role"], "content": m["content"]} for m in rest]
        args = {}
        if max_tokens:
            args["max_tokens"] = max_tokens
        if reasoning_effort:
            args["reasoning_effort"] = reasoning_effort
        body = {"model": model, "store": False, "inputs": inputs, "tools": [{"type": "web_search"}]}
        if args:
            body["completion_args"] = args
        if system:
            body["instructions"] = system
    elif route == "openai_search":
        system, rest = _split_system(messages)
        inp = rest[0]["content"] if len(rest) == 1 and rest[0]["role"] == "user" else \
            [{"role": m["role"], "content": m["content"]} for m in rest]
        body = {"model": model, "input": inp, "tools": [{"type": "web_search"}], "store": False}
        if system:
            body["instructions"] = system
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        if max_tokens:
            body["max_output_tokens"] = max_tokens
    elif route == "openai_agent":
        system, rest = _split_system(messages)
        body = {"model": model, "input": rest, "store": False, "include": ["reasoning.encrypted_content"],
                "tools": _responses_tools(tools), "parallel_tool_calls": True}
        if system:
            body["instructions"] = system
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        if max_tokens:
            body["max_output_tokens"] = max_tokens
    else:
        raise ValueError(f"unknown route {route}")
    return {"provider": provider, "uri": uri, "body": body}


def _text_and_thinking(content):
    """Mistral content is a string, or a list of chunks (thinking / text / tool_reference ...)."""
    if content is None:
        return "", "", []
    if isinstance(content, str):
        return content, "", []
    text, thinking, refs = [], [], []
    for ch in content:
        t = ch.get("type")
        if t == "text":
            text.append(ch.get("text", ""))
        elif t == "thinking":
            for sub in ch.get("thinking", []) or []:
                if isinstance(sub, dict):
                    thinking.append(sub.get("text", ""))
                else:
                    thinking.append(str(sub))
        elif t == "tool_reference":
            if ch.get("url"):
                refs.append(ch["url"])
    return "".join(text), "".join(thinking), refs


def _tool_calls(raw):
    out = []
    for tc in raw or []:
        fn = tc.get("function", {})
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {"_unparsed": args}
        out.append({"id": tc.get("id"), "name": fn.get("name"), "arguments": args or {}})
    return out


def _urls(text):
    return [u.rstrip(".,;:") for u in URL_RE.findall(text or "")]


def normalize(route, response, http_status=None, task_status=None, reason=None,
              start_time=None, end_time=None, scheduled_time=None, retry_count=None):
    """Turn an HTTP task's response into the common result shape."""
    res = {
        "route": route, "ok": False, "http_status": None, "error": None,
        "text": "", "thinking_chars": 0, "tool_calls": [], "citations": [],
        "usage": {"input_tokens": None, "output_tokens": None, "reasoning_tokens": None,
                  "cached_input_tokens": None, "search_calls": None, "search_tokens": None},
        "finish_reason": None,
        "latency_ms": (end_time - start_time) if (start_time and end_time) else None,
        "queue_ms": (start_time - scheduled_time) if (start_time and scheduled_time) else None,
        "retries": retry_count or 0,
        "assistant_message": None,
    }
    response = response or {}
    body = response.get("body")
    res["http_status"] = response.get("statusCode") or http_status
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"_raw": body[:2000]}
    if not isinstance(body, dict) or res["http_status"] not in (200, 201):
        err = None
        if isinstance(body, dict):
            err = body.get("message") or body.get("error") or body.get("detail") or body.get("_raw")
        res["error"] = str(err or reason or f"HTTP {res['http_status']} ({task_status})")[:1000]
        return res
    u = body.get("usage") or {}
    try:
        if route in ("mistral_chat", "openai_chat"):
            choice = (body.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            text, thinking, _ = _text_and_thinking(msg.get("content"))
            res["text"], res["thinking_chars"] = text, len(thinking)
            res["tool_calls"] = _tool_calls(msg.get("tool_calls"))
            res["finish_reason"] = choice.get("finish_reason")
            res["usage"].update({
                "input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens"),
                "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
                "cached_input_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0})
            am = {"role": "assistant", "content": text if (text or route == "mistral_chat") else None}
            if msg.get("tool_calls"):
                am["tool_calls"] = msg["tool_calls"]
            res["assistant_message"] = am
        elif route == "mistral_search":
            calls, text_parts, refs = 0, [], []
            for o in body.get("outputs") or []:
                if o.get("type") == "tool.execution":
                    calls += 1
                elif o.get("type") == "message.output":
                    t, th, r = _text_and_thinking(o.get("content"))
                    text_parts.append(t)
                    res["thinking_chars"] += len(th)
                    refs += r
            res["text"] = "".join(text_parts)
            res["citations"] = list(dict.fromkeys(refs + _urls(res["text"])))
            res["finish_reason"] = "stop"
            res["usage"].update({
                "input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens"),
                "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
                "search_calls": (u.get("connectors") or {}).get("web_search", calls),
                "search_tokens": u.get("connector_tokens") or 0})
        elif route == "openai_agent":
            text_parts, calls, items = [], [], []
            for o in body.get("output") or []:
                items.append(o)
                if o.get("type") == "function_call":
                    args = o.get("arguments")
                    try:
                        args = json.loads(args) if isinstance(args, str) and args.strip() else (args or {})
                    except json.JSONDecodeError:
                        args = {"_unparsed": args}
                    calls.append({"id": o.get("call_id"), "name": o.get("name"), "arguments": args})
                elif o.get("type") == "message":
                    for c in o.get("content") or []:
                        if c.get("type") == "output_text":
                            text_parts.append(c.get("text", ""))
            res["text"], res["tool_calls"] = "".join(text_parts), calls
            res["finish_reason"] = body.get("status")
            res["usage"].update({
                "input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
                "reasoning_tokens": (u.get("output_tokens_details") or {}).get("reasoning_tokens") or 0,
                "cached_input_tokens": (u.get("input_tokens_details") or {}).get("cached_tokens") or 0})
            # output items (reasoning incl. encrypted content, function calls, messages) go back as input
            res["assistant_message"] = {"items": items}
        elif route == "openai_search":
            calls, text_parts, refs = 0, [], []
            for o in body.get("output") or []:
                if o.get("type") == "web_search_call":
                    calls += 1
                elif o.get("type") == "message":
                    for c in o.get("content") or []:
                        if c.get("type") == "output_text":
                            text_parts.append(c.get("text", ""))
                            refs += [a.get("url") for a in c.get("annotations") or [] if a.get("type") == "url_citation"]
            res["text"] = "".join(text_parts)
            res["citations"] = list(dict.fromkeys([r for r in refs if r] + _urls(res["text"])))
            res["finish_reason"] = body.get("status")
            res["usage"].update({
                "input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
                "reasoning_tokens": (u.get("output_tokens_details") or {}).get("reasoning_tokens") or 0,
                "cached_input_tokens": (u.get("input_tokens_details") or {}).get("cached_tokens") or 0,
                "search_calls": calls, "search_tokens": 0})
        res["ok"] = True
    except Exception as e:  # keep the run going; record what broke
        res["error"] = f"normalize failed: {type(e).__name__}: {e}"[:1000]
    return res
