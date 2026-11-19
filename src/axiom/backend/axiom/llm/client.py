"""Provider-agnostic chat completion.

API keys are stored encrypted. Mock mode never leaves the machine and is the
default, so the studio and its tests run without a credential.
"""

from __future__ import annotations

from dataclasses import dataclass

from axiom.errors import AxiomError


@dataclass
class LLMSettings:
    provider: str = "mock"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    anthropic_version: str = "2023-06-01"


class LLMClient:
    def __init__(self, settings: LLMSettings | None = None, *, role: str | None = None) -> None:
        self.settings = settings or LLMSettings()
        self.role = role

    def complete(self, messages: list[dict[str, str]], *, temperature: float = 0.1) -> str:
        if self.role:
            from axiom.llm.store import complete_text

            return complete_text(self.role, messages, temperature=temperature)
        provider = (self.settings.provider or "mock").lower()
        if provider == "mock":
            raise AxiomError("当前是离线推理模式，没有调用外部模型。", "Mock mode does not call an external model.", code="mock")
        from axiom.llm.gateway import complete
        from axiom.llm.store import connection_from_settings
        from axiom.llm.types import ChatRequest, messages_from_dicts

        conn = connection_from_settings(self.settings)
        request = ChatRequest(
            messages=messages_from_dicts(messages),
            model=conn.model,
            temperature=temperature,
            omit_temperature=conn.omit_temperature,
        )
        return complete(conn, request).text

    def test(self) -> dict:
        if (self.settings.provider or "mock").lower() == "mock" and not self.role:
            return {
                "ok": True,
                "provider": "mock",
                "message": "离线模式可用，不会访问网络。",
                "message_en": "Offline mode is ready and does not use the network.",
                "latency_ms": 0,
            }
        from axiom.llm.gateway import test_connection
        from axiom.llm.store import connection_from_settings

        return test_connection(connection_from_settings(self.settings))


def aml_from_llm(client: LLMClient, problem: str) -> str | None:
    spec = (
        "Write only an Axiom Modeling Language program. "
        "Use set/param/var/minimize|maximize/subject to. Multiplication is explicit with *. "
        "End statements with semicolons. No prose outside one ```aml fence."
    )
    try:
        text = client.complete(
            [
                {"role": "system", "content": spec},
                {"role": "user", "content": problem},
            ]
        )
    except AxiomError:
        return None
    if "```" in text:
        inner = text.split("```", 2)[1]
        if inner.startswith("aml"):
            inner = inner[3:]
        return inner.strip()
    if "minimize" in text or "maximize" in text:
        return text.strip()
    return None
