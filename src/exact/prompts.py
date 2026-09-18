from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from exact.models import JsonMapping

DECIDE_CLARIFY = """You decide if the user query needs clarification before research.
You already have a SCOUT of web/paper hits. Prefer skipping if the query is specific enough.

Only ask if the query is ambiguous (audience, time range, which entity, web vs academic).
If you ask, the question MUST mention at least one scout title. Offer 2-4 angles drawn from hits.
If scout is empty, you may ask a generic narrowing question.
Read the clarification chat below. If the user already answered, do NOT ask the same
question again: skip unless a new ambiguity remains that the answer did not settle.

Query: {query}

Scout:
{scout}

Clarification so far:
{chat}
"""

BRIEF = """Write a focused research brief. This is the north star for later research.
Compress the query, scout, and any clarification chat. Fill must_cover (1-5 items).
Set intent to academic if the query or user asked for papers/trials/evidence; mixed if both; else web.

Query: {query}
Scout:
{scout}
Clarification:
{chat}
"""

PLAN = """Split the brief into independent research sub-topics.
Each topic carries a search-oriented "query" and a "focus" lane.
Use 1 topic when one lane covers the brief.
Use 2-{first_cap} topics when the brief needs more than one lane, or compares entities.
Do not duplicate a query in the same lane.
Pick the focus that fits the question:
- people: roles, expertise, or named professionals. Shape the query with role, skill, company, location.
- company: organizations, funding, headcount, competitors, or org facts.
- publication: academic or empirical questions, papers, trials, evidence.
- web: everything else, including recent events and press coverage. Put time and outlet cues in the query.
One wave may mix lanes, for example a people topic beside a publication topic.
Do not invent a topic per lane when one lane covers the brief.
Every suggested follow-up below must appear as a topic, in its own wording, with a focus.
Order topics by importance: waves after the first keep the first {followup_cap} only.

Brief:
{brief}
Prior topics (do not repeat): {prior}
Suggested follow-ups: {followups}
"""

RESEARCH_SYS = """You are a research sub-agent. Focus ONLY on this topic.
This topic is on the {focus} lane. You hold the search tool for that lane and
exa_highlights. Use only the tools you are given; no other lane is yours.
Search first, then call exa_highlights on the best URLs you found.
Do not invent sources. After you have enough, stop calling tools.
Topic: {topic}
Brief must_cover: {must_cover}
Already seen titles (avoid repeating): {prior}
"""

PRUNE = """Extract structured findings from the tool results below.
Claims must be supported by the snippets. Use source ids exactly as given.
If a must_cover item is unsupported, put it in gaps, not claims.
Topic id: {topic_id}
Must cover: {must_cover}
Sources:
{sources}
Tool notes:
{notes}
"""

REFLECT = """Compare findings to the research brief.
If the brief is sufficiently covered, set done=true.
If gaps remain and more research would help, set done=false and give 1-{followup_cap} follow-up topic queries.
Do not repeat prior topics.

Brief:
{brief}
Findings:
{findings}
Prior topics: {prior}
"""

WRITE = """Write a cohesive Markdown research report.
Use the brief as the north star. Only cite source ids that exist, as [src_...].
Every non-obvious factual sentence should end with a citation.
End with ## Open questions listing the gaps.
Do not invent a bibliography; the runtime appends ## References from retrieved sources.

Brief:
{brief}
Findings:
{findings}
Known sources (cite these ids only):
{bib}
"""


def chat_block(messages: Sequence[Any] | None) -> str:
    """Format the clarify thread for the decide and brief prompts."""
    chat = [getattr(m, "content", None) or str(m) for m in messages or []]
    return "\n".join(chat) or "(none)"


def findings_block(findings: Sequence[JsonMapping] | None) -> str:
    """Format finding dicts for reflect/write prompts."""
    if not findings:
        return "(none)"
    parts = []
    for finding in findings:
        claims = "; ".join(finding.get("claims") or []) or "(none)"
        gaps = "; ".join(finding.get("gaps") or []) or "(none)"
        ids = ", ".join(finding.get("source_ids") or []) or "(none)"
        parts.append(
            f"topic={finding.get('topic_id')}\n"
            f"claims: {claims}\n"
            f"source_ids: {ids}\n"
            f"gaps: {gaps}"
        )
    return "\n\n".join(parts)
