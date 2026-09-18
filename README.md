# exact

Open Deep Research agent on LangGraph. Tools: **Exa**. Clarification is grounded in an Exa scout that adds a publication lane on an academic signal. The Elicit client stays in the tree but is dormant: no live path binds it. Each planner topic carries a focus lane (`web`, `people`, `company`, `publication`), and a worker binds only the search tool of its lane plus `exa_highlights`.

Architecture: [docs/architecture.md](docs/architecture.md) · Contract: [docs/spec.md](docs/spec.md) v1.4 · [Contributing](CONTRIBUTING.md) · [ODR blog](https://www.langchain.com/blog/open-deep-research)

```
make setup             # uv sync --extra dev + pre-commit hooks
cp .env.example .env   # set EXA_API_KEY and ANTHROPIC_API_KEY (or OPENAI_API_KEY)
uv run exact "Are GLP-1 agonists effective for heart failure?"
uv run exact --skip-clarify "What is a Durable Object?"
make check             # lint + format-check + complexity + imports + tests
make lint-fix         # ruff format + safe lint fixes
```
Default model: `anthropic:claude-haiku-4-5`. Optional per-role overrides: `EXACT_MODEL_*`, `EXACT_MAX_TOKENS_*`, plus `EXACT_TEMPERATURE`, `EXACT_REASONING_EFFORT`, `EXACT_THINKING_BUDGET` (see `.env.example` / architecture).

Optional: `ELICIT_API_KEY` for paper search on academic queries.

Does not guarantee truth. Citations must resolve. Spend is capped by the effort profile: `normal` (3 waves, 3 topics, 4 tool rounds, 5 hits) or `max` (4, 4, 6, 8). Pick one with `--effort` or `EXACT_EFFORT`.
