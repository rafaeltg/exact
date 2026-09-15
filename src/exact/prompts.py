from __future__ import annotations

from collections.abc import Sequence

from exact.models import JsonMapping

DECIDE_CLARIFY = """You decide if the user query needs clarification before research.
You already have a SCOUT of web/paper hits. Prefer skipping if the query is specific enough.

Only ask if the query is ambiguous (audience, time range, which entity, web vs academic).
If you ask, the question MUST mention at least one scout title. Offer 2-4 angles drawn from hits.
If scout is empty, you may ask a generic narrowing question.

Query: {query}

Scout:
{scout}
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
Use 1 topic for a simple single-entity question.
Use 2-3 topics for comparisons, lists, or multi-entity questions.
Each topic is a search-oriented query string. Do not duplicate.
Shape each topic so the researcher picks the right Exa tool:
- People, roles, expertise, or named professionals → people query (role, skill, company, location).
- Organizations, funding, headcount, competitors, or company facts → company query.
- Recent events or press coverage → news-shaped web query (time and outlet cues in the string).
- Else general web. Do not invent parallel topics for every mode.

Brief:
{brief}
Prior topics (do not repeat): {prior}
Suggested follow-ups: {followups}
"""

RESEARCH_SYS = """You are a research sub-agent. Focus ONLY on this topic.
Use tools to search.
Prefer exa_people_search when the topic is about people, roles, or expertise.
Prefer exa_company_search when the topic is about companies, funding, or org facts.
Prefer exa_search for general web and news, then exa_highlights on the best URLs.
Use elicit_search only for academic/empirical questions when the tool is available.
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
If gaps remain and more research would help, set done=false and give 1-2 follow-up topic queries.
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
