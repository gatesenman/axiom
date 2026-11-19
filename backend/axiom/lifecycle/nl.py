"""Natural-language commands that drive a problem. Formulation text is ignored."""

from __future__ import annotations

import re

_SOLVERS = (
    ("cp-sat", "cp-sat"),
    ("cpsat", "cp-sat"),
    ("highs", "highs"),
    ("scip", "scip"),
    ("cbc", "cbc"),
    ("glpk", "glpk"),
    ("glop", "glop"),
    ("pdlp", "pdlp"),
    ("clp", "clp"),
)

_STAGE_WORDS = (
    ("归档", "archived"),
    ("关闭", "closed"),
    ("决策", "decided"),
    ("评审", "review"),
    ("分析", "analyzing"),
    ("求解", "solving"),
    ("方程", "equations"),
    ("建模", "modeling"),
    ("受理", "intake"),
    ("草稿", "draft"),
    ("archived", "archived"),
    ("closed", "closed"),
    ("decided", "decided"),
    ("review", "review"),
    ("analyzing", "analyzing"),
    ("solving", "solving"),
    ("equations", "equations"),
    ("modeling", "modeling"),
    ("intake", "intake"),
    ("draft", "draft"),
)


def mentioned_solvers(text: str) -> list[str]:
    lower = text.lower()
    found: list[str] = []
    for needle, name in _SOLVERS:
        if needle in lower and name not in found:
            found.append(name)
    return found


def _stage(text: str) -> str | None:
    lower = text.lower()
    for needle, name in _STAGE_WORDS:
        if needle in text or needle in lower:
            return name
    return None


def interpret(text: str) -> dict | None:
    """Return a command dict, or None when the text is an ordinary problem statement.

    Triggers are explicit lifecycle verbs. A comparison counts only when a solver
    name is present, so a sentence that merely says 对比 does not take over chat.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    lower = raw.lower()
    solvers = mentioned_solvers(raw)
    compare = bool(solvers) and ("对比" in raw or "compare" in lower)
    create = any(token in raw for token in ("新建问题", "记成问题", "建成问题", "建立问题")) or "new problem" in lower
    hold = "挂起" in raw or "on hold" in lower
    archive = "归档" in raw or re.search(r"\barchive\b", lower) is not None
    baseline = "基线" in raw or "baseline" in lower
    reopen = "重开" in raw or "reopen" in lower
    accept = "验收" in raw
    advance = "推进" in raw or "生命周期" in raw or re.search(r"\badvance\b", lower) is not None or compare
    if not any((compare, create, hold, archive, baseline, reopen, accept, advance)):
        return None
    stage = _stage(raw)
    if create and "推进" not in raw and not compare:
        return {"action": "create", "text": raw, "fresh": "新建" in raw or "new problem" in lower}
    if compare or (advance and solvers):
        return {"action": "advance", "stage": stage or "solving", "solvers": solvers, "text": raw}
    if hold and not advance:
        return {"action": "hold", "text": raw}
    if archive and not advance:
        return {"action": "archive", "text": raw}
    if baseline and not advance:
        return {"action": "baseline", "text": raw}
    if reopen and not advance:
        return {"action": "reopen", "text": raw}
    if accept and not advance:
        return {"action": "accept", "text": raw}
    if advance:
        return {"action": "advance", "stage": stage, "solvers": [], "text": raw}
    return None
