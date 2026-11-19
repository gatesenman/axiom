"""Classic multidisciplinary templates: Sellar, a coupled wing, and a supply chain."""

from __future__ import annotations

import math

from axiom.errors import AxiomError
from axiom.mdo.problem import DesignVar, Discipline, MDOProblem


def get_problem(name: str) -> MDOProblem:
    key = (name or "").lower().strip()
    builder = {"sellar": sellar, "wing": wing, "aircraft": wing, "supply": supply, "supply-chain": supply}.get(key)
    if builder is None:
        raise AxiomError(f"没有这个多学科模板 {name}。", f"Unknown multidisciplinary template {name}.", code="mdo")
    return builder()


def list_problems() -> list[dict]:
    return [
        {"id": "sellar", "title_zh": "Sellar 问题", "title_en": "Sellar problem"},
        {"id": "wing", "title_zh": "机翼尺度", "title_en": "Wing sizing"},
        {"id": "supply", "title_zh": "供应—生产—市场", "title_en": "Supply, production, and market"},
    ]


def sellar() -> MDOProblem:
    def discipline1(state):
        y1 = state["z1"] ** 2 + state["z2"] + state["x1"] - 0.2 * state["y2"]
        return {"y1": y1}

    def discipline2(state):
        y2 = math.sqrt(max(state["y1"], 1e-12)) + state["z1"] + state["z2"]
        return {"y2": y2}

    def limit1(state):
        return [("y1 >= 3.16", 3.16 - state["y1"])]

    def limit2(state):
        return [("y2 <= 24", state["y2"] - 24.0)]

    def objective(state):
        return state["x1"] ** 2 + state["z2"] + state["y1"] + math.exp(-state["y2"])

    def contributions(state):
        return {"x1^2": state["x1"] ** 2, "z2": state["z2"], "y1": state["y1"], "exp(-y2)": math.exp(-state["y2"])}

    return MDOProblem(
        name="sellar",
        title_zh="Sellar 问题",
        title_en="Sellar problem",
        design=[
            DesignVar("z1", -10.0, 10.0, 5.0, unit="—"),
            DesignVar("z2", 0.0, 10.0, 2.0, unit="—"),
            DesignVar("x1", 0.0, 10.0, 1.0, owner="discipline1", unit="—"),
        ],
        couplings=["y1", "y2"],
        disciplines=[
            Discipline("discipline1", ["z1", "z2", "x1", "y2"], ["y1"], discipline1, limit1),
            Discipline("discipline2", ["z1", "z2", "y1"], ["y2"], discipline2, limit2),
        ],
        objective=objective,
        sense="minimize",
        units={"z1": "—", "z2": "—", "x1": "—", "y1": "—", "y2": "—", "objective": "—"},
        contributions=contributions,
    )


def wing() -> MDOProblem:
    """Coupled aerostructural sizing. Weight depends on lift; lift depends on weight."""

    dynamic = 0.5 * 1.225 * 62.0 ** 2

    def structures(state):
        weight = 1800.0 + 28.0 * state["S"] * (state["AR"] ** 0.6) / state["tc"] + 180.0 * state["CL"] * state["S"]
        return {"W": weight}

    def aero(state):
        lift = state["W"] / (dynamic * state["S"])
        drag = 0.02 + lift ** 2 / (math.pi * state["AR"] * 0.82)
        return {"CL": lift, "CD": drag}

    def stress(state):
        # Allowable wing loading leaves an interior trade between drag and stress.
        value = state["W"] * state["AR"] / (state["S"] * state["tc"]) / 65000.0 - 1.0
        return [("stress", value)]

    def lift_limit(state):
        return [("CL <= 1.1", state["CL"] - 1.1)]

    def objective(state):
        lift = state["CL"]
        drag = 0.02 + lift ** 2 / (math.pi * state["AR"] * 0.82)
        # Drag counts in counts; weight pulls the design off the largest wing.
        return drag * 1000.0 + state["W"] / 400.0

    return MDOProblem(
        name="wing",
        title_zh="机翼尺度",
        title_en="Wing sizing",
        design=[
            DesignVar("S", 12.0, 40.0, 22.0, unit="m^2"),
            DesignVar("AR", 5.0, 12.0, 8.0, unit="—"),
            DesignVar("tc", 0.09, 0.16, 0.12, owner="structures", unit="—"),
        ],
        couplings=["W", "CL"],
        disciplines=[
            Discipline("structures", ["S", "AR", "tc", "CL"], ["W"], structures, stress),
            Discipline("aero", ["S", "AR", "W"], ["CL", "CD"], aero, lift_limit),
        ],
        objective=objective,
        sense="minimize",
        units={"S": "m^2", "AR": "—", "tc": "—", "W": "N", "CL": "—", "CD": "—", "objective": "—"},
    )


def supply() -> MDOProblem:
    """Procurement, plant, and market, closed by utilization and service."""

    def procurement(state):
        unit = 6.0 + 0.015 * state["order"] + 1.5 * state["service"]
        return {"unit_cost": unit}

    def plant(state):
        factor = 1.0 / (1.0 + 0.02 * max(state["unit_cost"] - 6.0, 0.0))
        make = min(state["order"], state["capacity"] * factor)
        return {"make": make}

    def market(state):
        demand = max(5.0, 70.0 - 1.4 * state["price"])
        sold = min(state["make"], demand)
        service = sold / demand
        return {"service": service, "demand": demand, "sold": sold}

    def service_limit(state):
        return [("service >= 0.75", 0.75 - state["service"])]

    def objective(state):
        demand = max(5.0, 70.0 - 1.4 * state["price"])
        sold = min(state["make"], demand)
        revenue = state["price"] * sold
        material = state["unit_cost"] * state["order"]
        opex = 3.0 * state["make"] + 0.04 * state["capacity"] ** 2
        backlog = max(demand - state["make"], 0.0)
        profit = revenue - material - opex - 8.0 * backlog
        return -profit

    def contributions(state):
        demand = max(5.0, 70.0 - 1.4 * state["price"])
        sold = min(state["make"], demand)
        return {
            "revenue": state["price"] * sold,
            "material": state["unit_cost"] * state["order"],
            "opex": 3.0 * state["make"] + 0.04 * state["capacity"] ** 2,
        }

    return MDOProblem(
        name="supply",
        title_zh="供应—生产—市场",
        title_en="Supply, production, and market",
        design=[
            DesignVar("order", 10.0, 80.0, 40.0, owner="procurement", unit="t"),
            DesignVar("capacity", 10.0, 90.0, 50.0, owner="plant", unit="t"),
            DesignVar("price", 8.0, 30.0, 18.0, owner="market", unit="currency"),
        ],
        couplings=["unit_cost", "make", "service"],
        disciplines=[
            Discipline("procurement", ["order", "service"], ["unit_cost"], procurement),
            Discipline("plant", ["order", "capacity", "unit_cost"], ["make"], plant),
            Discipline("market", ["price", "make"], ["service", "demand", "sold"], market, service_limit),
        ],
        objective=objective,
        sense="minimize",
        units={"order": "t", "capacity": "t", "price": "currency", "unit_cost": "currency/t", "make": "t", "service": "—", "objective": "currency"},
        contributions=contributions,
    )
