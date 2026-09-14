from __future__ import annotations

import re

ACADEMIC = re.compile(
    r"\b(study|studies|trial|trials|paper|papers|doi|pubmed|"
    r"meta-?analysis|systematic review|rct|clinical|peer-?reviewed)\b",
    re.I,
)


def academic_signal(query: str) -> bool:
    return bool(ACADEMIC.search(query or ""))
