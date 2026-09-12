"""OpenAI-compatible chat completions over urllib, streamed as SSE."""

import asyncio
import json
import urllib.error
import urllib.request

RETRIES = 3


def _parse_args(text: str) -> dict:
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {"raw_arguments": text}


def _usage(u: dict) -> dict:
    return {k: u.get(k) or 0 for k in ("prompt_tokens", "completion_tokens", "total_tokens")}


async def chat(config, messages: list[dict], tools: list[dict] | None = None, stream: bool = True):
    """Yield ("text", str) | ("tool_call", {"id","name","arguments"}) | ("usage", dict) | ("error", str)."""
    body = {"model": config.model_name, "messages": messages, "temperature": config.temperature, "stream": stream}
    if stream:
        body["stream_options"] = {"include_usage": True}
    if tools:
        body["tools"] = [{"type": "function", "function": t} for t in tools]
        body["tool_choice"] = "auto"
    req = urllib.request.Request(
        config.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.api_key}"},
    )

    for attempt in range(RETRIES + 1):
        try:
            resp = urllib.request.urlopen(req, timeout=600)
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < RETRIES:
                await asyncio.sleep(2**attempt)
                continue
            yield ("error", f"API error {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
            return
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < RETRIES:
                await asyncio.sleep(2**attempt)
                continue
            yield ("error", f"Connection error: {e}")
            return

    if not stream:
        data = json.loads(resp.read())
        msg = data["choices"][0]["message"]
        if msg.get("content"):
            yield ("text", msg["content"])
        for tc in msg.get("tool_calls") or []:
            yield ("tool_call", {"id": tc["id"], "name": tc["function"]["name"], "arguments": _parse_args(tc["function"].get("arguments", ""))})
        if data.get("usage"):
            yield ("usage", _usage(data["usage"]))
        return

    calls: dict[int, dict] = {}  # index -> partial tool call, arguments accumulate across chunks
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        chunk = json.loads(payload)
        if chunk.get("usage"):
            yield ("usage", _usage(chunk["usage"]))
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if delta.get("content"):
                yield ("text", delta["content"])
            for tc in delta.get("tool_calls") or []:
                call = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                fn = tc.get("function") or {}
                call["id"] = tc.get("id") or call["id"]
                call["name"] = fn.get("name") or call["name"]
                call["arguments"] += fn.get("arguments") or ""
    for call in calls.values():
        yield ("tool_call", {**call, "arguments": _parse_args(call["arguments"])})
