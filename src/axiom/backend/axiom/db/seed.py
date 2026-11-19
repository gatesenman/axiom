"""Idempotent demo workspace so a fresh install can be signed into immediately."""

from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from axiom.db.models import Membership, Project, Setting, User, Workspace, utcnow
from axiom.security import hash_password

DEMO_STATEMENT = (
    "一家工厂生产产品A和产品B。产品A单位利润40元，产品B单位利润30元。"
    "生产一件A需要2小时机器时间和3公斤原料，生产一件B需要3小时机器时间和1公斤原料。"
    "每周机器时间不超过120小时，原料不超过90公斤。请制定利润最大的生产计划。"
)


def seed(session: Session) -> User:
    user = session.scalar(select(User).where(User.username == "demo"))
    if user is None:
        user = User(
            username="demo",
            display_name="演示用户",
            password_hash=hash_password("demo1234"),
            role="admin",
            locale="zh-CN",
            theme="dark",
        )
        session.add(user)
        session.flush()
    workspace = session.scalar(select(Workspace).where(Workspace.owner_id == user.id))
    if workspace is None:
        workspace = Workspace(name="默认工作区", owner_id=user.id)
        session.add(workspace)
        session.flush()
        session.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
    defaults = {
        "llm.provider": "mock",
        "llm.base_url": "https://api.openai.com/v1",
        "llm.model": "gpt-4o-mini",
        "llm.api_key": "",
        "app.locale": "zh-CN",
    }
    for key, value in defaults.items():
        if session.get(Setting, key) is None:
            session.add(Setting(key=key, value=value))
    if os.environ.get("AXIOM_SKIP_EXAMPLE") != "1":
        existing = session.scalar(select(Project).where(Project.title == "产品组合示例"))
        if existing is None:
            project = Project(
                workspace_id=workspace.id,
                title="产品组合示例",
                statement=DEMO_STATEMENT,
                locale="zh-CN",
                status="draft",
                created_by=user.id,
                updated_at=utcnow(),
            )
            session.add(project)
            session.flush()
            from axiom.lifecycle.service import ensure_problem

            ensure_problem(session, project, user)
    session.commit()
    return user
