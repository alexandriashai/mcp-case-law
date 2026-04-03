"""CourtListener / RECAP API client — 9M+ opinions, 2,000+ courts."""

import os
import httpx

BASE_URL = "https://www.courtlistener.com/api/rest/v4"
TOKEN = os.getenv("COURTLISTENER_TOKEN", "")

_client = httpx.AsyncClient(timeout=20.0)


def _headers() -> dict:
    h = {"Accept": "application/json"}
    if TOKEN:
        h["Authorization"] = f"Token {TOKEN}"
    return h


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
    sub_opinions = data.get("sub_opinions", [])
    if sub_opinions:
        # Fetch the first sub-opinion for text
        op_url = sub_opinions[0] if isinstance(sub_opinions[0], str) else sub_opinions[0].get("resource_uri", "")
        if op_url:
            op_resp = await _client.get(op_url if op_url.startswith("http") else f"https://www.courtlistener.com{op_url}", headers=_headers())
            if op_resp.status_code == 200:
                op_data = op_resp.json()
                opinion_text = op_data.get("plain_text", op_data.get("html_with_citations", ""))
                # Strip HTML if we got html_with_citations
                if "<" in opinion_text:
                    import re
                    opinion_text = re.sub(r'<[^>]+>', ' ', opinion_text)
                    opinion_text = re.sub(r'\s+', ' ', opinion_text).strip()

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
        "opinion_text": opinion_text[:10000] if opinion_text else "",
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
        results.append({
            "case_name": r.get("caseName", ""),
            "court": r.get("court", ""),
            "date_filed": r.get("dateFiled", ""),
            "docket_number": r.get("docketNumber", ""),
            "url": f"https://www.courtlistener.com{r.get('absolute_url', '')}",
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
