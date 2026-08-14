"""Machine-written summaries of court opinions, cached and budgeted.

WHY THIS IS CACHE-FIRST AND CAPPED, and not simply "call the model".

The endpoint that fronts this is unauthenticated and rate-limited at 4 requests
per second per address, which is 345,600 a day. That ceiling is harmless for a
free CourtListener proxy and is a money faucet for a paid one, so the budget is
not a nicety — it is the only thing standing between a loop and a bill. Past
the cap the answer is an honest "not available yet", never a spend.

The cache is keyed on (cluster_id, model, PROMPT_VERSION). Bumping the prompt
therefore invalidates every summary written under the old one rather than
leaving a corpus that silently mixes two behaviours — the failure mode where
half your data was produced by an instruction you can no longer read.

WHAT THE CACHE DOES AND DOES NOT RECORD. It stores that case N has a summary.
It stores no address, no session, no timestamp of any READ, and nothing about
who asked. The site's whole posture on /cases is that a search leaves no
server-side record — nginx has access_log off on those routes for exactly this
reason — and a cache that logged readers would quietly undo it.

DEGRADES TO OFF. With no SUMMARY_API_KEY set, this returns available=False with
a reason and never raises. That is the state the service ships in: the feature
announces itself as unavailable rather than erroring, so deploying the code and
enabling the spend are two separate decisions.
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import httpx

# Bump when the instruction below changes. See the cache-key note above.
PROMPT_VERSION = 1

CACHE_PATH = Path(os.getenv("SUMMARY_CACHE_PATH", "data/summaries.sqlite3"))
API_KEY = os.getenv("SUMMARY_API_KEY", "")
API_BASE = os.getenv("SUMMARY_API_BASE", "https://api.openai.com/v1")
MODEL = os.getenv("SUMMARY_MODEL", "gpt-4o-mini")
DAILY_CAP = int(os.getenv("SUMMARY_DAILY_CAP", "50"))

# How much opinion text to summarise from. The service can now return whole
# opinions (see courtlistener.DEFAULT_TEXT_CHARS), and the summary is only as
# good as what it read — but an unbounded slice is an unbounded prompt, so this
# is the deliberate ceiling for one summary.
MAX_INPUT_CHARS = 120_000

SYSTEM = """You summarise US court opinions for people fighting a health-insurance denial for transgender healthcare. They are usually not lawyers, they are on a deadline, and they want to know whether this case is worth citing.

Write in plain, direct language. Short sentences. Define any term of art in six words or fewer the first time.

Cover, in this order, and skip anything the opinion does not decide:
1. What the court actually held. One or two sentences.
2. Which law it turns on — ERISA, ACA Section 1557, a state mandate, Medicaid, the Constitution — and what kind of plan was involved.
3. Whether it helps or hurts someone appealing a denial, and why.
4. What it does NOT decide. This is the most useful line in most summaries, because a reader who has just found a case that sounds like theirs is usually over-estimating its reach.

Hard rules:
- Never predict how any other case will come out.
- Never tell the reader what to do. Describe what the court decided.
- If the opinion is procedural, or does not reach the merits, say so plainly and keep it short.
- If the text you were given is clearly partial, say what you could not see.
- No preamble. Start with the holding."""


def _db() -> sqlite3.Connection:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS summaries (
               cluster_id     INTEGER NOT NULL,
               model          TEXT    NOT NULL,
               prompt_version INTEGER NOT NULL,
               summary        TEXT    NOT NULL,
               source_chars   INTEGER NOT NULL,
               partial        INTEGER NOT NULL,
               created_at     INTEGER NOT NULL,
               PRIMARY KEY (cluster_id, model, prompt_version)
           )"""
    )
    return conn


def cached_summary(cluster_id: int) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT summary, source_chars, partial, created_at FROM summaries"
            " WHERE cluster_id = ? AND model = ? AND prompt_version = ?",
            (cluster_id, MODEL, PROMPT_VERSION),
        ).fetchone()
    if not row:
        return None
    return {
        "summary": row[0],
        "source_chars": row[1],
        "partial": bool(row[2]),
        "created_at": row[3],
    }


def _spent_today(conn: sqlite3.Connection) -> int:
    """Summaries WRITTEN since midnight UTC.

    Counted from the cache itself rather than a separate counter, so the budget
    cannot drift from what was actually produced and cannot be reset by a
    restart. A cache row is the receipt for a spend.
    """
    midnight = int(time.time()) // 86400 * 86400
    return conn.execute(
        "SELECT COUNT(*) FROM summaries WHERE created_at >= ?", (midnight,)
    ).fetchone()[0]


def budget_state() -> dict:
    with _db() as conn:
        used = _spent_today(conn)
    return {"used_today": used, "daily_cap": DAILY_CAP, "remaining": max(0, DAILY_CAP - used)}


async def summarise(cluster_id: int, text: str, full_length: int) -> dict:
    """Return a summary for one opinion, from cache when possible.

    Never raises for an expected condition — no key, budget spent, empty text
    and an upstream failure all come back as available=False with a reason,
    because the caller is a button on a web page and an exception there is a
    stack trace where an explanation belongs.
    """
    hit = cached_summary(cluster_id)
    if hit:
        return {"available": True, "cached": True, **hit, "model": MODEL}

    if not API_KEY:
        return {
            "available": False,
            "cached": False,
            "reason": "Summaries are not switched on for this server.",
        }
    if not text.strip():
        return {
            "available": False,
            "cached": False,
            "reason": "This case has no opinion text to summarise. CourtListener holds the docket but not the written opinion.",
        }

    with _db() as conn:
        if _spent_today(conn) >= DAILY_CAP:
            return {
                "available": False,
                "cached": False,
                "reason": "The daily limit for new summaries has been reached. Cases summarised earlier still open instantly, and this one can be summarised tomorrow.",
            }

    source = text[:MAX_INPUT_CHARS]
    partial = len(source) < full_length

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{API_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                f"Opinion text"
                                f"{f' (first {len(source):,} characters of {full_length:,} — say so if it matters)' if partial else ''}:\n\n{source}"
                            ),
                        },
                    ],
                },
            )
            resp.raise_for_status()
            summary = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # noqa: BLE001 — surfaced to the reader, not swallowed
        return {
            "available": False,
            "cached": False,
            "reason": f"The summary could not be generated just now ({type(exc).__name__}). The full opinion is still linked below.",
        }

    if not summary:
        return {"available": False, "cached": False, "reason": "The model returned nothing."}

    now = int(time.time())
    with _db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO summaries"
            " (cluster_id, model, prompt_version, summary, source_chars, partial, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cluster_id, MODEL, PROMPT_VERSION, summary, len(source), int(partial), now),
        )

    return {
        "available": True,
        "cached": False,
        "summary": summary,
        "source_chars": len(source),
        "partial": partial,
        "created_at": now,
        "model": MODEL,
    }
