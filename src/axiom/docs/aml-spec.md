# Axiom Modeling Language

AML is a declarative language for linear, mixed-integer, and nonlinear models. A program is a sequence of statements. `#` starts a comment. A line `#@ key: value` is metadata (for example `#@ view: gantt`) and is stripped before parsing. Multiplication is explicit: write `2 * x`, not `2 x`.

```
model ProductMix;
set P := {A, B};
param profit[P] := {A: 40, B: 30} default 0;
var x[P] >= 0;
maximize total: sum {p in P} profit[p] * x[p];
subject to cap: sum {p in P} x[p] <= 100;
```

## Statements

| Form | Meaning |
| --- | --- |
| `model Name;` | Model name |
| `set Name := {A, B};` or `set T := 1..3;` | Finite set. Elements are names, numbers, or strings. A trailing comma is allowed. |
| `param Name := 3;` | Scalar parameter |
| `param Name[I, J] := {(A, 1): 10} default 0;` | Indexed parameter. A missing entry uses `default` when it is declared. |
| `var Name >= 0 <= 10 integer;` | Variable. Domain keywords `continuous`, `integer`, and `binary` may appear in any order with bounds. Binary defaults to 0..1. Unbounded variables stay free. |
| `minimize Name: expr;` / `maximize Name: expr;` | Objective. `min` and `max` are accepted. Several objectives become a weighted minimization; `weight Name value;` sets a weight (a maximization is negated). |
| `subject to Name[i in I]: expr <= expr;` | Constraint. `s.t.` is the same keyword. Relations are `<=`, `>=`, `==`, and `=`. |
| `subject to rows[i in I]: alldiff {j in J} x[i, j];` | All-different. The domain must be a finite integer set of at most 40 values. It is linearized into an assignment MIP before export and before MIP solvers. |

Indexes inside a quantifier are `i in Set`. An index expression may be a name, a number, a string, `t-1`, `t+1`, or `prev(t)`.

## Expressions

Precedence, tightest last: unary minus, power `^`, product `*` and `/`, sum `+` and `-`. Parentheses group. A summation is `sum {i in I, j in J} product`. The body of `sum` is a product, so `sum {i in I} a[i] + sum {j in J} b[j]` is two sums.

## What the validator rejects

Duplicate names, empty sets, parameters with missing data and no default, wrong index arity, a lower bound above an upper bound, `alldiff` over a non-integer or huge domain, names used outside their quantifier, and models that would expand past 100,000 variables.

## JSON IR

`Model.to_dict()` is the interchange form: sets, parameters, variables, objectives, constraints, and meta. `Model.from_dict` reads it back. `backend/axiom/modeling/schema.json` is a JSON Schema for that document. Translators and solvers consume the IR, not source text.

## Export

`translate(model, target)` writes Pyomo, PuLP, OR-Tools, CVXPY, AMPL, GAMS, JuMP, CPLEX LP, or free MPS. LP and MPS can also be imported. A custom backend implements `translate(self, model) -> str` and is added with `axiom.modeling.translators.base.register`.
