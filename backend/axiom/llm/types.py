"""Shared request and result types for every model protocol."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolSpec:
    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)


@dataclass
class ChatMessage:
    role: str
    content: str = ""
    tool_calls: list[dict] | None = None
    tool_call_id: str = ""
    name: str = ""


@dataclass
class ChatRequest:
    messages: list[ChatMessage]
    model: str
    temperature: float = 0.1
    max_tokens: int = 4096
    tools: list[ToolSpec] | None = None
    json_schema: dict | None = None
    json_mode: bool = False
    stream: bool = False
    omit_temperature: bool = False

    @property
    def wants_json(self) -> bool:
        return bool(self.json_schema) or self.json_mode


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class ChatResult:
    text: str
    tool_calls: list[dict]
    usage: Usage
    latency_ms: int
    model: str
    provider: str
    finish_reason: str = ""
    protocol: str = ""
    json_fallback: bool = False
    cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "tool_calls": self.tool_calls,
            "usage": self.usage.to_dict(),
            "latency_ms": self.latency_ms,
            "model": self.model,
            "provider": self.provider,
            "finish_reason": self.finish_reason,
            "protocol": self.protocol,
            "json_fallback": self.json_fallback,
            "cost_usd": self.cost_usd,
        }


@dataclass
class Connection:
    """One configured endpoint. Secrets stay in memory for the call only."""

    provider_id: str
    protocol: str
    base_url: str
    api_key: str = ""
    model: str = ""
    auth: str = "bearer"
    api_version: str = "2024-10-21"
    region: str = "us-east-1"
    aws_secret: str = ""
    aws_session: str = ""
    proxy: str = ""
    timeout: float = 60
    api_style: str = "chat"
    bedrock_mode: str = "native"
    key_optional: bool = False
    supports_json: bool = True
    input_usd_per_mtok: float = 0.0
    output_usd_per_mtok: float = 0.0
    omit_temperature: bool = False


def messages_from_dicts(items: list[dict]) -> list[ChatMessage]:
    converted: list[ChatMessage] = []
    for item in items:
        converted.append(
            ChatMessage(
                role=str(item.get("role") or "user"),
                content=item.get("content") or "",
                tool_calls=item.get("tool_calls"),
                tool_call_id=str(item.get("tool_call_id") or ""),
                name=str(item.get("name") or ""),
            )
        )
    return converted
