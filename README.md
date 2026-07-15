# deep-research-agent
An autonomous deep research agent powered by LLMs — searches, reads, and synthesizes information into reports

## Getting started

Requires **Python 3.11+** and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                 # create .venv + install deps (and this package, editable)
cp .env.example .env    # then fill in GROQ_API_KEY and TAVILY_API_KEY
                        # (Windows PowerShell: Copy-Item .env.example .env)
uv run pytest           # run the test suite
```

Import convention (src-layout): `from deep_research_agent.tools.search import search`.
