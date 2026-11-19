"""HTTP gateway: retries, streaming, proxies, and normalized results."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator
from dataclasses import replace

import httpx

from axiom.errors import AxiomError
from axiom.llm.protocols import (
    StreamAssembler,
    apply_result,
    iter_sse_data,
    model_ids_from_list,
    parse_payload,
    prepare,
)
from axiom.llm.types import ChatRequest, ChatResult, Connection, Usage

MAX_ATTEMPTS = 3
RETRYABLE = {429, 500, 502, 503, 504}
Sleeper = Callable[[float], None]


def proxy_kwargs(proxy: str) -> dict:
    value = (proxy or "").strip()
    if not value:
        return {}
    lowered = value.lower()
    if not lowered.startswith(("http://", "https://", "socks5://", "socks5h://", "socks://")):
        raise AxiomError(
            "代理地址需要以 http://、https:// 或 socks5:// 开头。",
            "A proxy URL must start with http://, https://, or socks5://.",
            code="proxy",
        )
    if lowered.startswith("socks"):
        try:
            import socksio  # noqa: F401
        except ImportError as exc:
            raise AxiomError(
                "SOCKS 代理需要 socksio。可以改用 HTTP 代理。",
                "SOCKS proxies need the socksio package. An HTTP proxy works without it.",
                code="proxy",
            ) from exc
    return {"proxy": value}


def complete(
    conn: Connection,
    request: ChatRequest,
    *,
    transport: httpx.BaseTransport | None = None,
    sleeper: Sleeper = time.sleep,
    jitter: float = 0.25,
) -> ChatResult:
    if conn.protocol == "mock":
        return _mock_result(conn)
    if conn.omit_temperature and not request.omit_temperature:
        request = ChatRequest(
            messages=request.messages,
            model=request.model or conn.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            tools=request.tools,
            json_schema=request.json_schema,
            json_mode=request.json_mode,
            stream=False,
            omit_temperature=True,
        )
    else:
        request = ChatRequest(
            messages=request.messages,
            model=request.model or conn.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            tools=request.tools,
            json_schema=request.json_schema,
            json_mode=request.json_mode,
            stream=False,
            omit_temperature=request.omit_temperature,
        )
    try:
        return _complete_once(conn, request, transport=transport, sleeper=sleeper, jitter=jitter)
    except AxiomError as exc:
        if exc.code == "bad_request" and request.wants_json and conn.supports_json and not request.tools:
            result = _complete_once(replace(conn, supports_json=False), request, transport=transport, sleeper=sleeper, jitter=jitter)
            result.json_fallback = True
            return result
        raise


def _complete_once(conn, request, *, transport, sleeper, jitter) -> ChatResult:
    started = time.perf_counter()
    response = _exchange(conn, request, transport=transport, sleeper=sleeper, jitter=jitter)
    latency = int((time.perf_counter() - started) * 1000)
    try:
        payload = response.json()
    except json_error():
        raise AxiomError("模型接口没有返回 JSON。", "The model endpoint did not return JSON.", code="llm") from None
    if not isinstance(payload, dict):
        raise AxiomError("模型接口的响应无法识别。", "The model response could not be read.", code="llm")
    text, calls, usage, finish = parse_payload(conn, payload)
    return apply_result(conn, request, text, calls, usage, finish, latency)


def complete_stream(
    conn: Connection,
    request: ChatRequest,
    *,
    transport: httpx.BaseTransport | None = None,
    sleeper: Sleeper = time.sleep,
    jitter: float = 0.25,
) -> ChatResult:
    events = list(iter_stream(conn, request, transport=transport, sleeper=sleeper, jitter=jitter))
    done = events[-1] if events else {}
    usage_raw = done.get("usage") or {}
    return apply_result(
        conn,
        request,
        done.get("text") or "",
        done.get("tool_calls") or [],
        Usage(int(usage_raw.get("prompt_tokens") or 0), int(usage_raw.get("completion_tokens") or 0)),
        str(done.get("finish_reason") or ""),
        int(done.get("latency_ms") or 0),
    )


def iter_stream(
    conn: Connection,
    request: ChatRequest,
    *,
    transport: httpx.BaseTransport | None = None,
    sleeper: Sleeper = time.sleep,
    jitter: float = 0.25,
) -> Iterator[dict]:
    if conn.protocol == "mock":
        result = _mock_result(conn)
        yield {"type": "text", "text": result.text}
        yield {"type": "done", "text": result.text, "tool_calls": [], "usage": result.usage.to_dict(), "latency_ms": 0, "finish_reason": "stop"}
        return
    streaming = ChatRequest(
        messages=request.messages,
        model=request.model or conn.model,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        tools=request.tools,
        json_schema=request.json_schema,
        json_mode=request.json_mode,
        stream=True,
        omit_temperature=request.omit_temperature or conn.omit_temperature,
    )
    protocol = "responses" if conn.api_style == "responses" and conn.protocol == "openai" else conn.protocol
    if conn.protocol == "bedrock" and conn.bedrock_mode == "gateway":
        protocol = "openai"
    started = time.perf_counter()
    response, client = _open_stream(conn, streaming, transport=transport, sleeper=sleeper, jitter=jitter)
    assembler = StreamAssembler("openai" if protocol == "bedrock" else protocol)
    if protocol == "bedrock":
        # Converse has no SSE form here; the caller should use complete().
        client.close()
        raise AxiomError("Bedrock Converse 使用整段响应，不走 SSE。", "Bedrock Converse returns a full body, not SSE.", code="llm")
    pending = ""
    try:
        for chunk in response.iter_text():
            payloads, pending = iter_sse_data(chunk, pending)
            for data in payloads:
                before = len(assembler.text_parts)
                assembler.feed(data)
                if len(assembler.text_parts) > before:
                    yield {"type": "text", "text": assembler.text_parts[-1]}
        if pending.strip():
            payloads, _ = iter_sse_data(pending + "\n\n", "")
            for data in payloads:
                assembler.feed(data)
    finally:
        response.close()
        client.close()
    text, calls, usage, finish = assembler.result_parts()
    result = apply_result(conn, streaming, text, calls, usage, finish, int((time.perf_counter() - started) * 1000))
    if calls:
        yield {"type": "tool_calls", "tool_calls": result.tool_calls}
    yield {
        "type": "done",
        "text": result.text,
        "tool_calls": result.tool_calls,
        "usage": result.usage.to_dict(),
        "latency_ms": result.latency_ms,
        "finish_reason": result.finish_reason,
        "json_fallback": result.json_fallback,
        "cost_usd": result.cost_usd,
        "provider": conn.provider_id,
        "model": result.model,
    }


def test_connection(
    conn: Connection,
    *,
    transport: httpx.BaseTransport | None = None,
    sleeper: Sleeper = time.sleep,
) -> dict:
    if conn.protocol == "mock":
        return {
            "ok": True,
            "provider": "mock",
            "model": conn.model or "offline",
            "latency_ms": 0,
            "message": "离线模式可用，不会访问网络。",
            "message_en": "Offline mode is ready and does not use the network.",
        }
    from axiom.llm.types import ChatMessage

    request = ChatRequest(
        messages=[
            ChatMessage("system", "Reply with the single word pong."),
            ChatMessage("user", "ping"),
        ],
        model=conn.model,
        temperature=0,
        max_tokens=32,
        omit_temperature=conn.omit_temperature,
    )
    started = time.perf_counter()
    try:
        result = complete(conn, request, transport=transport, sleeper=sleeper, jitter=0)
    except AxiomError as exc:
        return {
            "ok": False,
            "provider": conn.provider_id,
            "model": conn.model,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "message": exc.message,
            "message_en": exc.message_en,
            "code": exc.code,
        }
    return {
        "ok": True,
        "provider": conn.provider_id,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "message": (result.text or "pong")[:200],
        "message_en": (result.text or "pong")[:200],
        "usage": result.usage.to_dict(),
        "cost_usd": result.cost_usd,
    }


def list_models(conn: Connection, *, transport: httpx.BaseTransport | None = None) -> list[str]:
    if conn.protocol == "mock" or not conn.base_url and conn.protocol != "bedrock":
        return []
    prepared = _list_request(conn)
    with _client(conn, transport) as client:
        response = client.send(httpx.Request(prepared.method, prepared.url, headers=_outgoing(prepared.headers), content=prepared.body))
    if response.status_code >= 400:
        _raise_status(response)
    try:
        payload = response.json()
    except json_error():
        raise AxiomError("模型列表不是 JSON。", "The model list was not JSON.", code="llm") from None
    protocol = "bedrock" if conn.protocol == "bedrock" and conn.bedrock_mode != "gateway" else conn.protocol
    if protocol == "bedrock" and conn.bedrock_mode == "gateway":
        protocol = "openai"
    return model_ids_from_list(protocol, payload if isinstance(payload, dict) else {})


def run_chain(
    connections: list[Connection],
    request: ChatRequest,
    *,
    compete: bool = False,
    transport: httpx.BaseTransport | None = None,
    sleeper: Sleeper = time.sleep,
    jitter: float = 0.25,
) -> tuple[ChatResult, list[tuple[Connection, ChatResult | None, AxiomError | None]]]:
    """Try a fallback chain, or fan out up to three models and keep the best success."""
    hops = [item for item in connections if item.protocol != "mock"]
    if not hops:
        raise AxiomError("当前是离线推理模式，没有调用外部模型。", "Mock mode does not call an external model.", code="mock")
    if compete and len(hops) > 1:
        return _compete(hops[:3], request, transport=transport, sleeper=sleeper)
    attempts: list[tuple[Connection, ChatResult | None, AxiomError | None]] = []
    last: AxiomError | None = None
    for conn in hops:
        try:
            result = complete(conn, request, transport=transport, sleeper=sleeper, jitter=jitter)
        except AxiomError as exc:
            attempts.append((conn, None, exc))
            last = exc
            continue
        attempts.append((conn, result, None))
        return result, attempts
    raise last or AxiomError("没有可用的模型。", "No model could be reached.", code="llm")


def _compete(hops, request, *, transport, sleeper) -> tuple[ChatResult, list]:
    from concurrent.futures import ThreadPoolExecutor

    attempts: list[tuple[Connection, ChatResult | None, AxiomError | None]] = []

    def one(conn: Connection):
        return complete(conn, request, transport=transport, sleeper=sleeper, jitter=0)

    with ThreadPoolExecutor(max_workers=len(hops)) as pool:
        futures = [(conn, pool.submit(one, conn)) for conn in hops]
        for conn, future in futures:
            try:
                attempts.append((conn, future.result(), None))
            except AxiomError as exc:
                attempts.append((conn, None, exc))
    winners = [item for item in attempts if item[1] is not None]
    if not winners:
        error = next((item[2] for item in attempts if item[2] is not None), None)
        raise error or AxiomError("没有可用的模型。", "No model could be reached.", code="llm")
    with_tools = [item for item in winners if item[1].tool_calls]
    pool_results = with_tools or winners
    pool_results.sort(key=lambda item: item[1].latency_ms)
    return pool_results[0][1], attempts


def _mock_result(conn: Connection) -> ChatResult:
    return ChatResult(
        text="离线模式不会调用外部模型。",
        tool_calls=[],
        usage=Usage(),
        latency_ms=0,
        model=conn.model or "offline",
        provider=conn.provider_id or "mock",
        finish_reason="stop",
        protocol="mock",
    )


def _client(conn: Connection, transport: httpx.BaseTransport | None) -> httpx.Client:
    timeout = max(1.0, float(conn.timeout or 60))
    kwargs: dict = {
        "timeout": httpx.Timeout(connect=min(10.0, timeout), read=timeout, write=min(30.0, timeout), pool=min(10.0, timeout)),
        "trust_env": False,
        "follow_redirects": False,
    }
    if transport is not None:
        kwargs["transport"] = transport
    if conn.proxy and transport is None:
        kwargs.update(proxy_kwargs(conn.proxy))
    elif conn.proxy:
        proxy_kwargs(conn.proxy)
    return httpx.Client(**kwargs)


def _outgoing(headers: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() != "host"}


def _exchange(conn, request: ChatRequest, *, transport, sleeper, jitter) -> httpx.Response:
    last: AxiomError | None = None
    for attempt in range(MAX_ATTEMPTS):
        prepared = prepare(conn, request)
        try:
            with _client(conn, transport) as client:
                response = client.send(httpx.Request(prepared.method, prepared.url, headers=_outgoing(prepared.headers), content=prepared.body))
        except httpx.TimeoutException as exc:
            last = AxiomError(f"模型接口超时：{exc}", f"The model endpoint timed out: {exc}", code="timeout")
        except httpx.HTTPError as exc:
            last = AxiomError(f"模型接口不可达：{exc}", f"The model endpoint is unreachable: {exc}", code="llm")
        else:
            if response.status_code in RETRYABLE and attempt + 1 < MAX_ATTEMPTS:
                sleeper(_delay(response, attempt, jitter))
                continue
            if response.status_code >= 400:
                _raise_status(response)
            return response
        if attempt + 1 < MAX_ATTEMPTS:
            sleeper(_delay(None, attempt, jitter))
            continue
        raise last or AxiomError("模型接口不可达。", "The model endpoint is unreachable.", code="llm")
    raise last or AxiomError("模型接口不可达。", "The model endpoint is unreachable.", code="llm")


def _open_stream(conn, request: ChatRequest, *, transport, sleeper, jitter):
    last: AxiomError | None = None
    for attempt in range(MAX_ATTEMPTS):
        prepared = prepare(conn, request)
        client = _client(conn, transport)
        try:
            response = client.send(
                httpx.Request(prepared.method, prepared.url, headers=_outgoing(prepared.headers), content=prepared.body),
                stream=True,
            )
        except httpx.TimeoutException as exc:
            client.close()
            last = AxiomError(f"模型接口超时：{exc}", f"The model endpoint timed out: {exc}", code="timeout")
        except httpx.HTTPError as exc:
            client.close()
            last = AxiomError(f"模型接口不可达：{exc}", f"The model endpoint is unreachable: {exc}", code="llm")
        else:
            if response.status_code in RETRYABLE and attempt + 1 < MAX_ATTEMPTS:
                response.read()
                response.close()
                client.close()
                sleeper(_delay(response, attempt, jitter))
                continue
            if response.status_code >= 400:
                raw = response.read()
                response.close()
                client.close()
                failed = httpx.Response(response.status_code, content=raw, headers=response.headers)
                _raise_status(failed)
            return response, client
        if attempt + 1 < MAX_ATTEMPTS:
            sleeper(_delay(None, attempt, jitter))
            continue
        raise last or AxiomError("模型接口不可达。", "The model endpoint is unreachable.", code="llm")
    raise last or AxiomError("模型接口不可达。", "The model endpoint is unreachable.", code="llm")


def _list_request(conn: Connection):
    from axiom.llm.protocols import PreparedCall, aws_sign

    if conn.protocol == "gemini":
        root = conn.base_url.rstrip("/")
        url = f"{root}/models?key={conn.api_key}"
        return PreparedCall("GET", url, {"x-goog-api-key": conn.api_key}, b"")
    if conn.protocol == "anthropic":
        root = (conn.base_url or "https://api.anthropic.com").rstrip("/")
        return PreparedCall(
            "GET",
            f"{root}/v1/models",
            {"x-api-key": conn.api_key, "anthropic-version": "2023-06-01"},
            b"",
        )
    if conn.protocol == "bedrock" and conn.bedrock_mode != "gateway":
        region = conn.region or "us-east-1"
        url = f"https://bedrock.{region}.amazonaws.com/foundation-models"
        headers = aws_sign(
            "GET",
            url,
            {},
            b"",
            access_key=conn.api_key,
            secret_key=conn.aws_secret,
            session_token=conn.aws_session,
            region=region,
            service="bedrock",
        )
        return PreparedCall("GET", url, headers, b"")
    root = conn.base_url.rstrip("/")
    headers = {"content-type": "application/json"}
    if conn.api_key:
        if conn.auth == "azure":
            headers["api-key"] = conn.api_key
        else:
            headers["authorization"] = f"Bearer {conn.api_key}"
    return PreparedCall("GET", f"{root}/models", headers, b"")


def _delay(response: httpx.Response | None, attempt: int, jitter: float) -> float:
    base = 0.4 * (2**attempt)
    if response is not None:
        header = response.headers.get("retry-after")
        if header:
            try:
                base = float(header)
            except ValueError:
                pass
    base = min(max(base, 0), 30)
    if jitter:
        base += random.random() * jitter
    return base


def _raise_status(response: httpx.Response) -> None:
    detail = _error_detail(response)
    code = response.status_code
    if code in {401, 403}:
        raise AxiomError(f"模型接口拒绝了密钥（{code}）：{detail}", f"The model endpoint rejected the key ({code}): {detail}", code="auth")
    if code == 404:
        raise AxiomError(f"模型接口不存在（404）：{detail}", f"The model endpoint was not found (404): {detail}", code="not_found")
    if code == 429:
        raise AxiomError(f"模型接口限流（429）：{detail}", f"The model endpoint rate-limited the call (429): {detail}", code="rate_limit")
    if code == 400:
        raise AxiomError(f"模型接口拒绝了请求（400）：{detail}", f"The model endpoint rejected the request (400): {detail}", code="bad_request")
    raise AxiomError(f"模型接口返回 {code}：{detail}", f"The model endpoint returned {code}: {detail}", code="llm")


def _error_detail(response: httpx.Response) -> str:
    text = ""
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            text = str(err.get("message") or err)
        elif isinstance(err, str):
            text = err
        elif payload.get("message"):
            text = str(payload["message"])
    if not text:
        try:
            text = response.text
        except Exception:
            text = ""
    return text[:300]


def json_error():
    import json

    return json.JSONDecodeError
