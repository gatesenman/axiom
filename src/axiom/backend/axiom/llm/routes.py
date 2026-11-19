"""Settings routes for the provider registry."""

import json
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from axiom.db.session import open_session
from axiom.errors import AxiomError
from axiom.llm.gateway import iter_stream, list_models
from axiom.llm.store import (
    add_custom,
    complete_role,
    connection_for_provider,
    delete_custom,
    delete_key,
    directory,
    primary_connection,
    probe,
    record_usage,
    remember_models,
    save_key,
    save_roles,
    update_provider,
)
from axiom.llm.types import ChatMessage, ChatRequest, ToolSpec


class ProviderPatch(BaseModel):
    enabled: bool | None = None
    base_url: str | None = None
    model: str | None = None
    proxy: str | None = None
    timeout: int | None = None
    api_version: str | None = None
    region: str | None = None
    api_style: str | None = None
    bedrock_mode: str | None = None
    extra_models: list[dict] | None = None


class KeyBody(BaseModel):
    api_key: str = ""
    aws_secret: str = ""
    aws_session: str = ""


class CustomBody(BaseModel):
    name: str
    base_url: str = ""
    protocol: str = "openai"
    group: str = "local"


class RolesBody(BaseModel):
    roles: dict


class CompleteBody(BaseModel):
    role: str = "planner"
    messages: list[dict] = []
    tools: list[dict] | None = None
    json_schema: dict | None = None
    json_mode: bool = False
    temperature: float = 0.1
    stream: bool = False


def mount_llm(app: FastAPI, current_user) -> None:
    @app.get("/api/llm/providers")
    def llm_providers(_user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            return directory(session)
        finally:
            session.close()

    @app.put("/api/llm/providers/{provider_id}")
    def llm_put_provider(provider_id: str, body: ProviderPatch, _user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            return update_provider(session, provider_id, body.model_dump(exclude_unset=True))
        finally:
            session.close()

    @app.post("/api/llm/providers/{provider_id}/key")
    def llm_put_key(provider_id: str, body: KeyBody, _user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            return save_key(session, provider_id, body.api_key, body.aws_secret, body.aws_session)
        finally:
            session.close()

    @app.delete("/api/llm/providers/{provider_id}/key")
    def llm_delete_key(provider_id: str, _user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            return delete_key(session, provider_id)
        finally:
            session.close()

    @app.post("/api/llm/providers/{provider_id}/test")
    def llm_test(provider_id: str, _user: Annotated[object, Depends(current_user)]):
        return probe(provider_id)

    @app.post("/api/llm/providers/{provider_id}/models")
    def llm_models(provider_id: str, _user: Annotated[object, Depends(current_user)]):
        conn = connection_for_provider(provider_id)
        if conn.protocol == "mock":
            return {"models": []}
        found = list_models(conn)
        session = open_session()
        try:
            card = remember_models(session, provider_id, found)
        finally:
            session.close()
        return {"models": found, "provider": card}

    @app.post("/api/llm/providers")
    def llm_custom(body: CustomBody, _user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            return add_custom(session, body.name, body.base_url, body.protocol, body.group)
        finally:
            session.close()

    @app.delete("/api/llm/providers/{provider_id}")
    def llm_delete_custom(provider_id: str, _user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            delete_custom(session, provider_id)
        finally:
            session.close()
        return {"ok": True}

    @app.get("/api/llm/roles")
    def llm_get_roles(_user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            return directory(session)["roles"]
        finally:
            session.close()

    @app.put("/api/llm/roles")
    def llm_put_roles(body: RolesBody, _user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            roles = save_roles(session, body.roles)
            active = directory(session)["active"]
        finally:
            session.close()
        return {"roles": roles, "active": active}

    @app.get("/api/llm/usage")
    def llm_usage(_user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            return directory(session)["usage"]
        finally:
            session.close()

    @app.post("/api/llm/complete")
    def llm_complete(body: CompleteBody, _user: Annotated[object, Depends(current_user)]):
        if body.stream:
            conn = primary_connection(body.role)
            tool_specs = [
                ToolSpec(item.get("name") or "", item.get("description") or "", item.get("parameters") or {})
                for item in (body.tools or [])
                if item.get("name")
            ]
            request = ChatRequest(
                messages=[ChatMessage(item.get("role") or "user", item.get("content") or "") for item in body.messages],
                model=conn.model,
                temperature=body.temperature,
                tools=tool_specs or None,
                json_schema=body.json_schema,
                json_mode=body.json_mode or bool(body.json_schema),
                stream=True,
                omit_temperature=conn.omit_temperature,
            )

            def generate():
                try:
                    for event in iter_stream(conn, request):
                        if event.get("type") == "done":
                            usage = event.get("usage") or {}
                            record_usage(
                                body.role,
                                conn.provider_id,
                                conn.model,
                                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                                completion_tokens=int(usage.get("completion_tokens") or 0),
                                cost_usd=float(event.get("cost_usd") or 0),
                                latency_ms=int(event.get("latency_ms") or 0),
                                ok=True,
                            )
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except AxiomError as exc:
                    record_usage(body.role, conn.provider_id, conn.model, prompt_tokens=0, completion_tokens=0, cost_usd=0, latency_ms=0, ok=False, error=exc.message)
                    payload = {"type": "error", "message": exc.message, "message_en": exc.message_en, "code": exc.code}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            return StreamingResponse(generate(), media_type="text/event-stream")
        result = complete_role(
            body.role,
            body.messages,
            temperature=body.temperature,
            tools=body.tools,
            json_schema=body.json_schema,
            json_mode=body.json_mode,
        )
        return result.to_dict()
