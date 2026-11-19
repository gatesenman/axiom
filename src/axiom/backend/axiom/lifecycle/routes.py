"""HTTP API for the problem lifecycle. No postponed annotations: FastAPI needs real types."""

from typing import Annotated

from fastapi import Depends, FastAPI

from axiom.db.session import open_session
from axiom.errors import AxiomError
from axiom.lifecycle import service
from axiom.lifecycle.tables import Artifact
from axiom.limit import check_rate


def mount_lifecycle(app: FastAPI, current_user) -> None:
    @app.get("/api/problems")
    def problem_list(
        user: Annotated[object, Depends(current_user)],
        q: str = "",
        tag: str = "",
        stage: str = "",
        favorite: int = 0,
        workspace_id: int | None = None,
        deleted: int = 0,
    ):
        check_rate(f"problem-read:{user.id}", limit=120, window=60)
        session = open_session()
        try:
            return service.list_problems(session, user, q=q, tag=tag, stage=stage, favorite=bool(favorite), workspace_id=workspace_id, deleted=bool(deleted))
        finally:
            session.close()

    @app.post("/api/problems")
    def problem_create(body: dict, user: Annotated[object, Depends(current_user)]):
        check_rate(f"problem-write:{user.id}", limit=60, window=60)
        session = open_session()
        try:
            problem = service.create_problem(
                session,
                user,
                title=str(body.get("title") or ""),
                description=str(body.get("description") or ""),
                tags=body.get("tags") or [],
                priority=str(body.get("priority") or "normal"),
                due_at=body.get("due_at"),
                custom_fields=body.get("custom_fields") or {},
                workspace_id=body.get("workspace_id"),
                project_id=body.get("project_id"),
                dsl=str(body.get("dsl") or ""),
                fill_existing=bool(body.get("fill_existing", True)),
            )
            session.commit()
            payload = service.detail(session, user, problem)
            return payload
        finally:
            session.close()

    @app.get("/api/problems/search")
    def problem_search(user: Annotated[object, Depends(current_user)], q: str = ""):
        check_rate(f"problem-read:{user.id}", limit=120, window=60)
        session = open_session()
        try:
            return service.search(session, user, q)
        finally:
            session.close()

    @app.get("/api/problems/templates")
    def problem_templates(_user: Annotated[object, Depends(current_user)]):
        return service.templates()

    @app.post("/api/problems/from-template")
    def problem_from_template(body: dict, user: Annotated[object, Depends(current_user)]):
        check_rate(f"problem-write:{user.id}", limit=40, window=60)
        session = open_session()
        try:
            problem = service.from_template(session, user, str(body.get("template_id") or ""), body.get("workspace_id"))
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.get("/api/problems/notices")
    def problem_notices(user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            return service.notices_for(session, user)
        finally:
            session.close()

    @app.post("/api/problems/notices/read")
    def problem_notices_read(body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            service.mark_notices(session, user, [int(item) for item in body.get("ids") or []])
            session.commit()
            return {"ok": True}
        finally:
            session.close()

    @app.get("/api/problems/views")
    def problem_views(user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            return service.views_for(session, user)
        finally:
            session.close()

    @app.post("/api/problems/views")
    def problem_save_view(body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            row = service.save_view(session, user, str(body.get("name") or ""), body.get("filters") or {}, body.get("workspace_id"))
            session.commit()
            return {"id": row.id, "name": row.name, "filters": body.get("filters") or {}}
        finally:
            session.close()

    @app.delete("/api/problems/views/{view_id}")
    def problem_delete_view(view_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            service.delete_view(session, user, view_id)
            session.commit()
            return {"ok": True}
        finally:
            session.close()

    @app.post("/api/problems/import")
    def problem_import(body: dict, user: Annotated[object, Depends(current_user)]):
        check_rate(f"problem-import:{user.id}", limit=20, window=60)
        session = open_session()
        try:
            package = body.get("package") if isinstance(body.get("package"), dict) else body
            problem = service.import_package(session, user, package, body.get("workspace_id"))
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.get("/api/problems/{problem_id}")
    def problem_get(problem_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id, include_deleted=True)
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.patch("/api/problems/{problem_id}")
    def problem_patch(problem_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.update_problem(session, user, problem, body)
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.delete("/api/problems/{problem_id}")
    def problem_delete(problem_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.soft_delete(session, user, problem)
            session.commit()
            return {"ok": True}
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/restore")
    def problem_restore(problem_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id, include_deleted=True)
            service.restore(session, user, problem)
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.delete("/api/problems/{problem_id}/purge")
    def problem_purge(problem_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id, include_deleted=True)
            service.purge(session, user, problem)
            session.commit()
            return {"ok": True}
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/transition")
    def problem_transition(problem_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        check_rate(f"problem-write:{user.id}", limit=60, window=60)
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            result = service.transition(session, user, problem, str(body.get("to_stage") or ""), str(body.get("comment") or ""))
            session.commit()
            payload = service.detail(session, user, problem)
            payload["notice"] = result.get("notice")
            return payload
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/proposals")
    def problem_propose(problem_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            result = service.propose_transition(
                session,
                user,
                problem,
                str(body.get("to_stage") or ""),
                str(body.get("comment") or ""),
                str(body.get("role") or "solver"),
                str(body.get("actor_name") or "求解顾问"),
            )
            session.commit()
            payload = service.detail(session, user, problem)
            payload["applied"] = result.get("applied")
            payload["request_id"] = result.get("request_id")
            payload["notice"] = result.get("notice")
            return payload
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/requests/{request_id}")
    def problem_resolve_request(problem_id: int, request_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            result = service.resolve_request(session, user, problem, request_id, str(body.get("decision") or ""), str(body.get("comment") or ""))
            session.commit()
            payload = service.detail(session, user, problem)
            payload["notice"] = result.get("notice")
            return payload
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/requirements")
    def problem_add_requirement(problem_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.add_requirement(session, user, problem, str(body.get("text") or ""), str(body.get("text_en") or ""))
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/requirements/suggest")
    def problem_suggest(problem_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service._require_area(session, user, problem, "requirements")
            service._add_suggestions(session, problem, problem.description, "agent", "规划智能体")
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.patch("/api/problems/{problem_id}/requirements/{requirement_id}")
    def problem_patch_requirement(problem_id: int, requirement_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.patch_requirement(session, user, problem, requirement_id, body)
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.delete("/api/problems/{problem_id}/requirements/{requirement_id}")
    def problem_delete_requirement(problem_id: int, requirement_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.delete_requirement(session, user, problem, requirement_id)
            session.commit()
            return {"ok": True}
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/data")
    def problem_add_data(problem_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.add_data(
                session,
                user,
                problem,
                name=str(body.get("name") or ""),
                filename=str(body.get("filename") or ""),
                content=str(body.get("content") or ""),
                note=str(body.get("note") or ""),
                parent_id=body.get("parent_id"),
            )
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/models")
    def problem_add_model(problem_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.add_model(
                session,
                user,
                problem,
                aml=str(body.get("aml") or ""),
                label=str(body.get("label") or ""),
                note=str(body.get("note") or ""),
                semver=str(body.get("semver") or ""),
                statement=str(body.get("statement") or ""),
            )
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.get("/api/problems/{problem_id}/models/diff")
    def problem_diff(problem_id: int, user: Annotated[object, Depends(current_user)], left: int, right: int):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            return service.diff_models(session, problem, left, right)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/models/{model_id}/baseline")
    def problem_baseline(problem_id: int, model_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.promote_baseline(session, user, problem, model_id)
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/runs")
    def problem_solve(problem_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        check_rate(f"problem-solve:{user.id}", limit=30, window=60)
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.solve_now(
                session,
                user,
                problem,
                str(body.get("solver") or "highs"),
                aml=str(body.get("aml") or ""),
                seed=body.get("seed"),
                note=str(body.get("note") or ""),
                model_revision_id=body.get("model_revision_id"),
                data_asset_id=body.get("data_asset_id"),
            )
            session.commit()
            payload = service.detail(session, user, problem)
            payload["notice"] = {"kind": "solve", "title": "求解完成", "title_en": "Solve finished", "body": problem.title, "body_en": problem.title}
            return payload
        finally:
            session.close()

    @app.get("/api/problems/{problem_id}/runs/compare")
    def problem_compare(problem_id: int, user: Annotated[object, Depends(current_user)], left: int, right: int):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            return service.compare_solves(session, problem, left, right)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/analyses")
    def problem_analysis(problem_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        check_rate(f"problem-solve:{user.id}", limit=30, window=60)
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.run_analysis(session, user, problem, str(body.get("kind") or "local"), body.get("options") or {}, body.get("model_revision_id"))
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/decisions")
    def problem_decision(problem_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.add_decision(
                session,
                user,
                problem,
                title=str(body.get("title") or ""),
                rationale=str(body.get("rationale") or ""),
                rationale_en=str(body.get("rationale_en") or ""),
                run_ids=body.get("run_ids") or [],
                chosen_run_id=body.get("chosen_run_id"),
            )
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/decisions/memo")
    def problem_memo(problem_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.write_memo(session, user, problem)
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/decisions/{decision_id}/accept")
    def problem_accept_decision(problem_id: int, decision_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.accept_decision(session, user, problem, decision_id)
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/changes")
    def problem_change(problem_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.add_change(session, user, problem, str(body.get("title") or ""), str(body.get("impact") or ""))
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/changes/{change_id}/accept")
    def problem_accept_change(problem_id: int, change_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.resolve_change(session, user, problem, change_id, "accepted")
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/changes/{change_id}/reject")
    def problem_reject_change(problem_id: int, change_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.resolve_change(session, user, problem, change_id, "rejected")
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/artifacts")
    def problem_artifact(problem_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.make_artifact(session, user, problem, str(body.get("kind") or "latex"))
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.get("/api/problems/{problem_id}/artifacts/{artifact_id}")
    def problem_artifact_get(problem_id: int, artifact_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id, include_deleted=True)
            row = session.get(Artifact, artifact_id)
            if row is None or row.problem_id != problem.id:
                raise AxiomError("没有这个产物。", "That artifact was not found.", status=404)
            return {"id": row.id, "kind": row.kind, "name": row.name, "media": row.media, "content": row.content}
        finally:
            session.close()

    @app.get("/api/problems/{problem_id}/package")
    def problem_package(problem_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            package = service.export_package(session, user, problem)
            session.commit()
            return package
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/members")
    def problem_member(problem_id: int, body: dict, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.set_member(session, user, problem, str(body.get("username") or ""), str(body.get("role") or "viewer"))
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()

    @app.post("/api/problems/{problem_id}/summary")
    def problem_summary(problem_id: int, user: Annotated[object, Depends(current_user)]):
        session = open_session()
        try:
            problem = service._require(session, user, problem_id)
            service.enrich_summary(session, user, problem)
            session.commit()
            return service.detail(session, user, problem)
        finally:
            session.close()
