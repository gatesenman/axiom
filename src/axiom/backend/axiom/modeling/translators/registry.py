"""Built-in translator registry."""

from __future__ import annotations

from axiom.errors import AxiomError
from axiom.modeling.exchange import write_cbf, write_flatzinc, write_free_mps, write_minizinc, write_nl, write_osil, write_qps, write_sdpa
from axiom.modeling.formats import write_lp, write_mps
from axiom.modeling.libraries import emit_library
from axiom.modeling.ir import Model
from axiom.modeling.linearize import expand_specials
from axiom.modeling.translators.base import Translation
from axiom.modeling.translators.emit import emit_source
from axiom.modeling.validator import validate

TRANSLATORS: dict = {}


class _FormatTranslator:
    def __init__(self, name: str, language: str, filename: str, writer) -> None:
        self.name = name
        self.language = language
        self.filename = filename
        self.writer = writer

    def translate(self, model: Model) -> str:
        return self.writer(model)


class _LibraryTranslator:
    def __init__(self, name: str, language: str, filename: str) -> None:
        self.name = name
        self.language = language
        self.filename = filename

    def translate(self, model: Model) -> str:
        return emit_library(model, self.name)


class _TextTranslator:
    def __init__(self, name: str, language: str, filename: str) -> None:
        self.name = name
        self.language = language
        self.filename = filename

    def translate(self, model: Model) -> str:
        return emit_source(expand_specials(model), self.name)


def _write_sdpa_model(model: Model) -> str:
    import json

    raw = model.meta.get("sdpa")
    if not raw:
        raise AxiomError(
            "这个模型没有 SDPA 数据。导入一个 SDPA 文件后再导出。",
            "This model has no SDPA data. Import an SDPA file before exporting one.",
            code="import",
        )
    return write_sdpa(json.loads(raw))


def _register_defaults() -> None:
    if TRANSLATORS:
        return
    for item in (
        _TextTranslator("pyomo", "python", "model_pyomo.py"),
        _TextTranslator("pulp", "python", "model_pulp.py"),
        _TextTranslator("ortools", "python", "model_ortools.py"),
        _TextTranslator("cvxpy", "python", "model_cvxpy.py"),
        _TextTranslator("ampl", "ampl", "model.mod"),
        _TextTranslator("gams", "gams", "model.gms"),
        _TextTranslator("jump", "julia", "model.jl"),
        _FormatTranslator("lp", "lp", "model.lp", write_lp),
        _FormatTranslator("mps", "mps", "model.mps", write_mps),
        _FormatTranslator("mps-free", "mps", "model.mps", write_free_mps),
        _FormatTranslator("qps", "qps", "model.qps", write_qps),
        _FormatTranslator("nl", "nl", "model.nl", write_nl),
        _FormatTranslator("osil", "xml", "model.osil", write_osil),
        _FormatTranslator("cbf", "cbf", "model.cbf", write_cbf),
        _FormatTranslator("sdpa", "sdpa", "model.dat-s", _write_sdpa_model),
        _FormatTranslator("minizinc", "minizinc", "model.mzn", write_minizinc),
        _FormatTranslator("flatzinc", "flatzinc", "model.fzn", write_flatzinc),
        _LibraryTranslator("gmpl", "gmpl", "model.mod"),
        _LibraryTranslator("zimpl", "zimpl", "model.zpl"),
        _LibraryTranslator("opl", "opl", "model.mod"),
        _LibraryTranslator("gurobipy", "python", "model_gurobi.py"),
        _LibraryTranslator("docplex", "python", "model_docplex.py"),
        _LibraryTranslator("linopy", "python", "model_linopy.py"),
        _LibraryTranslator("mip", "python", "model_mip.py"),
        _LibraryTranslator("casadi", "python", "model_casadi.py"),
    ):
        TRANSLATORS[item.name] = item


def translate(model: Model, target: str) -> Translation:
    _register_defaults()
    key = target.lower().strip()
    translator = TRANSLATORS.get(key)
    if translator is None:
        known = ", ".join(sorted(TRANSLATORS))
        raise AxiomError(
            f"未知导出目标 {target}。可选：{known}。",
            f"Unknown export target {target}. Choices: {known}.",
            code="unknown_translator",
        )
    checked = validate(model)
    errors = [item for item in checked.diagnostics if item.level == "error"]
    if errors:
        raise AxiomError(errors[0].message, errors[0].message_en, code=errors[0].code, details=[i.to_dict() for i in errors])
    code = translator.translate(model)
    return Translation(target=translator.name, language=translator.language, filename=translator.filename, code=code)


def list_translators() -> list[dict[str, str]]:
    _register_defaults()
    return [
        {"name": item.name, "language": item.language, "filename": item.filename}
        for item in TRANSLATORS.values()
    ]
