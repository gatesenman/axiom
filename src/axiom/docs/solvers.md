# Solvers

Every adapter implements the same solve call and publishes capability metadata: problem classes (`lp`, `milp`, `qp`, `miqp`, `socp`, `sdp`, `nlp`, `minlp`, `cp`), and whether it can return duals, take a warm start, expose callbacks, compute an irreducible infeasible set, and run multithreaded. The license type is `open-source` or `commercial`. Distribution is `bundled` when the Windows package ships it, and `detected` when Axiom only uses a library or executable the user installed.

Settings → 求解器 (`data-solver-manager`) lists the detection status, version, license state (`open`, `licensed`, `unlicensed`, `not_installed`), and a documentation link. A solver that is not installed stays out of the race. The cross-solver table (`data-solver-compare`) times the same small LP, MILP, QP, SOCP, NLP, MINLP, CP, and SDP set on every available adapter.

Automatic selection and the parallel race consider every available solver whose classes accept the flattened model. HiGHS stays the preferred winner when objectives agree within 1e-4 relative tolerance.

## Bundled open-source solvers

| Name | Classes | How it runs |
| --- | --- | --- |
| HiGHS | LP, MILP, convex QP | `highspy` in process. HiGHS 1.15 does not solve mixed-integer QP |
| CBC | LP, MILP | PuLP `PULP_CBC_CMD` |
| CLP | LP | OR-Tools, separate process |
| GLPK | LP, MILP | `glpsol` through PuLP |
| SCIP | LP, MILP | OR-Tools, separate process |
| PySCIPOpt | LP, MILP, QP, MIQP | `pyscipopt` in process |
| GLOP | LP | OR-Tools, separate process |
| PDLP | LP | OR-Tools, separate process |
| CP-SAT | CP, integer MILP | OR-Tools, separate process, integral data only |
| Clarabel | LP, QP, SOCP, SDP | CVXPY |
| ECOS | LP, SOCP | CVXPY. No quadratic objective |
| SCS | LP, QP, SOCP, SDP | CVXPY |
| OSQP | LP, QP | CVXPY |
| CVXOPT | LP, QP, SOCP, SDP | `cvxopt` |
| python-mip | LP, MILP | bundled CBC |
| SciPy SLSQP | NLP | finite-difference derivatives |
| SciPy HiGHS | LP, MILP | `linprog` / `milp` |
| trust-constr | NLP | SciPy trust-region |
| IPOPT ASL | NLP, LP | `ipopt.exe` plus its DLLs on Windows, from the COIN-OR MSVC build |

OR-Tools solvers stay in a child process. HiGHS and OR-Tools both ship a HiGHS library and cannot be loaded together.

## Detected, not bundled

| Name | Why it is not in the Windows package |
| --- | --- |
| IPOPT via cyipopt | PyPI has no Windows wheel. Linux uses `cyipopt` when Ipopt is installed. Windows uses the ASL executable above. |
| Bonmin, Couenne | Current COIN-OR releases do not publish a Windows executable, and the AMPL solver portal requires an account. If `bonmin` or `couenne` is on `PATH` or in `AXIOM_SOLVER_DIR`, the adapter writes an NL file and reads the `.sol`. |
| Gurobi, CPLEX, FICO Xpress, MOSEK, COPT, Knitro, BARON, Hexaly | Commercial. The package does not include libraries or licenses. When the Python module or executable imports and a license is present, the row shows the version and `licensed`. Otherwise the row is `not_installed`, with the vendor's documentation link. |

Linopy is an import/export target only. Its runtime depends on a large dataframe stack, so that stack is not vendored.

## Modeling languages and file formats

Import and export, both directions unless noted:

| Target | Notes |
| --- | --- |
| Pyomo, PuLP, CVXPY, python-mip, JuMP, AMPL, GAMS, GMPL, ZIMPL | Scalar models round-trip through AML |
| OPL, gurobipy, docplex | Export, and the same scalar subset imports |
| CasADi | NLP export (`nlpsol` / IPOPT) and import of that scalar form |
| linopy | Source import and export. The library itself is not bundled |
| LP, fixed MPS, free MPS, QPS | Read and write |
| NL | AMPL ASCII NL for linear, quadratic, and smooth nonlinear models |
| OSiL, CBF, SDPA | Read and write. SDPA export needs a model that was imported from SDPA |
| FlatZinc, MiniZinc | Read and write. Continuous domains are written with float bounds so MiniZinc does not treat them as integers |

A second file input accepts `.qps`, `.nl`, `.osil`, `.cbf`, `.sdpa`, `.fzn`, `.mzn`, `.py`, `.mod`, `.gms`, `.zpl`, `.jl`. The original LP/MPS input is unchanged.

Round-trip tests use the product-mix LP, a convex QP, Netlib `afiro.mps` (optimum −464.753142857), and MIPLIB `flugpl.mps` (optimum 1,201,500).
