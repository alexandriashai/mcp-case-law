# MCP Case Law

An MCP server for searching 9M+ court opinions and federal dockets via CourtListener / RECAP for insurance litigation precedent.

## Features

- **9M+ opinions** from 2,000+ courts (CourtListener / RECAP)
- **Full opinion text** retrieval with citation metadata
- **Federal docket search** for active litigation
- **Influential precedent finder** — filter by citation count for authoritative cases
- **Insurance court filters** — SCOTUS, all appeals, 9th Circuit, 5th Circuit, etc.
- **MCP protocol** endpoint for Claude.ai
- **REST API** with Swagger docs

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_case_law` | Search opinions by keyword, court, date, citation count |
| `get_opinion` | Full opinion text by CourtListener cluster ID |
| `search_dockets` | Search federal court dockets (RECAP archive) |
| `insurance_precedent` | Find frequently-cited appellate insurance decisions |

## Quick Start

### Connect via MCP (Claude.ai)

- **URL:** `https://caselaw.wyldfyre.ai/mcp`
- **Authentication:** None required

### REST API

```bash
# Search opinions
curl "https://caselaw.wyldfyre.ai/opinions/search?q=ERISA+arbitrary+capricious+denial"

# Filter by court and date
curl "https://caselaw.wyldfyre.ai/opinions/search?q=mental+health+parity&court=ca9&filed_after=2020-01-01"

# Get full opinion
curl "https://caselaw.wyldfyre.ai/opinions/8765638"

# Search dockets
curl "https://caselaw.wyldfyre.ai/dockets/search?q=UnitedHealthcare+class+action"
```

Swagger docs: https://caselaw.wyldfyre.ai/docs

## Self-Hosting

```bash
pip install -r requirements.txt

# Required: free CourtListener account
# Register: https://www.courtlistener.com/register/
# Get token: https://www.courtlistener.com/profile/api/
export COURTLISTENER_TOKEN="your-token"

uvicorn app.main:app --host 0.0.0.0 --port 8130
python run_mcp.py  # separate process
```

## Data Source

| Source | Coverage | Auth | Rate Limits |
|--------|----------|------|-------------|
| [CourtListener](https://www.courtlistener.com) | 9M+ opinions, 2,000+ courts | Free token | 5,000 req/hour |

## License

MIT
