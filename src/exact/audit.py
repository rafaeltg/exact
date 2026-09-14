from __future__ import annotations

import re

CITE = re.compile(r"\[(src_[^\]]+)\]")


def audit_report(report: str, sources: list[dict]) -> tuple[str, list[str]]:
    ids = {s.get("id") for s in sources if s.get("id")}
    used = CITE.findall(report or "")
    dangling = sorted({cid for cid in used if cid not in ids})
    if not dangling:
        return report or "", []
    block = "\n\n## Audit\nDangling citations (no matching source): " + ", ".join(
        f"`[{d}]`" for d in dangling
    )
    return (report or "") + block, dangling
