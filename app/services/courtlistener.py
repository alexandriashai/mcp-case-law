"""CourtListener / RECAP API client — 9M+ opinions, 2,000+ courts."""

import os
import re

import httpx

BASE_URL = "https://www.courtlistener.com/api/rest/v4"
TOKEN = os.getenv("COURTLISTENER_TOKEN", "")

_client = httpx.AsyncClient(timeout=20.0)


def _headers() -> dict:
    h = {"Accept": "application/json"}
    if TOKEN:
        h["Authorization"] = f"Token {TOKEN}"
    return h




# Ordered by fidelity. plain_text first because it needs no tag-stripping; the
# HTML variants are equivalent in content and differ only in who digitised them.
_TEXT_FIELDS = (
    "plain_text",
    "html_with_citations",
    "html_lawbox",
    "xml_harvard",
    "html_columbia",
    "html_anon_2020",
    "html",
)


def _best_text(op_data: dict) -> str:
    """
    First NON-EMPTY text field, stripped of markup.

    This used to be `op_data.get("plain_text", op_data.get("html_with_citations", ""))`,
    which looks like a fallback and is not one: dict.get returns the default only
    when the KEY IS MISSING, and CourtListener always sends plain_text — as an
    EMPTY STRING for anything it did not OCR itself. So every scanned or
    Harvard-digitised opinion returned nothing while its text sat in
    html_lawbox or xml_harvard.

    Measured 2026-08-06 on six pre-1990 insurance-coverage opinions: 6 of 6 had
    plain_text == "" with 3.5k-64k characters available in the HTML variants.
    That is the older case law an appeal is most likely to cite, and it read as
    "no text available for this case" rather than as a bug.
    """
    for field in _TEXT_FIELDS:
        raw = op_data.get(field) or ""
        if not raw.strip():
            continue
        if "<" in raw:
            raw = re.sub(r"<[^>]+>", " ", raw)
        return re.sub(r"\s+", " ", raw).strip()
    return ""

async def search_opinions(
    query: str,
    court: str = "",
    filed_after: str = "",
    filed_before: str = "",
    cited_gt: int = 0,
    page_size: int = 10,
) -> dict:
    """Search court opinions by keyword. Returns cases with citations and metadata."""
    params = {
        "q": query,
        "type": "o",  # opinions
        "page_size": min(page_size, 20),
        "order_by": "score desc",
    }
    if court:
        params["court"] = court
    if filed_after:
        params["filed_after"] = filed_after
    if filed_before:
        params["filed_before"] = filed_before
    if cited_gt:
        params["cited_gt"] = cited_gt

    resp = await _client.get(f"{BASE_URL}/search/", params=params, headers=_headers())
    resp.raise_for_status()
    data = resp.json()

    results = []
    for r in data.get("results", []):
        citations = r.get("citation", [])
        results.append({
            "case_name": r.get("caseName", ""),
            "court": r.get("court", ""),
            "date_filed": r.get("dateFiled", ""),
            "citations": citations if isinstance(citations, list) else [citations],
            "cite_count": r.get("citeCount", 0),
            "url": f"https://www.courtlistener.com{r.get('absolute_url', '')}",
            "cluster_id": r.get("cluster_id", ""),
            "snippet": r.get("snippet", ""),
        })

    return {"count": data.get("count", 0), "results": results}


async def get_opinion(cluster_id: int) -> dict | None:
    """Get full opinion details by cluster ID."""
    resp = await _client.get(f"{BASE_URL}/clusters/{cluster_id}/", headers=_headers())
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    data = resp.json()

    # Get the opinion text (first sub-opinion)
    opinion_text = ""
    full_length = 0
    sub_opinions = data.get("sub_opinions", [])
    if sub_opinions:
        # Fetch the first sub-opinion for text
        op_url = sub_opinions[0] if isinstance(sub_opinions[0], str) else sub_opinions[0].get("resource_uri", "")
        if op_url:
            op_resp = await _client.get(op_url if op_url.startswith("http") else f"https://www.courtlistener.com{op_url}", headers=_headers())
            if op_resp.status_code == 200:
                op_data = op_resp.json()
                opinion_text = _best_text(op_data)
                full_length = len(opinion_text)

    return {
        "case_name": data.get("case_name", ""),
        "case_name_full": data.get("case_name_full", ""),
        "court": data.get("court", ""),
        "date_filed": data.get("date_filed", ""),
        "citations": [c.get("cite", "") for c in data.get("citations", []) if isinstance(c, dict)],
        "judges": data.get("judges", ""),
        "nature_of_suit": data.get("nature_of_suit", ""),
        "precedential_status": data.get("precedential_status", ""),
        "url": f"https://www.courtlistener.com/opinion/{cluster_id}/",
        # Truncation is REPORTED. A 10k slice of a 106k opinion reads exactly
        # like a short opinion that ended, and a reader deciding whether a case
        # helps them would be judging on 9% of it without knowing.
        "opinion_text": opinion_text[:10000],
        "opinion_text_truncated": full_length > 10000,
        "opinion_text_full_length": full_length,
    }


async def search_dockets(
    query: str,
    court: str = "",
    page_size: int = 10,
) -> dict:
    """Search federal court dockets."""
    params = {
        "q": query,
        "type": "r",  # RECAP dockets
        "page_size": min(page_size, 20),
    }
    if court:
        params["court"] = court

    resp = await _client.get(f"{BASE_URL}/search/", params=params, headers=_headers())
    resp.raise_for_status()
    data = resp.json()

    results = []
    for r in data.get("results", []):
        # RECAP docket results carry docket_absolute_url, NOT absolute_url —
        # that field is empty here, so this used to build the bare domain
        # "https://www.courtlistener.com" for every docket. It returned 200,
        # which is why it read as a working link: it just went to the homepage
        # instead of the case. A dead link that 404s announces itself; one that
        # lands on a valid page does not.
        path = r.get("docket_absolute_url") or r.get("absolute_url") or ""
        results.append({
            "case_name": r.get("caseName", ""),
            "court": r.get("court", ""),
            "date_filed": r.get("dateFiled", ""),
            "docket_number": r.get("docketNumber", ""),
            "docket_id": r.get("docket_id", ""),
            "url": f"https://www.courtlistener.com{path}" if path else "",
            "snippet": r.get("snippet", ""),
        })

    return {"count": data.get("count", 0), "results": results}


# Common insurance litigation court filters
INSURANCE_COURTS = {
    "all_federal": "",
    "scotus": "scotus",
    "all_appeals": "ca1,ca2,ca3,ca4,ca5,ca6,ca7,ca8,ca9,ca10,ca11,cadc,cafc",
    "ca9": "ca9",  # 9th Circuit (common for insurance)
    "ca5": "ca5",  # 5th Circuit
    "ca3": "ca3",  # 3rd Circuit (ERISA)
    "ca7": "ca7",  # 7th Circuit
}
