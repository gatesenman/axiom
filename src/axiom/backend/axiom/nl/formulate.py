"""Turn a natural-language problem into AML.

The offline reasoner is deterministic and covered by tests. When a live model
is configured, the orchestrator may replace the primary formulation with the
model's AML after the same validator accepts it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from axiom.errors import AxiomError
from axiom.modeling import emit_aml, parse_aml, validate
from axiom.modeling.ir import Constraint, Expr, Model, VarDecl, const, ref
from axiom.templates.library import TEMPLATES, get_template

_DSL_FENCE = re.compile(r"```(?:aml|axiom)?\s*([\s\S]*?)```", re.I)
_HAS_ZH = re.compile(r"[\u4e00-\u9fff]")


@dataclass
class Formulation:
    kind: str
    title: str
    summary: str
    summary_en: str
    aml: str | None = None
    confidence: float = 0.0
    questions: list[str] = field(default_factory=list)
    simulation: dict | None = None
    template_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "title": self.title,
            "summary": self.summary,
            "summary_en": self.summary_en,
            "aml": self.aml,
            "confidence": self.confidence,
            "questions": self.questions,
            "simulation": self.simulation,
            "template_id": self.template_id,
        }


def formulate(text: str, locale: str = "zh-CN") -> Formulation:
    raw = (text or "").strip()
    if not raw:
        return _clarify(locale)
    fenced = _DSL_FENCE.search(raw)
    candidate = fenced.group(1) if fenced else raw
    if _looks_like_aml(candidate):
        try:
            model = parse_aml(candidate)
        except AxiomError:
            model = None
        if model is not None:
            checked = validate(model)
            if not any(item.level == "error" for item in checked.diagnostics):
                return Formulation(
                    kind="optimization",
                    title=model.name,
                    summary="已识别为 Axiom 建模语言，将直接校验并求解。" if locale.startswith("zh") else "Recognized as Axiom Modeling Language.",
                    summary_en="Recognized as Axiom Modeling Language and solved directly.",
                    aml=emit_aml(model),
                    confidence=0.98,
                )
    product = _product_mix(raw)
    if product:
        return product
    algebraic = _algebraic(raw)
    if algebraic:
        return algebraic
    queue = _queue(raw)
    if queue:
        return queue
    template = _keyword_template(raw)
    if template:
        return template
    return _clarify(locale, raw)


def alternative_aml(aml: str) -> str | None:
    """Slack-variable form of a linear model, used as a parallel formulation."""
    try:
        model = parse_aml(aml)
    except AxiomError:
        return None
    if not validate(model).ok:
        return None
    try:
        from axiom.modeling.flatten import flatten

        flat = flatten(model)
    except AxiomError:
        return None
    if flat.nonlinear or not model.constraints:
        return None
    cloned = model.copy()
    rewritten: list[Constraint] = []
    for con in cloned.constraints:
        if con.kind != "comparison" or con.relation not in {"<=", ">="} or con.lhs is None or con.rhs is None:
            rewritten.append(con)
            continue
        sets = [quant.set_name for quant in con.quants]
        slack = f"s_{con.name}"
        cloned.variables[slack] = VarDecl(name=slack, index_sets=sets, domain="continuous", lower=0.0, upper=None)
        slack_expr = ref(slack, tuple(ref_index(quant.index) for quant in con.quants)) if sets else ref(slack)
        if con.relation == "<=":
            lhs = Expr(op="add", args=(con.lhs, slack_expr))
        else:
            lhs = Expr(op="sub", args=(con.lhs, slack_expr))
        rewritten.append(
            Constraint(name=con.name, quants=con.quants, kind="comparison", relation="==", lhs=lhs, rhs=con.rhs)
        )
    cloned.constraints = rewritten
    cloned.name = f"{cloned.name}_slack"
    return emit_aml(cloned)


def ref_index(name: str):
    from axiom.modeling.ir import Index

    return Index(kind="symbol", value=name)


def _looks_like_aml(text: str) -> bool:
    lowered = text.lower()
    return "subject to" in lowered or "s.t." in lowered or lowered.strip().startswith("minimize") or lowered.strip().startswith("maximize") or "\nminimize" in lowered or "\nmaximize" in lowered or bool(re.search(r"\b(var|param|set)\b", lowered))


def _product_mix(text: str) -> Formulation | None:
    profits = dict(re.findall(r"产品\s*([A-Za-z0-9]+)[^。\n]{0,16}?利润(?:为|是)?\s*([0-9]+(?:\.[0-9]+)?)", text))
    if not profits:
        profits = dict(re.findall(r"(?:profit of|unit profit of)\s*([A-Za-z0-9]+)\s*(?:is|=)\s*([0-9]+(?:\.[0-9]+)?)", text, re.I))
    needs = re.findall(
        r"(?:生产一件|producing one|one unit of)\s*([A-Za-z0-9]+)\s*(?:需要|requires)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:小时|hours)[^0-9]{0,16}([0-9]+(?:\.[0-9]+)?)\s*(?:公斤|kg)",
        text,
        re.I,
    )
    labor = re.search(r"(?:机器时间不超过|machine time(?: limit)?(?: is)?(?: at most)?)\s*([0-9]+(?:\.[0-9]+)?)", text, re.I)
    material = re.search(r"(?:原料不超过|material(?: limit)?(?: is)?(?: at most)?)\s*([0-9]+(?:\.[0-9]+)?)", text, re.I)
    if len(profits) < 2 or len(needs) < 2 or not labor or not material:
        return None
    order = []
    for name in list(profits) + [item[0] for item in needs]:
        if name not in order:
            order.append(name)
    hours = {name: float(hour) for name, hour, _kg in needs}
    kilograms = {name: float(kg) for name, _hour, kg in needs}
    lines = ["#@ view: bars", "model ProductMix;"]
    objective = []
    labor_terms = []
    material_terms = []
    for name in order:
        var = f"x_{name}"
        lines.append(f"var {var} >= 0;")
        objective.append(f"{_num(float(profits[name]))} * {var}")
        labor_terms.append(f"{_num(hours[name])} * {var}")
        material_terms.append(f"{_num(kilograms[name])} * {var}")
    lines.append("maximize profit: " + " + ".join(objective) + ";")
    lines.append("subject to labor: " + " + ".join(labor_terms) + f" <= {_num(float(labor.group(1)))};")
    lines.append("subject to material: " + " + ".join(material_terms) + f" <= {_num(float(material.group(1)))};")
    aml = "\n".join(lines) + "\n"
    summary = "识别为产品组合线性规划。决策变量是各产品产量，目标是利润最大，约束来自机器工时和原料。"
    return Formulation(
        kind="optimization",
        title="产品组合",
        summary=summary,
        summary_en="Recognized as a product-mix linear program. Variables are production quantities, the objective is profit, and the constraints are machine time and material.",
        aml=aml,
        confidence=0.93,
        template_id="product-mix",
    )


def _algebraic(text: str) -> Formulation | None:
    compact = text.replace("，", "\n").replace("；", "\n").replace(";", "\n")
    sense = None
    objective = None
    constraints = []
    for line in compact.splitlines():
        body = line.strip().rstrip(".")
        if not body:
            continue
        match = re.match(r"^(maximize|minimize|max|min)\s*:?\s*(.+)$", body, re.I)
        if match:
            word = match.group(1).lower()
            sense = "maximize" if word.startswith("max") else "minimize"
            objective = match.group(2).strip()
            continue
        relation = re.search(r"(<=|>=|==|=)", body)
        if relation and re.search(r"[A-Za-z_]", body):
            constraints.append(body.replace("=", "==") if relation.group(1) == "=" else body)
    if not sense or not objective or not constraints:
        return None
    names = []
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", objective + " " + " ".join(constraints)):
        if token.lower() in {"sum", "subject", "to"}:
            continue
        if token not in names:
            names.append(token)
    if not names:
        return None
    lines = ["model Algebraic;"]
    for name in names:
        lines.append(f"var {name};")
    lines.append(f"{sense} objective: {objective};")
    for index, row in enumerate(constraints, start=1):
        lines.append(f"subject to c{index}: {row};")
    aml = "\n".join(lines) + "\n"
    try:
        model = parse_aml(aml)
    except AxiomError:
        return None
    if not validate(model).ok:
        return None
    return Formulation(
        kind="optimization",
        title="代数模型",
        summary="从文本中的目标函数和不等式直接建立了模型。未写上下界的变量保持自由，可在模型编辑器里补上。",
        summary_en="Built the model directly from the objective and inequalities in the text. Variables without bounds stay free.",
        aml=emit_aml(model),
        confidence=0.8,
    )


def _queue(text: str) -> Formulation | None:
    if not re.search(r"排队|队列|仿真|离散事件|queue|discrete-event|simulat", text, re.I):
        return None
    if re.search(r"蒙特卡洛|monte carlo", text, re.I) and not re.search(r"排队|队列|queue", text, re.I):
        return None
    arrival = _first_number(text, r"(?:到达率|arrival rate)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)") or 8
    service = _first_number(text, r"(?:服务率|service rate)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)") or 10
    servers = int(_first_number(text, r"(?:服务台|servers?)[^0-9]{0,8}([0-9]+)") or 1)
    horizon = _first_number(text, r"(?:仿真|horizon|模拟)[^0-9]{0,8}([0-9]+(?:\.[0-9]+)?)") or 8
    config = {"arrival_rate": arrival, "service_rate": service, "servers": max(servers, 1), "horizon": horizon, "seed": 7}
    return Formulation(
        kind="simulation",
        title="排队仿真",
        summary=f"离散事件仿真：到达率 {arrival}、服务率 {service}、{config['servers']} 个服务台、时长 {horizon}。",
        summary_en=f"Discrete-event queue: arrival {arrival}, service {service}, {config['servers']} servers, horizon {horizon}.",
        aml=get_template("queue")["dsl"] if get_template("queue") else None,
        confidence=0.86,
        simulation=config,
        template_id="queue",
    )


def _keyword_template(text: str) -> Formulation | None:
    rules = [
        (r"运输|产销|transport", "transportation"),
        (r"背包|knapsack", "knapsack"),
        (r"指派|分配问题|assignment", "assignment"),
        (r"选址|facility", "facility-location"),
        (r"调度|甘特|schedul", "scheduling"),
        (r"排班|staff", "staffing"),
        (r"配料|营养|diet|blend", "diet"),
        (r"多目标|multi-objective|tradeoff", "multiobjective"),
        (r"拉丁|alldiff|约束规划", "latin"),
        (r"旅行商|tsp|巡回路", "tsp"),
        (r"二次|非线性|quadratic", "portfolio-qp"),
        (r"生产计划|库存|production plan", "production-planning"),
    ]
    for pattern, template_id in rules:
        if re.search(pattern, text, re.I):
            template = get_template(template_id)
            if not template:
                continue
            return Formulation(
                kind=template["kind"],
                title=template["title_zh"],
                summary=f"按「{template['title_zh']}」模板建立了标准实例。{template['summary_zh']} 如果这不是你的数据，可以在模型编辑器里替换参数。",
                summary_en=f"Used the standard {template['title_en']} instance. {template['summary_en']} Replace the data in the editor if needed.",
                aml=template["dsl"],
                confidence=0.62,
                template_id=template_id,
                simulation=template.get("simulation"),
                questions=["确认使用模板中的示例数据，或在批准前改写模型。"],
            )
    return None


def _clarify(locale: str, text: str = "") -> Formulation:
    questions = [
        "决策变量是什么？请给出名称和单位。",
        "要最大化还是最小化什么？",
        "有哪些资源上限或需求下限？请带上数字。",
    ]
    if text and not _HAS_ZH.search(text):
        questions = [
            "What are the decision variables?",
            "What should be minimized or maximized?",
            "Which limits or requirements apply, with numbers?",
        ]
    return Formulation(
        kind="clarification",
        title="需要补充问题结构",
        summary="还不能唯一确定模型。请补充变量、目标和带数字的约束，或从模板库选一个相近问题。",
        summary_en="The problem is not specific enough to formulate yet. Add variables, an objective, and numeric constraints, or start from a template.",
        confidence=0.2,
        questions=questions,
    )


def _first_number(text: str, pattern: str) -> float | None:
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    return float(match.group(1))


def _num(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return format(value, ".12g")
