"""Multi-agent run: parallel formulation, a solver race, verification, and approval gates.

Agents write events as they finish. Human gates block on the approvals table so
the API and the studio can approve or reject without sharing a thread. Tests
pass ``auto_approve`` and the same gates are recorded as system approvals.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import select
from sqlalchemy.orm import Session

from axiom.analysis.figures import academic_figures
from axiom.analysis.service import diagnose, monte_carlo, present, scenarios, sensitivity, statistics
from axiom.db.models import Approval, Event, Project, Run, utcnow
from axiom.db.session import open_session
from axiom.errors import AxiomError
from axiom.llm.client import LLMClient, aml_from_llm
from axiom.modeling import emit_aml, parse_aml, validate
from axiom.modeling.evaluate import constraint_report
from axiom.modeling.flatten import flatten
from axiom.modeling.standard import standard_form
from axiom.modeling.translators.registry import translate
from axiom.nl.formulate import alternative_aml, formulate
from axiom.simulation.des import simulate_queue
from axiom.solvers.registry import get_solver, solve_model

log = logging.getLogger("axiom.agents")

_THREADS: dict[int, threading.Thread] = {}


def launch(run_id: int) -> None:
    thread = threading.Thread(target=execute_run, args=(run_id,), name=f"axiom-run-{run_id}", daemon=True)
    _THREADS[run_id] = thread
    thread.start()


def execute_run(run_id: int) -> None:
    session = open_session()
    try:
        _execute(session, run_id)
    except Exception as exc:  # the run must always reach a terminal status
        log.exception("run %s failed", run_id)
        session.rollback()
        run = session.get(Run, run_id)
        if run is not None and run.status not in {"completed", "rejected"}:
            run.status = "failed"
            run.error = str(exc)
            run.error_en = str(exc)
            run.finished_at = utcnow()
            session.commit()
            _event(
                session,
                run,
                "supervisor",
                "error",
                "运行失败",
                "The run failed",
                str(exc),
                str(exc),
                status="error",
            )
    finally:
        session.close()
        _THREADS.pop(run_id, None)


def _execute(session: Session, run_id: int) -> None:
    run = session.get(Run, run_id)
    if run is None:
        return
    project = session.get(Project, run.project_id)
    run.status = "running"
    session.commit()
    _event(session, run, "supervisor", "start", "开始编排", "Orchestration started", "分析、建模、求解和校验会并行推进。", "Analysis, modeling, solving, and verification proceed in parallel.")

    statement = run.statement or (project.statement if project else "")
    locale = project.locale if project else "zh-CN"
    supplied = (run.dsl or "").strip()

    with ThreadPoolExecutor(max_workers=2) as pool:
        rules = pool.submit(formulate, statement, locale)
        live = pool.submit(_llm_formulation, statement)
        formulation = rules.result()
        llm_aml = live.result()

    if llm_aml:
        try:
            checked = validate(parse_aml(llm_aml))
        except AxiomError:
            checked = None
        if checked is not None and checked.ok:
            formulation.aml = emit_aml(parse_aml(llm_aml))
            formulation.confidence = max(formulation.confidence, 0.9)
            formulation.summary = "外部模型给出的建模语言已通过校验，采用该版本。"
            formulation.summary_en = "The external model's AML passed validation and was adopted."
            _event(session, run, "analyst", "llm", "采用外部模型给出的模型", "Adopted the external model's formulation", formulation.summary, formulation.summary_en)
        else:
            _event(session, run, "analyst", "llm", "外部模型的输出未通过校验", "The external model's output failed validation", "继续使用离线建模结果。", "Continuing with the offline formulation.")

    if supplied:
        try:
            model = parse_aml(supplied)
            checked = validate(model)
        except AxiomError as exc:
            _fail(session, run, exc.message, exc.message_en)
            return
        if not checked.ok:
            first = next(item for item in checked.diagnostics if item.level == "error")
            _fail(session, run, first.message, first.message_en)
            return
        formulation.kind = "optimization"
        formulation.aml = emit_aml(model)
        formulation.title = model.name or formulation.title
        formulation.summary = "使用你在编辑器中确认的模型。"
        formulation.summary_en = "Using the model confirmed in the editor."
        formulation.confidence = 0.99

    _event(
        session,
        run,
        "analyst",
        "formulation",
        formulation.title or "问题分析",
        formulation.title or "Problem analysis",
        formulation.summary,
        formulation.summary_en,
    )

    if formulation.kind == "clarification" or not formulation.aml:
        run.status = "needs_input"
        run.finished_at = utcnow()
        run.result_json = json.dumps({"formulation": formulation.to_dict(), "questions": formulation.questions}, ensure_ascii=False)
        if project is not None:
            project.status = "needs_input"
            project.updated_at = utcnow()
        session.commit()
        _event(
            session,
            run,
            "analyst",
            "question",
            "需要补充问题结构",
            "More structure is needed",
            "\n".join(formulation.questions),
            formulation.summary_en,
            status="waiting",
        )
        return

    if not _gate(session, run, "formulation", "请确认问题理解", "Confirm the reading of the problem", formulation.summary, formulation.summary_en):
        return

    if formulation.kind == "simulation" or formulation.simulation:
        _simulate(session, run, project, formulation)
        return

    primary = formulation.aml
    with ThreadPoolExecutor(max_workers=2) as pool:
        primary_future = pool.submit(_inspect, primary)
        alternative_future = pool.submit(alternative_aml, primary)
        inspected, primary_error = primary_future.result()
        alternative = alternative_future.result()

    if primary_error:
        _fail(session, run, primary_error[0], primary_error[1])
        return

    _event(
        session,
        run,
        "modeler",
        "model",
        "主模型已通过校验",
        "Primary model validated",
        f"{inspected['variables']} 个变量，{inspected['constraints']} 条约束。",
        f"{inspected['variables']} variables, {inspected['constraints']} constraints.",
    )
    if alternative:
        alt_info, alt_error = _inspect(alternative)
        if alt_error:
            alternative = None
            _event(session, run, "modeler-b", "model", "对照模型未通过校验", "The alternative model failed validation", alt_error[0], alt_error[1], status="warning")
        else:
            _event(
                session,
                run,
                "modeler-b",
                "model",
                "对照模型：松弛等式形式",
                "Alternative model: slack equalities",
                f"{alt_info['variables']} 个变量。两个建模器并行完成。",
                f"{alt_info['variables']} variables. Both modelers finished in parallel.",
            )
    else:
        _event(session, run, "modeler-b", "model", "没有生成对照模型", "No alternative model was generated", "非线性或空约束模型只保留主模型。", "Nonlinear or unconstrained models keep a single formulation.")

    params = _parameter_table(primary)
    _event(
        session,
        run,
        "data",
        "data",
        "数据已整理",
        "Data prepared",
        params or "模型把系数直接写在约束里，没有单独的参数表。",
        params or "Coefficients are written directly into the constraints; there is no separate parameter table.",
    )

    try:
        formed = standard_form(parse_aml(primary))
    except AxiomError as exc:
        _fail(session, run, exc.message, exc.message_en, "标准方程未能生成", "Standard equations were not generated")
        return
    _event(
        session,
        run,
        "modeler",
        "equations",
        "标准方程已生成",
        "Standard equations generated",
        formed["plain"][:1500],
        (formed.get("plain_en") or formed["plain"])[:1500],
    )
    if not _gate(session, run, "model", "请确认模型", "Confirm the model", primary[:1200], primary[:1200]):
        return

    if project is not None:
        project.dsl = primary
        project.statement = statement
        project.status = "solving"
        project.updated_at = utcnow()
    run.dsl = primary
    try:
        pending = json.loads(run.result_json or "{}")
    except json.JSONDecodeError:
        pending = {}
    algorithm_id = str(pending.get("algorithm") or "auto") if isinstance(pending, dict) else "auto"
    run.result_json = json.dumps(
        {"dsl": primary, "standard_form": formed, "algorithm": algorithm_id},
        ensure_ascii=False,
    )
    session.commit()
    if not _gate(
        session,
        run,
        "equations",
        "请确认标准方程",
        "Confirm the standard equations",
        formed["plain"][:1500],
        (formed.get("plain_en") or formed["plain"])[:1500],
    ):
        return

    model = parse_aml(primary)
    from axiom.analysis.algorithms import resolve

    choice = resolve(model, algorithm_id, run.solver)
    preferred = run.solver if choice["id"] == "auto" else choice["solver"]
    names = _solver_names(model, preferred)
    if choice["method"] == "local-search":
        names = ["local"] + [name for name in names if name != "local"]
    else:
        names = [name for name in names if name != "local"]
    race_zh = "、".join(names)
    race_en = ", ".join(names)
    if choice["id"] != "auto":
        race_zh = f"{choice['label_zh']} · {race_zh}"
        race_en = f"{choice['label_en']} · {race_en}"
    _event(
        session,
        run,
        "solver",
        "race",
        "求解器并行竞赛",
        "Solver race",
        race_zh,
        race_en,
        status="running",
    )
    race: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(2, len(names) + 1)) as pool:
        futures = {
            pool.submit(_solve_safe, primary, name, choice["options"] if name == choice.get("options_for") else None): name
            for name in names
        }
        alt_future = pool.submit(_solve_safe, alternative, "highs") if alternative else None
        for future in as_completed(futures):
            race.append(future.result())
        alternative_result = alt_future.result() if alt_future else None

    winner = _pick(race, model)
    for row in race:
        _event(
            session,
            run,
            "solver",
            "solver",
            f"{row['solver']} · {row['status']}",
            f"{row['solver']} · {row['status']}",
            _solver_line(row),
            _solver_line(row),
            status="done" if row["status"] in {"optimal", "feasible"} else "warning",
        )

    if winner is None:
        message = race[0]["message"] if race else "没有求解器返回结果。"
        message_en = race[0]["message_en"] if race else "No solver returned a result."
        diagnosis = {}
        if any(row["status"] == "infeasible" for row in race):
            try:
                diagnosis = diagnose(model)
            except AxiomError as exc:
                diagnosis = {"message": exc.message, "message_en": exc.message_en}
            _event(session, run, "verifier", "diagnosis", "不可行诊断", "Infeasibility diagnosis", diagnosis.get("message", ""), diagnosis.get("message_en", ""))
        run.status = "completed" if diagnosis else "failed"
        run.error = "" if diagnosis else message
        run.error_en = "" if diagnosis else message_en
        run.finished_at = utcnow()
        run.result_json = json.dumps(
            {
                "formulation": formulation.to_dict(),
                "dsl": primary,
                "alternative_dsl": alternative,
                "race": race,
                "diagnosis": diagnosis,
                "translations": _translations(model),
                "standard_form": formed,
            },
            ensure_ascii=False,
        )
        if project is not None:
            project.status = "infeasible" if diagnosis else "failed"
            project.updated_at = utcnow()
        session.commit()
        _lifecycle_attach(run.id)
        if not diagnosis:
            _event(session, run, "solver", "error", "求解失败", "Solve failed", message, message_en, status="error")
        return

    solution = winner
    verification = _verify(model, solution, alternative_result)
    _event(
        session,
        run,
        "verifier",
        "verify",
        "校验通过" if verification["ok"] else "校验发现差异",
        "Verification passed" if verification["ok"] else "Verification found a difference",
        verification["message"],
        verification["message_en"],
        status="done" if verification["ok"] else "warning",
    )

    views = present(model, solution["variables"], solution["objective"])
    report_rows = solution.get("constraints") or []
    stats = statistics(solution["variables"], report_rows)
    analysis: dict = {}
    try:
        if len(solution["variables"]) <= 80:
            analysis["sensitivity"] = sensitivity(model, solver=solution["solver"], widths=(-0.1, 0.1))
            _event(session, run, "analyst", "sensitivity", "灵敏度已计算", "Sensitivity computed", f"{len(analysis['sensitivity'].get('rows', []))} 个因素。", f"{len(analysis['sensitivity'].get('rows', []))} factors.")
            analysis["scenarios"] = scenarios(
                model,
                [
                    {"name": "基准"},
                    {"name": "右端 +10%", "rhs_scale": _rhs_scale(model, 1.1)},
                    {"name": "右端 -10%", "rhs_scale": _rhs_scale(model, 0.9)},
                ],
                solver=solution["solver"],
            )
            _event(session, run, "analyst", "scenario", "情景对比完成", "Scenarios compared", "基准、右端 +10%、右端 -10%。", "Base, RHS +10%, RHS -10%.")
            analysis["monte_carlo"] = monte_carlo(model, samples=8, cv=0.08, seed=7, solver=solution["solver"])
            mc = analysis["monte_carlo"]
            _event(
                session,
                run,
                "simulation",
                "monte-carlo",
                "蒙特卡洛完成",
                "Monte Carlo finished",
                f"{mc.get('samples', 0)} 个样本，均值 {mc.get('mean')}",
                f"{mc.get('samples', 0)} samples, mean {mc.get('mean')}",
            )
    except Exception as exc:
        log.warning("analysis failed: %s", exc)
        _event(session, run, "analyst", "warning", "分析未全部完成", "Analysis was incomplete", str(exc), str(exc), status="warning")

    try:
        from axiom.agents.studies import propose
        from axiom.analysis.studio import run_study

        proposal = propose(statement, primary)
        auto = proposal.get("auto") or {}
        if auto.get("kind") in {"local", "doe", "sweep", "schedule", "morris"}:
            study = run_study(auto["kind"], primary, auto.get("options") or {})
            analysis["study"] = {"kind": auto["kind"], "summary": study.get("summary_metrics"), "message": study.get("message") or study.get("note")}
            _event(
                session,
                run,
                "analyst",
                "study",
                "已按语句安排分析",
                "Ran the analysis named in the statement",
                auto.get("reason_zh") or auto["kind"],
                auto.get("reason_en") or auto["kind"],
            )
    except Exception as exc:
        log.warning("requested study failed: %s", exc)

    payload = {
        "formulation": formulation.to_dict(),
        "dsl": primary,
        "alternative_dsl": alternative,
        "solver": solution["solver"],
        "objective": solution["objective"],
        "status": solution["status"],
        "variables": solution["variables"],
        "constraints": report_rows,
        "duals": solution.get("duals") or {},
        "reduced_costs": solution.get("reduced_costs") or {},
        "race": race,
        "alternative_result": _brief(alternative_result),
        "verification": verification,
        "views": views,
        "statistics": stats,
        "sensitivity": analysis.get("sensitivity"),
        "scenarios": analysis.get("scenarios"),
        "monte_carlo": analysis.get("monte_carlo"),
        "study": analysis.get("study"),
        "figures": _figures(model, solution),
        "translations": _translations(model),
        "standard_form": formed,
        "algorithm": choice["method"] if choice["id"] == "auto" else choice["id"],
        "algorithm_label_zh": choice["label_zh"],
        "algorithm_label_en": choice["label_en"],
        "summary": formulation.summary,
        "summary_en": formulation.summary_en,
        "title": formulation.title,
        "statement": statement,
    }
    session.expire_all()
    fresh = session.get(Run, run.id)
    if fresh is not None and fresh.status == "cancelled":
        return
    run.status = "completed"
    run.solver = solution["solver"]
    run.objective = "" if solution["objective"] is None else f"{solution['objective']:.8g}"
    run.dsl = primary
    run.result_json = json.dumps(payload, ensure_ascii=False)
    run.finished_at = utcnow()
    if project is not None:
        project.status = "solved"
        project.dsl = primary
        project.updated_at = utcnow()
    session.commit()
    _lifecycle_attach(run.id)
    _event(
        session,
        run,
        "report",
        "done",
        "报告已生成",
        "Report ready",
        f"目标值 {run.objective}，求解器 {run.solver}。",
        f"Objective {run.objective}, solver {run.solver}.",
    )


def _simulate(session: Session, run: Run, project: Project | None, formulation) -> None:
    config = dict(formulation.simulation or {})
    _event(session, run, "data", "data", "仿真参数", "Simulation parameters", json.dumps(config, ensure_ascii=False), json.dumps(config))
    if not _gate(session, run, "model", "请确认仿真配置", "Confirm the simulation", formulation.summary, formulation.summary_en):
        return
    result = simulate_queue(
        arrival_rate=float(config.get("arrival_rate", 8)),
        service_rate=float(config.get("service_rate", 10)),
        servers=int(config.get("servers", 1)),
        horizon=float(config.get("horizon", 8)),
        seed=int(config.get("seed", 7)),
    )
    _event(
        session,
        run,
        "simulation",
        "des",
        "离散事件仿真完成",
        "Discrete-event simulation finished",
        f"服务 {result['served']} 人，平均等待 {result['avg_wait']:.4g}，利用率 {result['utilization']:.2%}。",
        f"Served {result['served']}, average wait {result['avg_wait']:.4g}, utilization {result['utilization']:.2%}.",
    )
    payload = {
        "formulation": formulation.to_dict(),
        "dsl": formulation.aml,
        "simulation": result,
        "kind": "simulation",
        "title": formulation.title,
        "summary": formulation.summary,
        "summary_en": formulation.summary_en,
        "statement": run.statement,
        "status": "completed",
        "solver": "simpy",
        "objective": result.get("avg_wait"),
        "variables": {},
        "constraints": [],
    }
    run.status = "completed"
    run.solver = "simpy"
    run.objective = f"{result['avg_wait']:.6g}"
    run.dsl = formulation.aml or ""
    run.result_json = json.dumps(payload, ensure_ascii=False)
    run.finished_at = utcnow()
    if project is not None:
        project.status = "simulated"
        project.dsl = formulation.aml or project.dsl
        project.updated_at = utcnow()
    session.commit()
    _lifecycle_attach(run.id)
    _event(session, run, "report", "done", "仿真报告已生成", "Simulation report ready", formulation.summary, formulation.summary_en)


def _llm_formulation(statement: str) -> str | None:
    return aml_from_llm(LLMClient(role="modeler"), statement)


def _inspect(aml: str) -> tuple[dict, tuple[str, str] | None]:
    try:
        model = parse_aml(aml)
        checked = validate(model)
    except AxiomError as exc:
        return {}, (exc.message, exc.message_en)
    errors = [item for item in checked.diagnostics if item.level == "error"]
    if errors:
        return {}, (errors[0].message, errors[0].message_en)
    return {"variables": len(model.variables), "constraints": len(model.constraints), "name": model.name}, None


def _parameter_table(aml: str) -> str:
    model = parse_aml(aml)
    lines = []
    for param in model.parameters.values():
        for key, value in list(param.values.items())[:12]:
            label = param.name if not key else f"{param.name}[{','.join(key)}]"
            lines.append(f"{label} = {value}")
    return "\n".join(lines)


def _solver_names(model, preferred: str) -> list[str]:
    from axiom.solvers.capabilities import race_names

    ready = race_names(model, preferred)
    return ready or ["highs"]


def _solve_safe(aml: str | None, solver: str, options: dict | None = None) -> dict:
    if not aml:
        return {"solver": solver, "status": "skipped", "objective": None, "message": "", "message_en": "", "runtime_sec": 0, "variables": {}, "constraints": []}
    started = time.perf_counter()
    try:
        result = solve_model(parse_aml(aml), solver, options)
    except AxiomError as exc:
        return {
            "solver": solver,
            "status": "error",
            "objective": None,
            "message": exc.message,
            "message_en": exc.message_en,
            "runtime_sec": time.perf_counter() - started,
            "variables": {},
            "constraints": [],
        }
    except Exception as exc:
        return {
            "solver": solver,
            "status": "error",
            "objective": None,
            "message": str(exc),
            "message_en": str(exc),
            "runtime_sec": time.perf_counter() - started,
            "variables": {},
            "constraints": [],
        }
    payload = result.to_dict()
    payload["runtime_sec"] = result.runtime_sec
    return payload


def _pick(race: list[dict], model) -> dict | None:
    feasible = [row for row in race if row.get("status") in {"optimal", "feasible"} and row.get("objective") is not None]
    if not feasible:
        return None
    flat = flatten(model)
    clean = []
    for row in feasible:
        rows = constraint_report(model, flat, row.get("variables") or {})
        if not any(item.get("violated") for item in rows):
            clean.append(row)
    pool = clean or feasible
    sense = model.objectives[0].sense if model.objectives else "minimize"

    def directed(row: dict) -> float:
        objective = float(row["objective"])
        return objective if sense == "minimize" else -objective

    best = min(directed(row) for row in pool)
    scale = max(1.0, abs(best))
    # A few open solvers disagree in the 6th digit. That noise must not outrank HiGHS.
    close = [row for row in pool if abs(directed(row) - best) <= 1e-4 * scale]
    priority = {
        "highs": 0,
        "pyscipopt": 1,
        "scip": 2,
        "cbc": 3,
        "python-mip": 4,
        "scipy-highs": 5,
        "glop": 6,
        "clp": 7,
        "clarabel": 8,
        "osqp": 9,
        "scs": 10,
        "ecos": 11,
        "cvxopt": 12,
        "glpk": 30,
    }
    close.sort(key=lambda row: (priority.get(str(row.get("solver")), 20), float(row.get("runtime_sec") or 0)))
    return close[0]


def _verify(model, solution: dict, alternative: dict | None) -> dict:
    flat = flatten(model)
    rows = constraint_report(model, flat, solution.get("variables") or {})
    solution["constraints"] = rows
    violated = [row for row in rows if row.get("violated")]
    recomputed = solution.get("objective")
    delta = None
    alt_ok = True
    if alternative and alternative.get("objective") is not None and solution.get("objective") is not None:
        delta = abs(float(alternative["objective"]) - float(solution["objective"]))
        alt_ok = delta <= 1e-2 * max(1.0, abs(float(solution["objective"])))
    ok = not violated and alt_ok and solution.get("status") in {"optimal", "feasible"}
    if ok:
        message = "约束残差在容差内，对照模型的目标值一致。" if alternative and alternative.get("objective") is not None else "约束残差在容差内。"
        message_en = "Constraint residuals are within tolerance and the alternative objective agrees." if alternative and alternative.get("objective") is not None else "Constraint residuals are within tolerance."
    elif violated:
        message = f"{len(violated)} 条约束仍被违反。"
        message_en = f"{len(violated)} constraints are still violated."
    else:
        message = f"对照模型目标相差 {delta}。"
        message_en = f"The alternative objective differs by {delta}."
    return {"ok": ok, "recomputed": recomputed, "delta": delta, "violated": len(violated), "message": message, "message_en": message_en}


def _rhs_scale(model, factor: float) -> dict:
    scales = {}
    for con in model.constraints:
        if con.rhs is not None and con.rhs.op == "const":
            scales[con.name] = factor
    return scales


def _translations(model) -> dict:
    exported = {}
    for target in ("pyomo", "pulp", "lp", "mps"):
        try:
            exported[target] = translate(model, target).to_dict()
        except AxiomError as exc:
            exported[target] = {"target": target, "error": exc.message, "error_en": exc.message_en}
    return exported


def _figures(model, solution: dict) -> dict:
    try:
        return academic_figures(model, solution.get("variables") or {}, solution.get("solver") or "highs")
    except Exception:
        return {}


def _brief(result: dict | None) -> dict | None:
    if not result:
        return None
    return {"solver": result.get("solver"), "status": result.get("status"), "objective": result.get("objective"), "runtime_sec": result.get("runtime_sec")}


def _solver_line(row: dict) -> str:
    objective = row.get("objective")
    runtime = row.get("runtime_sec") or 0
    if objective is None:
        return row.get("message") or row.get("status") or ""
    return f"目标 {objective:.8g}，用时 {runtime:.3f}s"


def _gate(session: Session, run: Run, gate: str, title: str, title_en: str, detail: str, detail_en: str) -> bool:
    if run.auto_approve:
        session.add(Approval(run_id=run.id, gate=gate, status="approved", note="auto", resolved_at=utcnow()))
        session.commit()
        _event(session, run, "human", "approval", f"已自动批准：{title}", f"Auto-approved: {title_en}", "测试或自动模式跳过等待。", "Automatic mode did not wait.", status="done")
        return True
    approval = Approval(run_id=run.id, gate=gate, status="pending")
    session.add(approval)
    run.status = "awaiting_approval"
    session.commit()
    _event(session, run, "human", "approval", title, title_en, detail, detail_en, status="waiting")
    deadline = time.time() + 30 * 60
    while time.time() < deadline:
        time.sleep(0.3)
        session.expire_all()
        current = session.get(Approval, approval.id)
        if current is None:
            return False
        fresh = session.get(Run, run.id)
        if fresh is not None and fresh.status == "cancelled":
            return False
        if current.status == "approved":
            run.status = "running"
            session.commit()
            _event(session, run, "human", "approval", "已批准", "Approved", current.note or title, current.note or title_en, status="done")
            return True
        if current.status == "rejected":
            run.status = "rejected"
            run.finished_at = utcnow()
            run.error = current.note or "已拒绝"
            run.error_en = current.note or "Rejected"
            session.commit()
            _event(session, run, "human", "approval", "已拒绝", "Rejected", current.note or "", current.note or "", status="error")
            return False
    run.status = "failed"
    run.error = "等待批准超时。"
    run.error_en = "Timed out waiting for approval."
    run.finished_at = utcnow()
    session.commit()
    return False


def _fail(
    session: Session,
    run: Run,
    message: str,
    message_en: str,
    title: str = "模型未能通过校验",
    title_en: str = "The model failed validation",
) -> None:
    run.status = "failed"
    run.error = message
    run.error_en = message_en
    run.finished_at = utcnow()
    session.commit()
    _event(session, run, "modeler", "error", title, title_en, message, message_en, status="error")


def _lifecycle_attach(run_id: int) -> None:
    try:
        from axiom.lifecycle.service import attach_completed_run

        attach_completed_run(run_id)
    except Exception as exc:
        log.warning("lifecycle attach failed: %s", exc)


def _event(session: Session, run: Run, agent: str, kind: str, title: str, title_en: str, detail: str = "", detail_en: str = "", status: str = "done") -> None:
    last = session.scalar(select(Event.seq).where(Event.run_id == run.id).order_by(Event.seq.desc()))
    session.add(
        Event(
            run_id=run.id,
            seq=(last or 0) + 1,
            agent=agent,
            kind=kind,
            title=title[:240],
            title_en=title_en[:240],
            detail=detail or "",
            detail_en=detail_en or "",
            status=status,
        )
    )
    session.commit()
