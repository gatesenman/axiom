"""Legal transitions for an optimization problem.

Main line, one step at a time:

    draft → intake → modeling → equations → solving
         → analyzing → review → decided → archived → closed

Side doors are on_hold, blocked, rejected, and reopened. A held or blocked
problem returns to the stage it left. Role names are viewer, modeler, solver,
reviewer, and owner. Admin is treated as owner by the service.
"""

from __future__ import annotations

MAIN: tuple[str, ...] = (
    "draft",
    "intake",
    "modeling",
    "equations",
    "solving",
    "analyzing",
    "review",
    "decided",
    "archived",
    "closed",
)
SIDE: tuple[str, ...] = ("on_hold", "blocked", "rejected", "reopened")
STAGES: tuple[str, ...] = MAIN + SIDE

_OWNED: dict[str, set[str]] = {
    "viewer": set(),
    "modeler": {"draft", "intake", "modeling", "equations", "reopened"},
    "solver": {"solving"},
    "reviewer": {"analyzing", "review", "decided", "rejected"},
    "owner": set(STAGES),
    "admin": set(STAGES),
}


def neighbors(stage: str) -> set[str]:
    """Stages reachable in one hop, not counting a held problem's resume target."""
    if stage in MAIN:
        index = MAIN.index(stage)
        out: set[str] = set()
        if index > 0 and stage not in {"archived", "closed"}:
            out.add(MAIN[index - 1])
        if index + 1 < len(MAIN) and stage != "closed":
            out.add(MAIN[index + 1])
        if stage not in {"archived", "closed"}:
            out.update({"on_hold", "blocked", "rejected"})
        if stage in {"decided", "archived", "rejected"}:
            out.add("reopened")
        if stage == "closed":
            return {"reopened"}
        if stage == "archived":
            return {"closed", "reopened"}
        if stage == "decided":
            return {"review", "archived", "reopened", "on_hold", "blocked", "rejected"}
        return out
    if stage in {"on_hold", "blocked"}:
        return {"rejected", "reopened"}
    if stage == "rejected":
        return {"reopened", "closed", "archived"}
    if stage == "reopened":
        return {"modeling", "intake", "draft", "equations", "on_hold", "blocked"}
    return set()


def legal(source: str, target: str, resume: str | None = None) -> bool:
    if source == target or source not in STAGES or target not in STAGES:
        return False
    if source in {"on_hold", "blocked"} and target == (resume or "draft"):
        return True
    return target in neighbors(source)


def allowed(role: str, source: str, target: str, resume: str | None = None) -> bool:
    if not legal(source, target, resume):
        return False
    if role in {"owner", "admin"}:
        return True
    if target in {"archived", "closed"}:
        return False
    if target == "rejected":
        return role == "reviewer"
    owned = _OWNED.get(role, set())
    return source in owned or target in owned


def walk(source: str, target: str, resume: str | None = None) -> list[str]:
    """Stages to enter, in order, including the target.

    A main-line target is expanded only when every hop is itself legal, so
    archived cannot step backward to decided. A single side hop is returned
    as itself. Illegal pairs raise ValueError.
    """
    if source == target:
        return []
    if source in MAIN and target in MAIN:
        start, end = MAIN.index(source), MAIN.index(target)
        step = 1 if end > start else -1
        hops: list[str] = []
        cursor = source
        index = start
        while index != end:
            index += step
            hop = MAIN[index]
            if not legal(cursor, hop, resume):
                raise ValueError(f"{cursor} -> {hop}")
            hops.append(hop)
            cursor = hop
        return hops
    if legal(source, target, resume):
        return [target]
    raise ValueError(f"{source} -> {target}")


def next_main(stage: str) -> str | None:
    if stage not in MAIN:
        return None
    index = MAIN.index(stage)
    if index + 1 >= len(MAIN):
        return None
    return MAIN[index + 1]
