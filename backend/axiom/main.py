"""HTTP API for the studio, the desktop shell, and tests."""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from axiom import __version__
from axiom.agents.orchestrator import launch
from axiom.config import configure_logging
from axiom.analysis.algorithms import public_catalog, resolve_request
from axiom.analysis.figures import academic_figures
from axiom.analysis.service import compare_solutions, diagnose, recommend, what_if, what_if_knobs
from axiom.limit import check_rate
from axiom.db.models import Approval, AuditLog, Event, Membership, ModelVersion, Project, Run, SessionToken, Setting, User, Workspace, utcnow
from axiom.db.seed import seed
from axiom.db.session import init_db, open_session
from axiom.errors import AxiomError
from axiom.llm.client import LLMClient, LLMSettings
from axiom.nl.formulate import formulate
from axiom.modeling import emit_aml, parse_aml, standard_form, validate
from axiom.agents.studies import propose
from axiom.analysis.benchmark import run_benchmark
from axiom.analysis.jobs import cancel_job, get_job, start_job
from axiom.analysis.studio import run_study
from axiom.analysis.compatibility import compatibility_matrix
from axiom.modeling.exchange import read_model
from axiom.modeling.tables import apply_outline, apply_table, outline, preview_table
from axiom.modeling.translators.registry import list_translators, translate
from axiom.security import decrypt_secret, encrypt_secret, hash_password, mask_secret, new_token, verify_password
from axiom.solvers.registry import list_solvers, solve_model
from axiom.templates.library import get_template, list_templates

_SOLVER_CACHE: dict = {"at": 0.0, "rows": []}


def cached_solvers() -> list[dict]:
    if time.time() - _SOLVER_CACHE["at"] > 60 or not _SOLVER_CACHE["rows"]:
        _SOLVER_CACHE["rows"] = list_solvers()
        _SOLVER_CACHE["at"] = time.time()
    return _SOLVER_CACHE["rows"]


def _example_later() -> None:
    if os.environ.get("AXIOM_SKIP_EXAMPLE") == "1":
        return
    session = open_session()
    try:
        project = session.scalar(select(Project).where(Project.title == "产品组合示例"))
        if project is None:
            return
        existing = session.scalar(select(Run.id).where(Run.project_id == project.id))
        if existing:
            return
        run = Run(
            project_id=project.id,
            status="queued",
            solver="highs",
            statement=project.statement,
            auto_approve=1,
            created_by=project.created_by,
        )
        session.add(run)
        session.commit()
        run_id = run.id
    finally:
        session.close()
    from axiom.agents.orchestrator import execute_run

    execute_run(run_id)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    init_db()
    session = open_session()
    try:
        seed(session)
    finally:
        session.close()
    import threading

    threading.Thread(target=_example_later, name="axiom-example", daemon=True).start()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Axiom", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AxiomError)
    async def _axiom_error(_request, exc: AxiomError):
        return JSONResponse(status_code=exc.status, content=exc.to_dict())

    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "name": "Axiom",
            "version": __version__,
            "python": sys.executable,
            "bundled": os.environ.get("AXIOM_BUNDLED") == "1",
        }

    @app.post("/api/auth/login")
    def login(body: LoginBody):
        session = open_session()
        try:
            user = session.scalar(select(User).where(User.username == body.username.strip()))
            if user is None or not verify_password(body.password, user.password_hash):
                raise AxiomError("用户名或密码不正确。", "Incorrect username or password.", code="auth", status=401)
            token = new_token()
            session.add(SessionToken(token=token, user_id=user.id))
            _audit(session, user, "login", "user", str(user.id), user.username)
            session.commit()
            return {"token": token, "user": user.public()}
        finally:
            session.close()

    @app.post("/api/auth/logout")
    def logout(user: Annotated[User, Depends(current_user)], authorization: Annotated[str | None, Header()] = None):
        session = open_session()
        try:
            token = _bearer(authorization)
            row = session.get(SessionToken, token)
            if row is not None:
                session.delete(row)
            _audit(session, user, "logout", "user", str(user.id), "")
            session.commit()
        finally:
            session.close()
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(user: Annotated[User, Depends(current_user)]):
        return user.public()

    @app.patch("/api/auth/me")
    def update_me(body: ProfileBody, user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            stored = session.get(User, user.id)
            if stored is None:
                raise AxiomError("用户不存在。", "User not found.", status=404)
            if body.display_name is not None:
                stored.display_name = body.display_name.strip() or stored.display_name
            if body.locale in {"zh-CN", "en"}:
                stored.locale = body.locale
            if body.theme in {"light", "dark", "system"}:
                stored.theme = body.theme
            if body.password:
                stored.password_hash = hash_password(body.password)
            session.commit()
            return stored.public()
        finally:
            session.close()

    @app.get("/api/dashboard")
    def dashboard(user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            workspace_ids = _workspace_ids(session, user)
            projects = list(session.scalars(select(Project).where(Project.workspace_id.in_(workspace_ids)).order_by(Project.updated_at.desc())))
            project_ids = [item.id for item in projects]
            runs = []
            if project_ids:
                runs = list(session.scalars(select(Run).where(Run.project_id.in_(project_ids)).order_by(Run.created_at.desc()).limit(8)))
            completed = 0
            if project_ids:
                completed = session.scalar(select(func.count()).select_from(Run).where(Run.project_id.in_(project_ids), Run.status == "completed")) or 0
            solvers = cached_solvers()
            return {
                "projects": len(projects),
                "runs": session.scalar(select(func.count()).select_from(Run).where(Run.project_id.in_(project_ids))) if project_ids else 0,
                "completed": completed,
                "solvers_available": sum(1 for item in solvers if item["available"]),
                "solvers": solvers,
                "recent_projects": [item.public() for item in projects[:6]],
                "recent_runs": [_run_public(session, item) for item in runs],
            }
        finally:
            session.close()

    @app.get("/api/workspaces")
    def workspaces(user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            return [_workspace_public(session, item) for item in _workspaces(session, user)]
        finally:
            session.close()

    @app.post("/api/workspaces")
    def create_workspace(body: WorkspaceBody, user: Annotated[User, Depends(current_user)]):
        name = body.name.strip()
        if not name:
            raise AxiomError("工作区需要一个名称。", "A workspace needs a name.")
        session = open_session()
        try:
            workspace = Workspace(name=name, owner_id=user.id)
            session.add(workspace)
            session.flush()
            session.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
            _audit(session, user, "workspace.create", "workspace", str(workspace.id), name)
            session.commit()
            return _workspace_public(session, workspace)
        finally:
            session.close()

    @app.post("/api/workspaces/{workspace_id}/members")
    def add_member(workspace_id: int, body: MemberBody, user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            _require_workspace(session, user, workspace_id, owner=True)
            member = session.scalar(select(User).where(User.username == body.username.strip()))
            if member is None:
                raise AxiomError("没有这个用户。", "No user with that username.", status=404)
            exists = session.scalar(select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == member.id))
            if exists is None:
                session.add(Membership(workspace_id=workspace_id, user_id=member.id, role=body.role if body.role in {"member", "owner"} else "member"))
            _audit(session, user, "workspace.member", "workspace", str(workspace_id), member.username)
            session.commit()
            workspace = session.get(Workspace, workspace_id)
            return _workspace_public(session, workspace)
        finally:
            session.close()

    @app.get("/api/users")
    def users(user: Annotated[User, Depends(current_user)]):
        _require_admin(user)
        session = open_session()
        try:
            return [item.public() for item in session.scalars(select(User).order_by(User.username))]
        finally:
            session.close()

    @app.post("/api/users")
    def create_user(body: UserBody, user: Annotated[User, Depends(current_user)]):
        _require_admin(user)
        username = body.username.strip()
        if len(username) < 2 or len(body.password) < 6:
            raise AxiomError("用户名至少 2 位，密码至少 6 位。", "Usernames need 2 characters and passwords need 6.")
        session = open_session()
        try:
            if session.scalar(select(User).where(User.username == username)):
                raise AxiomError("用户名已存在。", "That username already exists.", status=409)
            created = User(
                username=username,
                display_name=body.display_name.strip() or username,
                password_hash=hash_password(body.password),
                role="admin" if body.role == "admin" else "member",
            )
            session.add(created)
            session.flush()
            workspace_ids = _workspace_ids(session, user)
            if workspace_ids:
                session.add(Membership(workspace_id=workspace_ids[0], user_id=created.id, role="member"))
            _audit(session, user, "user.create", "user", str(created.id), username)
            session.commit()
            return created.public()
        finally:
            session.close()

    @app.get("/api/projects")
    def projects(user: Annotated[User, Depends(current_user)], workspace_id: int | None = None):
        session = open_session()
        try:
            ids = _workspace_ids(session, user)
            if workspace_id is not None:
                if workspace_id not in ids and user.role != "admin":
                    raise AxiomError("你不在这个工作区。", "You are not in this workspace.", status=403)
                ids = [workspace_id]
            rows = session.scalars(select(Project).where(Project.workspace_id.in_(ids)).order_by(Project.updated_at.desc()))
            return [item.public() for item in rows]
        finally:
            session.close()

    @app.post("/api/projects")
    def create_project(body: ProjectBody, user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            ids = _workspace_ids(session, user)
            workspace_id = body.workspace_id or (ids[0] if ids else None)
            if workspace_id is None:
                raise AxiomError("先创建一个工作区。", "Create a workspace first.")
            _require_workspace(session, user, workspace_id)
            project = Project(
                workspace_id=workspace_id,
                title=body.title.strip() or "未命名问题",
                statement=body.statement,
                dsl=body.dsl,
                locale=body.locale if body.locale in {"zh-CN", "en"} else "zh-CN",
                created_by=user.id,
            )
            session.add(project)
            session.flush()
            from axiom.lifecycle.service import ensure_problem

            ensure_problem(session, project, user)
            _audit(session, user, "project.create", "project", str(project.id), project.title)
            session.commit()
            return project.public()
        finally:
            session.close()

    @app.get("/api/projects/{project_id}")
    def get_project(project_id: int, user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            return _require_project(session, user, project_id).public()
        finally:
            session.close()

    @app.patch("/api/projects/{project_id}")
    def patch_project(project_id: int, body: ProjectPatch, user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            project = _require_project(session, user, project_id)
            if body.title is not None:
                project.title = body.title.strip() or project.title
            if body.statement is not None:
                project.statement = body.statement
            if body.dsl is not None:
                project.dsl = body.dsl
            if body.locale in {"zh-CN", "en"}:
                project.locale = body.locale
            project.updated_at = utcnow()
            _audit(session, user, "project.update", "project", str(project.id), project.title)
            session.commit()
            return project.public()
        finally:
            session.close()

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: int, user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            project = _require_project(session, user, project_id)
            run_ids = list(session.scalars(select(Run.id).where(Run.project_id == project.id)))
            if run_ids:
                session.query(Event).filter(Event.run_id.in_(run_ids)).delete(synchronize_session=False)
                session.query(Approval).filter(Approval.run_id.in_(run_ids)).delete(synchronize_session=False)
                session.query(Run).filter(Run.id.in_(run_ids)).delete(synchronize_session=False)
            _audit(session, user, "project.delete", "project", str(project.id), project.title)
            session.delete(project)
            session.commit()
            return {"ok": True}
        finally:
            session.close()

    @app.get("/api/projects/{project_id}/runs")
    def project_runs(project_id: int, user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            _require_project(session, user, project_id)
            rows = session.scalars(select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc()))
            return [_run_public(session, item) for item in rows]
        finally:
            session.close()

    @app.post("/api/projects/{project_id}/runs")
    def start_run(project_id: int, body: RunBody, user: Annotated[User, Depends(current_user)]):
        check_rate(f"run:{user.id}", limit=48, window=60)
        session = open_session()
        try:
            project = _require_project(session, user, project_id)
            statement = body.statement if body.statement else project.statement
            dsl = body.dsl if body.dsl else ""
            if body.locale in {"zh-CN", "en"}:
                project.locale = body.locale
            if statement:
                project.statement = statement
            project.status = "running"
            project.updated_at = utcnow()
            algorithm = (body.algorithm or "auto").strip() or "auto"
            solver_name = resolve_request(algorithm, body.solver or "highs")
            run = Run(
                project_id=project.id,
                status="queued",
                solver=solver_name,
                statement=statement,
                dsl=dsl,
                auto_approve=1 if body.auto_approve else 0,
                created_by=user.id,
                result_json=json.dumps({"algorithm": algorithm}, ensure_ascii=False),
            )
            session.add(run)
            session.flush()
            if dsl.strip():
                session.add(ModelVersion(project_id=project.id, label="求解前", dsl=dsl, statement=statement or "", note=f"run {run.id}"))
            _audit(session, user, "run.start", "run", str(run.id), project.title)
            session.commit()
            payload = _run_public(session, run)
        finally:
            session.close()
        launch(payload["id"])
        return payload

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: int, user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            run = _require_run(session, user, run_id)
            return _run_public(session, run)
        finally:
            session.close()

    @app.get("/api/runs/{run_id}/events")
    def run_events(run_id: int, user: Annotated[User, Depends(current_user)], after: int = 0):
        session = open_session()
        try:
            _require_run(session, user, run_id)
            rows = session.scalars(select(Event).where(Event.run_id == run_id, Event.id > after).order_by(Event.id))
            return [item.public() for item in rows]
        finally:
            session.close()

    @app.get("/api/runs/{run_id}/stream")
    def stream_run(run_id: int, user: Annotated[User, Depends(current_user)], after: int = 0):
        session = open_session()
        try:
            _require_run(session, user, run_id)
        finally:
            session.close()

        def generate():
            last = after
            idle = 0
            while idle < 400:
                watch = open_session()
                try:
                    rows = list(watch.scalars(select(Event).where(Event.run_id == run_id, Event.id > last).order_by(Event.id)))
                    run = watch.get(Run, run_id)
                    status = run.status if run else "missing"
                finally:
                    watch.close()
                if rows:
                    idle = 0
                    for item in rows:
                        last = item.id
                        yield f"data: {json.dumps(item.public(), ensure_ascii=False)}\n\n"
                else:
                    idle += 1
                    yield f"event: ping\ndata: {json.dumps({'status': status})}\n\n"
                    if status in {"completed", "failed", "rejected", "needs_input", "cancelled"}:
                        yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
                        break
                time.sleep(0.4)

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: int, user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            run = _require_run(session, user, run_id)
            if run.status not in {"queued", "running", "awaiting_approval"}:
                raise AxiomError("这次运行已经结束。", "This run has already finished.", status=409)
            run.status = "cancelled"
            run.error = "已停止"
            run.error_en = "Stopped"
            run.finished_at = utcnow()
            pending = session.scalar(select(Approval).where(Approval.run_id == run.id, Approval.status == "pending"))
            if pending is not None:
                pending.status = "rejected"
                pending.note = "stopped"
                pending.resolved_at = utcnow()
            _audit(session, user, "run.cancel", "run", str(run.id), run.error)
            session.commit()
            return _run_public(session, run)
        finally:
            session.close()

    @app.post("/api/runs/{run_id}/decision")
    def decide(run_id: int, body: DecisionBody, user: Annotated[User, Depends(current_user)]):
        decision = body.decision.strip().lower()
        if decision not in {"approved", "rejected"}:
            raise AxiomError("决定只能是批准或拒绝。", "Decision must be approved or rejected.")
        session = open_session()
        try:
            run = _require_run(session, user, run_id)
            approval = session.scalar(select(Approval).where(Approval.run_id == run.id, Approval.status == "pending").order_by(Approval.id))
            if approval is None:
                raise AxiomError("当前没有等待批准的步骤。", "Nothing is waiting for approval.", status=409)
            approval.status = decision
            approval.note = body.note
            approval.resolved_at = utcnow()
            _audit(session, user, f"run.{decision}", "run", str(run.id), approval.gate)
            session.commit()
            return _run_public(session, run)
        finally:
            session.close()

    @app.get("/api/runs/{run_id}/report")
    def report(run_id: int, user: Annotated[User, Depends(current_user)], format: str = Query("md"), locale: str = "zh-CN"):
        session = open_session()
        try:
            run = _require_run(session, user, run_id)
            project = session.get(Project, run.project_id)
            result = _loads(run.result_json)
            _audit(session, user, "report.export", "run", str(run.id), format)
            session.commit()
            document = {
                "title": (project.title if project else None) or result.get("title") or "Axiom",
                "statement": run.statement,
                "status": result.get("status") or run.status,
                "solver": run.solver,
                "objective": result.get("objective") if result.get("objective") is not None else run.objective,
                "dsl": run.dsl or result.get("dsl") or "",
                "variables": result.get("variables") or {},
                "constraints": result.get("constraints") or [],
                "summary": result.get("summary") if locale.startswith("zh") else result.get("summary_en") or result.get("summary"),
                "sensitivity": result.get("sensitivity"),
                "scenarios": result.get("scenarios"),
                "duals": result.get("duals") or {},
                "figures": result.get("figures") or {},
                "race": result.get("race") or [],
                "standard_form": result.get("standard_form"),
            }
        finally:
            session.close()
        fmt = format.lower()
        if fmt in {"md", "markdown"}:
            from axiom.reports.build import markdown_report

            text = markdown_report(document, locale)
            return Response(content=text, media_type="text/markdown; charset=utf-8")
        if fmt in {"xlsx", "excel"}:
            from axiom.reports.build import excel_report

            return Response(
                content=excel_report(document),
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": 'attachment; filename="axiom-report.xlsx"'},
            )
        if fmt == "pdf":
            from axiom.reports.build import pdf_report

            return Response(
                content=pdf_report(document, locale),
                media_type="application/pdf",
                headers={"Content-Disposition": 'attachment; filename="axiom-report.pdf"'},
            )
        if fmt in {"zip", "package"}:
            from axiom.reports.build import package_report

            return Response(
                content=package_report(document, locale),
                media_type="application/zip",
                headers={"Content-Disposition": 'attachment; filename="axiom-package.zip"'},
            )
        raise AxiomError("报告格式只支持 Markdown、PDF、Excel 和打包。", "Reports are Markdown, PDF, Excel, or a zip package.")

    @app.post("/api/validate")
    def validate_route(body: DslBody, _user: Annotated[User, Depends(current_user)]):
        try:
            model = parse_aml(body.dsl)
        except AxiomError as exc:
            return {"ok": False, "diagnostics": [{"level": "error", "message": exc.message, "message_en": exc.message_en, "code": exc.code}]}
        checked = validate(model)
        return {"ok": checked.ok, "name": model.name, "diagnostics": [item.to_dict() for item in checked.diagnostics], "aml": emit_aml(model)}

    @app.post("/api/standard-form")
    def standard_route(body: DslBody, _user: Annotated[User, Depends(current_user)]):
        if not (body.dsl or "").strip():
            return {"ok": False, "code": "empty", "message": "还没有模型，无法写出标准方程。", "message_en": "There is no model to write as standard equations."}
        try:
            model = parse_aml(body.dsl)
        except AxiomError as exc:
            return {"ok": False, "code": exc.code, "message": exc.message, "message_en": exc.message_en}
        checked = validate(model)
        if not checked.ok:
            first = next(item for item in checked.diagnostics if item.level == "error")
            return {
                "ok": False,
                "code": first.code,
                "message": first.message,
                "message_en": first.message_en,
                "diagnostics": [item.to_dict() for item in checked.diagnostics],
            }
        try:
            return standard_form(model)
        except AxiomError as exc:
            return {"ok": False, "code": exc.code, "message": exc.message, "message_en": exc.message_en}

    @app.post("/api/translate")
    def translate_route(body: TranslateBody, _user: Annotated[User, Depends(current_user)]):
        model = parse_aml(body.dsl)
        return translate(model, body.target).to_dict()

    @app.post("/api/solve")
    def solve_route(body: SolveBody, _user: Annotated[User, Depends(current_user)]):
        model = parse_aml(body.dsl)
        return solve_model(model, body.solver or "highs").to_dict()

    @app.post("/api/import")
    def import_route(body: ImportBody, user: Annotated[User, Depends(current_user)]):
        fmt = body.format.lower().strip()
        try:
            model = read_model(fmt, body.text)
        except AxiomError:
            raise
        except Exception as exc:
            raise AxiomError(f"无法导入 {fmt}：{exc}", f"Could not import {fmt}: {exc}", code="import") from exc
        checked = validate(model)
        session = open_session()
        try:
            _audit(session, user, "model.import", "model", fmt, model.name)
            session.commit()
        finally:
            session.close()
        return {"ok": checked.ok, "aml": emit_aml(model), "diagnostics": [item.to_dict() for item in checked.diagnostics]}

    @app.post("/api/tables/preview")
    def table_preview(body: TablePreviewBody, _user: Annotated[User, Depends(current_user)]):
        try:
            raw = base64.b64decode(body.content_base64, validate=True)
        except Exception as exc:
            raise AxiomError("表格内容不是有效的 Base64。", "The table payload is not valid Base64.", code="bad_table") from exc
        if len(raw) > 5_000_000:
            raise AxiomError("表格超过 5 MB。", "The table is larger than 5 MB.", code="bad_table")
        return preview_table(raw, body.filename, body.encoding, body.sheet)

    @app.post("/api/tables/apply")
    def table_apply(body: TableApplyBody, user: Annotated[User, Depends(current_user)]):
        aml = apply_table(body.dsl, body.columns, body.rows, body.mapping)
        session = open_session()
        try:
            _audit(session, user, "data.import", "model", "table", f"{len(body.rows)} rows")
            session.commit()
        finally:
            session.close()
        return {"ok": True, "aml": aml}

    @app.post("/api/model-data")
    def model_data(body: DslBody, _user: Annotated[User, Depends(current_user)]):
        if not (body.dsl or "").strip():
            return {"sets": [], "parameters": [], "rhs": []}
        model = parse_aml(body.dsl)
        return outline(model)

    @app.post("/api/model-data/apply")
    def model_data_apply(body: OutlineBody, user: Annotated[User, Depends(current_user)]):
        aml = apply_outline(body.dsl, {"sets": body.sets, "parameters": body.parameters, "rhs": body.rhs})
        session = open_session()
        try:
            _audit(session, user, "model.edit", "model", "outline", f"{len(body.rhs)} rhs")
            session.commit()
        finally:
            session.close()
        return {"ok": True, "aml": aml}

    @app.post("/api/figures")
    def figures_route(body: DslBody, _user: Annotated[User, Depends(current_user)]):
        if not (body.dsl or "").strip():
            return {"feasible_region": None, "pareto": None}
        return academic_figures(parse_aml(body.dsl))

    @app.post("/api/diagnose")
    def diagnose_route(body: DslBody, _user: Annotated[User, Depends(current_user)]):
        model = parse_aml(body.dsl)
        return diagnose(model)

    @app.post("/api/recommend")
    def recommend_route(body: DslBody, _user: Annotated[User, Depends(current_user)]):
        if not (body.dsl or "").strip():
            return {
                "solver": "highs",
                "family": "lp",
                "algorithm": "auto",
                "label_zh": "自动",
                "label_en": "Auto",
                "reason_zh": "还没有模型。写出方程后，这里会说明为什么选这个算法。",
                "reason_en": "There is no model yet. Once the equations exist, this line explains the algorithm.",
            }
        return recommend(parse_aml(body.dsl))

    @app.post("/api/what-if/knobs")
    def what_if_knobs_route(body: DslBody, _user: Annotated[User, Depends(current_user)]):
        if not (body.dsl or "").strip():
            return {"knobs": []}
        return {"knobs": what_if_knobs(parse_aml(body.dsl))}

    @app.post("/api/what-if")
    def what_if_route(body: WhatIfBody, _user: Annotated[User, Depends(current_user)]):
        model = parse_aml(body.dsl)
        return what_if(model, body.changes, body.solver or "highs")

    @app.post("/api/compare")
    def compare_route(body: CompareBody, _user: Annotated[User, Depends(current_user)]):
        return compare_solutions(body.left, body.right)

    @app.get("/api/projects/{project_id}/versions")
    def project_versions(project_id: int, user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            _require_project(session, user, project_id)
            rows = session.scalars(select(ModelVersion).where(ModelVersion.project_id == project_id).order_by(ModelVersion.id.desc()))
            return [item.public() for item in rows]
        finally:
            session.close()

    @app.post("/api/projects/{project_id}/versions")
    def save_version(project_id: int, body: VersionBody, user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            project = _require_project(session, user, project_id)
            row = ModelVersion(
                project_id=project.id,
                label=(body.label or "手动保存").strip() or "手动保存",
                dsl=body.dsl if body.dsl is not None else project.dsl,
                statement=body.statement if body.statement is not None else project.statement,
                note=body.note or "",
            )
            session.add(row)
            _audit(session, user, "version.save", "project", str(project.id), row.label)
            session.commit()
            return row.public()
        finally:
            session.close()

    @app.get("/api/templates")
    def templates(_user: Annotated[User, Depends(current_user)]):
        return list_templates()

    @app.get("/api/templates/{template_id}")
    def template(template_id: str, _user: Annotated[User, Depends(current_user)]):
        item = get_template(template_id)
        if item is None:
            raise AxiomError("没有这个模板。", "Unknown template.", status=404)
        return item

    @app.get("/api/algorithms")
    def algorithms(_user: Annotated[User, Depends(current_user)]):
        return public_catalog()

    @app.get("/api/solvers")
    def solvers(_user: Annotated[User, Depends(current_user)]):
        return cached_solvers()

    @app.post("/api/benchmark")
    def benchmark(_user: Annotated[User, Depends(current_user)]):
        return run_benchmark()

    @app.get("/api/compatibility")
    def compatibility(_user: Annotated[User, Depends(current_user)], execute: bool = False):
        return compatibility_matrix(execute=execute)

    @app.post("/api/analyses/propose")
    def analyses_propose(body: AnalysisBody, _user: Annotated[User, Depends(current_user)]):
        return propose(body.statement or body.dsl, body.dsl)

    @app.post("/api/analyses/run")
    def analyses_run(body: AnalysisBody, _user: Annotated[User, Depends(current_user)]):
        return run_study(body.kind or "local", body.dsl, body.options)

    @app.post("/api/analyses")
    def analyses_start(body: AnalysisBody, user: Annotated[User, Depends(current_user)]):
        run_id = _analysis_run(user, body)
        def _persist(job: dict) -> None:
            if run_id is None:
                return
            session = open_session()
            try:
                row = session.get(Run, run_id)
                if row is None:
                    return
                result = job.get("result") or {}
                row.status = "completed" if job["status"] == "completed" else ("cancelled" if job["status"] == "cancelled" else "failed")
                row.objective = "" if result.get("objective") is None else f"{float(result['objective']):.8g}"[:64]
                row.error = job.get("error") or ""
                row.error_en = job.get("error_en") or ""
                row.result_json = json.dumps({"kind": "analysis", "job": job["id"], "study": result}, ensure_ascii=False)
                row.finished_at = utcnow()
                session.commit()
            finally:
                session.close()

        job = start_job(body.kind or "local", body.dsl, body.options, _persist)
        job["run_id"] = run_id
        return job

    @app.get("/api/analyses/{job_id}")
    def analyses_get(job_id: str, _user: Annotated[User, Depends(current_user)]):
        job = get_job(job_id)
        if job is None:
            raise AxiomError("没有这次分析。", "That analysis is not in memory.", status=404)
        return job

    @app.post("/api/analyses/{job_id}/cancel")
    def analyses_cancel(job_id: str, _user: Annotated[User, Depends(current_user)]):
        job = cancel_job(job_id)
        if job is None:
            raise AxiomError("没有这次分析。", "That analysis is not in memory.", status=404)
        return job

    @app.get("/api/translators")
    def translators(_user: Annotated[User, Depends(current_user)]):
        return list_translators()

    @app.get("/api/settings")
    def get_settings(_user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            return _settings_public(session)
        finally:
            session.close()

    @app.put("/api/settings")
    def put_settings(body: SettingsBody, user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            _put_setting(session, "llm.provider", body.provider or "mock")
            _put_setting(session, "llm.base_url", body.base_url or "https://api.openai.com/v1")
            _put_setting(session, "llm.model", body.model or "gpt-4o-mini")
            if body.api_key:
                _put_setting(session, "llm.api_key", encrypt_secret(body.api_key))
            from axiom.llm.store import absorb_legacy

            absorb_legacy(session, body.provider or "mock", body.base_url or "https://api.openai.com/v1", body.model or "gpt-4o-mini", body.api_key)
            _audit(session, user, "settings.update", "settings", "llm", body.provider)
            session.commit()
            return _settings_public(session)
        finally:
            session.close()

    @app.post("/api/chat")
    def chat(body: ChatBody, user: Annotated[User, Depends(current_user)]):
        check_rate(f"chat:{user.id}", limit=40, window=60)
        from axiom.llm.store import complete_text, provider_name_for

        provider = provider_name_for("planner")
        last_user = next((item.content for item in reversed(body.messages) if item.role == "user" and item.content.strip()), "")
        from axiom.lifecycle.nl import interpret

        command = interpret(last_user)
        if command is not None:
            from axiom.lifecycle.service import apply_command

            session = open_session()
            try:
                result = apply_command(session, user, command, body.project_id)
                session.commit()
            finally:
                session.close()
            return {
                "role": "assistant",
                "content": result["content"],
                "provider": "lifecycle",
                "lifecycle": result.get("lifecycle"),
                "proposals": [],
                "study": None,
            }
        if provider == "mock":
            context = "\n".join(item.content for item in body.messages if item.content.strip())
            formulated = formulate(context or last_user or "帮我看看")
            text = formulated.summary or formulated.summary_en
            if formulated.aml:
                text = f"{text}\n\n```aml\n{formulated.aml.strip()}\n```"
            proposal = propose(last_user, formulated.aml or context)
            study = None
            if proposal["auto"]:
                try:
                    study = run_study(proposal["auto"]["kind"], formulated.aml or "", proposal["auto"]["options"])
                    extra = proposal["auto"]["reason_zh"]
                    if isinstance(study, dict) and study.get("objective") is not None:
                        extra = f"{extra} 目标 {float(study['objective']):.6g}。"
                    text = f"{text}\n\n{extra}"
                except AxiomError as exc:
                    text = f"{text}\n\n{exc.message}"
            return {"role": "assistant", "content": text, "provider": "mock", "proposals": proposal["proposals"], "study": study}
        dialog = [{"role": item.role, "content": item.content} for item in body.messages if item.content.strip()]
        try:
            content = complete_text("planner", dialog or [{"role": "user", "content": last_user or "ping"}])
        except AxiomError:
            raise
        except Exception as exc:
            raise AxiomError(
                f"语言模型暂时不可用：{exc}",
                f"The language model is unavailable: {exc}",
                code="llm",
            ) from exc
        return {"role": "assistant", "content": content, "provider": provider}

    @app.post("/api/settings/test-llm")
    def test_llm(_user: Annotated[User, Depends(current_user)]):
        session = open_session()
        try:
            rows = {item.key: item.value for item in session.scalars(select(Setting))}
        finally:
            session.close()
        client = LLMClient(
            LLMSettings(
                provider=rows.get("llm.provider") or "mock",
                base_url=rows.get("llm.base_url") or "https://api.openai.com/v1",
                api_key=decrypt_secret(rows.get("llm.api_key") or ""),
                model=rows.get("llm.model") or "gpt-4o-mini",
            )
        )
        return client.test()

    @app.get("/api/audit")
    def audit(user: Annotated[User, Depends(current_user)], limit: int = 200):
        session = open_session()
        try:
            query = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 500))
            if user.role != "admin":
                query = select(AuditLog).where(AuditLog.user_id == user.id).order_by(AuditLog.id.desc()).limit(min(limit, 500))
            return [item.public() for item in session.scalars(query)]
        finally:
            session.close()

    from axiom.llm.routes import mount_llm
    from axiom.lifecycle.routes import mount_lifecycle

    mount_llm(app, current_user)
    mount_lifecycle(app, current_user)
    return app


class LoginBody(BaseModel):
    username: str
    password: str


class ProfileBody(BaseModel):
    display_name: str | None = None
    locale: str | None = None
    theme: str | None = None
    password: str | None = None


class WorkspaceBody(BaseModel):
    name: str


class MemberBody(BaseModel):
    username: str
    role: str = "member"


class UserBody(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: str = "member"


class ProjectBody(BaseModel):
    title: str = ""
    statement: str = ""
    dsl: str = ""
    workspace_id: int | None = None
    locale: str = "zh-CN"


class ProjectPatch(BaseModel):
    title: str | None = None
    statement: str | None = None
    dsl: str | None = None
    locale: str | None = None


class RunBody(BaseModel):
    statement: str = ""
    dsl: str = ""
    solver: str = "highs"
    algorithm: str = "auto"
    auto_approve: bool = False
    locale: str | None = None


class DecisionBody(BaseModel):
    decision: str
    note: str = ""


class DslBody(BaseModel):
    dsl: str = ""


class TranslateBody(BaseModel):
    dsl: str
    target: str


class SolveBody(BaseModel):
    dsl: str
    solver: str = "highs"


class ImportBody(BaseModel):
    format: str
    text: str


class SettingsBody(BaseModel):
    provider: str = "mock"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    api_key: str | None = None


class ChatMessage(BaseModel):
    role: str = "user"
    content: str = ""


class ChatBody(BaseModel):
    messages: list[ChatMessage] = []
    project_id: int | None = None


class TablePreviewBody(BaseModel):
    filename: str = "data.csv"
    content_base64: str
    encoding: str | None = None
    sheet: str | None = None


class TableApplyBody(BaseModel):
    dsl: str = ""
    columns: list[str] = []
    rows: list[list] = []
    mapping: list[dict] = []


class OutlineBody(BaseModel):
    dsl: str = ""
    sets: list[dict] = []
    parameters: list[dict] = []
    rhs: list[dict] = []


class WhatIfBody(BaseModel):
    dsl: str = ""
    solver: str = "highs"
    changes: list[dict] = []


class CompareBody(BaseModel):
    left: dict = {}
    right: dict = {}


class AnalysisBody(BaseModel):
    kind: str = "local"
    dsl: str = ""
    statement: str = ""
    project_id: int | None = None
    options: dict = {}


class VersionBody(BaseModel):
    label: str = ""
    dsl: str | None = None
    statement: str | None = None
    note: str = ""


def current_user(authorization: Annotated[str | None, Header()] = None) -> User:
    token = _bearer(authorization)
    session = open_session()
    try:
        row = session.get(SessionToken, token)
        if row is None:
            raise AxiomError("登录已失效，请重新登录。", "The session expired. Sign in again.", code="auth", status=401)
        user = session.get(User, row.user_id)
        if user is None:
            raise AxiomError("登录已失效，请重新登录。", "The session expired. Sign in again.", code="auth", status=401)
        session.expunge(user)
        return user
    finally:
        session.close()


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AxiomError("请先登录。", "Sign in first.", code="auth", status=401)
    return authorization.split(" ", 1)[1].strip()


def _workspace_ids(session: Session, user: User) -> list[int]:
    if user.role == "admin":
        return list(session.scalars(select(Workspace.id)))
    return list(session.scalars(select(Membership.workspace_id).where(Membership.user_id == user.id)))


def _workspaces(session: Session, user: User) -> list[Workspace]:
    ids = _workspace_ids(session, user)
    if not ids:
        return []
    return list(session.scalars(select(Workspace).where(Workspace.id.in_(ids)).order_by(Workspace.name)))


def _require_workspace(session: Session, user: User, workspace_id: int, owner: bool = False) -> Workspace:
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise AxiomError("工作区不存在。", "Workspace not found.", status=404)
    if user.role == "admin" and not owner:
        return workspace
    membership = session.scalar(select(Membership).where(Membership.workspace_id == workspace_id, Membership.user_id == user.id))
    if membership is None:
        raise AxiomError("你不在这个工作区。", "You are not in this workspace.", status=403)
    if owner and membership.role != "owner" and user.role != "admin":
        raise AxiomError("只有工作区所有者可以管理成员。", "Only a workspace owner can manage members.", status=403)
    return workspace


def _require_project(session: Session, user: User, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise AxiomError("项目不存在。", "Project not found.", status=404)
    _require_workspace(session, user, project.workspace_id)
    return project


def _require_run(session: Session, user: User, run_id: int) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise AxiomError("运行记录不存在。", "Run not found.", status=404)
    _require_project(session, user, run.project_id)
    return run


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise AxiomError("需要管理员权限。", "Administrator access is required.", status=403)


def _audit(session: Session, user: User | None, action: str, entity: str, entity_id: str, detail: str) -> None:
    session.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else "",
            action=action,
            entity=entity,
            entity_id=entity_id,
            detail=detail[:500],
        )
    )


def _loads(text: str) -> dict:
    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _analysis_run(user: User, body: AnalysisBody) -> int | None:
    if not body.project_id:
        return None
    session = open_session()
    try:
        project = _require_project(session, user, int(body.project_id))
        row = Run(
            project_id=project.id,
            status="running",
            solver="analysis",
            statement=(body.statement or body.kind or "analysis")[:4000],
            dsl=body.dsl or "",
            auto_approve=1,
            created_by=user.id,
            result_json=json.dumps({"kind": "analysis", "study": {"kind": body.kind}}, ensure_ascii=False),
        )
        session.add(row)
        session.commit()
        return int(row.id)
    finally:
        session.close()


def _run_public(session: Session, run: Run) -> dict:
    pending = session.scalar(select(Approval).where(Approval.run_id == run.id, Approval.status == "pending").order_by(Approval.id))
    result = _loads(run.result_json)
    return {
        "id": run.id,
        "project_id": run.project_id,
        "status": run.status,
        "solver": run.solver,
        "objective": run.objective,
        "statement": run.statement,
        "dsl": run.dsl,
        "error": run.error,
        "error_en": run.error_en,
        "auto_approve": bool(run.auto_approve),
        "pending_gate": None if pending is None else {"id": pending.id, "gate": pending.gate, "status": pending.status},
        "result": result,
        "created_by": run.created_by,
        "created_at": run.created_at.isoformat(),
        "finished_at": None if run.finished_at is None else run.finished_at.isoformat(),
    }


def _workspace_public(session: Session, workspace: Workspace | None) -> dict:
    if workspace is None:
        return {}
    members = []
    rows = session.scalars(select(Membership).where(Membership.workspace_id == workspace.id))
    for membership in rows:
        person = session.get(User, membership.user_id)
        if person is None:
            continue
        members.append({"user_id": person.id, "username": person.username, "display_name": person.display_name, "role": membership.role})
    payload = workspace.public()
    payload["members"] = members
    return payload


def _settings_public(session: Session) -> dict:
    rows = {item.key: item.value for item in session.scalars(select(Setting))}
    secret = decrypt_secret(rows.get("llm.api_key") or "")
    return {
        "provider": rows.get("llm.provider") or "mock",
        "base_url": rows.get("llm.base_url") or "https://api.openai.com/v1",
        "model": rows.get("llm.model") or "gpt-4o-mini",
        "api_key_set": bool(secret),
        "api_key_mask": mask_secret(secret),
    }


def _put_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("axiom.main:app", host="127.0.0.1", port=int(os.environ.get("AXIOM_PORT", "43124")), factory=False)


if __name__ == "__main__":
    main()
