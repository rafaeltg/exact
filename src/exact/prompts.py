from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from exact.models import JsonMapping

# The clarify bias sentence: ``clarify_mode=prefer`` asks, every other mode skips.
SKIP_BIAS = "Prefer skipping if the query is specific enough."
ASK_BIAS = "Prefer asking one grounded question if the query leaves an angle open."

PRIMARY_LINE = (
    "Prefer official and primary sources, such as regulators, original studies, "
    "filings and official statistics, over secondary roundups."
)
NEWS_LINE = (
    "Shape web-lane queries as news queries: name the event, likely outlets, "
    "and date cues."
)

LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "pt": "Portuguese"}

# The ``WRITE`` line of each output value; ``neutral`` tone adds no line.
TONE_LINES = {
    "academic": (
        "Tone: formal and academic. Use precise terms, and hedge each claim to "
        "the strength of its evidence."
    ),
    "executive": (
        "Tone: executive. Lead with conclusions and decisions, and keep jargon "
        "to a minimum."
    ),
    "plain": (
        "Tone: plain. Use short sentences and everyday words, and define each "
        "technical term."
    ),
}
LENGTH_LINES = {
    "short": "Length: 300 to 500 words.",
    "standard": "Length: 800 to 1500 words.",
    "long": "Length: 2000 to 3500 words.",
}
STRUCTURE_LINES = {
    "report": "Structure: a cohesive report with headed sections.",
    "memo": (
        "Structure: a memo with Summary, Findings and Implications sections, in prose."
    ),
    "bullets": (
        "Structure: headed sections whose bodies are bullet lists, with one cited "
        "claim for each bullet. The bullets under ## Open questions need no "
        "citation."
    ),
}
_KEEP_OPEN_QUESTIONS = "Keep the heading ## Open questions in English, word for word."
_TRANSLATE_ONLY = (
    "You may translate claims from the findings, but add no content that no "
    "source cites."
)

# The clarify axis each preference settles once it leaves its default.
_SETTLED_AXES = (
    ("source_mix", "auto", "web versus academic sources"),
    ("recency", "any", "the time range"),
    ("tone", "neutral", "the audience"),
)

DECIDE_CLARIFY = """You decide if the user query needs clarification before research.
You already have a SCOUT of web/paper hits. {clarify_bias}

Only ask if the query is ambiguous (audience, time range, which entity, web vs academic).
If you ask, the question MUST mention at least one scout title. Offer 2-4 angles drawn from hits.
If scout is empty, you may ask a generic narrowing question.
Read the clarification chat below. If the user already answered, do NOT ask the same
question again: skip unless a new ambiguity remains that the answer did not settle.{pref_lines}

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
Order topics by importance: waves after the first keep the first {followup_cap} only.{bias}

Brief:
{brief}
Prior topics (do not repeat): {prior}
Suggested follow-ups: {followups}
"""

RESEARCH_SYS = """You are a research sub-agent. Focus ONLY on this topic.
This topic is on the {focus} lane. You hold the search tool for that lane and
exa_highlights. Use only the tools you are given; no other lane is yours.
Search first, then call exa_highlights on the best URLs you found.
Do not invent sources. After you have enough, stop calling tools.{bias}
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

WRITE = """Write a Markdown research report.
Use the brief as the north star. Only cite source ids that exist, as [src_...].
Every non-obvious factual sentence should end with a citation.
End with ## Open questions listing the gaps.
Do not invent a bibliography; the runtime appends ## References from retrieved sources.{style}

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


def _joined_lines(lines: list[str]) -> str:
    """Lines to append to a prompt line: each on its own line, or nothing."""
    if not lines:
        return ""
    return "\n" + "\n".join(lines)


def _clarify_lines(prefs: Mapping[str, Any]) -> str:
    """The clarify rules the preferences add; empty when they add none."""
    lines = [
        f"A user preference already settles {axis}; do not ask about it."
        for name, default, axis in _SETTLED_AXES
        if prefs.get(name, default) != default
    ]
    language = prefs.get("language") or "auto"
    if language != "auto":
        lines.append(
            f"Write the question and the options in {LANGUAGE_NAMES[language]}. "
            "Quote scout titles unchanged, in their original language."
        )
    return _joined_lines(lines)


def clarify_prompt(query: str, scout: str, chat: str, prefs: Mapping[str, Any]) -> str:
    """The ``DECIDE_CLARIFY`` system prompt under the thread's preferences."""
    return DECIDE_CLARIFY.format(
        query=query,
        scout=scout,
        chat=chat,
        clarify_bias=ASK_BIAS if prefs.get("clarify_mode") == "prefer" else SKIP_BIAS,
        pref_lines=_clarify_lines(prefs),
    )


def plan_bias(prefs: Mapping[str, Any]) -> str:
    """The ``PLAN`` lines the search-bias preferences add.

    ``recency`` is a hard filter, so the news line never depends on it.
    """
    lines = []
    if prefs.get("prefer_primary"):
        lines.append(PRIMARY_LINE)
    if prefs.get("news_bias"):
        lines.append(NEWS_LINE)
    return _joined_lines(lines)


def research_bias(prefs: Mapping[str, Any]) -> str:
    """The ``RESEARCH_SYS`` line ``prefer_primary`` adds, on every lane."""
    return "\n" + PRIMARY_LINE if prefs.get("prefer_primary") else ""


def language_line(language: str, query: str) -> str:
    """The ``WRITE`` language rule; ``auto`` follows the language of ``query``."""
    if language == "auto":
        return (
            f'Write in the language of the user query "{query}". Write the other '
            f"headings in that language. {_KEEP_OPEN_QUESTIONS} {_TRANSLATE_ONLY}"
        )
    name = LANGUAGE_NAMES[language]
    headings = "" if language == "en" else f" Write the other headings in {name}."
    return f"Write in {name}.{headings} {_KEEP_OPEN_QUESTIONS} {_TRANSLATE_ONLY}"


def write_style(prefs: Mapping[str, Any], query: str) -> str:
    """The ``WRITE`` lines of the output preferences, defaults included."""
    lines = [
        language_line(prefs["language"], query),
        TONE_LINES.get(prefs["tone"]),
        LENGTH_LINES[prefs["length"]],
        STRUCTURE_LINES[prefs["structure"]],
    ]
    return "\n" + "\n".join(line for line in lines if line)
