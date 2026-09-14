# exact

Open Deep Research agent on LangGraph. Tools: **Exa** and **Elicit**. Clarification is grounded in an Exa scout.

Architecture: [docs/architecture.md](docs/architecture.md) · Contract: [docs/spec.md](docs/spec.md) v1.2 · [Contributing](CONTRIBUTING.md) · [ODR blog](https://www.langchain.com/blog/open-deep-research)

```
uv sync --extra dev
uv run pre-commit install   # ruff lint + format on commit
cp .env.example .env   # set EXA_API_KEY and ANTHROPIC_API_KEY (or OPENAI_API_KEY)
uv run exact "Are GLP-1 agonists effective for heart failure?"
uv run exact --skip-clarify "What is a Durable Object?"
uv run pytest -q
uv run ruff check --fix && uv run ruff format
```

Default model: `anthropic:claude-haiku-4-5`. Optional per-role overrides: `EXACT_MODEL_*`, `EXACT_MAX_TOKENS_*`, plus `EXACT_TEMPERATURE`, `EXACT_REASONING_EFFORT`, `EXACT_THINKING_BUDGET` (see `.env.example` / architecture).

Optional: `ELICIT_API_KEY` for paper search on academic queries.

Does not guarantee truth. Citations must resolve. Spend is capped (3 clarify turns, 3 waves, 4 tool rounds per worker).
