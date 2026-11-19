"""Translator plugin contract.

Register a translator by adding it to ``TRANSLATORS`` or by calling
``register``. A translator receives a validated ``Model`` and returns source
text. It must not solve the model and must not depend on a live solver
license. Linear global constraints such as ``alldiff`` are linearized before
emission so every backend sees a pure algebraic model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from axiom.modeling.ir import Model


@dataclass
class Translation:
    target: str
    language: str
    filename: str
    code: str

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "language": self.language,
            "filename": self.filename,
            "code": self.code,
        }


class Translator(Protocol):
    name: str
    language: str
    filename: str

    def translate(self, model: Model) -> str: ...


def register(translator: Translator) -> Translator:
    from axiom.modeling.translators.registry import TRANSLATORS

    TRANSLATORS[translator.name] = translator
    return translator
