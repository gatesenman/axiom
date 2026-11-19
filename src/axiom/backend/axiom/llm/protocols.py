"""Protocol adapters.

OpenAI Chat Completions (and Responses), Anthropic Messages, Gemini
generateContent, Cohere v2, and AWS Bedrock Converse. Other vendors in the
registry are mapped onto one of these.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlsplit

from axiom.llm.types import ChatRequest, ChatResult, Connection, ToolSpec, Usage


ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class PreparedCall:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes
    sign: bool = False
    aws_service: str = ""


def parse_arguments(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": raw}


def normalize_tool_call(raw: dict, *, index: int = 0) -> dict:
    if "function" in raw and isinstance(raw["function"], dict):
        function = raw["function"]
        name = function.get("name") or ""
        arguments = parse_arguments(function.get("arguments"))
    else:
        name = raw.get("name") or ""
        arguments = parse_arguments(raw.get("arguments") if "arguments" in raw else raw.get("input"))
    identifier = raw.get("id") or raw.get("toolUseId") or raw.get("call_id") or f"call_{index}_{name}"
    return {"id": str(identifier), "name": str(name), "arguments": arguments}


def extract_json(text: str) -> tuple[str, bool]:
    """Return a JSON value found in text. The flag is true when the original text was not itself JSON."""
    stripped = (text or "").strip()
    if not stripped:
        return text, False
    if _is_json(stripped):
        return stripped, False
    fenced = stripped
    if "```" in fenced:
        inner = fenced.split("```", 2)[1]
        if inner.startswith("json"):
            inner = inner[4:]
        inner = inner.strip()
        if _is_json(inner):
            return inner, True
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        if start < 0:
            continue
        snippet = _balanced(stripped[start:], opener, closer)
        if snippet and _is_json(snippet):
            return snippet, True
    return text, False


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
    except json.JSONDecodeError:
        return False
    return True


def _balanced(text: str, opener: str, closer: str) -> str:
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[: index + 1]
    return ""


def _json_instruction(request: ChatRequest) -> str:
    if request.json_schema:
        return "Respond with one JSON value matching this schema and nothing else: " + json.dumps(request.json_schema, ensure_ascii=False)
    return "Respond with one JSON value and nothing else."


def _localhost(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    return host in {"localhost", "127.0.0.1", "::1"}


def _require_key(conn: Connection) -> None:
    from axiom.errors import AxiomError

    if conn.api_key or conn.key_optional or _localhost(conn.base_url):
        return
    if conn.protocol == "bedrock" and conn.bedrock_mode == "native":
        return
    raise AxiomError("还没有填写 API key。", "No API key has been saved.", code="llm")


def prepare(conn: Connection, request: ChatRequest) -> PreparedCall:
    protocol = conn.protocol
    if protocol == "anthropic":
        return _prepare_anthropic(conn, request)
    if protocol == "gemini":
        return _prepare_gemini(conn, request)
    if protocol == "bedrock" and conn.bedrock_mode != "gateway":
        return _prepare_bedrock(conn, request)
    if protocol == "cohere":
        return _prepare_cohere(conn, request)
    return _prepare_openai(conn, request)


def parse_payload(conn: Connection, payload: dict) -> tuple[str, list[dict], Usage, str]:
    protocol = _wire_protocol(conn)
    if protocol == "anthropic":
        return _parse_anthropic(payload)
    if protocol == "gemini":
        return _parse_gemini(payload)
    if protocol == "bedrock":
        return _parse_bedrock(payload)
    if protocol == "cohere":
        return _parse_cohere(payload)
    if conn.api_style == "responses" and protocol == "openai":
        return _parse_responses(payload)
    return _parse_openai(payload)


def _wire_protocol(conn: Connection) -> str:
    if conn.protocol == "bedrock" and conn.bedrock_mode == "gateway":
        return "openai"
    return conn.protocol


def apply_result(conn: Connection, request: ChatRequest, text: str, tool_calls: list[dict], usage: Usage, finish: str, latency_ms: int) -> ChatResult:
    fallback = False
    if request.wants_json and not tool_calls:
        extracted, fallback = extract_json(text)
        if _is_json(extracted):
            text = extracted
        else:
            fallback = False
    prompt = usage.prompt_tokens
    completion = usage.completion_tokens
    cost = (prompt / 1_000_000) * conn.input_usd_per_mtok + (completion / 1_000_000) * conn.output_usd_per_mtok
    return ChatResult(
        text=text or "",
        tool_calls=tool_calls,
        usage=usage,
        latency_ms=latency_ms,
        model=request.model or conn.model,
        provider=conn.provider_id,
        finish_reason=finish,
        protocol=_wire_protocol(conn),
        json_fallback=fallback,
        cost_usd=round(cost, 8),
    )


def _bearer_headers(conn: Connection) -> dict[str, str]:
    headers = {"content-type": "application/json"}
    _require_key(conn)
    if conn.api_key:
        headers["authorization"] = f"Bearer {conn.api_key}"
    if conn.provider_id == "openrouter":
        headers["x-title"] = "Axiom"
        headers["http-referer"] = "https://axiom.local"
    return headers


def _openai_messages(request: ChatRequest, *, hint_json: bool) -> list[dict]:
    messages: list[dict] = []
    if hint_json:
        messages.append({"role": "system", "content": _json_instruction(request)})
    for item in request.messages:
        if item.role == "tool":
            messages.append({"role": "tool", "tool_call_id": item.tool_call_id, "content": item.content})
            continue
        if item.tool_calls:
            calls = []
            for index, raw in enumerate(item.tool_calls):
                normalized = normalize_tool_call(raw, index=index)
                calls.append(
                    {
                        "id": normalized["id"],
                        "type": "function",
                        "function": {"name": normalized["name"], "arguments": json.dumps(normalized["arguments"], ensure_ascii=False)},
                    }
                )
            messages.append({"role": "assistant", "content": item.content or None, "tool_calls": calls})
            continue
        messages.append({"role": item.role, "content": item.content})
    return messages


def _openai_tools(tools: list[ToolSpec] | None) -> list[dict] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters or {"type": "object", "properties": {}},
            },
        }
        for tool in tools
    ]


def _prepare_openai(conn: Connection, request: ChatRequest) -> PreparedCall:
    root = conn.base_url.rstrip("/")
    if conn.auth == "azure":
        version = quote(conn.api_version or "2024-10-21", safe="")
        deployment = quote(request.model or conn.model, safe="")
        if "/deployments/" in root:
            url = f"{root}/chat/completions?api-version={version}"
        else:
            url = f"{root}/openai/deployments/{deployment}/chat/completions?api-version={version}"
        headers = {"content-type": "application/json", "api-key": conn.api_key}
        _require_key(conn)
        body = _openai_chat_body(conn, request, include_model=False)
        return PreparedCall("POST", url, headers, json.dumps(body).encode())
    if conn.api_style == "responses":
        url = f"{root}/responses"
        body = _responses_body(conn, request)
    else:
        url = f"{root}/chat/completions"
        body = _openai_chat_body(conn, request, include_model=True)
    return PreparedCall("POST", url, _bearer_headers(conn), json.dumps(body).encode())


def _openai_chat_body(conn: Connection, request: ChatRequest, *, include_model: bool) -> dict:
    body: dict = {
        "messages": _openai_messages(request, hint_json=request.wants_json and not conn.supports_json),
        "max_tokens": request.max_tokens,
    }
    if include_model:
        body["model"] = request.model
    if not request.omit_temperature:
        body["temperature"] = request.temperature
    tools = _openai_tools(request.tools)
    if tools:
        body["tools"] = tools
    if request.wants_json and conn.supports_json and not request.tools:
        if request.json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "axiom", "schema": request.json_schema, "strict": False},
            }
        else:
            body["response_format"] = {"type": "json_object"}
    if request.stream:
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
    return body


def _responses_body(conn: Connection, request: ChatRequest) -> dict:
    items = []
    for message in request.messages:
        if message.role == "tool":
            items.append({"type": "function_call_output", "call_id": message.tool_call_id, "output": message.content})
        else:
            items.append({"role": message.role, "content": message.content})
    if request.wants_json and not conn.supports_json:
        items.insert(0, {"role": "system", "content": _json_instruction(request)})
    body: dict = {"model": request.model, "input": items, "max_output_tokens": request.max_tokens}
    if not request.omit_temperature:
        body["temperature"] = request.temperature
    tools = _openai_tools(request.tools)
    if tools:
        body["tools"] = tools
    if request.wants_json and conn.supports_json and request.json_schema and not request.tools:
        body["text"] = {"format": {"type": "json_schema", "name": "axiom", "schema": request.json_schema, "strict": False}}
    if request.stream:
        body["stream"] = True
    return body


def _prepare_anthropic(conn: Connection, request: ChatRequest) -> PreparedCall:
    _require_key(conn)
    root = conn.base_url.rstrip("/") or "https://api.anthropic.com"
    url = f"{root}/v1/messages"
    system_parts = [item.content for item in request.messages if item.role == "system" and item.content]
    if request.wants_json and not conn.supports_json:
        system_parts.append(_json_instruction(request))
    elif request.wants_json:
        system_parts.append(_json_instruction(request))
    dialog: list[dict] = []
    for item in request.messages:
        if item.role == "system":
            continue
        if item.role == "tool":
            dialog.append(
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": item.tool_call_id, "content": item.content}],
                }
            )
            continue
        if item.tool_calls:
            blocks: list[dict] = []
            if item.content:
                blocks.append({"type": "text", "text": item.content})
            for index, raw in enumerate(item.tool_calls):
                normalized = normalize_tool_call(raw, index=index)
                blocks.append({"type": "tool_use", "id": normalized["id"], "name": normalized["name"], "input": normalized["arguments"]})
            dialog.append({"role": "assistant", "content": blocks})
            continue
        dialog.append({"role": item.role if item.role in {"user", "assistant"} else "user", "content": item.content})
    if not dialog:
        dialog = [{"role": "user", "content": "ping"}]
    body: dict = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "messages": dialog,
    }
    if not request.omit_temperature:
        body["temperature"] = request.temperature
    if system_parts:
        body["system"] = "\n".join(system_parts)
    if request.tools:
        body["tools"] = [
            {"name": tool.name, "description": tool.description, "input_schema": tool.parameters or {"type": "object", "properties": {}}}
            for tool in request.tools
        ]
    if request.stream:
        body["stream"] = True
    headers = {
        "content-type": "application/json",
        "x-api-key": conn.api_key,
        "anthropic-version": ANTHROPIC_VERSION,
    }
    return PreparedCall("POST", url, headers, json.dumps(body).encode())


def _gemini_parts(message) -> list[dict]:
    if message.role == "tool":
        try:
            payload = json.loads(message.content) if message.content else {}
        except json.JSONDecodeError:
            payload = {"result": message.content}
        if not isinstance(payload, dict):
            payload = {"result": payload}
        return [{"functionResponse": {"name": message.name or "tool", "response": payload}}]
    if message.tool_calls:
        parts = []
        if message.content:
            parts.append({"text": message.content})
        for index, raw in enumerate(message.tool_calls):
            normalized = normalize_tool_call(raw, index=index)
            parts.append({"functionCall": {"name": normalized["name"], "args": normalized["arguments"]}})
        return parts
    return [{"text": message.content}]


def _prepare_gemini(conn: Connection, request: ChatRequest) -> PreparedCall:
    _require_key(conn)
    root = conn.base_url.rstrip("/") or "https://generativelanguage.googleapis.com/v1beta"
    model = (request.model or conn.model).removeprefix("models/")
    action = "streamGenerateContent" if request.stream else "generateContent"
    url = f"{root}/models/{quote(model, safe='')}:{action}?key={quote(conn.api_key, safe='')}"
    if request.stream:
        url += "&alt=sse"
    system = [item.content for item in request.messages if item.role == "system" and item.content]
    if request.wants_json and not conn.supports_json:
        system.append(_json_instruction(request))
    contents = []
    for item in request.messages:
        if item.role == "system":
            continue
        role = "model" if item.role == "assistant" else "user"
        contents.append({"role": role, "parts": _gemini_parts(item)})
    if not contents:
        contents = [{"role": "user", "parts": [{"text": "ping"}]}]
    generation: dict = {"maxOutputTokens": request.max_tokens}
    if not request.omit_temperature:
        generation["temperature"] = request.temperature
    if request.wants_json and conn.supports_json and not request.tools:
        generation["responseMimeType"] = "application/json"
        if request.json_schema:
            generation["responseSchema"] = request.json_schema
    body: dict = {"contents": contents, "generationConfig": generation}
    if system:
        body["systemInstruction"] = {"parts": [{"text": "\n".join(system)}]}
    if request.tools:
        body["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters or {"type": "object", "properties": {}},
                    }
                    for tool in request.tools
                ]
            }
        ]
    headers = {"content-type": "application/json", "x-goog-api-key": conn.api_key}
    return PreparedCall("POST", url, headers, json.dumps(body).encode())


def _prepare_bedrock(conn: Connection, request: ChatRequest) -> PreparedCall:
    from axiom.errors import AxiomError

    if not conn.api_key or not conn.aws_secret:
        raise AxiomError(
            "Bedrock 需要 Access Key 和 Secret Key。",
            "Bedrock needs an access key and a secret key.",
            code="llm",
        )
    region = conn.region or "us-east-1"
    model = quote(request.model or conn.model, safe="")
    url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{model}/converse"
    system = [{"text": item.content} for item in request.messages if item.role == "system" and item.content]
    if request.wants_json:
        system.append({"text": _json_instruction(request)})
    messages = []
    for item in request.messages:
        if item.role == "system":
            continue
        if item.role == "tool":
            messages.append(
                {
                    "role": "user",
                    "content": [{"toolResult": {"toolUseId": item.tool_call_id, "content": [{"text": item.content}]}}],
                }
            )
            continue
        blocks: list[dict] = []
        if item.content:
            blocks.append({"text": item.content})
        for index, raw in enumerate(item.tool_calls or []):
            normalized = normalize_tool_call(raw, index=index)
            blocks.append({"toolUse": {"toolUseId": normalized["id"], "name": normalized["name"], "input": normalized["arguments"]}})
        role = "assistant" if item.role == "assistant" else "user"
        messages.append({"role": role, "content": blocks or [{"text": ""}]})
    if not messages:
        messages = [{"role": "user", "content": [{"text": "ping"}]}]
    inference: dict = {"maxTokens": request.max_tokens}
    if not request.omit_temperature:
        inference["temperature"] = request.temperature
    body: dict = {"messages": messages, "inferenceConfig": inference}
    if system:
        body["system"] = system
    if request.tools:
        body["toolConfig"] = {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": {"json": tool.parameters or {"type": "object", "properties": {}}},
                    }
                }
                for tool in request.tools
            ]
        }
    payload = json.dumps(body).encode()
    headers = aws_sign(
        "POST",
        url,
        {"content-type": "application/json"},
        payload,
        access_key=conn.api_key,
        secret_key=conn.aws_secret,
        session_token=conn.aws_session,
        region=region,
        service="bedrock",
    )
    return PreparedCall("POST", url, headers, payload, sign=True, aws_service="bedrock")


def _prepare_cohere(conn: Connection, request: ChatRequest) -> PreparedCall:
    root = conn.base_url.rstrip("/") or "https://api.cohere.ai"
    if root.endswith("/v2"):
        url = f"{root}/chat"
    elif "/compatibility/" in root:
        url = f"{root}/chat/completions"
        return _prepare_openai(conn, request)
    else:
        url = f"{root}/v2/chat"
    messages = []
    if request.wants_json:
        messages.append({"role": "system", "content": _json_instruction(request)})
    for item in request.messages:
        if item.role == "tool":
            messages.append({"role": "tool", "tool_call_id": item.tool_call_id, "content": item.content})
        else:
            messages.append({"role": item.role, "content": item.content})
    body: dict = {"model": request.model, "messages": messages}
    if not request.omit_temperature:
        body["temperature"] = request.temperature
    if request.tools:
        body["tools"] = _openai_tools(request.tools)
    if request.wants_json and request.json_schema and not request.tools:
        body["response_format"] = {"type": "json_object", "schema": request.json_schema}
    return PreparedCall("POST", url, _bearer_headers(conn), json.dumps(body).encode())


def _text_from_content(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content)


def _parse_openai(payload: dict) -> tuple[str, list[dict], Usage, str]:
    choices = payload.get("choices") or [{}]
    choice = choices[0] if choices else {}
    message = choice.get("message") or {}
    tool_calls = [normalize_tool_call(item, index=index) for index, item in enumerate(message.get("tool_calls") or [])]
    usage_raw = payload.get("usage") or {}
    usage = Usage(int(usage_raw.get("prompt_tokens") or 0), int(usage_raw.get("completion_tokens") or 0))
    return _text_from_content(message.get("content")), tool_calls, usage, str(choice.get("finish_reason") or "")


def _parse_responses(payload: dict) -> tuple[str, list[dict], Usage, str]:
    texts: list[str] = []
    tool_calls: list[dict] = []
    for item in payload.get("output") or []:
        kind = item.get("type")
        if kind == "message":
            for block in item.get("content") or []:
                if block.get("type") in {"output_text", "text"}:
                    texts.append(block.get("text") or "")
        elif kind == "function_call":
            tool_calls.append(normalize_tool_call(item, index=len(tool_calls)))
    if not texts and isinstance(payload.get("output_text"), str):
        texts.append(payload["output_text"])
    usage_raw = payload.get("usage") or {}
    usage = Usage(int(usage_raw.get("input_tokens") or usage_raw.get("prompt_tokens") or 0), int(usage_raw.get("output_tokens") or usage_raw.get("completion_tokens") or 0))
    return "".join(texts), tool_calls, usage, str(payload.get("status") or "")


def _parse_anthropic(payload: dict) -> tuple[str, list[dict], Usage, str]:
    texts: list[str] = []
    tool_calls: list[dict] = []
    for block in payload.get("content") or []:
        if block.get("type") == "text":
            texts.append(block.get("text") or "")
        elif block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "id": str(block.get("id") or f"tool_{len(tool_calls)}"),
                    "name": str(block.get("name") or ""),
                    "arguments": parse_arguments(block.get("input")),
                }
            )
    usage_raw = payload.get("usage") or {}
    usage = Usage(int(usage_raw.get("input_tokens") or 0), int(usage_raw.get("output_tokens") or 0))
    return "".join(texts), tool_calls, usage, str(payload.get("stop_reason") or "")


def _parse_gemini(payload: dict) -> tuple[str, list[dict], Usage, str]:
    texts: list[str] = []
    tool_calls: list[dict] = []
    candidates = payload.get("candidates") or []
    parts = (((candidates[0] if candidates else {}).get("content") or {}).get("parts")) or []
    for index, part in enumerate(parts):
        if "text" in part:
            texts.append(part.get("text") or "")
        call = part.get("functionCall")
        if isinstance(call, dict):
            tool_calls.append(
                {
                    "id": f"gem_{index}_{call.get('name') or 'fn'}",
                    "name": str(call.get("name") or ""),
                    "arguments": parse_arguments(call.get("args")),
                }
            )
    usage_raw = payload.get("usageMetadata") or {}
    usage = Usage(int(usage_raw.get("promptTokenCount") or 0), int(usage_raw.get("candidatesTokenCount") or 0))
    finish = str((candidates[0] if candidates else {}).get("finishReason") or "")
    return "".join(texts), tool_calls, usage, finish


def _parse_bedrock(payload: dict) -> tuple[str, list[dict], Usage, str]:
    message = ((payload.get("output") or {}).get("message") or {})
    texts: list[str] = []
    tool_calls: list[dict] = []
    for block in message.get("content") or []:
        if "text" in block:
            texts.append(block.get("text") or "")
        use = block.get("toolUse")
        if isinstance(use, dict):
            tool_calls.append(
                {
                    "id": str(use.get("toolUseId") or f"bd_{len(tool_calls)}"),
                    "name": str(use.get("name") or ""),
                    "arguments": parse_arguments(use.get("input")),
                }
            )
    usage_raw = payload.get("usage") or {}
    usage = Usage(int(usage_raw.get("inputTokens") or 0), int(usage_raw.get("outputTokens") or 0))
    return "".join(texts), tool_calls, usage, str(payload.get("stopReason") or "")


def _parse_cohere(payload: dict) -> tuple[str, list[dict], Usage, str]:
    message = payload.get("message") or {}
    texts: list[str] = []
    tool_calls: list[dict] = []
    content = message.get("content")
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                texts.append(block.get("text") or "")
            if block.get("type") in {"tool_call", "function"} or "tool_call" in block:
                call = block.get("tool_call") or block
                tool_calls.append(normalize_tool_call(call, index=len(tool_calls)))
    usage_raw = ((payload.get("usage") or {}).get("tokens") or payload.get("usage") or {})
    usage = Usage(
        int(usage_raw.get("input_tokens") or usage_raw.get("prompt_tokens") or 0),
        int(usage_raw.get("output_tokens") or usage_raw.get("completion_tokens") or 0),
    )
    return "".join(texts), tool_calls, usage, str(payload.get("finish_reason") or "")


class StreamAssembler:
    """Fold provider SSE into text, normalized tool calls, and usage."""

    def __init__(self, protocol: str) -> None:
        self.protocol = protocol
        self.text_parts: list[str] = []
        self.tool_calls: dict[int, dict] = {}
        self.usage = Usage()
        self.finish = ""

    def feed(self, data: str) -> None:
        if not data or data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return
        if self.protocol == "anthropic":
            self._anthropic(payload)
        elif self.protocol == "gemini":
            text, calls, usage, finish = _parse_gemini(payload)
            if text:
                self.text_parts.append(text)
            self._merge_calls(calls)
            self._merge_usage(usage)
            if finish:
                self.finish = finish
        elif self.protocol == "responses":
            self._responses(payload)
        else:
            self._openai(payload)

    def result_parts(self) -> tuple[str, list[dict], Usage, str]:
        ordered = [self.tool_calls[key] for key in sorted(self.tool_calls)]
        calls = []
        for item in ordered:
            calls.append(
                {
                    "id": item.get("id") or "",
                    "name": item.get("name") or "",
                    "arguments": parse_arguments(item.get("arguments")),
                }
            )
        return "".join(self.text_parts), calls, self.usage, self.finish

    def _merge_usage(self, usage: Usage) -> None:
        if usage.prompt_tokens or usage.completion_tokens:
            self.usage = usage

    def _merge_calls(self, calls: list[dict]) -> None:
        for index, call in enumerate(calls):
            self.tool_calls[index] = call

    def _openai(self, payload: dict) -> None:
        usage_raw = payload.get("usage") or {}
        if usage_raw:
            self._merge_usage(Usage(int(usage_raw.get("prompt_tokens") or 0), int(usage_raw.get("completion_tokens") or 0)))
        for choice in payload.get("choices") or []:
            if choice.get("finish_reason"):
                self.finish = str(choice["finish_reason"])
            delta = choice.get("delta") or {}
            if delta.get("content"):
                self.text_parts.append(delta["content"])
            for call in delta.get("tool_calls") or []:
                index = int(call.get("index") or 0)
                current = self.tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                if call.get("id"):
                    current["id"] = call["id"]
                function = call.get("function") or {}
                if function.get("name"):
                    current["name"] = function["name"]
                if function.get("arguments"):
                    current["arguments"] = f"{current.get('arguments') or ''}{function['arguments']}"

    def _anthropic(self, payload: dict) -> None:
        kind = payload.get("type")
        if kind == "content_block_start":
            block = payload.get("content_block") or {}
            if block.get("type") == "tool_use":
                index = int(payload.get("index") or 0)
                self.tool_calls[index] = {"id": block.get("id") or "", "name": block.get("name") or "", "arguments": ""}
        elif kind == "content_block_delta":
            delta = payload.get("delta") or {}
            index = int(payload.get("index") or 0)
            if delta.get("type") == "text_delta":
                self.text_parts.append(delta.get("text") or "")
            elif delta.get("type") == "input_json_delta":
                current = self.tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                current["arguments"] = f"{current.get('arguments') or ''}{delta.get('partial_json') or ''}"
        elif kind == "message_delta":
            delta = payload.get("delta") or {}
            if delta.get("stop_reason"):
                self.finish = str(delta["stop_reason"])
            usage_raw = payload.get("usage") or {}
            if usage_raw:
                completion = int(usage_raw.get("output_tokens") or 0)
                self.usage = Usage(self.usage.prompt_tokens, completion or self.usage.completion_tokens)
        elif kind == "message_start":
            usage_raw = (payload.get("message") or {}).get("usage") or {}
            if usage_raw:
                self.usage = Usage(int(usage_raw.get("input_tokens") or 0), self.usage.completion_tokens)

    def _responses(self, payload: dict) -> None:
        kind = payload.get("type") or ""
        if kind == "response.output_text.delta":
            self.text_parts.append(payload.get("delta") or "")
        elif kind == "response.output_item.done" and (payload.get("item") or {}).get("type") == "function_call":
            item = payload["item"]
            self.tool_calls[len(self.tool_calls)] = normalize_tool_call(item)
        elif kind in {"response.completed", "response.incomplete"}:
            response = payload.get("response") or payload
            usage_raw = response.get("usage") or {}
            if usage_raw:
                self.usage = Usage(
                    int(usage_raw.get("input_tokens") or 0),
                    int(usage_raw.get("output_tokens") or 0),
                )
            self.finish = str(response.get("status") or kind)


def iter_sse_data(chunk_text: str, pending: str) -> tuple[list[str], str]:
    """Split an SSE byte stream into data payloads. Returns completed payloads and the leftover buffer."""
    pending += chunk_text
    payloads: list[str] = []
    while "\n\n" in pending:
        frame, pending = pending.split("\n\n", 1)
        data_lines = []
        for line in frame.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            payloads.append("\n".join(data_lines))
    return payloads, pending


def model_ids_from_list(protocol: str, payload: dict) -> list[str]:
    if protocol == "gemini":
        names = []
        for item in payload.get("models") or []:
            name = str(item.get("name") or "")
            names.append(name.removeprefix("models/"))
        return [item for item in names if item]
    if protocol == "bedrock":
        return [str(item.get("modelId")) for item in payload.get("modelSummaries") or [] if item.get("modelId")]
    rows = payload.get("data") or payload.get("models") or []
    found = []
    for item in rows:
        if isinstance(item, str):
            found.append(item)
        elif isinstance(item, dict) and item.get("id"):
            found.append(str(item["id"]))
    return found


def aws_sign(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
    *,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
    session_token: str = "",
    now: datetime | None = None,
) -> dict[str, str]:
    """Return headers including an AWS Signature Version 4 Authorization value."""
    parsed = urlsplit(url)
    moment = now or datetime.now(timezone.utc)
    amz_date = moment.strftime("%Y%m%dT%H%M%SZ")
    datestamp = amz_date[:8]
    payload_hash = hashlib.sha256(body).hexdigest()
    signed: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered == "authorization":
            continue
        signed[lowered] = " ".join(value.strip().split())
    signed["host"] = parsed.netloc
    signed["x-amz-date"] = amz_date
    signed["x-amz-content-sha256"] = payload_hash
    if session_token:
        signed["x-amz-security-token"] = session_token
    canonical_headers = "".join(f"{key}:{signed[key]}\n" for key in sorted(signed))
    signed_headers = ";".join(sorted(signed))
    canonical_uri = aws_uri(parsed.path or "/")
    canonical_query = aws_query(parsed.query)
    canonical_request = f"{method}\n{canonical_uri}\n{canonical_query}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = "AWS4-HMAC-SHA256\n" + amz_date + "\n" + scope + "\n" + hashlib.sha256(canonical_request.encode()).hexdigest()
    signing_key = _signing_key(secret_key, datestamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    authorization = f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
    output = {key: value for key, value in headers.items() if key.lower() != "host"}
    output["Host"] = parsed.netloc
    output["x-amz-date"] = amz_date
    output["x-amz-content-sha256"] = payload_hash
    output["Authorization"] = authorization
    if session_token:
        output["x-amz-security-token"] = session_token
    return output


def aws_uri(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return "/" + "/".join(quote(segment, safe="-_.~") for segment in path.split("/")[1:])


def aws_query(query: str) -> str:
    if not query:
        return ""
    pairs = []
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        pairs.append((quote(unquote(key), safe="-_.~"), quote(unquote(value), safe="-_.~")))
    pairs.sort()
    return "&".join(f"{key}={value}" for key, value in pairs)


def _signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    key = ("AWS4" + secret).encode()
    for piece in (datestamp, region, service, "aws4_request"):
        key = hmac.new(key, piece.encode(), hashlib.sha256).digest()
    return key
