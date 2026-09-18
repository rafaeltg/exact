from __future__ import annotations

import re

# "study" alone is dropped: "case study" is a business phrase, not a signal.
ACADEMIC = re.compile(
    r"\b(studies|trial|trials|paper|papers|doi|pubmed|literature|evidence|"
    r"journal|arxiv|preprint|"
    r"meta-?analysis|systematic review|rct|clinical|peer-?reviewed)\b",
    re.I,
)


def academic_signal(query: str) -> bool:
    return bool(ACADEMIC.search(query or ""))
