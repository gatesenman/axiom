"""Lifecycle state machine, versions, share packages, and natural-language commands."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from axiom.lifecycle import machine
from axiom.lifecycle.nl import interpret
from tests.support import login

AML = """
model ProductMix;
var xA >= 0;
var xB >= 0;
maximize profit: 40 * xA + 30 * xB;
subject to labor: 2 * xA + 3 * xB <= 120;
subject to material: 3 * xA + xB <= 90;
"""

AML_NEXT = AML.replace("40 * xA", "42 * xA")

PRODUCT = (
    "一家工厂生产产品A和产品B。产品A单位利润40元，产品B单位利润30元。"
    "生产一件A需要2小时机器时间和3公斤原料，生产一件B需要3小时机器时间和1公斤原料。"
    "每周机器时间不超过120小时，原料不超过90公斤。请制定利润最大的生产计划。"
)


def test_machine_rejects_illegal_and_accepts_a_main_line_walk():
    assert machine.legal("draft", "intake")
    assert not machine.legal("draft", "decided")
    assert machine.walk("draft", "solving") == ["intake", "modeling", "equations", "solving"]
    with pytest.raises(ValueError):
        machine.walk("archived", "decided")
    with pytest.raises(ValueError):
        machine.walk("on_hold", "solving", resume="modeling")
    assert machine.legal("on_hold", "modeling", resume="modeling")
    assert machine.legal("closed", "reopened")
    assert not machine.legal("closed", "archived")
    assert not machine.allowed("viewer", "draft", "intake")
    assert machine.allowed("modeler", "equations", "solving")
    assert machine.allowed("solver", "solving", "analyzing")
    assert not machine.allowed("modeler", "decided", "archived")
    assert machine.allowed("owner", "decided", "archived")
    assert machine.allowed("reviewer", "review", "rejected")
    assert not machine.allowed("solver", "modeling", "rejected")


def test_product_statement_is_not_a_lifecycle_command():
    assert interpret(PRODUCT) is None
    parsed = interpret("把这个问题推进到求解并跑 HiGHS 和 SCIP 对比")
    assert parsed is not None
    assert parsed["action"] == "advance"
    assert parsed["stage"] == "solving"
    assert parsed["solvers"] == ["highs", "scip"]
    assert interpret("对比一下结果") is None


def _problem(client: TestClient, headers: dict, **body) -> dict:
    response = client.post("/api/problems", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_legal_walk_records_actor_and_illegal_hold_jump_is_rejected(client: TestClient):
    headers = login(client)
    created = _problem(client, headers, title="走步", description="先看状态机")
    moved = client.post(f"/api/problems/{created['id']}/transition", json={"to_stage": "solving", "comment": "一次走到求解"}, headers=headers)
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["stage"] == "solving"
    assert [row["to_stage"] for row in body["transitions"]] == ["intake", "modeling", "equations", "solving"]
    assert all(row["actor_name"] and row["created_at"] and row["actor_kind"] == "user" for row in body["transitions"])
    held = client.post(f"/api/problems/{created['id']}/transition", json={"to_stage": "on_hold", "comment": "等数据"}, headers=headers)
    assert held.status_code == 200, held.text
    assert held.json()["stage"] == "on_hold"
    assert held.json()["resume_stage"] == "solving"
    illegal = client.post(f"/api/problems/{created['id']}/transition", json={"to_stage": "review"}, headers=headers)
    assert illegal.status_code == 400, illegal.text
    current = client.get(f"/api/problems/{created['id']}", headers=headers)
    assert current.json()["stage"] == "on_hold"


def test_viewer_cannot_transition_and_only_owner_purges(client: TestClient):
    headers = login(client)
    created = _problem(client, headers, title="权限", description="只读不能改阶段")
    viewer = client.post("/api/users", json={"username": "viewer1", "password": "secret1", "display_name": "只读", "role": "member"}, headers=headers)
    assert viewer.status_code == 200, viewer.text
    viewer_headers = login(client, "viewer1", "secret1")
    denied = client.post(f"/api/problems/{created['id']}/transition", json={"to_stage": "intake"}, headers=viewer_headers)
    assert denied.status_code == 403, denied.text
    lead = client.post("/api/users", json={"username": "lead1", "password": "secret1", "display_name": "负责人", "role": "member"}, headers=headers)
    assert lead.status_code == 200, lead.text
    assigned = client.post(f"/api/problems/{created['id']}/members", json={"username": "lead1", "role": "owner"}, headers=headers)
    assert assigned.status_code == 200, assigned.text
    lead_headers = login(client, "lead1", "secret1")
    stepped = client.post(f"/api/problems/{created['id']}/transition", json={"to_stage": "intake", "comment": "负责人受理"}, headers=lead_headers)
    assert stepped.status_code == 200, stepped.text
    assert stepped.json()["stage"] == "intake"
    removed = client.delete(f"/api/problems/{created['id']}", headers=lead_headers)
    assert removed.status_code == 200, removed.text
    listed = client.get("/api/problems", headers=headers)
    assert all(item["id"] != created["id"] for item in listed.json())
    recycle = client.get("/api/problems?deleted=1", headers=headers)
    assert any(item["id"] == created["id"] for item in recycle.json())
    blocked = client.delete(f"/api/problems/{created['id']}/purge", headers=viewer_headers)
    assert blocked.status_code == 403, blocked.text
    purged = client.delete(f"/api/problems/{created['id']}/purge", headers=lead_headers)
    assert purged.status_code == 200, purged.text
    missing = client.get(f"/api/problems/{created['id']}", headers=headers)
    assert missing.status_code == 404


def test_semver_diff_and_single_baseline(client: TestClient):
    headers = login(client)
    created = _problem(client, headers, title="版本", description="两版模型")
    first = client.post(f"/api/problems/{created['id']}/models", json={"aml": AML, "label": "初版"}, headers=headers)
    assert first.status_code == 200, first.text
    second = client.post(f"/api/problems/{created['id']}/models", json={"aml": AML_NEXT, "label": "改利润"}, headers=headers)
    assert second.status_code == 200, second.text
    models = second.json()["models"]
    assert [item["semver"] for item in models] == ["0.1.0", "0.1.1"]
    diff = client.get(f"/api/problems/{created['id']}/models/diff", params={"left": models[0]["id"], "right": models[1]["id"]}, headers=headers)
    assert diff.status_code == 200, diff.text
    text = diff.json()["diff"]
    assert "40 * xA" in text and "42 * xA" in text
    pinned = client.post(f"/api/problems/{created['id']}/models/{models[1]['id']}/baseline", headers=headers)
    assert pinned.status_code == 200, pinned.text
    body = pinned.json()
    assert body["baseline_model_id"] == models[1]["id"]
    assert [item["baseline"] for item in body["models"]] == [False, True]
    assert "matrix_latex" in body["models"][0]["equations"] or body["models"][0]["latex"]


def test_share_package_round_trip(client: TestClient):
    headers = login(client)
    created = _problem(client, headers, title="分享", description=PRODUCT, dsl=AML)
    solved = client.post(f"/api/problems/{created['id']}/runs", json={"solver": "highs", "note": "基线求解"}, headers=headers)
    assert solved.status_code == 200, solved.text
    assert solved.json()["runs"][-1]["status"] in {"optimal", "feasible"}
    objective = solved.json()["best_objective"]
    assert objective == pytest.approx(11400 / 7, rel=1e-4)
    package = client.get(f"/api/problems/{created['id']}/package", headers=headers)
    assert package.status_code == 200, package.text
    payload = package.json()
    assert payload["format"] == "axiom-problem-1"
    imported = client.post("/api/problems/import", json={"package": payload}, headers=headers)
    assert imported.status_code == 200, imported.text
    body = imported.json()
    assert body["id"] != created["id"]
    assert body["project_id"]
    assert any(item["aml"].strip() == AML.strip() for item in body["models"])
    assert body["best_objective"] == pytest.approx(objective, rel=1e-6)
    assert body["runs"][0]["solver"] == "highs"


def test_mock_chat_still_formulates_product_mix(client: TestClient):
    headers = login(client)
    reply = client.post("/api/chat", json={"messages": [{"role": "user", "content": PRODUCT}]}, headers=headers)
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["provider"] == "mock"
    assert "x_A" in body["content"]


def test_nl_advances_and_compares_highs_with_scip(client: TestClient):
    headers = login(client)
    project = client.post("/api/projects", json={"title": "对比", "statement": PRODUCT, "dsl": AML}, headers=headers)
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]
    reply = client.post(
        "/api/chat",
        json={"project_id": project_id, "messages": [{"role": "user", "content": "把这个问题推进到求解并跑 HiGHS 和 SCIP 对比"}]},
        headers=headers,
    )
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["provider"] == "lifecycle"
    assert body["lifecycle"]["stage"] == "solving"
    detail = client.get(f"/api/problems/{body['lifecycle']['problem_id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    runs = detail.json()["runs"]
    assert [row["solver"] for row in runs] == ["highs", "scip"]
    highs = runs[0]
    assert highs["status"] in {"optimal", "feasible"}
    assert highs["objective"] == pytest.approx(11400 / 7, rel=1e-4)
    assert "actor_name" in detail.json()["activities"][0]


def test_agent_proposal_waits_until_a_human_approves(client: TestClient):
    headers = login(client)
    created = _problem(client, headers, title="门禁", description="智能体提议，人来批准")
    solving = client.post(f"/api/problems/{created['id']}/transition", json={"to_stage": "solving"}, headers=headers)
    assert solving.status_code == 200, solving.text
    proposed = client.post(
        f"/api/problems/{created['id']}/proposals",
        json={"to_stage": "analyzing", "comment": "求解结束", "role": "solver", "actor_name": "求解顾问"},
        headers=headers,
    )
    assert proposed.status_code == 200, proposed.text
    assert proposed.json()["stage"] == "solving"
    assert proposed.json()["applied"] is False
    request_id = proposed.json()["requests"][0]["id"]
    approved = client.post(f"/api/problems/{created['id']}/requests/{request_id}", json={"decision": "approved", "comment": "可以分析"}, headers=headers)
    assert approved.status_code == 200, approved.text
    assert approved.json()["stage"] == "analyzing"
