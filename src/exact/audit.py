from __future__ import annotations

import re
from collections.abc import Sequence

from exact.models import JsonMapping

CITE = re.compile(r"\[(src_[^\]]+)\]")
# One bracket may group several ids: "[src_t0_1, src_t0_2]".
CITE_SEP = re.compile(r"[,;\s]+")


def cited_ids(report: str | None) -> list[str]:
    """Every ``src_…`` id cited in ``report``, including grouped brackets."""
    return [
        cid
        for group in CITE.findall(report or "")
        for cid in CITE_SEP.split(group)
        if cid
    ]


def audit_report(
    report: str | None, sources: Sequence[JsonMapping]
) -> tuple[str, list[str]]:
    """Validate ``[src_…]`` citations against retrieved source ids.

    When citations lack a matching ``id``, append an ``## Audit`` section and
    return the dangling ids. Does not invent or rewrite body text.
    """
    ids = {s.get("id") for s in sources if s.get("id")}
    used = cited_ids(report)
    dangling = sorted({cid for cid in used if cid not in ids})
    if not dangling:
        return report or "", []
    block = "\n\n## Audit\nDangling citations (no matching source): " + ", ".join(
        f"`[{d}]`" for d in dangling
    )
    return (report or "") + block, dangling
