"""Chart payloads must match the solved quantities and the variable table."""

from __future__ import annotations

import pytest

from axiom.analysis.service import present, scenarios, sensitivity
from axiom.modeling import parse_aml
from axiom.templates.library import get_template

PRODUCT = """
model ProductMix;
var x_A >= 0;
var x_B >= 0;
maximize profit: 40 * x_A + 30 * x_B;
subject to labor: 2 * x_A + 3 * x_B <= 120;
subject to material: 3 * x_A + 1 * x_B <= 90;
"""

OPT = 11400 / 7


def test_present_bars_follow_variable_order_and_values():
    model = parse_aml(PRODUCT)
    variables = {"x_A": 150 / 7, "x_B": 180 / 7, "_aux": 3.0, "s_labor": 1.0}
    view = present(model, variables, OPT)
    assert [row["name"] for row in view["bars"]] == ["x_A", "x_B"]
    assert view["bars"][0]["value"] == pytest.approx(21.428571, rel=1e-4)
    assert view["bars"][1]["value"] == pytest.approx(25.714286, rel=1e-4)
    assert view["objective"] == pytest.approx(OPT)


def test_scenarios_use_the_objective_scale():
    model = parse_aml(PRODUCT)
    cases = scenarios(
        model,
        [
            {"name": "基准"},
            {"name": "右端 +10%", "rhs_scale": {"labor": 1.1, "material": 1.1}},
            {"name": "右端 -10%", "rhs_scale": {"labor": 0.9, "material": 0.9}},
        ],
    )
    by_name = {row["name"]: row["objective"] for row in cases}
    assert by_name["基准"] == pytest.approx(OPT, rel=1e-3)
    assert by_name["右端 +10%"] > by_name["基准"] > by_name["右端 -10%"]
    assert min(by_name.values()) > 1000


def test_sensitivity_span_is_the_objective_range():
    model = parse_aml(PRODUCT)
    sens = sensitivity(model, "highs", widths=(-0.1, 0.1))
    assert sens["base"] == pytest.approx(OPT, rel=1e-3)
    assert sens["rows"]
    for row in sens["rows"]:
        assert row["low"] <= row["base"] + 1e-4
        assert row["base"] <= row["high"] + 1e-4
        assert row["span"] == pytest.approx(row["high"] - row["low"], abs=1e-6)
        assert 0 <= row["span"] < abs(sens["base"])


def test_gantt_payload_uses_job_start_and_duration():
    template = get_template("scheduling")
    assert template is not None
    model = parse_aml(template["dsl"])
    view = present(
        model,
        {"start[J1]": 0.0, "start[J2]": 10.0, "start[J3]": 20.0, "makespan": 24.0},
        24.0,
    )
    gantt = view["gantt"]
    assert [row["id"] for row in gantt] == ["J1", "J2", "J3"]
    assert gantt[2]["start"] == pytest.approx(20)
    assert gantt[2]["duration"] == pytest.approx(4)
    assert gantt[2]["end"] == pytest.approx(24)
