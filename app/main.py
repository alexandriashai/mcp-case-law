"""Case Law MCP Server — FastAPI application."""

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .services import courtlistener, summarize

app = FastAPI(
    title="Case Law MCP Server",
    description="Search 9M+ court opinions and federal dockets via CourtListener / RECAP "
                "for insurance litigation precedent.",
    version="1.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"status": "ok", "source": "courtlistener", "opinions": "9M+", "courts": "2000+"}


@app.get("/")
def root():
    return {
        "name": "Case Law MCP Server",
        "version": "1.0.0",
        "docs": "/docs",
        "mcp": "https://caselaw.wyldfyre.ai/mcp",
    }


@app.get("/opinions/search")
async def opinion_search(
    q: str = Query(...),
    court: str = Query(""),
    filed_after: str = Query(""),
    filed_before: str = Query(""),
    cited_gt: int = Query(0),
    limit: int = Query(10, ge=1, le=20),
):
    return await courtlistener.search_opinions(q, court, filed_after, filed_before, cited_gt, limit)


@app.get("/opinions/{cluster_id}")
async def opinion_detail(
    cluster_id: int,
    offset: int = Query(0, ge=0),
    # Same window controls as the MCP tool. The REST side is what
    # transhealth.guide's build-time /sources page reads, so an endpoint able
    # to return only the first slice would cap the site's own quoted sources at
    # the same arbitrary point.
    max_chars: int = Query(
        courtlistener.DEFAULT_TEXT_CHARS, ge=1, le=courtlistener.HARD_MAX_TEXT_CHARS
    ),
):
    result = await courtlistener.get_opinion(cluster_id, offset=offset, max_chars=max_chars)
    return result or {"error": "Not found"}


@app.get("/opinions/{cluster_id}/summary")
async def opinion_summary(cluster_id: int):
    """A machine-written summary of one opinion, from cache when possible.

    Returns 200 with available=false and a reason for every expected failure —
    no key, budget spent, no opinion text, upstream refused. The caller is a
    button on a web page, and a 500 there is a stack trace where a sentence
    belongs.

    Summarises the WHOLE opinion, which only became possible when the 8k cap
    came off earlier today: a summary of the first 26% would have been a
    confident account of a quarter of a case.
    """
    result = await courtlistener.get_opinion(
        cluster_id, offset=0, max_chars=summarize.MAX_INPUT_CHARS
    )
    if not result:
        return {"available": False, "reason": "Opinion not found."}

    out = await summarize.summarise(
        cluster_id,
        result.get("opinion_text") or "",
        result.get("opinion_text_full_length") or 0,
    )
    out["case_name"] = result.get("case_name_full") or result.get("case_name") or ""
    out["url"] = result.get("url", "")
    out["full_length"] = result.get("opinion_text_full_length") or 0
    return out


@app.get("/dockets/{docket_id}/summary")
async def docket_summary(docket_id: int):
    """A machine-written summary of where an active lawsuit stands.

    Built from the filing history, not from opinion text — a docket has none,
    and its search snippet is empty too. So this answers a different question
    from the opinion summary: not "what did the court hold" but "where has this
    got to", which is what the reader on the active-lawsuits tab is asking.
    """
    d = await courtlistener.get_docket(docket_id)
    if not d:
        return {"available": False, "reason": "Docket not found."}

    header = " · ".join(
        x for x in [d["case_name"], d["court"], f"filed {d['date_filed']}" if d["date_filed"] else "",
                    d["docket_number"], d["nature_of_suit"]] if x
    )
    body = "\n".join(d["entries"])
    text = f"{header}\n\nDocket entries, newest first:\n{body}" if body else ""

    out = await summarize.summarise(docket_id, text, len(text), kind="docket")
    out["case_name"] = d["case_name"]
    out["url"] = d["url"]
    out["full_length"] = len(text)
    out["entry_count"] = d["entry_count"]
    return out


@app.get("/summaries/budget")
async def summary_budget():
    """What today's summary budget looks like. Used by nothing on the site;
    here so the cap is inspectable without reading the database."""
    return summarize.budget_state()


@app.get("/dockets/search")
async def docket_search(
    q: str = Query(...),
    court: str = Query(""),
    limit: int = Query(10, ge=1, le=20),
):
    return await courtlistener.search_dockets(q, court, limit)
