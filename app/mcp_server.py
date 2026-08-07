"""MCP Server for Case Law — CourtListener / RECAP."""

from dotenv import load_dotenv
load_dotenv()

from mcp.server.fastmcp import FastMCP
from .services import courtlistener

mcp = FastMCP(
    "Case Law",
    instructions="Search 9M+ court opinions and federal dockets for insurance litigation precedent. "
                 "Covers ERISA, ACA, mental health parity, network adequacy, prior authorization, "
                 "insurance bad faith, and coverage denial case law across all federal and state courts.",
    host="0.0.0.0",
    port=8131,
)


@mcp.resource("docs://about")
async def about() -> str:
    """About this MCP server and its data sources."""
    return (
        "Case Law Search MCP Server\n\n"
        "Search 9M+ court opinions and federal dockets from CourtListener / RECAP.\n\n"
        "Data Sources:\n"
        "- CourtListener: 9M+ court opinions across all federal and state courts\n"
        "- RECAP Archive: Federal court dockets and filings\n\n"
        "Coverage Areas:\n"
        "- ERISA benefit denial litigation\n"
        "- ACA coverage mandate cases\n"
        "- Mental health parity (MHPAEA) enforcement\n"
        "- Network adequacy challenges\n"
        "- Prior authorization disputes\n"
        "- Insurance bad faith claims\n"
        "- Coverage denial appeals\n\n"
        "Tools:\n"
        "- search_case_law: Keyword search across court opinions\n"
        "- get_opinion: Full text of a specific opinion by cluster ID\n"
        "- search_dockets: Search federal court dockets (RECAP)\n"
        "- insurance_precedent: Find influential, frequently-cited insurance precedent\n"
    )


@mcp.prompt()
async def erisa_denial_research(diagnosis: str = "major depressive disorder", treatment: str = "residential treatment") -> str:
    """Research ERISA denial case law for a specific diagnosis and treatment."""
    return (
        f"I need to research ERISA denial case law for {diagnosis} involving {treatment}.\n\n"
        f"1. Use insurance_precedent to find influential appellate cases on "
        f"'ERISA arbitrary capricious {diagnosis} {treatment} denial'\n"
        f"2. Search for cases about standard of review with "
        f"search_case_law query='ERISA de novo arbitrary capricious standard review {treatment}'\n"
        f"3. Check for recent circuit court decisions with "
        f"search_case_law query='{diagnosis} {treatment} coverage denial ERISA' filed_after='2020-01-01'\n\n"
        f"Summarize the key holdings and which standard of review applies."
    )


@mcp.prompt()
async def bad_faith_precedent(insurer: str = "UnitedHealthcare", state: str = "") -> str:
    """Find insurance bad faith precedent against a specific insurer."""
    return (
        f"Search for insurance bad faith case law against {insurer}.\n\n"
        f"1. Use search_case_law with query='bad faith {insurer} insurance denial' "
        f"{'court=' + state if state else ''}\n"
        f"2. Use insurance_precedent with topic='insurance bad faith punitive damages {insurer}'\n"
        f"3. Look for class action dockets with search_dockets "
        f"query='{insurer} class action denial'\n\n"
        f"Identify patterns in how courts have ruled against this insurer."
    )


@mcp.tool()
async def search_case_law(
    query: str,
    court: str = "",
    filed_after: str = "",
    filed_before: str = "",
    cited_gt: int = 0,
    max_results: int = 10,
) -> str:
    """Search court opinions by keyword. Returns case names, citations, courts, and dates.

    Args:
        query: Legal search terms (e.g., "ERISA arbitrary capricious standard of review insurance denial")
        court: Court filter — "scotus", "all_appeals", "ca9", "ca5", "ca3", "ca7", or "" for all
        filed_after: Date filter YYYY-MM-DD (e.g., "2020-01-01")
        filed_before: Date filter YYYY-MM-DD
        cited_gt: Minimum citation count (use to find influential cases)
        max_results: Number of results (default 10, max 20)
    """
    court_id = courtlistener.INSURANCE_COURTS.get(court, court)
    data = await courtlistener.search_opinions(
        query, court_id, filed_after, filed_before, cited_gt, min(max_results, 20)
    )
    results = data.get("results", [])

    if not results:
        return f"No case law found for: {query}"

    lines = [f"**Case law search:** {query} ({data['count']:,} total results)\n"]
    for r in results:
        cites = ", ".join(r["citations"][:3]) if r["citations"] else "unpublished"
        cited = f" (cited {r['cite_count']}x)" if r["cite_count"] > 0 else ""
        lines.append(f"### {r['case_name']}")
        lines.append(f"**{r['court']}** | {r['date_filed']} | {cites}{cited}")
        lines.append(f"[Full opinion]({r['url']})")
        if r.get("snippet"):
            import re
            snippet = re.sub(r'<[^>]+>', '', r["snippet"])[:300]
            lines.append(f"\n{snippet}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def get_opinion(cluster_id: int) -> str:
    """Get the full text of a court opinion by CourtListener cluster ID.

    Args:
        cluster_id: The CourtListener cluster ID (from search results)
    """
    result = await courtlistener.get_opinion(cluster_id)
    if not result:
        return f"Opinion {cluster_id} not found."

    cites = ", ".join(result["citations"][:5]) if result["citations"] else "unpublished"
    lines = [
        f"## {result['case_name_full'] or result['case_name']}",
        f"**Court:** {result['court']}",
        f"**Filed:** {result['date_filed']}",
        f"**Citations:** {cites}",
    ]
    if result.get("judges"):
        lines.append(f"**Judges:** {result['judges']}")
    if result.get("nature_of_suit"):
        lines.append(f"**Nature of Suit:** {result['nature_of_suit']}")
    if result.get("precedential_status"):
        lines.append(f"**Status:** {result['precedential_status']}")
    lines.append(f"[Full text]({result['url']})")

    if result.get("opinion_text"):
        text = result["opinion_text"][:8000]
        if len(result["opinion_text"]) > 8000:
            text += "\n\n[... truncated — see full text at URL above]"
        lines.append(f"\n### Opinion Text\n\n{text}")

    return "\n".join(lines)


@mcp.tool()
async def search_dockets(
    query: str,
    court: str = "",
    max_results: int = 10,
) -> str:
    """Search federal court dockets (RECAP archive) for active litigation.

    Args:
        query: Search terms (e.g., "UnitedHealthcare mental health parity class action")
        court: Court filter or "" for all
        max_results: Number of results (default 10, max 20)
    """
    data = await courtlistener.search_dockets(query, court, min(max_results, 20))
    results = data.get("results", [])

    if not results:
        return f"No dockets found for: {query}"

    lines = [f"**Docket search:** {query} ({data['count']:,} total results)\n"]
    for r in results:
        lines.append(f"### {r['case_name']}")
        lines.append(f"**{r['court']}** | {r['date_filed']} | Docket #{r['docket_number']}")
        lines.append(f"[Docket]({r['url']})")
        if r.get("snippet"):
            import re
            snippet = re.sub(r'<[^>]+>', '', r["snippet"])[:300]
            lines.append(f"\n{snippet}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
async def insurance_precedent(
    topic: str,
    jurisdiction: str = "all_appeals",
    min_citations: int = 5,
) -> str:
    """Find influential insurance litigation precedent on a specific topic.
    Filters to frequently-cited appellate decisions for maximum authority.

    Args:
        topic: The legal issue (e.g., "arbitrary capricious standard ERISA", "mental health parity NQTL", "network adequacy Medicaid managed care")
        jurisdiction: "scotus", "all_appeals", "ca9", "ca5", "ca3", "ca7", or "" for all courts
        min_citations: Minimum citation count to filter for influential cases (default 5)
    """
    court_id = courtlistener.INSURANCE_COURTS.get(jurisdiction, jurisdiction)
    data = await courtlistener.search_opinions(
        topic, court_id, cited_gt=min_citations, page_size=10,
    )
    results = data.get("results", [])

    if not results:
        # Fall back to no citation filter
        data = await courtlistener.search_opinions(topic, court_id, page_size=10)
        results = data.get("results", [])

    if not results:
        return f"No insurance precedent found for: {topic}"

    lines = [
        f"**Influential precedent:** {topic}",
        f"**Jurisdiction:** {jurisdiction} | **Min citations:** {min_citations}",
        f"**Total matching:** {data['count']:,}\n",
    ]

    for r in results:
        cites = ", ".join(r["citations"][:2]) if r["citations"] else "unpublished"
        lines.append(f"- **{r['case_name']}** ({r['court']}, {r['date_filed']})")
        lines.append(f"  {cites} — cited {r['cite_count']}x | [Opinion]({r['url']})")

    return "\n".join(lines)
