"""Structured errors shared by the modeling core, solvers, and HTTP API."""

from __future__ import annotations


class AxiomError(Exception):
    """Recoverable product error with bilingual messages."""

    def __init__(
        self,
        message: str,
        message_en: str | None = None,
        *,
        code: str = "error",
        details: list | None = None,
        status: int = 400,
    ) -> None:
        self.message = message
        self.message_en = message_en or message
        self.code = code
        self.details = details or []
        self.status = status
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "message_en": self.message_en,
            "details": self.details,
        }


class NonlinearError(AxiomError):
    def __init__(self, message: str, message_en: str | None = None) -> None:
        super().__init__(message, message_en, code="nonlinear")
