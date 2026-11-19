"""Feasible-region geometry and the two-objective Pareto sweep."""

from __future__ import annotations

from axiom.analysis.figures import academic_figures, feasible_region, pareto_front
from axiom.modeling import parse_aml

PRODUCT = """
model ProductMix;
var xA >= 0;
var xB >= 0;
maximize profit: 40 * xA + 30 * xB;
subject to labor: 2 * xA + 3 * xB <= 120;
subject to material: 3 * xA + xB <= 90;
"""

TRADEOFF = """
model Tradeoff;
var x >= 0 <= 10;
var y >= 0 <= 8;
minimize cost: 5 * x + 4 * y;
maximize output: 2 * x + 3 * y;
weight cost 0.5;
weight output 0.5;
subject to labor: 2 * x + y <= 16;
subject to material: x + 2 * y <= 14;
subject to quota: x + y >= 8;
"""


def test_product_mix_feasible_region_contains_the_optimum_vertex():
    region = feasible_region(parse_aml(PRODUCT))
    assert region is not None
    assert region["x"] == "xA"
    assert region["y"] == "xB"
    polygon = region["polygon"]
    assert len(polygon) >= 3
    optimum = (150 / 7, 180 / 7)
    assert any(abs(point[0] - optimum[0]) < 1e-4 and abs(point[1] - optimum[1]) < 1e-4 for point in polygon)
    names = {line["name"] for line in region["lines"]}
    assert "labor" in names and "material" in names


def test_integer_model_has_no_continuous_region():
    model = parse_aml("var x binary;\nvar y binary;\nmaximize obj: x + y;\nsubject to cap: x + y <= 1;\n")
    assert feasible_region(model) is None


def test_pareto_front_trades_cost_against_output():
    front = pareto_front(parse_aml(TRADEOFF), "highs")
    assert front is not None
    assert front["x"] == "cost"
    assert front["y"] == "output"
    assert len(front["points"]) >= 2
    costs = [point["x"] for point in front["points"]]
    outputs = [point["y"] for point in front["points"]]
    assert max(costs) > min(costs)
    assert max(outputs) > min(outputs)


def test_report_embeds_a_captioned_figure():
    from axiom.reports.build import markdown_report, pdf_report

    document = {
        "title": "产品组合",
        "status": "optimal",
        "solver": "highs",
        "objective": 1628.57,
        "variables": {"xA": 21.4},
        "sensitivity": {"rows": [{"name": "rhs:labor", "low": 1500, "base": 1628, "high": 1800, "span": 300}]},
        "duals": {"labor": 4.5},
        "figures": feasible_region(parse_aml(PRODUCT)),
    }
    document["figures"] = {"feasible_region": document["figures"]}
    text = markdown_report(document, "zh-CN")
    assert "\\begin{figure}" in text
    assert "图1" in text
    pdf = pdf_report(document, "zh-CN")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 800


def test_academic_figures_attach_the_solved_point():
    from axiom.solvers.registry import solve_model

    model = parse_aml(PRODUCT)
    solved = solve_model(model, "highs")
    figures = academic_figures(model, solved.variables, "highs")
    region = figures["feasible_region"]
    assert abs(region["optimum"]["x"] - 150 / 7) < 1e-3
    assert abs(region["optimum"]["y"] - 180 / 7) < 1e-3
    assert figures["pareto"] is None
