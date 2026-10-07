"""Snapshot diffing — the heart of detection.

Comparing two snapshots of the same game yields three kinds of operations:

* ``removed``  — a goal present in the old snapshot is absent in the new one
                 (goal -> no-goal; changes the game total)
* ``added``    — a goal absent in the old snapshot is present in the new one
                 (no-goal -> goal; changes the game total)
* ``changed``  — the same goal persists but attribution/strength fields differ
                 (attribution-only correction)

Goals are aligned per (period, team) with an LCS on game clock (tolerance below),
so a clock tweak does not masquerade as a removed+added goal pair.
"""

from __future__ import annotations

from .livefeed import time_to_seconds

# Two goal events are "the same goal" if their period clocks are within this many
# seconds. Official clock corrections are small; a removed/added goal would shift
# the sequence much more than this.
CLOCK_TOLERANCE_SECONDS = 120

# Goal fields whose change constitutes an attribution correction.
ATTR_FIELDS = ("scorer", "assists", "strength", "empty_net")


def _matchable_clock(goal: dict) -> int | None:
    return time_to_seconds(goal.get("clock"))


def _same_goal(a: dict, b: dict) -> bool:
    ca, cb = _matchable_clock(a), _matchable_clock(b)
    if ca is None and cb is None:
        return True
    if ca is None or cb is None:
        return False
    return abs(ca - cb) <= CLOCK_TOLERANCE_SECONDS


def _lcs_ops(old: list[dict], new: list[dict]) -> list[tuple]:
    """Align one (period, team) group. Returns list of (op, old_goal, new_goal)."""
    n, m = len(old), len(new)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if _same_goal(old[i], new[j]):
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
    ops: list[tuple] = []
    i = j = 0
    while i < n and j < m:
        if _same_goal(old[i], new[j]):
            ops.append(("same", old[i], new[j]))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            ops.append(("removed", old[i], None))
            i += 1
        else:
            ops.append(("added", None, new[j]))
            j += 1
    while i < n:
        ops.append(("removed", old[i], None))
        i += 1
    while j < m:
        ops.append(("added", None, new[j]))
        j += 1
    return ops


def _group_key(goal: dict):
    return (goal.get("period"), (goal.get("team") or "").upper() if goal.get("team") else None)


def diff_goals(old_goals: list[dict], new_goals: list[dict]) -> list[dict]:
    """Diff two goal lists. Returns change dicts ready for record-building.

    Each change dict: {op: 'removed'|'added'|'changed', period, team, old, new,
    old_ordinal, new_ordinal, fields_changed (for 'changed')}
    """
    old_groups: dict = {}
    new_groups: dict = {}
    for idx, g in enumerate(old_goals):
        old_groups.setdefault(_group_key(g), []).append((idx, g))
    for idx, g in enumerate(new_goals):
        new_groups.setdefault(_group_key(g), []).append((idx, g))

    changes: list[dict] = []
    for key in sorted(set(old_groups) | set(new_groups), key=lambda k: (k[0] or 0, k[1] or "")):
        old_items = old_groups.get(key, [])
        new_items = new_groups.get(key, [])
        ops = _lcs_ops([g for _, g in old_items], [g for _, g in new_items])
        # Recompute ordinals within the (period, team) group.
        old_ord = {id(g): i + 1 for i, (_, g) in enumerate(old_items)}
        new_ord = {id(g): i + 1 for i, (_, g) in enumerate(new_items)}
        for op, old_g, new_g in ops:
            if op == "same":
                fields = field_changes(old_g, new_g)
                if fields:
                    changes.append({
                        "op": "changed",
                        "period": new_g.get("period"),
                        "team": new_g.get("team"),
                        "old": old_g,
                        "new": new_g,
                        "old_ordinal": old_ord.get(id(old_g)),
                        "new_ordinal": new_ord.get(id(new_g)),
                        "fields_changed": fields,
                    })
            elif op == "removed":
                changes.append({
                    "op": "removed",
                    "period": old_g.get("period"),
                    "team": old_g.get("team"),
                    "old": old_g,
                    "new": None,
                    "old_ordinal": old_ord.get(id(old_g)),
                    "new_ordinal": None,
                    "fields_changed": None,
                })
            else:  # added
                changes.append({
                    "op": "added",
                    "period": new_g.get("period"),
                    "team": new_g.get("team"),
                    "old": None,
                    "new": new_g,
                    "old_ordinal": None,
                    "new_ordinal": new_ord.get(id(new_g)),
                    "fields_changed": None,
                })
    return changes


def field_changes(old_g: dict, new_g: dict) -> dict:
    """Return {field: (old, new)} for attribution fields that differ."""
    changed = {}
    for field in ATTR_FIELDS:
        ov, nv = old_g.get(field), new_g.get(field)
        if field == "assists":
            ov, nv = list(ov or []), list(nv or [])
        if ov != nv:
            changed[field] = (ov, nv)
    return changed


def diff_report_hashes(old_snap: dict, new_snap: dict) -> list[dict]:
    """Detect silent edits of official PDF reports via hash changes."""
    changes = []
    old_hashes = old_snap.get("report_hashes") or {}
    new_hashes = new_snap.get("report_hashes") or {}
    for rtype, new_info in new_hashes.items():
        old_info = old_hashes.get(rtype) or {}
        if not new_info.get("ok") or not old_info.get("ok"):
            continue
        if new_info.get("sha256") and old_info.get("sha256") and \
                new_info["sha256"] != old_info["sha256"]:
            changes.append({"report": rtype, "url": new_info.get("url")})
    return changes
