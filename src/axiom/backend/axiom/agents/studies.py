"""Natural-language proposals for the analysis workbench.

The matcher is deliberately lexical so a local agent can start a study
without a language-model call. A confident match is safe to run.
"""

from __future__ import annotations


_RULES = (
    ("mdo", ("sellar", "多学科", "mdo", "idf", "协同优化", "collaborative optimization", "bliss", "n2", "机翼尺度", "wing sizing")),
    ("sobol", ("sobol", "索博尔", "全局灵敏度", "variance-based", "敏感性指数")),
    ("morris", ("morris", "莫里斯", "筛选", "elementary effect")),
    ("local", ("对偶", "影子价格", "reduced cost", "既约费用", "目标系数范围", "局部灵敏度", "local sensitivity", "ranging")),
    ("doe", ("试验设计", "拉丁超立方", "latin hypercube", "box-behnken", "中心复合", "响应面", "response surface", "kriging", "doe")),
    ("uq", ("不确定性", "蒙特卡洛", "monte carlo", "拉丁超立方传播", "可靠度", "form", "失效概率")),
    ("robust", ("稳健", "两阶段", "recourse", "随机规划", "情景优化")),
    ("chance", ("机会约束", "chance constraint")),
    ("multi", ("多目标", "帕累托", "pareto", "nsga", "加权和", "epsilon", "ε-约束")),
    ("iis", ("不可行", "iis", "冲突约束", "不可约")),
    ("schedule", ("甘特", "gantt", "调度", "完工时间")),
    ("sweep", ("假设", "what-if", "扫描", "参数摄动")),
    ("compatibility", ("兼容", "compatibility", "求解器矩阵")),
)


def propose(text: str, dsl: str = "") -> dict:
    haystack = f"{text}\n{dsl}".lower()
    hits = []
    for kind, words in _RULES:
        matched = [word for word in words if word.lower() in haystack]
        if matched:
            hits.append({"kind": kind, "matched": matched, "confidence": min(0.95, 0.55 + 0.15 * len(matched))})
    hits.sort(key=lambda item: item["confidence"], reverse=True)
    auto = hits[0] if hits and hits[0]["confidence"] >= 0.7 else None
    options = _options(auto["kind"], haystack) if auto else {}
    return {
        "proposals": [_describe(item) | {"options": _options(item["kind"], haystack)} for item in hits],
        "auto": None
        if auto is None
        else {
            "kind": auto["kind"],
            "confidence": auto["confidence"],
            "options": options,
            "reason_zh": _describe(auto)["reason_zh"],
            "reason_en": _describe(auto)["reason_en"],
        },
    }


def _options(kind: str, text: str) -> dict:
    options: dict = {}
    if "sellar" in text:
        options["template"] = "sellar"
    elif "机翼" in text or "wing" in text:
        options["template"] = "wing"
    elif "供应" in text or "supply" in text:
        options["template"] = "supply"
    if kind == "mdo":
        options.setdefault("template", "sellar")
        if "idf" in text:
            options["architecture"] = "idf"
        elif "协同" in text or "collaborative" in text:
            options["architecture"] = "co"
        elif "bliss" in text:
            options["architecture"] = "bliss"
        elif "openmdao" in text:
            options["architecture"] = "openmdao"
        else:
            options["architecture"] = "mdf"
        if "newton" in text or "牛顿" in text:
            options["mda"] = "newton"
    if kind == "multi":
        options["method"] = "nsga3" if "nsga-iii" in text or "nsga3" in text else "nsga2"
        if "加权" in text or "weighted" in text:
            options["method"] = "weighted"
        if "epsilon" in text or "ε" in text:
            options["method"] = "epsilon"
    if kind == "doe":
        options["method"] = "lhs"
        options["surrogate"] = "kriging" if "kriging" in text or "克里金" in text else "polynomial"
        if "box" in text:
            options["method"] = "box-behnken"
        if "sobol" in text:
            options["method"] = "sobol"
    if kind == "sobol":
        options["samples"] = 16
    if kind == "uq":
        options["method"] = "lhs" if "拉丁" in text or "lhs" in text else "monte-carlo"
        options["samples"] = 16
        if "form" in text or "可靠" in text:
            options["form"] = True
    if kind == "compatibility":
        options["execute"] = False
    return options


def _describe(item: dict) -> dict:
    kind = item["kind"]
    reasons = {
        "mdo": ("语句在问多学科设计和耦合。", "The request asks for multidisciplinary design and coupling."),
        "sobol": ("语句在问方差分解后的全局灵敏度。", "The request asks for variance-based global sensitivity."),
        "morris": ("语句在问 Morris 筛选。", "The request asks for Morris screening."),
        "local": ("语句在问对偶、既约费用或系数范围。", "The request asks for duals, reduced costs, or coefficient ranges."),
        "doe": ("语句在问试验设计或响应面。", "The request asks for a design of experiments or a response surface."),
        "uq": ("语句在问不确定性如何传到目标。", "The request asks how uncertainty reaches the objective."),
        "robust": ("语句在问稳健或情景随机规划。", "The request asks for robust or scenario optimization."),
        "chance": ("语句在问机会约束。", "The request asks for chance constraints."),
        "multi": ("语句在问帕累托或多目标。", "The request asks for a Pareto front or a multi-objective run."),
        "iis": ("语句在问是哪几条约束冲突。", "The request asks which constraints conflict."),
        "schedule": ("语句在问调度和甘特图。", "The request asks for a schedule and a Gantt chart."),
        "sweep": ("语句在问参数扫描。", "The request asks for a parametric sweep."),
        "compatibility": ("语句在问求解器和建模语言的兼容范围。", "The request asks for the solver and language matrix."),
    }
    zh, en = reasons.get(kind, ("可以做这项分析。", "This analysis can be run."))
    return {"kind": kind, "confidence": item["confidence"], "matched": item["matched"], "reason_zh": zh, "reason_en": en}
