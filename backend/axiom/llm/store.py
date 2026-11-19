"""Persisted provider configs, encrypted keys, role assignment, and usage."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from axiom.db.models import Setting
from axiom.db.session import open_session
from axiom.errors import AxiomError
from axiom.llm.gateway import run_chain, test_connection
from axiom.llm.providers import GROUPS, PRESETS, ROLES, ModelSpec, find_model, preset_for
from axiom.llm.types import ChatMessage, ChatRequest, ChatResult, Connection, ToolSpec
from axiom.security import decrypt_secret, encrypt_secret, mask_secret

_USAGE_LOCK = threading.Lock()
_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
_USAGE_CAP = 200


def directory(session: Session) -> dict:
    rows = _rows(session)
    document = _document(rows)
    cards = [_card(preset.id, rows, document) for preset in PRESETS]
    for custom in document["custom"]:
        if isinstance(custom, dict) and custom.get("id"):
            cards.append(_custom_card(custom, rows, document))
    groups = []
    for group in GROUPS:
        groups.append({"id": group, "providers": [card for card in cards if card["group"] == group]})
    return {
        "groups": groups,
        "roles": load_roles(rows),
        "usage": usage_view(rows),
        "active": {
            "provider": rows.get("llm.provider") or "mock",
            "base_url": rows.get("llm.base_url") or "",
            "model": rows.get("llm.model") or "",
        },
    }


def update_provider(session: Session, provider_id: str, patch: dict) -> dict:
    document = _document(_rows(session))
    _require_known(provider_id, document)
    config = document["configs"].setdefault(provider_id, {})
    if "enabled" in patch:
        config["enabled"] = bool(patch["enabled"])
    if "base_url" in patch:
        config["base_url"] = _clean_url(str(patch.get("base_url") or ""))
    if "model" in patch:
        config["model"] = str(patch.get("model") or "")[:200]
    if "proxy" in patch:
        config["proxy"] = _clean_proxy(str(patch.get("proxy") or ""))
    if "timeout" in patch and patch["timeout"] is not None:
        config["timeout"] = min(300, max(1, int(patch["timeout"])))
    if "api_version" in patch:
        config["api_version"] = str(patch.get("api_version") or "")[:40]
    if "region" in patch:
        config["region"] = str(patch.get("region") or "")[:40]
    if "api_style" in patch and patch["api_style"] in {"chat", "responses", ""}:
        config["api_style"] = patch["api_style"]
    if "bedrock_mode" in patch and patch["bedrock_mode"] in {"native", "gateway", ""}:
        config["bedrock_mode"] = patch["bedrock_mode"]
    if "extra_models" in patch:
        config["extra_models"] = [_clean_model(item, custom=True) for item in (patch.get("extra_models") or []) if isinstance(item, dict) and item.get("id")]
    _write_document(session, document)
    _mirror_legacy_if_active(session, provider_id)
    session.commit()
    return _card(provider_id, _rows(session), document) if provider_id in {item.id for item in PRESETS} else _custom_card(_custom(document, provider_id), _rows(session), document)


def save_key(session: Session, provider_id: str, api_key: str, aws_secret: str = "", aws_session: str = "") -> dict:
    document = _document(_rows(session))
    _require_known(provider_id, document)
    if aws_secret:
        payload = json.dumps({"api_key": api_key, "aws_secret": aws_secret, "aws_session": aws_session}, ensure_ascii=False)
        _put(session, f"llm.key.{provider_id}", encrypt_secret(payload))
    elif api_key:
        _put(session, f"llm.key.{provider_id}", encrypt_secret(api_key))
    _mirror_legacy_if_active(session, provider_id)
    session.commit()
    rows = _rows(session)
    return _card(provider_id, rows, _document(rows)) if provider_id in {item.id for item in PRESETS} else _custom_card(_custom(_document(rows), provider_id), rows, _document(rows))


def delete_key(session: Session, provider_id: str) -> dict:
    row = session.get(Setting, f"llm.key.{provider_id}")
    if row is not None:
        session.delete(row)
    _mirror_legacy_if_active(session, provider_id)
    session.commit()
    rows = _rows(session)
    document = _document(rows)
    if provider_id in {item.id for item in PRESETS}:
        return _card(provider_id, rows, document)
    return _custom_card(_custom(document, provider_id), rows, document)


def add_custom(session: Session, name: str, base_url: str, protocol: str, group: str) -> dict:
    if protocol not in {"openai", "anthropic", "gemini", "cohere", "bedrock"}:
        raise AxiomError("协议必须是 openai、anthropic、gemini、cohere 或 bedrock。", "Protocol must be openai, anthropic, gemini, cohere, or bedrock.")
    if group not in GROUPS:
        raise AxiomError("分组无效。", "Unknown provider group.")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "custom"
    document = _document(_rows(session))
    existing = {item.id for item in PRESETS} | {item.get("id") for item in document["custom"]}
    provider_id = slug
    suffix = 2
    while provider_id in existing or not _ID_RE.match(provider_id):
        provider_id = f"{slug[:28]}-{suffix}"
        suffix += 1
    document["custom"].append(
        {
            "id": provider_id,
            "name": name.strip()[:80] or provider_id,
            "name_zh": name.strip()[:80] or provider_id,
            "group": group,
            "protocol": protocol,
            "base_url": _clean_url(base_url) or "http://127.0.0.1:8080/v1",
            "monogram": (name.strip()[:2] or "CU").upper(),
            "color": "#57534E",
        }
    )
    _write_document(session, document)
    session.commit()
    rows = _rows(session)
    return _custom_card(_custom(_document(rows), provider_id), rows, _document(rows))


def delete_custom(session: Session, provider_id: str) -> None:
    document = _document(_rows(session))
    before = len(document["custom"])
    document["custom"] = [item for item in document["custom"] if item.get("id") != provider_id]
    if len(document["custom"]) == before:
        raise AxiomError("只能删除自定义提供方。", "Only a custom provider can be removed.", status=404)
    document["configs"].pop(provider_id, None)
    _write_document(session, document)
    row = session.get(Setting, f"llm.key.{provider_id}")
    if row is not None:
        session.delete(row)
    session.commit()


def save_roles(session: Session, roles: dict) -> dict:
    document = _document(_rows(session))
    cleaned = {}
    for role in ROLES:
        incoming = roles.get(role) if isinstance(roles, dict) else None
        incoming = incoming or {}
        chain = []
        for hop in (incoming.get("chain") or [])[:3]:
            if not isinstance(hop, dict):
                continue
            provider_id = str(hop.get("provider") or "")
            model = str(hop.get("model") or "")[:200]
            if not provider_id:
                continue
            _require_known(provider_id, document)
            chain.append({"provider": provider_id, "model": model})
        cleaned[role] = {"chain": chain, "compete": bool(incoming.get("compete")) and len(chain) > 1}
    _put(session, "llm.roles", json.dumps(cleaned, ensure_ascii=False))
    _sync_legacy_from_planner(session, cleaned)
    session.commit()
    return cleaned


def remember_models(session: Session, provider_id: str, model_ids: list[str]) -> dict:
    document = _document(_rows(session))
    _require_known(provider_id, document)
    config = document["configs"].setdefault(provider_id, {})
    known = {item["id"] for item in _models_of(provider_id, document, config)}
    fetched = [item for item in dict.fromkeys(str(model_id) for model_id in model_ids) if item and item not in known]
    config["fetched_models"] = (config.get("fetched_models") or []) + fetched
    config["fetched_models"] = config["fetched_models"][:200]
    _write_document(session, document)
    session.commit()
    rows = _rows(session)
    fresh = _document(rows)
    if provider_id in {item.id for item in PRESETS}:
        return _card(provider_id, rows, fresh)
    return _custom_card(_custom(fresh, provider_id), rows, fresh)


def record_usage(role: str, provider: str, model: str, *, prompt_tokens: int, completion_tokens: int, cost_usd: float, latency_ms: int, ok: bool, error: str = "") -> None:
    with _USAGE_LOCK:
        session = open_session()
        try:
            rows = _rows(session)
            try:
                current = json.loads(rows.get("llm.usage") or "[]")
            except json.JSONDecodeError:
                current = []
            if not isinstance(current, list):
                current = []
            current.append(
                {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "role": role,
                    "provider": provider,
                    "model": model,
                    "prompt_tokens": int(prompt_tokens),
                    "completion_tokens": int(completion_tokens),
                    "cost_usd": round(float(cost_usd), 8),
                    "latency_ms": int(latency_ms),
                    "ok": bool(ok),
                    "error": (error or "")[:200],
                }
            )
            _put(session, "llm.usage", json.dumps(current[-_USAGE_CAP:], ensure_ascii=False))
            session.commit()
        finally:
            session.close()


def complete_role(
    role: str,
    messages: list[dict],
    *,
    temperature: float = 0.1,
    tools: list[dict] | None = None,
    json_schema: dict | None = None,
    json_mode: bool = False,
    transport=None,
    sleeper=None,
    jitter: float = 0.25,
) -> ChatResult:
    if role not in ROLES and role not in {"legacy", "test"}:
        raise AxiomError("未知的智能体角色。", "Unknown agent role.")
    session = open_session()
    try:
        rows = _rows(session)
        roles = load_roles(rows)
        assignment = roles.get(role) or {"chain": [], "compete": False}
        connections = _connections_for(session, rows, assignment.get("chain") or [])
        compete = bool(assignment.get("compete"))
    finally:
        session.close()
    if not connections:
        raise AxiomError("当前是离线推理模式，没有调用外部模型。", "Mock mode does not call an external model.", code="mock")
    tool_specs = [
        ToolSpec(name=item.get("name") or "", description=item.get("description") or "", parameters=item.get("parameters") or {})
        for item in (tools or [])
        if item.get("name")
    ]
    request = ChatRequest(
        messages=[ChatMessage(item.get("role") or "user", item.get("content") or "", item.get("tool_calls"), item.get("tool_call_id") or "", item.get("name") or "") for item in messages],
        model=connections[0].model,
        temperature=temperature,
        tools=tool_specs or None,
        json_schema=json_schema,
        json_mode=json_mode or bool(json_schema),
    )
    kwargs = {"transport": transport, "jitter": jitter}
    if sleeper is not None:
        kwargs["sleeper"] = sleeper
    try:
        result, attempts = run_chain(connections, request, compete=compete, **kwargs)
    except AxiomError as exc:
        record_usage(role, connections[-1].provider_id, connections[-1].model, prompt_tokens=0, completion_tokens=0, cost_usd=0, latency_ms=0, ok=False, error=exc.message)
        raise
    for conn, attempt, error in attempts:
        if attempt is None:
            record_usage(role, conn.provider_id, conn.model, prompt_tokens=0, completion_tokens=0, cost_usd=0, latency_ms=0, ok=False, error=error.message if error else "")
        else:
            record_usage(
                role,
                attempt.provider,
                attempt.model,
                prompt_tokens=attempt.usage.prompt_tokens,
                completion_tokens=attempt.usage.completion_tokens,
                cost_usd=attempt.cost_usd,
                latency_ms=attempt.latency_ms,
                ok=True,
            )
    return result


def complete_text(role: str, messages: list[dict], *, temperature: float = 0.1) -> str:
    return complete_role(role, messages, temperature=temperature).text


def provider_name_for(role: str) -> str:
    session = open_session()
    try:
        rows = _rows(session)
        roles = load_roles(rows)
        chain = (roles.get(role) or {}).get("chain") or []
        usable = [hop for hop in chain if hop.get("provider") and hop.get("provider") != "mock"]
        if usable:
            return str(usable[0]["provider"])
        return (rows.get("llm.provider") or "mock").lower()
    finally:
        session.close()


def connection_from_settings(settings) -> Connection:
    provider = (settings.provider or "mock").lower()
    preset = preset_for(provider)
    model = settings.model or (preset.models[0].id if preset and preset.models else "")
    spec = find_model(preset.id, model) if preset else None
    return Connection(
        provider_id=provider,
        protocol="mock" if provider == "mock" else (preset.protocol if preset else "openai"),
        base_url=settings.base_url or (preset.base_url if preset else ""),
        api_key=settings.api_key or "",
        model=model,
        auth="none" if provider == "mock" else (preset.auth if preset else "bearer"),
        api_version=(preset.api_version if preset and preset.api_version else "2024-10-21"),
        region=(preset.region if preset and preset.region else "us-east-1"),
        key_optional=bool(preset and preset.key_optional) or provider in {"openai-compatible", "custom", "ollama"},
        supports_json=True if spec is None else spec.json_mode,
        omit_temperature=bool(spec and spec.reasoning),
        input_usd_per_mtok=0 if spec is None else spec.input_usd_per_mtok,
        output_usd_per_mtok=0 if spec is None else spec.output_usd_per_mtok,
        timeout=60,
    )


def primary_connection(role: str) -> Connection:
    session = open_session()
    try:
        rows = _rows(session)
        roles = load_roles(rows)
        chain = (roles.get(role) or {}).get("chain") or []
        connections = _connections_for(session, rows, chain)
    finally:
        session.close()
    if not connections:
        raise AxiomError("当前是离线推理模式，没有调用外部模型。", "Mock mode does not call an external model.", code="mock")
    return connections[0]


def connection_for_provider(provider_id: str, model: str = "") -> Connection:
    session = open_session()
    try:
        rows = _rows(session)
        document = _document(rows)
        _require_known(provider_id, document)
        return _connection(provider_id, model, rows, document)
    finally:
        session.close()


def load_roles(rows: dict | None = None) -> dict:
    if rows is None:
        session = open_session()
        try:
            rows = _rows(session)
        finally:
            session.close()
    try:
        parsed = json.loads(rows.get("llm.roles") or "{}")
    except json.JSONDecodeError:
        parsed = {}
    roles = {}
    for role in ROLES:
        incoming = parsed.get(role) if isinstance(parsed, dict) else None
        incoming = incoming if isinstance(incoming, dict) else {}
        chain = []
        for hop in incoming.get("chain") or []:
            if isinstance(hop, dict) and hop.get("provider"):
                chain.append({"provider": str(hop["provider"]), "model": str(hop.get("model") or "")})
        roles[role] = {"chain": chain[:3], "compete": bool(incoming.get("compete")) and len(chain) > 1}
    return roles


def usage_view(rows: dict) -> dict:
    try:
        raw = json.loads(rows.get("llm.usage") or "[]")
    except json.JSONDecodeError:
        raw = []
    if not isinstance(raw, list):
        raw = []
    totals = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
    by_provider: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        totals["calls"] += 1
        totals["prompt_tokens"] += int(item.get("prompt_tokens") or 0)
        totals["completion_tokens"] += int(item.get("completion_tokens") or 0)
        totals["cost_usd"] += float(item.get("cost_usd") or 0)
        bucket = by_provider.setdefault(str(item.get("provider") or ""), {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0})
        bucket["calls"] += 1
        bucket["prompt_tokens"] += int(item.get("prompt_tokens") or 0)
        bucket["completion_tokens"] += int(item.get("completion_tokens") or 0)
        bucket["cost_usd"] += float(item.get("cost_usd") or 0)
    totals["cost_usd"] = round(totals["cost_usd"], 6)
    for bucket in by_provider.values():
        bucket["cost_usd"] = round(bucket["cost_usd"], 6)
    return {"rows": raw[-50:], "totals": totals, "by_provider": by_provider}


def absorb_legacy(session: Session, provider: str, base_url: str, model: str, api_key: str | None) -> None:
    """Mirror a legacy settings write onto a built-in card when the id matches one."""
    if provider not in {item.id for item in PRESETS}:
        return
    document = _document(_rows(session))
    config = document["configs"].setdefault(provider, {})
    config["base_url"] = base_url
    config["model"] = model
    if provider != "mock":
        config["enabled"] = True
    _write_document(session, document)
    if api_key:
        _put(session, f"llm.key.{provider}", encrypt_secret(api_key))


def _connections_for(session: Session, rows: dict, chain: list[dict]) -> list[Connection]:
    document = _document(rows)
    usable = [hop for hop in chain if hop.get("provider") and hop["provider"] != "mock"]
    if usable:
        found = []
        for hop in usable:
            try:
                _require_known(hop["provider"], document)
            except AxiomError:
                continue
            card_enabled = _enabled(hop["provider"], document)
            if not card_enabled:
                continue
            found.append(_connection(hop["provider"], hop.get("model") or "", rows, document))
        return found
    legacy = _legacy_connection(rows)
    return [legacy] if legacy is not None else []


def _legacy_connection(rows: dict) -> Connection | None:
    provider = (rows.get("llm.provider") or "mock").lower()
    if provider == "mock":
        return None
    preset = preset_for(provider)
    model = rows.get("llm.model") or (preset.models[0].id if preset and preset.models else "")
    spec = find_model(preset.id, model) if preset else None
    return Connection(
        provider_id=provider,
        protocol=preset.protocol if preset else "openai",
        base_url=rows.get("llm.base_url") or (preset.base_url if preset else ""),
        api_key=decrypt_secret(rows.get("llm.api_key") or ""),
        model=model,
        auth=preset.auth if preset else "bearer",
        api_version=(preset.api_version if preset and preset.api_version else "2024-10-21"),
        region=(preset.region if preset and preset.region else "us-east-1"),
        key_optional=bool(preset and preset.key_optional) or provider == "openai-compatible",
        supports_json=True if spec is None else spec.json_mode,
        omit_temperature=bool(spec and spec.reasoning),
        input_usd_per_mtok=0 if spec is None else spec.input_usd_per_mtok,
        output_usd_per_mtok=0 if spec is None else spec.output_usd_per_mtok,
    )


def _connection(provider_id: str, model: str, rows: dict, document: dict) -> Connection:
    preset = preset_for(provider_id)
    custom = None if preset and provider_id == preset.id else _custom(document, provider_id)
    config = document["configs"].get(provider_id) or {}
    api_key, aws_secret, aws_session = _decode_secret(rows.get(f"llm.key.{provider_id}") or "")
    if preset and provider_id == preset.id:
        protocol = preset.protocol
        auth = preset.auth
        base_url = config.get("base_url") or preset.base_url
        default_model = preset.models[0].id if preset.models else ""
        key_optional = preset.key_optional
        api_version = config.get("api_version") or preset.api_version or "2024-10-21"
        region = config.get("region") or preset.region or "us-east-1"
    else:
        protocol = (custom or {}).get("protocol") or "openai"
        auth = {"anthropic": "x-api-key", "gemini": "query", "bedrock": "aws"}.get(protocol, "bearer")
        base_url = config.get("base_url") or (custom or {}).get("base_url") or ""
        default_model = ""
        key_optional = True
        api_version = config.get("api_version") or "2024-10-21"
        region = config.get("region") or "us-east-1"
    chosen = model or config.get("model") or default_model
    spec = find_model(provider_id, chosen)
    bedrock_mode = config.get("bedrock_mode") or "native"
    if protocol == "bedrock" and bedrock_mode == "gateway":
        auth = "bearer"
    return Connection(
        provider_id=provider_id,
        protocol=protocol,
        base_url=base_url,
        api_key=api_key,
        model=chosen,
        auth=auth,
        api_version=api_version,
        region=region,
        aws_secret=aws_secret,
        aws_session=aws_session,
        proxy=config.get("proxy") or "",
        timeout=float(config.get("timeout") or 60),
        api_style=config.get("api_style") or "chat",
        bedrock_mode=bedrock_mode,
        key_optional=key_optional,
        supports_json=True if spec is None else spec.json_mode,
        omit_temperature=bool(spec and spec.reasoning),
        input_usd_per_mtok=0 if spec is None else spec.input_usd_per_mtok,
        output_usd_per_mtok=0 if spec is None else spec.output_usd_per_mtok,
    )


def _card(provider_id: str, rows: dict, document: dict) -> dict:
    preset = next(item for item in PRESETS if item.id == provider_id)
    config = document["configs"].get(provider_id) or {}
    api_key, aws_secret, _session = _decode_secret(rows.get(f"llm.key.{provider_id}") or "")
    models = _models_of(provider_id, document, config)
    chosen = config.get("model") or (models[0]["id"] if models else "")
    payload = preset.public_base()
    payload.update(
        {
            "base_url": config.get("base_url") or preset.base_url,
            "enabled": config["enabled"] if "enabled" in config else preset.enabled_by_default,
            "model": chosen,
            "models": models,
            "key_set": bool(api_key) or bool(aws_secret),
            "key_mask": mask_secret(api_key),
            "secret_set": bool(aws_secret),
            "proxy": config.get("proxy") or "",
            "timeout": int(config.get("timeout") or 60),
            "api_version": config.get("api_version") or preset.api_version,
            "region": config.get("region") or preset.region,
            "api_style": config.get("api_style") or "chat",
            "bedrock_mode": config.get("bedrock_mode") or "native",
        }
    )
    return payload


def _custom_card(custom: dict, rows: dict, document: dict) -> dict:
    provider_id = custom["id"]
    config = document["configs"].get(provider_id) or {}
    api_key, aws_secret, _session = _decode_secret(rows.get(f"llm.key.{provider_id}") or "")
    models = _models_of(provider_id, document, config)
    protocol = custom.get("protocol") or "openai"
    return {
        "id": provider_id,
        "name": custom.get("name") or provider_id,
        "name_zh": custom.get("name_zh") or custom.get("name") or provider_id,
        "group": custom.get("group") or "local",
        "protocol": protocol,
        "auth": {"anthropic": "x-api-key", "gemini": "query", "bedrock": "aws"}.get(protocol, "bearer"),
        "default_base_url": custom.get("base_url") or "",
        "base_url": config.get("base_url") or custom.get("base_url") or "",
        "monogram": custom.get("monogram") or "CU",
        "color": custom.get("color") or "#57534E",
        "notes": "Custom endpoint.",
        "notes_zh": "自定义端点。",
        "key_optional": True,
        "listable": protocol != "bedrock",
        "builtin": False,
        "api_version": config.get("api_version") or "",
        "region": config.get("region") or "",
        "supports": {
            "tools": any(item["tools"] for item in models) if models else True,
            "json_mode": any(item["json_mode"] for item in models) if models else True,
            "vision": any(item["vision"] for item in models) if models else False,
            "reasoning": any(item["reasoning"] for item in models) if models else False,
        },
        "models": models,
        "enabled": bool(config.get("enabled")),
        "model": config.get("model") or (models[0]["id"] if models else ""),
        "key_set": bool(api_key) or bool(aws_secret),
        "key_mask": mask_secret(api_key),
        "secret_set": bool(aws_secret),
        "proxy": config.get("proxy") or "",
        "timeout": int(config.get("timeout") or 60),
        "api_style": config.get("api_style") or "chat",
        "bedrock_mode": config.get("bedrock_mode") or "native",
    }


def _models_of(provider_id: str, document: dict, config: dict) -> list[dict]:
    preset = next((item for item in PRESETS if item.id == provider_id), None)
    seen: dict[str, dict] = {}
    if preset is not None:
        for item in preset.models:
            seen[item.id] = item.public()
    for item in config.get("extra_models") or []:
        if isinstance(item, dict) and item.get("id"):
            seen[str(item["id"])] = _clean_model(item, custom=True)
    for model_id in config.get("fetched_models") or []:
        if model_id and model_id not in seen:
            seen[str(model_id)] = ModelSpec(str(model_id), str(model_id), 8192).public(fetched=True)
    return list(seen.values())


def _clean_model(item: dict, *, custom: bool) -> dict:
    model_id = str(item.get("id") or "").strip()[:200]
    return ModelSpec(
        model_id,
        str(item.get("label") or model_id)[:200],
        min(2_000_000, max(0, int(item.get("context") or 8192))),
        tools=bool(item.get("tools", True)),
        json_mode=bool(item.get("json_mode", True)),
        vision=bool(item.get("vision", False)),
        reasoning=bool(item.get("reasoning", False)),
        input_usd_per_mtok=float(item.get("input_usd_per_mtok") or 0),
        output_usd_per_mtok=float(item.get("output_usd_per_mtok") or 0),
    ).public(custom=custom)


def _enabled(provider_id: str, document: dict) -> bool:
    config = document["configs"].get(provider_id) or {}
    if "enabled" in config:
        return bool(config["enabled"])
    preset = next((item for item in PRESETS if item.id == provider_id), None)
    if preset is not None:
        return preset.enabled_by_default
    return False


def _require_known(provider_id: str, document: dict) -> None:
    if provider_id in {item.id for item in PRESETS}:
        return
    if any(item.get("id") == provider_id for item in document["custom"]):
        return
    raise AxiomError("没有这个提供方。", "Unknown provider.", status=404)


def _custom(document: dict, provider_id: str) -> dict:
    for item in document["custom"]:
        if item.get("id") == provider_id:
            return item
    raise AxiomError("没有这个提供方。", "Unknown provider.", status=404)


def _mirror_legacy_if_active(session: Session, provider_id: str) -> None:
    rows = _rows(session)
    active = (rows.get("llm.provider") or "").lower()
    if active != provider_id and not (active == "openai-compatible" and provider_id == "custom"):
        return
    document = _document(rows)
    if provider_id not in {item.id for item in PRESETS} and provider_id != "custom":
        return
    conn = _connection(provider_id if active != "openai-compatible" else "custom", "", rows, document)
    if active != "openai-compatible":
        _put(session, "llm.base_url", conn.base_url)
        _put(session, "llm.model", conn.model)
    secret_row = session.get(Setting, f"llm.key.{provider_id}")
    if secret_row is not None and active == provider_id:
        plain, aws_secret, _token = _decode_secret(secret_row.value)
        _put(session, "llm.api_key", encrypt_secret(plain or aws_secret))


def _sync_legacy_from_planner(session: Session, roles: dict) -> None:
    chain = (roles.get("planner") or {}).get("chain") or []
    if not chain:
        return
    hop = chain[0]
    provider_id = hop["provider"]
    if provider_id == "mock":
        _put(session, "llm.provider", "mock")
        _put(session, "llm.model", "offline")
        return
    rows = _rows(session)
    document = _document(rows)
    conn = _connection(provider_id, hop.get("model") or "", rows, document)
    legacy_name = "openai-compatible" if provider_id == "custom" else provider_id
    _put(session, "llm.provider", legacy_name)
    _put(session, "llm.base_url", conn.base_url)
    _put(session, "llm.model", conn.model)
    if conn.api_key:
        _put(session, "llm.api_key", encrypt_secret(conn.api_key))


def _clean_url(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        raise AxiomError("接口地址需要以 http:// 或 https:// 开头。", "The base URL must start with http:// or https://.")
    return text[:300]


def _clean_proxy(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if not text.lower().startswith(("http://", "https://", "socks5://", "socks5h://", "socks://")):
        raise AxiomError("代理地址需要以 http://、https:// 或 socks5:// 开头。", "A proxy URL must start with http://, https://, or socks5://.")
    return text[:300]


def _document(rows: dict) -> dict:
    try:
        data = json.loads(rows.get("llm.providers") or "{}")
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    configs = data.get("configs")
    custom = data.get("custom")
    return {"configs": configs if isinstance(configs, dict) else {}, "custom": custom if isinstance(custom, list) else []}


def _write_document(session: Session, document: dict) -> None:
    _put(session, "llm.providers", json.dumps(document, ensure_ascii=False))


def _rows(session: Session) -> dict:
    return {item.key: item.value for item in session.scalars(select(Setting))}


def _put(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


def _decode_secret(stored: str) -> tuple[str, str, str]:
    plain = decrypt_secret(stored)
    if plain.startswith("{") and "aws_secret" in plain:
        try:
            data = json.loads(plain)
        except json.JSONDecodeError:
            return plain, "", ""
        if isinstance(data, dict) and "aws_secret" in data:
            return str(data.get("api_key") or ""), str(data.get("aws_secret") or ""), str(data.get("aws_session") or "")
    return plain, "", ""


def probe(provider_id: str, *, transport=None) -> dict:
    conn = connection_for_provider(provider_id)
    result = test_connection(conn, transport=transport)
    if conn.protocol != "mock":
        record_usage(
            "test",
            provider_id,
            conn.model,
            prompt_tokens=int((result.get("usage") or {}).get("prompt_tokens") or 0),
            completion_tokens=int((result.get("usage") or {}).get("completion_tokens") or 0),
            cost_usd=float(result.get("cost_usd") or 0),
            latency_ms=int(result.get("latency_ms") or 0),
            ok=bool(result.get("ok")),
            error="" if result.get("ok") else str(result.get("message") or ""),
        )
    return result
