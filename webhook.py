"""
webhook.py — Real-time event ingestion endpoint.

Run alongside the dashboard with:
    uvicorn webhook:app --port 8001 --reload

Accepts POST requests from any social platform's webhook
(or a curl command for demo purposes).

Example:
    curl -X POST http://localhost:8001/webhook/social \
      -H "Content-Type: application/json" \
      -H "X-Webhook-Secret: your_secret" \
      -d '{"platform":"twitter","type":"mention","author":"@user","content":"Your product broke!"}'

Security:
  - WEBHOOK_SECRET env var REQUIRED for HMAC-SHA256 signature verification
    (compatible with Twitter/Meta webhook format).
  - Rate limiting: 100 requests per minute per IP (asyncio.Lock protected).
  - All raw payloads are logged to the DB for audit (capped at 1000 chars).
  - Author field sanitized to prevent prompt injection.
"""

import os
import re
import json
import hmac
import hashlib
import asyncio
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
from dotenv import load_dotenv

from store import init_db, insert_event, get_stats

load_dotenv()

log = logging.getLogger("webhook")

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
if not WEBHOOK_SECRET:
    log.warning(
        "WEBHOOK_SECRET is not set in environment variables. "
        "Webhook authentication is DISABLED — set WEBHOOK_SECRET in .env before production use."
    )
    print("WARNING: WEBHOOK_SECRET not set - webhook auth is DISABLED in this session.")


# ---------------------------------------------------------------------------
# Lifespan context manager (replaces deprecated @app.on_event("startup"))
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="LoopBack — Webhook API",
    description="Real-time inbound social event ingestion endpoint.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# In-memory rate limiter (per-IP, 100 req/min) — asyncio.Lock for thread safety
# ---------------------------------------------------------------------------
_rate_data: dict[str, list[float]] = defaultdict(list)
_rate_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
RATE_LIMIT  = 100
RATE_WINDOW = 60   # seconds


async def _check_rate_limit(ip: str):
    async with _rate_locks[ip]:
        now   = time.time()
        calls = _rate_data[ip]
        # Drop timestamps outside the window
        calls[:] = [t for t in calls if now - t < RATE_WINDOW]
        if len(calls) >= RATE_LIMIT:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again in a minute.")
        calls.append(now)


# ---------------------------------------------------------------------------
# Author sanitization — strips non-safe characters to prevent prompt injection
# ---------------------------------------------------------------------------
_AUTHOR_SAFE = re.compile(r"[^a-zA-Z0-9@._\-\s]")


def _sanitize_author(author: str) -> str:
    """Keep only safe characters in author field; limit length to 100."""
    return _AUTHOR_SAFE.sub("", author).strip()[:100]


# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------
VALID_PLATFORMS   = {"twitter", "instagram", "facebook", "tiktok", "linkedin", "api", "email"}
VALID_EVENT_TYPES = {"comment", "dm", "mention", "review", "reply", "other"}


class InboundEvent(BaseModel):
    platform:   str             = Field(..., description="Source platform")
    type:       str             = Field(..., description="Event type: comment|dm|mention|review")
    author:     str             = Field(..., description="Author handle or name")
    content:    str             = Field(..., min_length=1, max_length=5000, description="Message content")
    created_at: Optional[str]   = Field(None, description="ISO 8601 UTC timestamp (optional)")
    source_url: Optional[str]   = Field(None, max_length=2000, description="Direct URL to the original post/comment on the platform")

    class Config:
        str_strip_whitespace = True


# ---------------------------------------------------------------------------
# Health routes
# ---------------------------------------------------------------------------
@app.get("/", tags=["Health"])
def root():
    return {
        "service": "LoopBack",
        "status":  "running",
        "time":    datetime.now(timezone.utc).isoformat(),
    }
@app.get("/health", tags=["Health"])
def health():
    try:
        stats = get_stats()
        return {"status": "ok", "db": "connected", "stats": stats}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "error", "detail": str(e)})


@app.post("/webhook/social", tags=["Ingestion"])
async def receive_event(
    request:             Request,
    x_hub_signature_256: Optional[str] = Header(None),
    x_webhook_secret:    Optional[str] = Header(None),
):
    """
    Accept an inbound social event and queue it for triage.

    Enforced Webhook Authentication:
      - Requires shared static secret via 'X-Webhook-Secret' header, or
      - Requires signature verification via 'X-Hub-Signature-256' header (sha256=<hex>).
      - If WEBHOOK_SECRET is not set, authentication is skipped (dev mode only).
    """
    client_ip = request.client.host if request.client else "unknown"
    await _check_rate_limit(client_ip)

    # Read raw body FIRST (before any parsing) so HMAC verification works correctly.
    body = await request.body()

    # Enforce webhook security only when secret is configured
    if WEBHOOK_SECRET:
        static_auth_ok = (x_webhook_secret == WEBHOOK_SECRET)
        hmac_auth_ok = False

        if x_hub_signature_256:
            expected = "sha256=" + hmac.new(
                WEBHOOK_SECRET.encode(), body, hashlib.sha256
            ).hexdigest()
            hmac_auth_ok = hmac.compare_digest(expected, x_hub_signature_256)

        if not (static_auth_ok or hmac_auth_ok):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Invalid X-Webhook-Secret or X-Hub-Signature-256 signature."
            )

    # Parse JSON manually after authentication check
    try:
        payload = json.loads(body)
        event = InboundEvent(**payload)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid payload: {e}")

    # Normalise and strictly validate platform / event type
    platform   = event.platform.lower().strip()
    event_type = event.type.lower().strip()

    if platform not in VALID_PLATFORMS:
        raise HTTPException(status_code=422, detail=f"Invalid platform '{platform}'. Must be one of {VALID_PLATFORMS}")
    if event_type not in VALID_EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid event type '{event_type}'. Must be one of {VALID_EVENT_TYPES}")

    # Sanitize author to prevent prompt injection attacks
    author = _sanitize_author(event.author)
    if not author:
        raise HTTPException(status_code=422, detail="Author handle/name cannot be empty or contains only invalid characters.")
    if not event.content.strip():
        raise HTTPException(status_code=422, detail="Message content cannot be empty.")

    # Cap stored payload at 1000 chars to prevent DB bloat attacks
    raw_payload = json.dumps(event.model_dump())[:1000]

    event_id = insert_event(
        platform    = platform,
        event_type  = event_type,
        author      = author,
        content     = event.content,
        created_at  = event.created_at,
        source_ip   = client_ip,
        raw_payload = raw_payload,
        source_url  = event.source_url,
    )

    return {
        "status":    "queued",
        "event_id":  event_id,
        "message":   "Event accepted and queued for triage.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/webhook/batch", tags=["Ingestion"])
async def receive_batch(
    request: Request,
    events: list[InboundEvent],
    x_webhook_secret: Optional[str] = Header(None),
):
    """
    Accept up to 50 events in a single batch request.
    Useful for bulk imports or replay scenarios.
    """
    client_ip = request.client.host if request.client else "unknown"
    await _check_rate_limit(client_ip)

    if WEBHOOK_SECRET and x_webhook_secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid X-Webhook-Secret.")

    if len(events) > 50:
        raise HTTPException(status_code=400, detail="Batch limit is 50 events per request.")

    results = []
    for ev in events:
        try:
            platform = ev.platform.lower().strip()
            event_type = ev.type.lower().strip()

            if platform not in VALID_PLATFORMS or event_type not in VALID_EVENT_TYPES:
                raise ValueError("Invalid platform or event type")

            author = _sanitize_author(ev.author)
            if not author:
                raise ValueError("Author is empty after sanitization")

            eid = insert_event(
                platform   = platform,
                event_type = event_type,
                author     = author,
                content    = ev.content,
                created_at = ev.created_at,
                source_ip  = client_ip,
            )
            results.append({"status": "queued", "event_id": eid})
        except Exception as e:
            results.append({"status": "error", "detail": str(e)})

    return {"accepted": len([r for r in results if r["status"] == "queued"]),
            "results": results}


@app.get("/stats", tags=["Monitoring"])
def stats():
    """Live statistics — useful for external monitoring tools."""
    return get_stats()
