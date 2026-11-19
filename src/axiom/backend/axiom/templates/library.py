"""Worked examples that ship with Axiom. Every optimization template solves."""

from __future__ import annotations

TEMPLATES: list[dict] = [
    {
        "id": "product-mix",
        "category": "lp",
        "title_zh": "产品组合",
        "title_en": "Product mix",
        "summary_zh": "两种产品、工时与原料限制下的利润最大化。",
        "summary_en": "Maximize profit for two products under labor and material limits.",
        "kind": "optimization",
        "solver": "highs",
        "dsl": """
#@ view: bars
model ProductMix;
var xA >= 0;
var xB >= 0;
maximize profit: 40 * xA + 30 * xB;
subject to labor: 2 * xA + 3 * xB <= 120;
subject to material: 3 * xA + xB <= 90;
""",
    },
    {
        "id": "production-planning",
        "category": "lp",
        "title_zh": "多周期生产计划",
        "title_en": "Multi-period production planning",
        "summary_zh": "库存平衡、产能上限，最小化生产与持有成本。",
        "summary_en": "Inventory balance and capacity limits, minimizing production and holding cost.",
        "kind": "optimization",
        "solver": "highs",
        "dsl": """
#@ view: bars
model ProductionPlan;
set P := {A, B};
set T := 1..3;
set Trest := 2..3;
param demand[P, T] := {(A, 1): 10, (A, 2): 12, (A, 3): 8, (B, 1): 6, (B, 2): 9, (B, 3): 7};
param prod_cost[P] := {A: 5, B: 4};
param hold_cost[P] := {A: 1, B: 1};
param init[P] := {A: 2, B: 1};
param capacity[T] := {1: 30, 2: 30, 3: 30};
var produce[P, T] >= 0;
var inventory[P, T] >= 0;
minimize cost: sum {p in P, t in T} (prod_cost[p] * produce[p, t] + hold_cost[p] * inventory[p, t]);
subject to open[p in P]: inventory[p, 1] == init[p] + produce[p, 1] - demand[p, 1];
subject to balance[p in P, t in Trest]: inventory[p, t] == inventory[p, t-1] + produce[p, t] - demand[p, t];
subject to capacity[t in T]: sum {p in P} produce[p, t] <= capacity[t];
""",
    },
    {
        "id": "transportation",
        "category": "lp",
        "title_zh": "运输问题",
        "title_en": "Transportation",
        "summary_zh": "从产地到销地的最小运费，供给与需求同时满足。",
        "summary_en": "Minimum-cost shipments that respect supply and meet demand.",
        "kind": "optimization",
        "solver": "highs",
        "dsl": """
#@ view: network
#@ network_flow: x
#@ network_origin_set: O
#@ network_dest_set: D
model Transport;
set O := {O1, O2};
set D := {D1, D2, D3};
param supply[O] := {O1: 20, O2: 30};
param demand[D] := {D1: 10, D2: 15, D3: 25};
param cost[O, D] := {(O1, D1): 2, (O1, D2): 4, (O1, D3): 5, (O2, D1): 3, (O2, D2): 1, (O2, D3): 7};
var x[O, D] >= 0;
minimize total: sum {o in O, d in D} cost[o, d] * x[o, d];
subject to supply_limit[o in O]: sum {d in D} x[o, d] <= supply[o];
subject to demand_met[d in D]: sum {o in O} x[o, d] >= demand[d];
""",
    },
    {
        "id": "assignment",
        "category": "mip",
        "title_zh": "指派问题",
        "title_en": "Assignment",
        "summary_zh": "每位员工恰好一项任务，每项任务恰好一人，总成本最小。",
        "summary_en": "One worker per job and one job per worker, at minimum cost.",
        "kind": "optimization",
        "solver": "highs",
        "dsl": """
model Assignment;
set W := {W1, W2, W3};
set J := {J1, J2, J3};
param cost[W, J] := {(W1, J1): 8, (W1, J2): 4, (W1, J3): 7, (W2, J1): 5, (W2, J2): 6, (W2, J3): 3, (W3, J1): 6, (W3, J2): 5, (W3, J3): 8};
var x[W, J] binary;
minimize total: sum {w in W, j in J} cost[w, j] * x[w, j];
subject to one_job[w in W]: sum {j in J} x[w, j] == 1;
subject to one_worker[j in J]: sum {w in W} x[w, j] == 1;
""",
    },
    {
        "id": "knapsack",
        "category": "mip",
        "title_zh": "0-1 背包",
        "title_en": "0-1 knapsack",
        "summary_zh": "在重量上限内选择物品，使价值最大。",
        "summary_en": "Choose items under a weight limit to maximize value.",
        "kind": "optimization",
        "solver": "highs",
        "dsl": """
model Knapsack;
set I := {1, 2, 3, 4};
param value[I] := {1: 16, 2: 19, 3: 23, 4: 28};
param weight[I] := {1: 2, 2: 3, 3: 4, 4: 5};
param capacity := 7;
var take[I] binary;
maximize total: sum {i in I} value[i] * take[i];
subject to limit: sum {i in I} weight[i] * take[i] <= capacity;
""",
    },
    {
        "id": "facility-location",
        "category": "mip",
        "title_zh": "设施选址",
        "title_en": "Facility location",
        "summary_zh": "开设仓库的固定成本加上配送成本。",
        "summary_en": "Fixed opening cost plus shipping cost.",
        "kind": "optimization",
        "solver": "highs",
        "dsl": """
model Facility;
set F := {F1, F2, F3};
set C := {C1, C2, C3};
param fixed[F] := {F1: 100, F2: 80, F3: 90};
param ship[F, C] := {(F1, C1): 4, (F1, C2): 6, (F1, C3): 9, (F2, C1): 5, (F2, C2): 4, (F2, C3): 7, (F3, C1): 6, (F3, C2): 3, (F3, C3): 4};
param demand[C] := {C1: 10, C2: 12, C3: 8};
var open[F] binary;
var flow[F, C] >= 0;
minimize cost: sum {f in F} fixed[f] * open[f] + sum {f in F, c in C} ship[f, c] * flow[f, c];
subject to serve[c in C]: sum {f in F} flow[f, c] >= demand[c];
subject to link[f in F, c in C]: flow[f, c] <= demand[c] * open[f];
""",
    },
    {
        "id": "scheduling",
        "category": "mip",
        "title_zh": "单机调度",
        "title_en": "Single-machine scheduling",
        "summary_zh": "三道工序互不重叠，最小化完工时间，并给出甘特图。",
        "summary_en": "Sequence three jobs without overlap and minimize the makespan.",
        "kind": "optimization",
        "solver": "highs",
        "dsl": """
#@ view: gantt
#@ gantt_job_set: J
#@ gantt_start: start
#@ gantt_duration: p
model Schedule;
set J := {J1, J2, J3};
param p[J] := {J1: 3, J2: 2, J3: 4};
var makespan >= 0;
var start[J] >= 0;
var y12 binary;
var y13 binary;
var y23 binary;
minimize horizon: makespan;
subject to done1: makespan >= start[J1] + p[J1];
subject to done2: makespan >= start[J2] + p[J2];
subject to done3: makespan >= start[J3] + p[J3];
subject to order12a: start[J2] >= start[J1] + p[J1] - 100 * (1 - y12);
subject to order12b: start[J1] >= start[J2] + p[J2] - 100 * y12;
subject to order13a: start[J3] >= start[J1] + p[J1] - 100 * (1 - y13);
subject to order13b: start[J1] >= start[J3] + p[J3] - 100 * y13;
subject to order23a: start[J3] >= start[J2] + p[J2] - 100 * (1 - y23);
subject to order23b: start[J2] >= start[J3] + p[J3] - 100 * y23;
""",
    },
    {
        "id": "diet",
        "category": "lp",
        "title_zh": "配料问题",
        "title_en": "Diet / blending",
        "summary_zh": "用最低成本满足营养下限。",
        "summary_en": "Meet nutrient floors at minimum cost.",
        "kind": "optimization",
        "solver": "highs",
        "dsl": """
model Diet;
set Food := {Bread, Milk, Eggs};
set Nutrient := {Protein, Calories};
param cost[Food] := {Bread: 2, Milk: 3, Eggs: 4};
param nutrition[Nutrient, Food] := {(Protein, Bread): 4, (Protein, Milk): 8, (Protein, Eggs): 13, (Calories, Bread): 100, (Calories, Milk): 150, (Calories, Eggs): 80};
param minimum[Nutrient] := {Protein: 50, Calories: 800};
var buy[Food] >= 0;
minimize spend: sum {f in Food} cost[f] * buy[f];
subject to need[n in Nutrient]: sum {f in Food} nutrition[n, f] * buy[f] >= minimum[n];
""",
    },
    {
        "id": "staffing",
        "category": "mip",
        "title_zh": "排班",
        "title_en": "Staff scheduling",
        "summary_zh": "用最少班次覆盖每天需求。每个班次连续覆盖三天。",
        "summary_en": "Cover daily demand with the fewest three-day shifts.",
        "kind": "optimization",
        "solver": "highs",
        "dsl": """
model Staffing;
set Day := {Mon, Tue, Wed, Thu, Fri};
set Shift := {S1, S2, S3, S4, S5};
param need[Day] := {Mon: 3, Tue: 4, Wed: 5, Thu: 4, Fri: 3};
param cover[Shift, Day] := {(S1, Mon): 1, (S1, Tue): 1, (S1, Wed): 1, (S1, Thu): 0, (S1, Fri): 0, (S2, Mon): 0, (S2, Tue): 1, (S2, Wed): 1, (S2, Thu): 1, (S2, Fri): 0, (S3, Mon): 0, (S3, Tue): 0, (S3, Wed): 1, (S3, Thu): 1, (S3, Fri): 1, (S4, Mon): 1, (S4, Tue): 0, (S4, Wed): 0, (S4, Thu): 1, (S4, Fri): 1, (S5, Mon): 1, (S5, Tue): 1, (S5, Wed): 0, (S5, Thu): 0, (S5, Fri): 1};
var n[Shift] >= 0 integer;
minimize staff: sum {s in Shift} n[s];
subject to cover_day[d in Day]: sum {s in Shift} cover[s, d] * n[s] >= need[d];
""",
    },
    {
        "id": "multiobjective",
        "category": "multiobjective",
        "title_zh": "多目标生产",
        "title_en": "Multi-objective production",
        "summary_zh": "同时压低成本并提高产量，按权重合成。",
        "summary_en": "Trade cost against output with explicit weights.",
        "kind": "optimization",
        "solver": "highs",
        "dsl": """
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
""",
    },
    {
        "id": "portfolio-qp",
        "category": "nlp",
        "title_zh": "二次成本",
        "title_en": "Quadratic cost",
        "summary_zh": "产量带来递增的二次成本，在需求约束下求最小成本。",
        "summary_en": "Increasing quadratic production cost subject to a demand floor.",
        "kind": "optimization",
        "solver": "ipopt",
        "dsl": """
model QuadraticCost;
var x >= 0 <= 20;
var y >= 0 <= 20;
minimize cost: 2 * x + 3 * y + 0.4 * x^2 + 0.3 * y^2;
subject to demand: x + y >= 10;
""",
    },
    {
        "id": "latin",
        "category": "cp",
        "title_zh": "拉丁方（约束规划）",
        "title_en": "Latin square (CP)",
        "summary_zh": "行、列均为 1..3 的排列，用 alldiff 表达。",
        "summary_en": "Every row and column is a permutation, written with alldiff.",
        "kind": "optimization",
        "solver": "cp-sat",
        "dsl": """
model Latin;
set R := {1, 2, 3};
set C := {1, 2, 3};
var cell[R, C] integer >= 1 <= 3;
minimize anchor: cell[1, 1];
subject to row[r in R]: alldiff {c in C} cell[r, c];
subject to col[c in C]: alldiff {r in R} cell[r, c];
subject to clue: cell[1, 1] == 1;
""",
    },
    {
        "id": "queue",
        "category": "simulation",
        "title_zh": "单服务台排队",
        "title_en": "Single-server queue",
        "summary_zh": "指数到达与服务的离散事件仿真，统计等待与利用率。",
        "summary_en": "Discrete-event simulation of an exponential queue.",
        "kind": "simulation",
        "solver": "simpy",
        "simulation": {
            "arrival_rate": 8,
            "service_rate": 10,
            "servers": 1,
            "horizon": 8,
            "seed": 7,
        },
        "dsl": """
#@ kind: simulation
model Queue;
param arrival_rate := 8;
param service_rate := 10;
param servers := 1;
param horizon := 8;
""",
    },
    {
        "id": "tsp",
        "category": "mip",
        "title_zh": "旅行商（MTZ）",
        "title_en": "Traveling salesperson (MTZ)",
        "summary_zh": "五个城市的最短回路，Miller–Tucker–Zemlin 消去子环。",
        "summary_en": "Shortest tour on five cities with MTZ subtour elimination.",
        "kind": "optimization",
        "solver": "highs",
        "dsl": """
model TSP;
set City := {A, B, C, D};
set Rest := {B, C, D};
param dist[City, City] := {(A, A): 0, (A, B): 2, (A, C): 9, (A, D): 10, (B, A): 1, (B, B): 0, (B, C): 6, (B, D): 4, (C, A): 15, (C, B): 7, (C, C): 0, (C, D): 8, (D, A): 6, (D, B): 3, (D, C): 12, (D, D): 0};
var go[City, City] binary;
var u[City] >= 1 <= 4;
minimize length: sum {i in City, j in City} dist[i, j] * go[i, j];
subject to leave[i in City]: sum {j in City} go[i, j] == 1;
subject to enter[j in City]: sum {i in City} go[i, j] == 1;
subject to noloop[i in City]: go[i, i] == 0;
subject to mtz[i in Rest, j in Rest]: u[i] - u[j] + 4 * go[i, j] <= 3;
subject to fix: u[A] == 1;
""",
    },
]


def get_template(template_id: str) -> dict | None:
    return next((item for item in TEMPLATES if item["id"] == template_id), None)


def list_templates() -> list[dict]:
    rows = []
    for item in TEMPLATES:
        rows.append({key: value for key, value in item.items() if key != "dsl"})
    return rows
