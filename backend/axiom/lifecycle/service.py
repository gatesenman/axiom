"""Persistence and rules for the problem lifecycle.

The studio Project stays the editor document. A Problem is the record that
moves from intake to archival. This module never changes Project.status.
"""

from __future__ import annotations

import base64
import difflib
import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from axiom.db.models import AuditLog, Membership, Project, Run, User, Workspace, utcnow
from axiom.errors import AxiomError
from axiom.lifecycle import machine
from axiom.lifecycle.tables import (
    Activity,
    AnalysisLink,
    Artifact,
    ChangeRequest,
    DataAsset,
    Decision,
    ModelRevision,
    Problem,
    ProblemMember,
    ProblemNotice,
    ProblemTransition,
    Requirement,
    SavedView,
    SolveRecord,
    TransitionRequest,
)

PRIORITIES = {"low", "normal", "high", "urgent"}
ROLES = {"viewer", "modeler", "solver", "reviewer", "owner"}
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_CONTENT_CAP = 1_000_000
_ARTIFACT_CAP = 2_000_000

STAGE_ZH = {
    "draft": "草稿",
    "intake": "受理",
    "modeling": "建模",
    "equations": "方程",
    "solving": "求解",
    "analyzing": "分析",
    "review": "评审",
    "decided": "决策",
    "archived": "归档",
    "closed": "关闭",
    "on_hold": "挂起",
    "blocked": "阻塞",
    "rejected": "驳回",
    "reopened": "重开",
}
STAGE_EN = {
    "draft": "Draft",
    "intake": "Intake",
    "modeling": "Modeling",
    "equations": "Equations",
    "solving": "Solving",
    "analyzing": "Analyzing",
    "review": "Review",
    "decided": "Decided",
    "archived": "Archived",
    "closed": "Closed",
    "on_hold": "On hold",
    "blocked": "Blocked",
    "rejected": "Rejected",
    "reopened": "Reopened",
}
NEXT = {
    "draft": ("补全陈述并进入受理", "Complete the statement and open intake"),
    "intake": ("确认验收标准", "Confirm the acceptance criteria"),
    "modeling": ("固定一版模型", "Pin a model version"),
    "equations": ("核对标准方程后进入求解", "Check the equations and start solving"),
    "solving": ("运行求解器并记录结果", "Run a solver and record the result"),
    "analyzing": ("完成一项分析研究", "Run an analysis study"),
    "review": ("写决策备忘并提交", "Write the decision memo"),
    "decided": ("归档这个问题", "Archive this problem"),
    "archived": ("关闭档案", "Close the record"),
    "closed": ("档案已关闭", "The record is closed"),
    "on_hold": ("恢复到挂起前的阶段", "Resume the stage that was paused"),
    "blocked": ("解除阻塞并恢复", "Clear the block and resume"),
    "rejected": ("重开并回到建模", "Reopen and return to modeling"),
    "reopened": ("回到建模处理变更", "Return to modeling"),
}
_AREAS = {
    "requirements": {"modeler", "owner"},
    "data": {"modeler", "owner"},
    "models": {"modeler", "owner"},
    "runs": {"solver", "owner"},
    "analyses": {"modeler", "solver", "reviewer", "owner"},
    "decisions": {"reviewer", "owner"},
    "artifacts": {"modeler", "reviewer", "owner"},
    "members": {"owner"},
    "delete": {"owner"},
}
_TEMPLATE_TAGS = {
    "product-mix": "supply-chain",
    "production-planning": "scheduling",
    "transportation": "supply-chain",
    "assignment": "scheduling",
    "knapsack": "supply-chain",
    "facility-location": "supply-chain",
    "scheduling": "scheduling",
    "diet": "supply-chain",
    "staffing": "scheduling",
    "multiobjective": "mdo",
    "portfolio-qp": "finance",
    "latin": "mdo",
    "queue": "scheduling",
    "tsp": "scheduling",
}


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(text: str, fallback):
    try:
        value = json.loads(text or "")
    except json.JSONDecodeError:
        return fallback
    return value


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _tags(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()[:32]
        if text and text not in out:
            out.append(text)
        if len(out) >= 12:
            break
    return out


def _custom(value) -> dict:
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, item in list(value.items())[:40]:
        if not isinstance(key, str):
            continue
        name = key.strip()[:64]
        if not name:
            continue
        if isinstance(item, str):
            out[name] = item[:500]
        elif isinstance(item, (int, float, bool)) or item is None:
            out[name] = item
    return out


def _due(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AxiomError("截止日期格式应为 ISO 日期。", "The due date must be an ISO date.") from exc


def workspace_ids(session: Session, user: User) -> list[int]:
    if user.role == "admin":
        return list(session.scalars(select(Workspace.id)))
    return list(session.scalars(select(Membership.workspace_id).where(Membership.user_id == user.id)))


def _role(session: Session, user: User, problem: Problem) -> str:
    if user.role == "admin":
        return "owner"
    row = session.scalar(select(ProblemMember).where(ProblemMember.problem_id == problem.id, ProblemMember.user_id == user.id))
    if row is not None and row.role in ROLES:
        return row.role
    workspace = session.get(Workspace, problem.workspace_id)
    if workspace is not None and workspace.owner_id == user.id:
        return "owner"
    return "viewer"


def _require_area(session: Session, user: User, problem: Problem, area: str) -> str:
    role = _role(session, user, problem)
    if role not in _AREAS[area]:
        raise AxiomError("当前角色不能修改这部分。", "Your role cannot change this part of the problem.", status=403)
    return role


def _audit(session: Session, user: User | None, action: str, problem: Problem | None, detail: str) -> None:
    session.add(
        AuditLog(
            user_id=None if user is None else user.id,
            username="" if user is None else user.username,
            action=action,
            entity="problem",
            entity_id="" if problem is None else str(problem.id),
            detail=detail[:500],
        )
    )


def _activity(session: Session, problem: Problem, actor_kind: str, actor_id: int | None, actor_name: str, action: str, detail: str, detail_en: str) -> None:
    session.add(
        Activity(
            problem_id=problem.id,
            actor_kind=actor_kind,
            actor_id=actor_id,
            actor_name=actor_name[:128],
            action=action[:64],
            detail=detail[:2000],
            detail_en=detail_en[:2000],
        )
    )


def _notify(session: Session, problem: Problem, kind: str, title: str, title_en: str, body: str, body_en: str) -> dict:
    ids = {problem.owner_id}
    for member in session.scalars(select(ProblemMember).where(ProblemMember.problem_id == problem.id)):
        ids.add(member.user_id)
    for user_id in ids:
        if user_id is None:
            continue
        session.add(
            ProblemNotice(
                user_id=user_id,
                problem_id=problem.id,
                kind=kind,
                title=title[:200],
                title_en=title_en[:200],
                body=body[:1000],
                body_en=body_en[:1000],
            )
        )
    return {"kind": kind, "title": title, "title_en": title_en, "body": body, "body_en": body_en}


def _solves(session: Session, problem_id: int) -> list[SolveRecord]:
    return list(session.scalars(select(SolveRecord).where(SolveRecord.problem_id == problem_id).order_by(SolveRecord.id)))


def _next_stage(problem: Problem) -> str | None:
    if problem.stage in {"on_hold", "blocked"}:
        return problem.resume_stage or "draft"
    if problem.stage == "reopened":
        return "modeling"
    if problem.stage == "rejected":
        return "reopened"
    return machine.next_main(problem.stage)


def best_objective(rows: list[SolveRecord]) -> float | None:
    good = [row for row in rows if row.objective is not None and row.status in {"optimal", "feasible", "completed"}]
    if not good:
        return None
    sense = good[-1].sense or "minimize"
    pool = [float(row.objective) for row in good if (row.sense or sense) == sense and row.objective is not None]
    if not pool:
        pool = [float(row.objective) for row in good if row.objective is not None]
        sense = "minimize"
    if sense == "maximize":
        return max(pool)
    return min(pool)


def _refresh(session: Session, problem: Problem) -> None:
    rows = _solves(session, problem.id)
    best = best_objective(rows)
    zh, en = NEXT.get(problem.stage, ("继续处理", "Continue"))
    best_zh = "尚无可行目标值" if best is None else f"当前最好目标 {best:.6g}"
    best_en = "no feasible objective yet" if best is None else f"best objective {best:.6g}"
    problem.ai_summary = f"{problem.title} 处于{STAGE_ZH.get(problem.stage, problem.stage)}。{best_zh}，共 {len(rows)} 次求解。{(problem.description or '')[:80]}"
    problem.ai_summary_en = f"{problem.title} is {STAGE_EN.get(problem.stage, problem.stage)}. {best_en}, {len(rows)} solves. {(problem.description or '')[:80]}"
    problem.next_action = zh
    problem.next_action_en = en
    problem.updated_at = utcnow()


def _owner_name(session: Session, user_id: int | None) -> str:
    if user_id is None:
        return ""
    person = session.get(User, user_id)
    return "" if person is None else person.display_name


def _last_activity(session: Session, problem_id: int) -> str | None:
    row = session.scalar(select(Activity).where(Activity.problem_id == problem_id).order_by(Activity.id.desc()))
    return None if row is None else _iso(row.created_at)


def card(session: Session, user: User, problem: Problem) -> dict:
    rows = _solves(session, problem.id)
    return {
        "id": problem.id,
        "project_id": problem.project_id,
        "workspace_id": problem.workspace_id,
        "title": problem.title,
        "description": problem.description,
        "tags": _loads(problem.tags_json, []),
        "priority": problem.priority,
        "owner_id": problem.owner_id,
        "owner_name": _owner_name(session, problem.owner_id),
        "due_at": _iso(problem.due_at),
        "custom_fields": _loads(problem.custom_json, {}),
        "stage": problem.stage,
        "resume_stage": problem.resume_stage,
        "auto_advance": bool(problem.auto_advance),
        "approval_required": bool(problem.approval_required),
        "favorite": bool(problem.favorite),
        "deleted_at": _iso(problem.deleted_at),
        "ai_summary": problem.ai_summary,
        "ai_summary_en": problem.ai_summary_en,
        "next_action": problem.next_action,
        "next_action_en": problem.next_action_en,
        "next_stage": _next_stage(problem),
        "baseline_model_id": problem.baseline_model_id,
        "best_objective": best_objective(rows),
        "run_count": len(rows),
        "last_activity": _last_activity(session, problem.id),
        "role": _role(session, user, problem),
        "created_at": _iso(problem.created_at),
        "updated_at": _iso(problem.updated_at),
    }


def _require(session: Session, user: User, problem_id: int, include_deleted: bool = False) -> Problem:
    problem = session.get(Problem, problem_id)
    if problem is None or (problem.deleted_at is not None and not include_deleted):
        raise AxiomError("问题不存在。", "Problem not found.", status=404)
    if user.role != "admin" and problem.workspace_id not in workspace_ids(session, user):
        raise AxiomError("你不在这个工作区。", "You are not in this workspace.", status=403)
    return problem


def ensure_problem(session: Session, project: Project, user: User | None) -> Problem:
    row = session.scalar(select(Problem).where(Problem.project_id == project.id))
    if row is not None:
        return row
    owner_id = project.created_by or (None if user is None else user.id)
    problem = Problem(
        project_id=project.id,
        workspace_id=project.workspace_id,
        title=(project.title or "未命名问题")[:200],
        description=project.statement or "",
        tags_json="[]",
        priority="normal",
        owner_id=owner_id,
        custom_json="{}",
        stage="draft",
        auto_advance=1,
        approval_required=1,
        created_by=owner_id,
    )
    session.add(problem)
    session.flush()
    if owner_id is not None:
        session.add(ProblemMember(problem_id=problem.id, user_id=owner_id, role="owner"))
    actor = user.display_name if user is not None else "规划智能体"
    _activity(session, problem, "agent" if user is None else "user", None if user is None else user.id, actor, "create", "建立问题档案", "Opened the problem record")
    if problem.description.strip():
        _add_suggestions(session, problem, problem.description, actor_kind="agent", actor_name="规划智能体")
    _refresh(session, problem)
    return problem


def backfill(session: Session, user: User) -> None:
    ids = workspace_ids(session, user)
    if not ids:
        return
    linked = set(session.scalars(select(Problem.project_id).where(Problem.project_id.is_not(None), Problem.workspace_id.in_(ids))))
    created = False
    for project in session.scalars(select(Project).where(Project.workspace_id.in_(ids))):
        if project.id in linked:
            continue
        ensure_problem(session, project, user)
        created = True
    if created:
        session.commit()


def list_problems(session: Session, user: User, *, q: str = "", tag: str = "", stage: str = "", favorite: bool = False, workspace_id: int | None = None, deleted: bool = False) -> list[dict]:
    backfill(session, user)
    ids = workspace_ids(session, user)
    if workspace_id is not None:
        if workspace_id not in ids and user.role != "admin":
            raise AxiomError("你不在这个工作区。", "You are not in this workspace.", status=403)
        ids = [workspace_id]
    if not ids:
        return []
    rows = list(session.scalars(select(Problem).where(Problem.workspace_id.in_(ids)).order_by(Problem.updated_at.desc())))
    needle = q.strip().lower()
    out = []
    for problem in rows:
        if deleted and problem.deleted_at is None:
            continue
        if not deleted and problem.deleted_at is not None:
            continue
        if stage and problem.stage != stage:
            continue
        if favorite and not problem.favorite:
            continue
        tags = _loads(problem.tags_json, [])
        if tag and tag not in tags:
            continue
        if needle and needle not in problem.title.lower() and needle not in (problem.description or "").lower():
            continue
        out.append(card(session, user, problem))
    return out


def create_problem(
    session: Session,
    user: User,
    *,
    title: str,
    description: str = "",
    tags: list | None = None,
    priority: str = "normal",
    due_at=None,
    custom_fields: dict | None = None,
    workspace_id: int | None = None,
    project_id: int | None = None,
    dsl: str = "",
    fill_existing: bool = False,
) -> Problem:
    ids = workspace_ids(session, user)
    if project_id is not None:
        project = session.get(Project, project_id)
        if project is None:
            raise AxiomError("项目不存在。", "Project not found.", status=404)
        if user.role != "admin" and project.workspace_id not in ids:
            raise AxiomError("你不在这个工作区。", "You are not in this workspace.", status=403)
        existing = session.scalar(select(Problem).where(Problem.project_id == project.id))
        if existing is not None:
            if existing.deleted_at is not None:
                raise AxiomError("问题在回收站里，请先恢复。", "The problem is in the recycle bin. Restore it first.", status=409)
            if fill_existing or True:
                if description.strip():
                    existing.description = description
                    project.statement = description
                if title.strip():
                    existing.title = title.strip()[:200]
                    project.title = existing.title
                if tags:
                    existing.tags_json = _dumps(_tags(tags))
                if priority in PRIORITIES:
                    existing.priority = priority
                if due_at not in (None, ""):
                    existing.due_at = _due(due_at)
                if custom_fields:
                    existing.custom_json = _dumps(_custom(custom_fields))
                _add_suggestions(session, existing, existing.description, actor_kind="agent", actor_name="规划智能体")
                if (dsl or "").strip():
                    add_model(session, user, existing, aml=dsl, label="对话", note="从对话写入", actor_kind="agent", actor_name="建模智能体")
                _activity(session, existing, "user", user.id, user.display_name, "intake", "从对话写入问题陈述", "Wrote the statement from chat")
                _refresh(session, existing)
                _audit(session, user, "problem.update", existing, existing.title)
                return existing
        workspace_id = project.workspace_id
    else:
        workspace_id = workspace_id or (ids[0] if ids else None)
        if workspace_id is None or (user.role != "admin" and workspace_id not in ids):
            raise AxiomError("先创建一个工作区。", "Create a workspace first.", status=400 if workspace_id is None else 403)
        project = Project(
            workspace_id=workspace_id,
            title=(title or "未命名问题").strip()[:200] or "未命名问题",
            statement=description or "",
            dsl=dsl or "",
            locale="zh-CN",
            status="draft",
            created_by=user.id,
            updated_at=utcnow(),
        )
        session.add(project)
        session.flush()
    if priority not in PRIORITIES:
        priority = "normal"
    problem = Problem(
        project_id=project.id,
        workspace_id=project.workspace_id,
        title=(title or project.title or "未命名问题").strip()[:200] or "未命名问题",
        description=description or "",
        tags_json=_dumps(_tags(tags or [])),
        priority=priority,
        owner_id=user.id,
        due_at=_due(due_at),
        custom_json=_dumps(_custom(custom_fields or {})),
        stage="draft",
        auto_advance=1,
        approval_required=1,
        created_by=user.id,
    )
    session.add(problem)
    session.flush()
    session.add(ProblemMember(problem_id=problem.id, user_id=user.id, role="owner"))
    _activity(session, problem, "user", user.id, user.display_name, "create", "建立问题档案", "Opened the problem record")
    if problem.description.strip():
        _add_suggestions(session, problem, problem.description, actor_kind="agent", actor_name="规划智能体")
    if (dsl or project.dsl or "").strip():
        add_model(session, user, problem, aml=(dsl or project.dsl), label="初始", note="建档时的模型", actor_kind="agent", actor_name="建模智能体")
    _refresh(session, problem)
    _audit(session, user, "problem.create", problem, problem.title)
    return problem


def update_problem(session: Session, user: User, problem: Problem, fields: dict) -> Problem:
    _require_area(session, user, problem, "requirements")
    if "title" in fields and fields["title"] is not None:
        problem.title = str(fields["title"]).strip()[:200] or problem.title
    if "description" in fields and fields["description"] is not None:
        problem.description = str(fields["description"])
    if "tags" in fields and fields["tags"] is not None:
        problem.tags_json = _dumps(_tags(fields["tags"]))
    if "priority" in fields and fields["priority"] in PRIORITIES:
        problem.priority = fields["priority"]
    if "due_at" in fields:
        problem.due_at = _due(fields["due_at"])
    if "custom_fields" in fields and fields["custom_fields"] is not None:
        problem.custom_json = _dumps(_custom(fields["custom_fields"]))
    if "favorite" in fields and fields["favorite"] is not None:
        problem.favorite = 1 if fields["favorite"] else 0
    if "auto_advance" in fields and fields["auto_advance"] is not None:
        problem.auto_advance = 1 if fields["auto_advance"] else 0
    if "approval_required" in fields and fields["approval_required"] is not None:
        problem.approval_required = 1 if fields["approval_required"] else 0
    if problem.project_id and ("title" in fields or "description" in fields):
        project = session.get(Project, problem.project_id)
        if project is not None:
            project.title = problem.title
            project.statement = problem.description
            project.updated_at = utcnow()
    _activity(session, problem, "user", user.id, user.display_name, "update", "更新了问题字段", "Updated problem fields")
    _refresh(session, problem)
    _audit(session, user, "problem.update", problem, problem.title)
    return problem


def _actor(user: User | None, kind: str, name: str | None) -> tuple[str, int | None, str]:
    if kind == "agent":
        return "agent", None if user is None else user.id, (name or "智能体")[:128]
    if user is None:
        return "user", None, name or ""
    return "user", user.id, user.display_name


def _apply_hop(session: Session, user: User | None, problem: Problem, hop: str, comment: str, actor_kind: str, actor_name: str | None) -> dict:
    kind, actor_id, name = _actor(user, actor_kind, actor_name)
    source = problem.stage
    if hop in {"on_hold", "blocked"} and source not in {"on_hold", "blocked"}:
        problem.resume_stage = source
    if source in {"on_hold", "blocked"} and hop not in {"on_hold", "blocked"}:
        problem.resume_stage = ""
    problem.stage = hop
    session.add(
        ProblemTransition(
            problem_id=problem.id,
            from_stage=source,
            to_stage=hop,
            comment=(comment or "")[:2000],
            actor_kind=kind,
            actor_id=actor_id,
            actor_name=name,
        )
    )
    _activity(
        session,
        problem,
        kind,
        actor_id,
        name,
        "transition",
        f"{STAGE_ZH.get(source, source)} → {STAGE_ZH.get(hop, hop)}。{comment}".strip(),
        f"{STAGE_EN.get(source, source)} → {STAGE_EN.get(hop, hop)}. {comment}".strip(),
    )
    kind_name = "blocked" if hop == "blocked" else "stage"
    title = f"{problem.title}：{STAGE_ZH.get(hop, hop)}"
    title_en = f"{problem.title}: {STAGE_EN.get(hop, hop)}"
    return _notify(session, problem, kind_name, title, title_en, comment or title, comment or title_en)


def transition(session: Session, user: User | None, problem: Problem, to_stage: str, comment: str = "", *, actor_kind: str = "user", actor_name: str | None = None, as_role: str | None = None) -> dict:
    if problem.deleted_at is not None:
        raise AxiomError("问题在回收站里。", "The problem is in the recycle bin.", status=409)
    if to_stage == "resume":
        to_stage = problem.resume_stage or "draft"
    if to_stage not in machine.STAGES:
        raise AxiomError("未知阶段。", "Unknown stage.")
    role = as_role or (_role(session, user, problem) if user is not None else "owner")
    resume = problem.resume_stage or None
    try:
        hops = machine.walk(problem.stage, to_stage, resume)
    except ValueError as exc:
        raise AxiomError(
            f"不能从{STAGE_ZH.get(problem.stage, problem.stage)}进入{STAGE_ZH.get(to_stage, to_stage)}。",
            f"Cannot move from {STAGE_EN.get(problem.stage, problem.stage)} to {STAGE_EN.get(to_stage, to_stage)}.",
        ) from exc
    if not hops:
        _refresh(session, problem)
        return {"notice": None}
    cursor = problem.stage
    current_resume = resume
    for hop in hops:
        if not machine.legal(cursor, hop, current_resume):
            raise AxiomError(
                f"不能从{STAGE_ZH.get(cursor, cursor)}进入{STAGE_ZH.get(hop, hop)}。",
                f"Cannot move from {STAGE_EN.get(cursor, cursor)} to {STAGE_EN.get(hop, hop)}.",
            )
        if not machine.allowed(role, cursor, hop, current_resume):
            raise AxiomError("当前角色不能做这个状态变更。", "Your role cannot make this transition.", status=403)
        if hop in {"on_hold", "blocked"} and cursor not in {"on_hold", "blocked"}:
            current_resume = cursor
        elif cursor in {"on_hold", "blocked"}:
            current_resume = None
        cursor = hop
    notice = None
    for hop in hops:
        notice = _apply_hop(session, user, problem, hop, comment, actor_kind, actor_name)
    _refresh(session, problem)
    _audit(session, user, "problem.transition", problem, f"{to_stage}")
    return {"notice": notice}


def propose_transition(session: Session, user: User, problem: Problem, to_stage: str, comment: str, role: str, actor_name: str) -> dict:
    if _role(session, user, problem) == "viewer":
        raise AxiomError("只读成员不能提议状态变更。", "A viewer cannot propose a transition.", status=403)
    if role not in ROLES:
        role = "solver"
    if to_stage not in machine.STAGES:
        raise AxiomError("未知阶段。", "Unknown stage.")
    resume = problem.resume_stage or None
    if not machine.legal(problem.stage, to_stage, resume):
        raise AxiomError(
            f"不能从{STAGE_ZH.get(problem.stage, problem.stage)}进入{STAGE_ZH.get(to_stage, to_stage)}。",
            f"Cannot move from {STAGE_EN.get(problem.stage, problem.stage)} to {STAGE_EN.get(to_stage, to_stage)}.",
        )
    if not machine.allowed(role, problem.stage, to_stage, resume):
        raise AxiomError("这个智能体角色不能做该变更。", "That agent role cannot make this transition.", status=403)
    if problem.approval_required:
        row = TransitionRequest(
            problem_id=problem.id,
            from_stage=problem.stage,
            to_stage=to_stage,
            comment=(comment or "")[:2000],
            status="pending",
            actor_kind="agent",
            actor_name=(actor_name or "智能体")[:128],
            role=role,
        )
        session.add(row)
        session.flush()
        _activity(session, problem, "agent", user.id, row.actor_name, "propose", f"提议进入{STAGE_ZH.get(to_stage, to_stage)}，等待批准。", f"Proposed {STAGE_EN.get(to_stage, to_stage)} and is waiting for approval.")
        notice = _notify(session, problem, "stage", f"{problem.title} 待批准", f"{problem.title} needs approval", comment or row.actor_name, comment or row.actor_name)
        return {"applied": False, "request_id": row.id, "notice": notice}
    if not problem.auto_advance:
        _activity(session, problem, "agent", user.id, actor_name or "智能体", "note", "自动推进已关闭，未改变阶段。", "Auto-advance is off, so the stage stayed put.")
        return {"applied": False, "request_id": None, "notice": None}
    result = transition(session, user, problem, to_stage, comment, actor_kind="agent", actor_name=actor_name, as_role=role)
    result["applied"] = True
    result["request_id"] = None
    return result


def resolve_request(session: Session, user: User, problem: Problem, request_id: int, decision: str, comment: str = "") -> dict:
    row = session.get(TransitionRequest, request_id)
    if row is None or row.problem_id != problem.id:
        raise AxiomError("没有这条待批准的变更。", "That approval request was not found.", status=404)
    if row.status != "pending":
        raise AxiomError("这条变更已经处理过。", "That request was already resolved.", status=409)
    role = _role(session, user, problem)
    if role == "viewer":
        raise AxiomError("只读成员不能批准。", "A viewer cannot approve a transition.", status=403)
    if decision not in {"approved", "rejected"}:
        raise AxiomError("决定只能是批准或拒绝。", "Decision must be approved or rejected.")
    row.status = "approved" if decision == "approved" else "rejected"
    row.resolved_at = utcnow()
    if decision == "rejected":
        _activity(session, problem, "user", user.id, user.display_name, "reject-proposal", comment or "拒绝了阶段提议", comment or "Rejected the proposed transition")
        _refresh(session, problem)
        return {"applied": False, "notice": None}
    result = transition(session, user, problem, row.to_stage, comment or row.comment, actor_kind="user", actor_name=user.display_name)
    result["applied"] = True
    return result


def _requirement_public(row: Requirement) -> dict:
    return {"id": row.id, "text": row.text, "text_en": row.text_en, "done": bool(row.done), "source": row.source, "sort": row.sort, "created_at": _iso(row.created_at)}


def suggest_lines(text: str) -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    if any(token in text for token in ("最大", "最小", "maximize", "minimize", "利润", "成本")):
        lines.append(("目标方向与单位已写清，最优值可以复核。", "The objective direction and units are stated and the optimum can be checked."))
    if any(token in text for token in ("不超过", "不少于", "至少", "至多", "at most", "at least")):
        lines.append(("每条资源限制都有可核对的验收阈值。", "Every resource limit has a threshold that can be checked."))
    if any(token in text.lower() for token in ("整数", "integer", "binary", "0-1", "二进制")):
        lines.append(("整数或 0-1 变量已标明。", "Integer or binary variables are identified."))
    if not lines:
        lines.append(("问题陈述写明了目标、变量和约束。", "The statement names an objective, variables, and constraints."))
        lines.append(("给出可以复核的数值验收标准。", "Numeric acceptance criteria are available for review."))
    return lines


def _add_suggestions(session: Session, problem: Problem, text: str, actor_kind: str, actor_name: str) -> list[Requirement]:
    existing = {row.text for row in session.scalars(select(Requirement).where(Requirement.problem_id == problem.id))}
    sort = session.scalar(select(Requirement.sort).where(Requirement.problem_id == problem.id).order_by(Requirement.sort.desc())) or 0
    created = []
    for zh, en in suggest_lines(text or ""):
        if zh in existing:
            continue
        sort += 1
        row = Requirement(problem_id=problem.id, text=zh, text_en=en, done=0, source="ai", sort=sort)
        session.add(row)
        created.append(row)
    if created:
        _activity(session, problem, actor_kind, None, actor_name, "requirements", f"补充了 {len(created)} 条验收标准。", f"Added {len(created)} acceptance criteria.")
    return created


def add_requirement(session: Session, user: User, problem: Problem, text: str, text_en: str = "") -> Requirement:
    _require_area(session, user, problem, "requirements")
    sort = session.scalar(select(Requirement.sort).where(Requirement.problem_id == problem.id).order_by(Requirement.sort.desc())) or 0
    row = Requirement(problem_id=problem.id, text=text.strip()[:500], text_en=(text_en or "")[:500], done=0, source="human", sort=sort + 1)
    session.add(row)
    _activity(session, problem, "user", user.id, user.display_name, "requirements", "新增验收标准", "Added an acceptance criterion")
    _refresh(session, problem)
    return row


def patch_requirement(session: Session, user: User, problem: Problem, requirement_id: int, fields: dict) -> Requirement:
    _require_area(session, user, problem, "requirements")
    row = session.get(Requirement, requirement_id)
    if row is None or row.problem_id != problem.id:
        raise AxiomError("没有这条验收标准。", "That requirement was not found.", status=404)
    if fields.get("text"):
        row.text = str(fields["text"]).strip()[:500]
    if "text_en" in fields and fields["text_en"] is not None:
        row.text_en = str(fields["text_en"])[:500]
    if "done" in fields and fields["done"] is not None:
        row.done = 1 if fields["done"] else 0
    _refresh(session, problem)
    return row


def delete_requirement(session: Session, user: User, problem: Problem, requirement_id: int) -> None:
    _require_area(session, user, problem, "requirements")
    row = session.get(Requirement, requirement_id)
    if row is None or row.problem_id != problem.id:
        raise AxiomError("没有这条验收标准。", "That requirement was not found.", status=404)
    session.delete(row)


def _schema_from_csv(content: str) -> list[dict]:
    line = ""
    for candidate in content.splitlines():
        if candidate.strip():
            line = candidate
            break
    if not line or "," not in line:
        return []
    return [{"name": cell.strip()[:80], "type": "string"} for cell in line.split(",") if cell.strip()]


def add_data(session: Session, user: User, problem: Problem, *, name: str, filename: str, content: str, note: str, parent_id: int | None) -> DataAsset:
    _require_area(session, user, problem, "data")
    version = 1
    if parent_id is not None:
        parent = session.get(DataAsset, parent_id)
        if parent is None or parent.problem_id != problem.id:
            raise AxiomError("找不到上一版数据。", "The parent data asset was not found.", status=404)
        version = parent.version + 1
    row = DataAsset(
        problem_id=problem.id,
        name=(name or filename or "data").strip()[:160],
        filename=(filename or "")[:240],
        schema_json=_dumps(_schema_from_csv(content or "")),
        content=(content or "")[:_CONTENT_CAP],
        version=version,
        parent_id=parent_id,
        note=(note or "")[:500],
        created_by=user.id,
    )
    session.add(row)
    session.flush()
    _activity(session, problem, "user", user.id, user.display_name, "data", f"数据 {row.name} v{row.version}", f"Data {row.name} v{row.version}")
    _refresh(session, problem)
    return row


def _next_semver(rows: list[ModelRevision]) -> str:
    best = (0, 1, -1)
    found = False
    for row in rows:
        match = _SEMVER.match(row.semver or "")
        if not match:
            continue
        found = True
        triple = tuple(int(part) for part in match.groups())
        if triple > best:
            best = triple
    if not found:
        return "0.1.0"
    return f"{best[0]}.{best[1]}.{best[2] + 1}"


def _capture_equations(aml: str) -> tuple[dict, str, dict]:
    from axiom.modeling.parser import parse_aml
    from axiom.modeling.standard import standard_form
    from axiom.modeling.translators.registry import translate

    try:
        model = parse_aml(aml)
        form = standard_form(model)
    except Exception:
        return {}, "", {}
    stored = {
        "ok": True,
        "kind": form.get("kind"),
        "sense": form.get("sense"),
        "matrix_latex": form.get("matrix_latex") or "",
        "latex": form.get("latex") or "",
        "equations": [
            {
                "role": item.get("role"),
                "name": item.get("name") or item.get("key") or item.get("id"),
                "plain": item.get("plain"),
                "latex": item.get("latex"),
            }
            for item in (form.get("equations") or [])
        ],
    }
    exports = {}
    for target in ("lp", "pyomo", "ampl"):
        try:
            exports[target] = translate(model, target).code[:100_000]
        except Exception:
            continue
    return stored, stored.get("latex") or "", exports


def add_model(session: Session, user: User | None, problem: Problem, *, aml: str, label: str = "", note: str = "", semver: str = "", statement: str = "", actor_kind: str = "user", actor_name: str | None = None) -> ModelRevision:
    if user is not None and actor_kind == "user":
        _require_area(session, user, problem, "models")
    rows = list(session.scalars(select(ModelRevision).where(ModelRevision.problem_id == problem.id)))
    version = semver.strip() if semver else ""
    if version:
        if _SEMVER.match(version) is None:
            raise AxiomError("版本号应为 x.y.z。", "Version must look like x.y.z.")
        if any(row.semver == version for row in rows):
            raise AxiomError("这个版本号已经用过。", "That version is already used.", status=409)
    else:
        version = _next_semver(rows)
    equations, latex, exports = _capture_equations(aml or "")
    kind, actor_id, name = _actor(user, actor_kind, actor_name or "建模智能体")
    row = ModelRevision(
        problem_id=problem.id,
        project_id=problem.project_id,
        semver=version,
        label=(label or version)[:160],
        aml=aml or "",
        statement=statement or problem.description or "",
        equations_json=_dumps(equations),
        latex=latex,
        exports_json=_dumps(exports),
        baseline=0,
        note=(note or "")[:500],
        created_by=None if user is None else user.id,
    )
    session.add(row)
    session.flush()
    if problem.project_id and (aml or "").strip():
        project = session.get(Project, problem.project_id)
        if project is not None:
            project.dsl = aml
            project.updated_at = utcnow()
    _activity(session, problem, kind, actor_id, name, "model", f"模型 {row.semver} {row.label}", f"Model {row.semver} {row.label}")
    _refresh(session, problem)
    return row


def diff_models(session: Session, problem: Problem, left_id: int, right_id: int) -> dict:
    left = session.get(ModelRevision, left_id)
    right = session.get(ModelRevision, right_id)
    if left is None or right is None or left.problem_id != problem.id or right.problem_id != problem.id:
        raise AxiomError("找不到要对比的模型版本。", "One of the model versions was not found.", status=404)
    text = "".join(
        difflib.unified_diff(
            (left.aml or "").splitlines(keepends=True),
            (right.aml or "").splitlines(keepends=True),
            fromfile=f"{left.semver} {left.label}",
            tofile=f"{right.semver} {right.label}",
        )
    )
    return {"left": _model_public(left), "right": _model_public(right), "diff": text}


def promote_baseline(session: Session, user: User, problem: Problem, model_id: int) -> ModelRevision:
    _require_area(session, user, problem, "models")
    row = session.get(ModelRevision, model_id)
    if row is None or row.problem_id != problem.id:
        raise AxiomError("找不到这个模型版本。", "That model version was not found.", status=404)
    for other in session.scalars(select(ModelRevision).where(ModelRevision.problem_id == problem.id)):
        other.baseline = 1 if other.id == row.id else 0
    problem.baseline_model_id = row.id
    _activity(session, problem, "user", user.id, user.display_name, "baseline", f"基线定为 {row.semver}", f"Baseline set to {row.semver}")
    _audit(session, user, "problem.baseline", problem, row.semver)
    _refresh(session, problem)
    return row


def _sense_of(aml: str, equations: dict) -> str:
    sense = str(equations.get("sense") or "")
    if sense in {"maximize", "minimize"}:
        return sense
    if re.search(r"(?m)^\s*maximize\b", aml or "", re.I):
        return "maximize"
    return "minimize"


def _model_for_aml(session: Session, user: User | None, problem: Problem, aml: str) -> ModelRevision | None:
    text = (aml or "").strip()
    if not text:
        return None
    for row in session.scalars(select(ModelRevision).where(ModelRevision.problem_id == problem.id).order_by(ModelRevision.id.desc())):
        if (row.aml or "").strip() == text:
            return row
    return add_model(session, user, problem, aml=aml, label="求解快照", note="求解前自动固定", actor_kind="agent", actor_name="建模智能体")


def record_solve(
    session: Session,
    user: User | None,
    problem: Problem,
    payload: dict,
    *,
    aml: str = "",
    note: str = "",
    seed: int | None = None,
    run_id: int | None = None,
    model_revision_id: int | None = None,
    data_asset_id: int | None = None,
    algorithm: str = "",
    actor_kind: str = "agent",
    actor_name: str = "求解顾问",
) -> SolveRecord:
    revision = session.get(ModelRevision, model_revision_id) if model_revision_id else None
    if revision is not None and revision.problem_id != problem.id:
        revision = None
    if revision is None and aml.strip():
        revision = _model_for_aml(session, user, problem, aml)
    equations = _loads(revision.equations_json, {}) if revision is not None else {}
    objective = payload.get("objective")
    try:
        objective = None if objective is None or objective == "" else float(objective)
    except (TypeError, ValueError):
        objective = None
    kind, actor_id, name = _actor(user, actor_kind, actor_name)
    row = SolveRecord(
        problem_id=problem.id,
        project_id=problem.project_id,
        run_id=run_id,
        model_revision_id=None if revision is None else revision.id,
        data_asset_id=data_asset_id,
        solver=str(payload.get("solver") or "")[:64],
        algorithm=(algorithm or str(payload.get("solver") or ""))[:64],
        parameters_json=_dumps({"seed": seed} if seed is not None else {}),
        seed=seed,
        wall_ms=int(float(payload.get("runtime_sec") or 0) * 1000),
        status=str(payload.get("status") or "error")[:32],
        sense=_sense_of(aml, equations),
        objective=objective,
        solution_json=_dumps(payload.get("variables") or {}),
        duals_json=_dumps(payload.get("duals") or {}),
        iis_json=_dumps(payload.get("iis") or {}),
        log=str(payload.get("message") or payload.get("message_en") or "")[:8000],
        note=(note or "")[:500],
        created_by=None if user is None else user.id,
    )
    session.add(row)
    session.flush()
    _activity(
        session,
        problem,
        kind,
        actor_id,
        name,
        "solve",
        f"{row.solver} {row.status} 目标 {'' if row.objective is None else f'{row.objective:.6g}'}",
        f"{row.solver} {row.status} objective {'' if row.objective is None else f'{row.objective:.6g}'}",
    )
    _notify(
        session,
        problem,
        "solve",
        f"{problem.title} 求解完成",
        f"{problem.title} solve finished",
        f"{row.solver} · {row.status}",
        f"{row.solver} · {row.status}",
    )
    _refresh(session, problem)
    return row


def solve_now(session: Session, user: User, problem: Problem, solver: str, *, aml: str = "", seed: int | None = None, note: str = "", model_revision_id: int | None = None, data_asset_id: int | None = None) -> SolveRecord:
    _require_area(session, user, problem, "runs")
    source = aml.strip()
    if not source and model_revision_id:
        revision = session.get(ModelRevision, model_revision_id)
        if revision is not None and revision.problem_id == problem.id:
            source = revision.aml
    if not source:
        source = _aml_for(session, problem)
    if not source.strip():
        raise AxiomError("没有可求解的模型。", "There is no model to solve.")
    from axiom.lifecycle.solve import solve_aml

    payload = solve_aml(source, solver, seed)
    return record_solve(
        session,
        user,
        problem,
        payload,
        aml=source,
        note=note,
        seed=seed,
        model_revision_id=model_revision_id,
        data_asset_id=data_asset_id,
        actor_kind="agent",
        actor_name="求解顾问",
    )


def compare_solves(session: Session, problem: Problem, left_id: int, right_id: int) -> dict:
    left = session.get(SolveRecord, left_id)
    right = session.get(SolveRecord, right_id)
    if left is None or right is None or left.problem_id != problem.id or right.problem_id != problem.id:
        raise AxiomError("找不到要对比的求解。", "One of the solves was not found.", status=404)
    left_vars = _loads(left.solution_json, {})
    right_vars = _loads(right.solution_json, {})
    keys = sorted(set(left_vars) | set(right_vars))
    delta = {}
    for key in keys:
        try:
            delta[key] = float(left_vars.get(key, 0)) - float(right_vars.get(key, 0))
        except (TypeError, ValueError):
            delta[key] = None
    objective_delta = None
    if left.objective is not None and right.objective is not None:
        objective_delta = float(left.objective) - float(right.objective)
    return {"left": _solve_public(left), "right": _solve_public(right), "objective_delta": objective_delta, "solution_delta": delta}


def _aml_for(session: Session, problem: Problem) -> str:
    revision = session.scalar(select(ModelRevision).where(ModelRevision.problem_id == problem.id, ModelRevision.baseline == 1).order_by(ModelRevision.id.desc()))
    if revision is None:
        revision = session.scalar(select(ModelRevision).where(ModelRevision.problem_id == problem.id).order_by(ModelRevision.id.desc()))
    if revision is not None and (revision.aml or "").strip():
        return revision.aml
    if problem.project_id:
        project = session.get(Project, problem.project_id)
        if project is not None and (project.dsl or "").strip():
            return project.dsl
    from axiom.nl.formulate import formulate

    formulated = formulate(problem.description or problem.title or "")
    return formulated.aml or ""


def run_analysis(session: Session, user: User, problem: Problem, kind: str, options: dict | None, model_revision_id: int | None) -> AnalysisLink:
    _require_area(session, user, problem, "analyses")
    aml = ""
    if model_revision_id:
        revision = session.get(ModelRevision, model_revision_id)
        if revision is None or revision.problem_id != problem.id:
            raise AxiomError("找不到这个模型版本。", "That model version was not found.", status=404)
        aml = revision.aml
    if not aml.strip():
        aml = _aml_for(session, problem)
    if not aml.strip():
        raise AxiomError("没有可分析的模型。", "There is no model to analyze.")
    from axiom.analysis.studio import run_study

    try:
        result = run_study(kind, aml, options or {})
        status = "completed"
        note = ""
    except AxiomError as exc:
        result = {"message": exc.message, "message_en": exc.message_en}
        status = "error"
        note = exc.message
    text = _dumps(result)
    if len(text) > 120_000:
        brief = {key: result.get(key) for key in ("message", "message_en", "note", "summary_metrics", "objective", "kind") if isinstance(result, dict) and key in result}
        brief["truncated"] = True
        text = _dumps(brief)
    row = AnalysisLink(
        problem_id=problem.id,
        kind=(kind or "local")[:32],
        options_json=_dumps(options or {}),
        result_json=text,
        model_revision_id=model_revision_id,
        status=status,
        note=note[:500],
        created_by=user.id,
    )
    session.add(row)
    session.flush()
    _activity(session, problem, "agent", user.id, "求解顾问", "analysis", f"分析 {row.kind} · {status}", f"Analysis {row.kind} · {status}")
    _refresh(session, problem)
    return row


def add_decision(session: Session, user: User, problem: Problem, *, title: str, rationale: str, rationale_en: str, run_ids: list, chosen_run_id: int | None) -> Decision:
    _require_area(session, user, problem, "decisions")
    ids = [int(item) for item in (run_ids or []) if str(item).isdigit() or isinstance(item, int)]
    row = Decision(
        problem_id=problem.id,
        title=(title or "决策")[:200],
        rationale=rationale or "",
        rationale_en=rationale_en or "",
        run_ids_json=_dumps(ids),
        chosen_run_id=chosen_run_id,
        status="proposed",
        created_by=user.id,
    )
    session.add(row)
    session.flush()
    _activity(session, problem, "user", user.id, user.display_name, "decision", f"提出决策：{row.title}", f"Proposed decision: {row.title}")
    _refresh(session, problem)
    return row


def write_memo(session: Session, user: User, problem: Problem) -> Decision:
    _require_area(session, user, problem, "decisions")
    rows = _solves(session, problem.id)
    best = _pick_best(rows)
    if best is None:
        rationale = "还没有可行求解。先完成求解，再选定方案。"
        rationale_en = "There is no feasible solve yet. Solve the model before choosing a design."
        chosen = None
        title = "暂缓决策"
    else:
        others = [row for row in rows if row.id != best.id and row.objective is not None]
        rationale = (
            f"建议采用 {best.solver} 的结果作为推荐设计，目标值 {best.objective:.6g}，"
            f"状态 {best.status}，耗时 {best.wall_ms} ms。对照了 {len(others)} 个其他记录，按优化方向这是当前最好的可行解。"
        )
        rationale_en = (
            f"Recommend the {best.solver} result, objective {best.objective:.6g}, status {best.status}, "
            f"wall time {best.wall_ms} ms. Compared with {len(others)} other records, it is the best feasible point so far."
        )
        chosen = best.id
        title = f"推荐 {best.solver}"
    row = Decision(
        problem_id=problem.id,
        title=title,
        rationale=rationale,
        rationale_en=rationale_en,
        run_ids_json=_dumps([item.id for item in rows]),
        chosen_run_id=chosen,
        status="proposed",
        created_by=user.id,
    )
    session.add(row)
    session.flush()
    _activity(session, problem, "agent", user.id, "评审智能体", "decision", "写了决策备忘", "Wrote the decision memo")
    _refresh(session, problem)
    return row


def _pick_best(rows: list[SolveRecord]) -> SolveRecord | None:
    good = [row for row in rows if row.objective is not None and row.status in {"optimal", "feasible", "completed"}]
    if not good:
        return None
    sense = good[-1].sense or "minimize"
    pool = [row for row in good if (row.sense or sense) == sense]
    if not pool:
        pool = good
        sense = "minimize"
    if sense == "maximize":
        return max(pool, key=lambda row: float(row.objective or 0))
    return min(pool, key=lambda row: float(row.objective or 0))


def accept_decision(session: Session, user: User, problem: Problem, decision_id: int) -> Decision:
    _require_area(session, user, problem, "decisions")
    row = session.get(Decision, decision_id)
    if row is None or row.problem_id != problem.id:
        raise AxiomError("没有这条决策。", "That decision was not found.", status=404)
    for other in session.scalars(select(Decision).where(Decision.problem_id == problem.id, Decision.status == "accepted")):
        other.status = "superseded"
    row.status = "accepted"
    resume = problem.resume_stage or None
    try:
        if problem.stage != "decided":
            machine.walk(problem.stage, "decided", resume)
            transition(session, user, problem, "decided", row.rationale[:500], actor_kind="user")
    except (ValueError, AxiomError):
        _refresh(session, problem)
    _activity(session, problem, "user", user.id, user.display_name, "decide", f"采纳决策：{row.title}", f"Accepted decision: {row.title}")
    return row


def add_change(session: Session, user: User, problem: Problem, title: str, impact: str) -> ChangeRequest:
    role = _role(session, user, problem)
    if role not in {"modeler", "reviewer", "owner"}:
        raise AxiomError("当前角色不能提出变更。", "Your role cannot open a change request.", status=403)
    row = ChangeRequest(
        problem_id=problem.id,
        title=title.strip()[:200] or "变更",
        impact=impact or "",
        from_stage=problem.stage,
        status="open",
        created_by=user.id,
    )
    session.add(row)
    session.flush()
    _activity(session, problem, "user", user.id, user.display_name, "change", f"变更请求：{row.title}", f"Change request: {row.title}")
    _refresh(session, problem)
    return row


def resolve_change(session: Session, user: User, problem: Problem, change_id: int, decision: str) -> ChangeRequest:
    role = _role(session, user, problem)
    if role not in {"modeler", "reviewer", "owner"}:
        raise AxiomError("当前角色不能处理变更。", "Your role cannot resolve a change request.", status=403)
    row = session.get(ChangeRequest, change_id)
    if row is None or row.problem_id != problem.id:
        raise AxiomError("没有这条变更。", "That change request was not found.", status=404)
    if decision == "rejected":
        row.status = "rejected"
        _activity(session, problem, "user", user.id, user.display_name, "change", "拒绝了变更请求", "Rejected the change request")
        return row
    row.status = "accepted"
    resume = problem.resume_stage or None
    if machine.legal(problem.stage, "reopened", resume) and machine.allowed(role, problem.stage, "reopened", resume):
        transition(session, user, problem, "reopened", row.impact[:500])
    try:
        if problem.stage != "modeling":
            hops = machine.walk(problem.stage, "modeling", problem.resume_stage or None)
            if hops:
                transition(session, user, problem, "modeling", row.impact[:500])
    except (ValueError, AxiomError):
        pass
    _activity(session, problem, "user", user.id, user.display_name, "change", f"接受变更并回到建模：{row.impact[:120]}", f"Accepted the change and returned to modeling: {row.impact[:120]}")
    _refresh(session, problem)
    return row


def _font_pdf(problem: Problem, session: Session) -> bytes:
    from axiom.reports.build import pdf_report

    rows = _solves(session, problem.id)
    best = _pick_best(rows)
    return pdf_report(
        {
            "title": problem.title,
            "status": problem.stage,
            "solver": "" if best is None else best.solver,
            "objective": None if best is None else best.objective,
            "summary": problem.ai_summary,
            "variables": {} if best is None else _loads(best.solution_json, {}),
            "standard_form": {"plain": problem.description},
        },
        "zh-CN",
    )


def _svg(rows: list[SolveRecord]) -> str:
    values = [(row.solver or str(row.id), float(row.objective)) for row in rows if row.objective is not None][:12]
    if not values:
        values = [("—", 0.0)]
    peak = max(abs(value) for _, value in values) or 1.0
    width = 48 * len(values) + 24
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="140" viewBox="0 0 {width} 140">']
    parts.append('<rect width="100%" height="100%" fill="#101410"/>')
    for index, (label, value) in enumerate(values):
        height = abs(value) / peak * 80
        x = 16 + index * 48
        y = 100 - height
        parts.append(f'<rect x="{x}" y="{y:.1f}" width="28" height="{height:.1f}" fill="#7dcea0"/>')
        parts.append(f'<text x="{x}" y="118" fill="#d5e8da" font-size="9">{label[:8]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _png(rows: list[SolveRecord]) -> bytes:
    import matplotlib

    matplotlib.use("Agg", force=False)
    import io

    import matplotlib.pyplot as plt

    labels = [row.solver or str(row.id) for row in rows if row.objective is not None][:12] or ["—"]
    values = [float(row.objective) for row in rows if row.objective is not None][:12] or [0.0]
    figure, axis = plt.subplots(figsize=(4.2, 2.4), dpi=120)
    axis.bar(labels, values, color="#3d6b4f")
    axis.set_title("Objective")
    axis.tick_params(labelsize=8)
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    plt.close(figure)
    return buffer.getvalue()


def make_artifact(session: Session, user: User, problem: Problem, kind: str) -> Artifact:
    _require_area(session, user, problem, "artifacts")
    kind = (kind or "latex").lower()
    if kind not in {"pdf", "png", "svg", "latex"}:
        raise AxiomError("产物类型应为 pdf、png、svg 或 latex。", "Artifact kind must be pdf, png, svg, or latex.")
    rows = _solves(session, problem.id)
    revision = None
    if problem.baseline_model_id:
        revision = session.get(ModelRevision, problem.baseline_model_id)
    if revision is None:
        revision = session.scalar(select(ModelRevision).where(ModelRevision.problem_id == problem.id).order_by(ModelRevision.id.desc()))
    if kind == "pdf":
        blob = _font_pdf(problem, session)
        content = base64.b64encode(blob).decode("ascii")
        media = "application/pdf"
        name = f"{problem.title}-报告.pdf"
    elif kind == "svg":
        content = _svg(rows)
        media = "image/svg+xml"
        name = f"{problem.title}-目标.svg"
    elif kind == "png":
        blob = _png(rows)
        content = base64.b64encode(blob).decode("ascii")
        media = "image/png"
        name = f"{problem.title}-目标.png"
    else:
        body = revision.latex if revision is not None and revision.latex else (revision.aml if revision is not None else problem.description)
        content = "\\[\n" + (body or "") + "\n\\]\n"
        media = "text/x-latex"
        name = f"{problem.title}.tex"
    if len(content) > _ARTIFACT_CAP:
        raise AxiomError("产物超过 2MB，未保存。", "The artifact is over 2MB and was not stored.")
    row = Artifact(problem_id=problem.id, kind=kind, name=name[:200], media=media, content=content, created_by=user.id)
    session.add(row)
    session.flush()
    _activity(session, problem, "agent", user.id, "报告智能体", "artifact", f"生成{kind}：{row.name}", f"Generated {kind}: {row.name}")
    _refresh(session, problem)
    return row


def _model_public(row: ModelRevision, with_body: bool = True) -> dict:
    payload = {
        "id": row.id,
        "semver": row.semver,
        "label": row.label,
        "baseline": bool(row.baseline),
        "note": row.note,
        "statement": row.statement,
        "created_at": _iso(row.created_at),
    }
    if with_body:
        payload["aml"] = row.aml
        payload["equations"] = _loads(row.equations_json, {})
        payload["latex"] = row.latex
        payload["exports"] = _loads(row.exports_json, {})
    return payload


def _solve_public(row: SolveRecord) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "model_revision_id": row.model_revision_id,
        "data_asset_id": row.data_asset_id,
        "solver": row.solver,
        "algorithm": row.algorithm,
        "parameters": _loads(row.parameters_json, {}),
        "seed": row.seed,
        "wall_ms": row.wall_ms,
        "status": row.status,
        "sense": row.sense,
        "objective": row.objective,
        "solution": _loads(row.solution_json, {}),
        "duals": _loads(row.duals_json, {}),
        "iis": _loads(row.iis_json, {}),
        "log": row.log,
        "note": row.note,
        "created_at": _iso(row.created_at),
    }


def _data_public(row: DataAsset) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "filename": row.filename,
        "schema": _loads(row.schema_json, []),
        "content": row.content,
        "version": row.version,
        "parent_id": row.parent_id,
        "note": row.note,
        "created_at": _iso(row.created_at),
    }


def detail(session: Session, user: User, problem: Problem) -> dict:
    payload = card(session, user, problem)
    payload["requirements"] = [_requirement_public(row) for row in session.scalars(select(Requirement).where(Requirement.problem_id == problem.id).order_by(Requirement.sort, Requirement.id))]
    payload["members"] = []
    for member in session.scalars(select(ProblemMember).where(ProblemMember.problem_id == problem.id)):
        person = session.get(User, member.user_id)
        payload["members"].append({"user_id": member.user_id, "username": "" if person is None else person.username, "display_name": "" if person is None else person.display_name, "role": member.role})
    payload["transitions"] = [
        {
            "id": row.id,
            "from_stage": row.from_stage,
            "to_stage": row.to_stage,
            "comment": row.comment,
            "actor_kind": row.actor_kind,
            "actor_id": row.actor_id,
            "actor_name": row.actor_name,
            "created_at": _iso(row.created_at),
        }
        for row in session.scalars(select(ProblemTransition).where(ProblemTransition.problem_id == problem.id).order_by(ProblemTransition.id))
    ]
    payload["requests"] = [
        {
            "id": row.id,
            "from_stage": row.from_stage,
            "to_stage": row.to_stage,
            "comment": row.comment,
            "status": row.status,
            "actor_name": row.actor_name,
            "role": row.role,
            "created_at": _iso(row.created_at),
        }
        for row in session.scalars(select(TransitionRequest).where(TransitionRequest.problem_id == problem.id).order_by(TransitionRequest.id.desc()))
        if row.status == "pending"
    ]
    payload["data"] = [
        _data_public(row)
        for row in session.scalars(select(DataAsset).where(DataAsset.problem_id == problem.id, DataAsset.deleted_at.is_(None)).order_by(DataAsset.id))
    ]
    payload["models"] = [_model_public(row) for row in session.scalars(select(ModelRevision).where(ModelRevision.problem_id == problem.id).order_by(ModelRevision.id))]
    payload["runs"] = [_solve_public(row) for row in _solves(session, problem.id)]
    payload["analyses"] = []
    for row in session.scalars(select(AnalysisLink).where(AnalysisLink.problem_id == problem.id).order_by(AnalysisLink.id.desc())):
        payload["analyses"].append(
            {
                "id": row.id,
                "kind": row.kind,
                "options": _loads(row.options_json, {}),
                "result": _loads(row.result_json, {}),
                "status": row.status,
                "note": row.note,
                "model_revision_id": row.model_revision_id,
                "created_at": _iso(row.created_at),
            }
        )
    payload["decisions"] = [
        {
            "id": row.id,
            "title": row.title,
            "rationale": row.rationale,
            "rationale_en": row.rationale_en,
            "run_ids": _loads(row.run_ids_json, []),
            "chosen_run_id": row.chosen_run_id,
            "status": row.status,
            "created_at": _iso(row.created_at),
        }
        for row in session.scalars(select(Decision).where(Decision.problem_id == problem.id).order_by(Decision.id.desc()))
    ]
    payload["changes"] = [
        {"id": row.id, "title": row.title, "impact": row.impact, "from_stage": row.from_stage, "status": row.status, "created_at": _iso(row.created_at)}
        for row in session.scalars(select(ChangeRequest).where(ChangeRequest.problem_id == problem.id).order_by(ChangeRequest.id.desc()))
    ]
    payload["artifacts"] = []
    for row in session.scalars(select(Artifact).where(Artifact.problem_id == problem.id).order_by(Artifact.id.desc())):
        item = {"id": row.id, "kind": row.kind, "name": row.name, "media": row.media, "created_at": _iso(row.created_at), "bytes": len(row.content or "")}
        if row.kind in {"latex", "svg"}:
            item["content"] = row.content
        payload["artifacts"].append(item)
    payload["activities"] = [
        {
            "id": row.id,
            "actor_kind": row.actor_kind,
            "actor_name": row.actor_name,
            "action": row.action,
            "detail": row.detail,
            "detail_en": row.detail_en,
            "created_at": _iso(row.created_at),
        }
        for row in session.scalars(select(Activity).where(Activity.problem_id == problem.id).order_by(Activity.id.desc()).limit(200))
    ]
    return payload


def search(session: Session, user: User, q: str) -> dict:
    needle = q.strip()
    if not needle:
        return {"problems": [], "models": [], "runs": []}
    ids = workspace_ids(session, user)
    if not ids:
        return {"problems": [], "models": [], "runs": []}
    like = f"%{needle}%"
    problems = []
    for problem in session.scalars(select(Problem).where(Problem.workspace_id.in_(ids), Problem.deleted_at.is_(None), (Problem.title.like(like)) | (Problem.description.like(like))).limit(40)):
        problems.append({"id": problem.id, "title": problem.title, "stage": problem.stage, "snippet": (problem.description or "")[:180]})
    models = []
    for row in session.scalars(select(ModelRevision).where(ModelRevision.aml.like(like)).limit(40)):
        problem = session.get(Problem, row.problem_id)
        if problem is None or problem.deleted_at is not None or problem.workspace_id not in ids:
            continue
        models.append({"problem_id": problem.id, "id": row.id, "semver": row.semver, "title": problem.title, "snippet": _snippet(row.aml, needle)})
    runs = []
    for row in session.scalars(select(SolveRecord).where((SolveRecord.note.like(like)) | (SolveRecord.log.like(like))).limit(40)):
        problem = session.get(Problem, row.problem_id)
        if problem is None or problem.deleted_at is not None or problem.workspace_id not in ids:
            continue
        runs.append({"problem_id": problem.id, "id": row.id, "solver": row.solver, "title": problem.title, "snippet": _snippet(row.note or row.log, needle)})
    return {"problems": problems, "models": models, "runs": runs}


def _snippet(text: str, needle: str) -> str:
    hay = text or ""
    index = hay.lower().find(needle.lower())
    if index < 0:
        return hay[:180]
    start = max(0, index - 40)
    return hay[start : start + 180]


def save_view(session: Session, user: User, name: str, filters: dict, workspace_id: int | None) -> SavedView:
    row = SavedView(user_id=user.id, workspace_id=workspace_id, name=name.strip()[:120] or "未命名视图", filters_json=_dumps(filters or {}))
    session.add(row)
    session.flush()
    return row


def views_for(session: Session, user: User) -> list[dict]:
    return [
        {"id": row.id, "name": row.name, "filters": _loads(row.filters_json, {}), "workspace_id": row.workspace_id, "created_at": _iso(row.created_at)}
        for row in session.scalars(select(SavedView).where(SavedView.user_id == user.id).order_by(SavedView.id.desc()))
    ]


def delete_view(session: Session, user: User, view_id: int) -> None:
    row = session.get(SavedView, view_id)
    if row is None or row.user_id != user.id:
        raise AxiomError("没有这个视图。", "That view was not found.", status=404)
    session.delete(row)


def notices_for(session: Session, user: User) -> list[dict]:
    rows = session.scalars(select(ProblemNotice).where(ProblemNotice.user_id == user.id, ProblemNotice.read == 0).order_by(ProblemNotice.id.desc()).limit(30))
    return [
        {"id": row.id, "problem_id": row.problem_id, "kind": row.kind, "title": row.title, "title_en": row.title_en, "body": row.body, "body_en": row.body_en, "created_at": _iso(row.created_at)}
        for row in rows
    ]


def mark_notices(session: Session, user: User, ids: list[int]) -> None:
    for row in session.scalars(select(ProblemNotice).where(ProblemNotice.user_id == user.id, ProblemNotice.id.in_(ids or [0]))):
        row.read = 1


def set_member(session: Session, user: User, problem: Problem, username: str, role: str) -> None:
    _require_area(session, user, problem, "members")
    if role not in ROLES:
        raise AxiomError("角色应为 viewer、modeler、solver、reviewer 或 owner。", "Role must be viewer, modeler, solver, reviewer, or owner.")
    person = session.scalar(select(User).where(User.username == username.strip()))
    if person is None:
        raise AxiomError("没有这个用户。", "No user with that username.", status=404)
    if person.id != user.id and user.role != "admin":
        member = session.scalar(select(Membership).where(Membership.workspace_id == problem.workspace_id, Membership.user_id == person.id))
        if member is None:
            raise AxiomError("对方不在这个工作区。", "That person is not in this workspace.", status=403)
    row = session.scalar(select(ProblemMember).where(ProblemMember.problem_id == problem.id, ProblemMember.user_id == person.id))
    if row is None:
        session.add(ProblemMember(problem_id=problem.id, user_id=person.id, role=role))
    else:
        row.role = role
    if role == "owner":
        problem.owner_id = person.id
    _activity(session, problem, "user", user.id, user.display_name, "member", f"{person.username} → {role}", f"{person.username} → {role}")
    _audit(session, user, "problem.member", problem, f"{person.username}:{role}")


def soft_delete(session: Session, user: User, problem: Problem) -> None:
    _require_area(session, user, problem, "delete")
    problem.deleted_at = utcnow()
    _activity(session, problem, "user", user.id, user.display_name, "delete", "移入回收站", "Moved to the recycle bin")
    _audit(session, user, "problem.delete", problem, problem.title)
    _refresh(session, problem)


def restore(session: Session, user: User, problem: Problem) -> None:
    _require_area(session, user, problem, "delete")
    problem.deleted_at = None
    _activity(session, problem, "user", user.id, user.display_name, "restore", "从回收站恢复", "Restored from the recycle bin")
    _refresh(session, problem)


def purge(session: Session, user: User, problem: Problem) -> None:
    _require_area(session, user, problem, "delete")
    if problem.deleted_at is None:
        raise AxiomError("请先移入回收站，再永久删除。", "Move the problem to the recycle bin before deleting it permanently.", status=409)
    pid = problem.id
    for model in (
        ProblemNotice,
        Activity,
        Artifact,
        ChangeRequest,
        Decision,
        AnalysisLink,
        SolveRecord,
        ModelRevision,
        DataAsset,
        Requirement,
        TransitionRequest,
        ProblemTransition,
        ProblemMember,
    ):
        for row in session.scalars(select(model).where(model.problem_id == pid)):
            session.delete(row)
    _audit(session, user, "problem.purge", problem, problem.title)
    session.delete(problem)


def export_package(session: Session, user: User, problem: Problem) -> dict:
    body = detail(session, user, problem)
    data_rows = list(session.scalars(select(DataAsset).where(DataAsset.problem_id == problem.id, DataAsset.deleted_at.is_(None)).order_by(DataAsset.id)))
    index = {row.id: position for position, row in enumerate(data_rows)}
    semver = {row.id: row.semver for row in session.scalars(select(ModelRevision).where(ModelRevision.problem_id == problem.id))}
    data_name = {row.id: row.name for row in data_rows}
    artifacts = []
    for row in session.scalars(select(Artifact).where(Artifact.problem_id == problem.id)):
        content = row.content or ""
        omitted = len(content) > 1_500_000
        artifacts.append({"kind": row.kind, "name": row.name, "media": row.media, "content": "" if omitted else content, "omitted": omitted})
    package = {
        "format": "axiom-problem-1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "problem": {
            "title": problem.title,
            "description": problem.description,
            "tags": body["tags"],
            "priority": problem.priority,
            "due_at": body["due_at"],
            "custom_fields": body["custom_fields"],
            "stage": problem.stage,
            "ai_summary": problem.ai_summary,
            "ai_summary_en": problem.ai_summary_en,
        },
        "requirements": [{"text": item["text"], "text_en": item["text_en"], "done": item["done"], "source": item["source"], "sort": item["sort"]} for item in body["requirements"]],
        "models": [
            {
                "semver": item["semver"],
                "label": item["label"],
                "aml": item["aml"],
                "statement": item["statement"],
                "equations": item["equations"],
                "latex": item["latex"],
                "exports": item["exports"],
                "baseline": item["baseline"],
                "note": item["note"],
            }
            for item in body["models"]
        ],
        "data": [
            {
                "name": row.name,
                "filename": row.filename,
                "schema": _loads(row.schema_json, []),
                "content": row.content,
                "version": row.version,
                "parent_index": None if row.parent_id is None else index.get(row.parent_id),
                "note": row.note,
            }
            for row in data_rows
        ],
        "runs": [
            {
                "solver": row.solver,
                "algorithm": row.algorithm,
                "parameters": _loads(row.parameters_json, {}),
                "seed": row.seed,
                "wall_ms": row.wall_ms,
                "status": row.status,
                "sense": row.sense,
                "objective": row.objective,
                "solution": _loads(row.solution_json, {}),
                "duals": _loads(row.duals_json, {}),
                "iis": _loads(row.iis_json, {}),
                "log": row.log,
                "note": row.note,
                "model_semver": semver.get(row.model_revision_id or 0, ""),
                "data_name": data_name.get(row.data_asset_id or 0, ""),
            }
            for row in _solves(session, problem.id)
        ],
        "analyses": body["analyses"],
        "decisions": body["decisions"],
        "changes": body["changes"],
        "activities": list(reversed(body["activities"])),
        "artifacts": artifacts,
        "best_objective": body["best_objective"],
    }
    _audit(session, user, "problem.share", problem, problem.title)
    _activity(session, problem, "user", user.id, user.display_name, "share", "导出问题包", "Exported the share package")
    return package


def import_package(session: Session, user: User, payload: dict, workspace_id: int | None) -> Problem:
    if not isinstance(payload, dict) or payload.get("format") != "axiom-problem-1":
        raise AxiomError("不是公理问题包（axiom-problem-1）。", "This is not an Axiom problem package (axiom-problem-1).")
    raw = payload.get("problem") or {}
    if not isinstance(raw, dict):
        raise AxiomError("问题包缺少 problem。", "The package has no problem.")
    ids = workspace_ids(session, user)
    workspace_id = workspace_id or (ids[0] if ids else None)
    if workspace_id is None or (user.role != "admin" and workspace_id not in ids):
        raise AxiomError("先创建一个工作区。", "Create a workspace first.", status=400 if workspace_id is None else 403)
    title = str(raw.get("title") or "导入的问题")[:200]
    description = str(raw.get("description") or "")
    models = payload.get("models") if isinstance(payload.get("models"), list) else []
    dsl = ""
    for item in models:
        if isinstance(item, dict) and item.get("baseline") and item.get("aml"):
            dsl = str(item["aml"])
            break
    if not dsl and models and isinstance(models[0], dict):
        dsl = str(models[0].get("aml") or "")
    project = Project(
        workspace_id=workspace_id,
        title=title,
        statement=description,
        dsl=dsl,
        locale="zh-CN",
        status="draft",
        created_by=user.id,
        updated_at=utcnow(),
    )
    session.add(project)
    session.flush()
    stage = str(raw.get("stage") or "draft")
    if stage not in machine.STAGES:
        stage = "draft"
    problem = Problem(
        project_id=project.id,
        workspace_id=workspace_id,
        title=title,
        description=description,
        tags_json=_dumps(_tags(raw.get("tags") or [])),
        priority=raw.get("priority") if raw.get("priority") in PRIORITIES else "normal",
        owner_id=user.id,
        due_at=_due(raw.get("due_at")),
        custom_json=_dumps(_custom(raw.get("custom_fields") or {})),
        stage="draft",
        auto_advance=1,
        approval_required=1,
        ai_summary=str(raw.get("ai_summary") or ""),
        ai_summary_en=str(raw.get("ai_summary_en") or ""),
        created_by=user.id,
    )
    session.add(problem)
    session.flush()
    session.add(ProblemMember(problem_id=problem.id, user_id=user.id, role="owner"))
    for item in payload.get("requirements") or []:
        if not isinstance(item, dict):
            continue
        session.add(Requirement(problem_id=problem.id, text=str(item.get("text") or "")[:500], text_en=str(item.get("text_en") or "")[:500], done=1 if item.get("done") else 0, source=str(item.get("source") or "human")[:16], sort=int(item.get("sort") or 0)))
    data_ids: list[int] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        parent_index = item.get("parent_index")
        parent_id = data_ids[parent_index] if isinstance(parent_index, int) and 0 <= parent_index < len(data_ids) else None
        row = DataAsset(
            problem_id=problem.id,
            name=str(item.get("name") or "data")[:160],
            filename=str(item.get("filename") or "")[:240],
            schema_json=_dumps(item.get("schema") or []),
            content=str(item.get("content") or "")[:_CONTENT_CAP],
            version=int(item.get("version") or 1),
            parent_id=parent_id,
            note=str(item.get("note") or "")[:500],
            created_by=user.id,
        )
        session.add(row)
        session.flush()
        data_ids.append(row.id)
    semver_id: dict[str, int] = {}
    for item in models:
        if not isinstance(item, dict):
            continue
        version = str(item.get("semver") or _next_semver([]))
        if _SEMVER.match(version) is None:
            version = _next_semver(list(session.scalars(select(ModelRevision).where(ModelRevision.problem_id == problem.id))))
        row = ModelRevision(
            problem_id=problem.id,
            project_id=project.id,
            semver=version,
            label=str(item.get("label") or version)[:160],
            aml=str(item.get("aml") or ""),
            statement=str(item.get("statement") or ""),
            equations_json=_dumps(item.get("equations") or {}),
            latex=str(item.get("latex") or ""),
            exports_json=_dumps(item.get("exports") or {}),
            baseline=1 if item.get("baseline") else 0,
            note=str(item.get("note") or "")[:500],
            created_by=user.id,
        )
        session.add(row)
        session.flush()
        semver_id[version] = row.id
        if row.baseline:
            problem.baseline_model_id = row.id
    name_id = {}
    for position, item in enumerate(payload.get("data") or []):
        if isinstance(item, dict) and position < len(data_ids):
            name_id[str(item.get("name") or "")] = data_ids[position]
    for item in payload.get("runs") or []:
        if not isinstance(item, dict):
            continue
        objective = item.get("objective")
        try:
            objective = None if objective is None else float(objective)
        except (TypeError, ValueError):
            objective = None
        session.add(
            SolveRecord(
                problem_id=problem.id,
                project_id=project.id,
                model_revision_id=semver_id.get(str(item.get("model_semver") or "")),
                data_asset_id=name_id.get(str(item.get("data_name") or "")),
                solver=str(item.get("solver") or "")[:64],
                algorithm=str(item.get("algorithm") or "")[:64],
                parameters_json=_dumps(item.get("parameters") or {}),
                seed=item.get("seed") if isinstance(item.get("seed"), int) else None,
                wall_ms=int(item.get("wall_ms") or 0),
                status=str(item.get("status") or "")[:32],
                sense=str(item.get("sense") or "")[:16],
                objective=objective,
                solution_json=_dumps(item.get("solution") or {}),
                duals_json=_dumps(item.get("duals") or {}),
                iis_json=_dumps(item.get("iis") or {}),
                log=str(item.get("log") or "")[:8000],
                note=str(item.get("note") or "")[:500],
                created_by=user.id,
            )
        )
    for item in payload.get("analyses") or []:
        if not isinstance(item, dict):
            continue
        session.add(
            AnalysisLink(
                problem_id=problem.id,
                kind=str(item.get("kind") or "")[:32],
                options_json=_dumps(item.get("options") or {}),
                result_json=_dumps(item.get("result") or {}),
                status=str(item.get("status") or "completed")[:32],
                note=str(item.get("note") or "")[:500],
                created_by=user.id,
            )
        )
    for item in payload.get("decisions") or []:
        if not isinstance(item, dict):
            continue
        session.add(
            Decision(
                problem_id=problem.id,
                title=str(item.get("title") or "")[:200],
                rationale=str(item.get("rationale") or ""),
                rationale_en=str(item.get("rationale_en") or ""),
                run_ids_json=_dumps(item.get("run_ids") or []),
                status=str(item.get("status") or "proposed")[:16],
                created_by=user.id,
            )
        )
    for item in payload.get("changes") or []:
        if not isinstance(item, dict):
            continue
        session.add(ChangeRequest(problem_id=problem.id, title=str(item.get("title") or "")[:200], impact=str(item.get("impact") or ""), from_stage=str(item.get("from_stage") or "")[:32], status=str(item.get("status") or "open")[:16], created_by=user.id))
    for item in payload.get("artifacts") or []:
        if not isinstance(item, dict) or item.get("omitted"):
            continue
        content = str(item.get("content") or "")
        if len(content) > _ARTIFACT_CAP:
            continue
        session.add(Artifact(problem_id=problem.id, kind=str(item.get("kind") or "latex")[:16], name=str(item.get("name") or "artifact")[:200], media=str(item.get("media") or "")[:64], content=content, created_by=user.id))
    for item in payload.get("activities") or []:
        if not isinstance(item, dict):
            continue
        session.add(Activity(problem_id=problem.id, actor_kind=str(item.get("actor_kind") or "user")[:16], actor_name=str(item.get("actor_name") or "")[:128], action=str(item.get("action") or "import")[:64], detail=str(item.get("detail") or "")[:2000], detail_en=str(item.get("detail_en") or "")[:2000]))
    _activity(session, problem, "user", user.id, user.display_name, "import", "导入问题包", "Imported a share package")
    if stage != "draft":
        try:
            transition(session, user, problem, stage, "导入时恢复阶段", actor_kind="user")
        except AxiomError:
            problem.stage = "draft"
    _refresh(session, problem)
    _audit(session, user, "problem.import", problem, problem.title)
    return problem


def templates() -> list[dict]:
    from axiom.templates.library import TEMPLATES

    rows = []
    for item in TEMPLATES:
        rows.append(
            {
                "id": item["id"],
                "title_zh": item["title_zh"],
                "title_en": item["title_en"],
                "summary_zh": item["summary_zh"],
                "summary_en": item["summary_en"],
                "category": item["category"],
                "tag": _TEMPLATE_TAGS.get(item["id"], item["category"]),
            }
        )
    return rows


def from_template(session: Session, user: User, template_id: str, workspace_id: int | None) -> Problem:
    from axiom.templates.library import TEMPLATES

    item = next((row for row in TEMPLATES if row["id"] == template_id), None)
    if item is None:
        raise AxiomError("没有这个行业模板。", "That industry template was not found.", status=404)
    tag = _TEMPLATE_TAGS.get(item["id"], item["category"])
    problem = create_problem(
        session,
        user,
        title=item["title_zh"],
        description=item["summary_zh"],
        tags=[tag],
        workspace_id=workspace_id,
        dsl=item.get("dsl") or "",
        custom_fields={"template": item["id"], "template_en": item["title_en"]},
    )
    transition(session, user, problem, "intake", f"由行业模板「{item['title_zh']}」生成", actor_kind="agent", actor_name="规划智能体", as_role="owner")
    return problem


def enrich_summary(session: Session, user: User, problem: Problem) -> Problem:
    _refresh(session, problem)
    try:
        from axiom.llm.store import complete_text, provider_name_for

        if provider_name_for("reporter") != "mock":
            text = complete_text("reporter", [{"role": "user", "content": "用两句中文概括这个优化问题的状态，不要编造数字：\n" + problem.ai_summary}])
            if text and text.strip():
                problem.ai_summary = text.strip()[:500]
                _activity(session, problem, "agent", user.id, "报告智能体", "summary", "重写了问题概述", "Rewrote the problem summary")
    except Exception:
        pass
    return problem


def apply_command(session: Session, user: User, command: dict, project_id: int | None) -> dict:
    action = command.get("action")
    text = str(command.get("text") or "")
    if action == "create":
        if project_id and not command.get("fresh"):
            problem = create_problem(session, user, title=text[:40] or "未命名问题", description=text, project_id=project_id, fill_existing=True)
        else:
            problem = create_problem(session, user, title=_title_from(text), description=text)
        return _command_result(problem, f"已建立问题「{problem.title}」，并写了验收建议。\nOpened “{problem.title}” and drafted acceptance criteria.")
    problem = _command_problem(session, user, project_id, text)
    if action == "hold":
        transition(session, user, problem, "on_hold", text)
    elif action == "archive":
        transition(session, user, problem, "archived", text)
    elif action == "reopen":
        transition(session, user, problem, "reopened", text)
    elif action == "baseline":
        revision = session.scalar(select(ModelRevision).where(ModelRevision.problem_id == problem.id).order_by(ModelRevision.id.desc()))
        if revision is None:
            aml = _aml_for(session, problem)
            if not aml.strip():
                raise AxiomError("还没有模型可以设为基线。", "There is no model to pin as the baseline.")
            revision = add_model(session, user, problem, aml=aml, label="基线", note=text, actor_kind="agent", actor_name="建模智能体")
        promote_baseline(session, user, problem, revision.id)
    elif action == "accept":
        for row in session.scalars(select(Requirement).where(Requirement.problem_id == problem.id)):
            row.done = 1
        _activity(session, problem, "user", user.id, user.display_name, "accept", "验收标准已勾选", "Acceptance criteria checked")
        target = "decided" if problem.stage == "review" else "review"
        try:
            if problem.stage != target:
                transition(session, user, problem, target, text)
        except AxiomError:
            _refresh(session, problem)
    elif action == "advance":
        target = command.get("stage") or machine.next_main(problem.stage) or problem.stage
        if target != problem.stage:
            transition(session, user, problem, target, text)
        solvers = list(command.get("solvers") or [])
        if solvers:
            aml = _aml_for(session, problem)
            if not aml.strip():
                raise AxiomError("没有可求解的模型。", "There is no model to solve.")
            lines = []
            for name in solvers:
                record = solve_now(session, user, problem, name, aml=aml, note=text)
                value = "—" if record.objective is None else f"{record.objective:.6g}"
                lines.append(f"{record.solver} {record.status} {value}")
            summary = "；".join(lines)
            _refresh(session, problem)
            return _command_result(problem, f"已推进到{STAGE_ZH.get(problem.stage, problem.stage)}，并记录求解：{summary}。\nAdvanced to {STAGE_EN.get(problem.stage, problem.stage)} and recorded: {summary}.")
    else:
        raise AxiomError("无法执行这条生命周期指令。", "That lifecycle command could not be applied.")
    _refresh(session, problem)
    return _command_result(problem, f"问题「{problem.title}」现在是{STAGE_ZH.get(problem.stage, problem.stage)}。\n“{problem.title}” is now {STAGE_EN.get(problem.stage, problem.stage)}.")


def _title_from(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else "未命名问题"
    for token in ("新建问题", "记成问题", "建成问题", "建立问题", "new problem"):
        line = line.replace(token, "")
    line = line.strip(" ：:，,")
    return (line or "未命名问题")[:40]


def _command_problem(session: Session, user: User, project_id: int | None, text: str) -> Problem:
    if project_id is not None:
        project = session.get(Project, int(project_id))
        if project is None:
            raise AxiomError("项目不存在。", "Project not found.", status=404)
        if user.role != "admin" and project.workspace_id not in workspace_ids(session, user):
            raise AxiomError("你不在这个工作区。", "You are not in this workspace.", status=403)
        return ensure_problem(session, project, user)
    ids = workspace_ids(session, user)
    row = session.scalar(select(Problem).where(Problem.workspace_id.in_(ids or [0]), Problem.deleted_at.is_(None)).order_by(Problem.updated_at.desc()))
    if row is not None:
        return row
    return create_problem(session, user, title=_title_from(text), description=text)


def _command_result(problem: Problem, content: str) -> dict:
    return {"content": content, "lifecycle": {"problem_id": problem.id, "project_id": problem.project_id, "stage": problem.stage, "title": problem.title}}


def attach_completed_run(run_id: int) -> None:
    """Record a finished studio run on its problem. Failures stay in the caller."""
    from axiom.db.session import open_session

    session = open_session()
    try:
        run = session.get(Run, run_id)
        if run is None or run.status not in {"completed", "failed"}:
            return
        if session.scalar(select(SolveRecord).where(SolveRecord.run_id == run.id)) is not None:
            return
        project = session.get(Project, run.project_id)
        if project is None:
            return
        user = session.get(User, run.created_by)
        problem = ensure_problem(session, project, user)
        try:
            payload = json.loads(run.result_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("solver", run.solver)
        payload.setdefault("status", run.status)
        if payload.get("objective") in (None, "") and run.objective:
            try:
                payload["objective"] = float(run.objective)
            except ValueError:
                payload["objective"] = None
        payload.setdefault("variables", payload.get("variables") or {})
        if run.error and not payload.get("message"):
            payload["message"] = run.error
        diagnosis = payload.get("diagnosis") if isinstance(payload.get("diagnosis"), dict) else {}
        if diagnosis:
            payload["iis"] = diagnosis
        record_solve(
            session,
            user,
            problem,
            payload,
            aml=run.dsl or project.dsl or "",
            note="",
            run_id=run.id,
            algorithm=str(payload.get("algorithm") or run.solver or ""),
            actor_kind="agent",
            actor_name="求解顾问",
        )
        if user is not None and problem.auto_advance and problem.stage == "solving" and run.status == "completed":
            try:
                propose_transition(session, user, problem, "analyzing", "求解已完成，提议进入分析。", "solver", "求解顾问")
            except AxiomError:
                pass
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
