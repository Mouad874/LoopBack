"""
Triage engine — v3 (intelligence upgrades).

New in v3:
  - Sentiment trajectory: detects escalating authors across message history
  - Multi-signal risk boost: follower count + verified status
  - Contact count injection: surfaces repeat-contact context to model
  - Intent clustering: normalised issue tags for spike detection
  - Sarcasm/irony detection flag
  - A/B draft variants: empathetic vs efficient tone options
  - Confidence score: model self-reports certainty
  - Routing team: smart routing to billing / support eng / comms / general
  - Hard legal block: never auto-send legal/PR/journalist messages
  - Platform-specific tone guidance in system prompt
"""

import os
import json
import time
import logging
import sys
import io


# ---------------------------------------------------------------------------
# Safe print — silently ignores broken-pipe / WinError 233 when called
# from Streamlit (which has no real stdout pipe on Windows)
# ---------------------------------------------------------------------------
def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
        sys.stdout.flush()
    except (OSError, BrokenPipeError, AttributeError):
        pass


from openai import OpenAI
from dotenv import load_dotenv
from store import (
    init_db, get_by_status, get_by_author, update_triage, mark_triage_failed,
    STATUS_PENDING_TRIAGE,
)

load_dotenv()

API_KEY = os.getenv("DASHSCOPE_API_KEY")

# Model cascade: primary -> fallback
# qwen-plus is the primary (higher quality), qwen-turbo is the cheaper fallback.
MODEL_PRIMARY  = os.getenv("QWEN_PRIMARY_MODEL", "qwen-plus")
MODEL_FALLBACK = os.getenv("QWEN_FALLBACK_MODEL", "qwen-turbo")

client = OpenAI(
    api_key=API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)

# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------
logging.basicConfig(
    filename="triage.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("triage")

# Risk boost thresholds
FOLLOWER_BOOST_THRESHOLD = 50_000   # accounts with >50k followers get +0.20 risk
FOLLOWER_BOOST_AMOUNT    = 0.20
ESCALATION_TRAJECTORY_BOOST = 0.15 # added if author's tone is escalating

# Hard-block keyword list (legal/PR/safety — NEVER auto-send)
LEGAL_BLOCK_KEYWORDS = [
    "sue", "lawsuit", "attorney", "lawyer", "legal action", "court",
    "injured", "injury", "allerg", "anaphylax", "hospital",
    "journalist", "reporter", "press inquiry", "media inquiry",
    "discrimination", "harassment", "racist", "defamation", "libel",
]

# ---------------------------------------------------------------------------
# Tool schema — forced function-call for safe, typed routing output
# ---------------------------------------------------------------------------
CLASSIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "classify_and_route",
        "description": "Classify an inbound social media message and decide how to route it.",
        "parameters": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": ["question", "complaint", "spam", "lead",
                             "legal_threat", "abuse", "praise", "other"],
                    "description": "Primary intent of the message.",
                },
                "intent_cluster": {
                    "type": "string",
                    "enum": [
                        "order_delay", "refund_request", "damaged_item",
                        "site_down", "billing_issue", "product_question",
                        "general_complaint", "shipping_query", "return_request",
                        "praise", "partnership", "spam", "legal_pr", "other",
                    ],
                    "description": (
                        "Normalised issue cluster for spike detection. "
                        "Pick the closest match. Used to identify recurring issue patterns."
                    ),
                },
                "risk_score": {
                    "type": "number",
                    "description": (
                        "0.0 = completely safe to auto-reply. "
                        "1.0 = brand/legal/safety threat requiring human escalation. "
                        "Public replies, money, legal language all raise this."
                    ),
                },
                "confidence_score": {
                    "type": "number",
                    "description": (
                        "Your confidence in the classification and draft reply. "
                        "0.0 = very uncertain (ambiguous message, sarcasm suspected). "
                        "1.0 = very certain (clear intent, straightforward reply). "
                        "Be calibrated — low confidence triggers human review."
                    ),
                },
                "tier": {
                    "type": "string",
                    "enum": ["auto", "draft_approve", "escalate"],
                    "description": (
                        "auto         – risk < 0.35, reply immediately without human review.\n"
                        "draft_approve – 0.35–0.74, draft reply but wait for human approval.\n"
                        "escalate     – risk >= 0.75, no draft, human handles manually."
                    ),
                },
                "reasoning": {
                    "type": "string",
                    "description": (
                        "1-2 sentences explaining the routing decision. "
                        "Shown to the human reviewer in the approval dashboard."
                    ),
                },
                "draft_reply": {
                    "type": "string",
                    "description": (
                        "Ready-to-send reply in the brand's voice — EMPATHETIC tone. "
                        "REQUIRED for auto and draft_approve tiers. "
                        "Must be in the SAME LANGUAGE as the customer's message. "
                        "Omit (null) for escalate. "
                        "Never promise refunds or make financial commitments."
                    ),
                },
                "draft_reply_alt": {
                    "type": "string",
                    "description": (
                        "Alternative reply in EFFICIENT/CONCISE tone (contrasts with draft_reply). "
                        "Provide this alongside draft_reply so the human reviewer can pick their preferred style. "
                        "Same language as the customer. Null for escalate tier."
                    ),
                },
                "language": {
                    "type": "string",
                    "description": (
                        "ISO 639-1 code of the customer's message language. "
                        "Examples: 'en', 'fr', 'ar', 'es', 'zh', 'de', 'ja'."
                    ),
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": (
                        "Business urgency, independent of risk. "
                        "high/critical messages should be surfaced first in the dashboard."
                    ),
                },
                "sarcasm_flag": {
                    "type": "boolean",
                    "description": (
                        "True if the message contains sarcasm or irony. "
                        "Examples: 'wow, love waiting 3 weeks 🙃', 'great customer service as always 😒'. "
                        "When true, set confidence_score lower and do NOT auto-reply."
                    ),
                },
                "routing_team": {
                    "type": "string",
                    "enum": ["billing", "support_eng", "comms_lead", "general"],
                    "description": (
                        "billing     – refunds, charges, payment issues.\n"
                        "support_eng – technical bugs, site down, app errors.\n"
                        "comms_lead  – PR risk, media, high-follower accounts, legal threats.\n"
                        "general     – everything else."
                    ),
                },
                "legal_block": {
                    "type": "boolean",
                    "description": (
                        "True if the message mentions lawsuits, injury, journalists, "
                        "discrimination, or any legal/PR landmine. "
                        "When true, ALWAYS escalate and NEVER auto-send regardless of confidence."
                    ),
                },
                "content_en": {
                    "type": "string",
                    "description": (
                        "English translation of the customer's message. "
                        "If the customer's message is already in English, copy the original message here."
                    ),
                },
                "draft_reply_en": {
                    "type": "string",
                    "description": (
                        "English translation of the draft_reply. "
                        "If the draft_reply is already in English, copy it here. "
                        "Set to empty string or null if no draft reply is generated."
                    ),
                },
                "ai_assist_analysis": {
                    "type": "string",
                    "description": (
                        "Analysis of the complicated situation. Explain the risk, why it is high risk or escalated, "
                        "and what issues/sarcasm/history details to note. Set to empty string if not a complicated situation."
                    ),
                },
                "ai_assist_steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "3 short, actionable step-by-step instructions for a human operator to resolve this issue "
                        "(e.g., '1. Look up order #12345 in CRM', '2. Verify delivery status', '3. Email customer status update'). "
                        "Empty array if not complicated."
                    ),
                },
                "ai_assist_suggested_reply": {
                    "type": "string",
                    "description": (
                        "A draft response template designed specifically for a human agent to review, edit, and send for "
                        "this complicated or escalated situation. Same language as customer. Empty string if not complicated."
                    ),
                },
                "sentiment": {
                    "type": "string",
                    "enum": ["positive", "neutral", "negative", "very_negative"],
                    "description": "Customer sentiment detected in the message."
                },
            },
            "required": [
                "intent", "intent_cluster", "risk_score", "confidence_score",
                "tier", "reasoning", "language", "urgency",
                "sarcasm_flag", "routing_team", "legal_block",
                "content_en", "draft_reply_en",
                "ai_assist_analysis", "ai_assist_steps", "ai_assist_suggested_reply",
                "sentiment",
            ],
        },
    },
}

SYSTEM_PROMPT = """You are the triage engine for a brand's LoopBack social media management system.

Classify every inbound social media message and route it to one of three tiers:

  AUTO          risk < 0.35   – Reply immediately. Use for: FAQs, spam, simple praise.
  DRAFT+APPROVE 0.35–0.74     – Draft reply, human approves before it goes live.
                                Use for: order issues, refunds, partnerships, nuanced complaints.
  ESCALATE      risk >= 0.75  – No draft at all. Human handles manually.
                                Use for: legal threats, safety/health, PR crises, media.

Hard rules (NEVER override these):
  1. Legal language ("lawyer", "sue", "lawsuit", "attorney", "legal action") → escalate, risk >= 0.90, legal_block = true
  2. Physical harm / allergic reaction / medical issue → escalate, risk >= 0.95, legal_block = true
  3. Journalist / press / media inquiry → escalate, risk >= 0.90, legal_block = true, routing_team = "comms_lead"
  4. Discrimination / harassment mentions → escalate, risk >= 0.90, legal_block = true, routing_team = "comms_lead"
  5. Spam → auto, risk = 0.05, draft_reply = "SPAM_NO_REPLY"
  6. Ambiguous messages: read emotional tone. Mild negative → draft_approve. Neutral/positive → auto.
  7. If sarcasm_flag = true → set confidence_score <= 0.60 and do NOT set tier to "auto".

Sarcasm detection rules:
  - Watch for: 🙃 😒 🤣 combined with complaints, "great service as always", "love how", "wow thanks for nothing"
  - Sarcasm makes sentiment appear neutral/positive when it's actually negative.
  - When detected: set sarcasm_flag = true, bump risk by ~0.15, lower confidence.

Sentiment classification rules:
  - Classify the emotional tone into one of the following:
    - positive      – praise, compliments, happy emojis, partnership offers.
    - neutral       – factual inquiries, order lookup requests, general business questions.
    - negative      – delay complaints, minor packaging issues, sarcasm (which is covertly negative).
    - very_negative – anger, legal threats, severe damage, multiple ignored contacts, physical harm.

Intent clustering rules:
  - Map to the closest intent_cluster enum value.
  - "order delay", "where is my package", "tracking" → "order_delay"
  - "refund", "money back", "charge" → "refund_request"
  - "broken", "damaged", "defective", "arrived broken" → "damaged_item"
  - "website down", "app not working", "error 500", "can't login" → "site_down"
  - "billing", "invoice", "overcharged" → "billing_issue"

Routing team rules:
  - billing_issue, refund_request → "billing"
  - site_down, technical bugs → "support_eng"
  - legal_block = true, high-follower accounts, PR → "comms_lead"
  - everything else → "general"

Platform-specific tone guidance for draft_reply:
  - Twitter/X: ≤280 characters, concise, direct, minimal punctuation.
  - Instagram: warm, slightly casual, can use 1 emoji.
  - Facebook: professional but friendly, slightly longer is fine.
  - LinkedIn: formal, professional tone.
  - TikTok: casual, empathetic, use the customer's name if known.
  - DM (any platform): warmer, more personal than public replies.

Draft reply style (empathetic — primary):
  - 1–3 sentences, warm and professional.
  - Never promise refunds, credits, or specific actions (requires human approval).
  - Sign off as "the team" not as a named person.
  - Match the customer's language exactly.

Draft reply alt (efficient — secondary):
  - Same message, but stripped to essentials: fewer words, more action-oriented.
  - Still polite, still in the customer's language.

Confidence calibration:
  - 0.90–1.0: Clear intent, simple reply, no ambiguity.
  - 0.70–0.89: Mostly clear but some nuance.
  - 0.50–0.69: Ambiguous, possible sarcasm, or complex situation.
  - <0.50: Very uncertain — flag for human review.

Language rules:
  - Detect the language of the customer's message.
  - Write draft_reply AND draft_reply_alt in the SAME language as the customer.
  - Provide English translations for content_en and draft_reply_en.

AI Assistor rules (for complicated/high-risk/escalated situations):
  - If a message has high risk (risk_score >= 0.35, or legal_block = true, or sarcasm_flag = true, or sentiment_trajectory = 'escalating'), generate:
    1. ai_assist_analysis: What is the issue, customer emotion, and critical risks.
    2. ai_assist_steps: 3 clear, actionable steps for the human operator (e.g. check order, refund, partner contact, legal protocol).
    3. ai_assist_suggested_reply: A customized, high-quality, polite draft reply for the human to edit and send. Even if the tier is escalate, generate a suggested reply here!
  - If the ticket is simple/spam/praise, you may set ai_assist_analysis and ai_assist_suggested_reply to empty strings, and ai_assist_steps to an empty list.
"""


# ---------------------------------------------------------------------------
# Core triage function — single event, with retry + fallback
# ---------------------------------------------------------------------------

def _check_legal_block_keywords(content: str) -> bool:
    """Fast pre-check for hard-block trigger words before calling the model."""
    content_lower = content.lower()
    return any(kw in content_lower for kw in LEGAL_BLOCK_KEYWORDS)


def triage_event(event: dict) -> dict:
    """
    Triage one event. Returns the classify_and_route args dict.

    v3 additions:
      - Sentiment trajectory detection from author history
      - Multi-signal risk boost (followers, verified)
      - Contact count injection
      - Hard legal block pre-check

    Retry strategy:
      Attempt 1: qwen-plus, temp=0.2
      Attempt 2: qwen-plus, temp=0.3 (slightly more creative on retry)
      Attempt 3: qwen-turbo (cheaper fallback, still capable)

    Raises if all 3 attempts fail.
    """
    # Build author history context (memory)
    history = get_by_author(event["author"])
    prior = [h for h in history if h["id"] != event["id"]][:3]

    # ── Sentiment trajectory analysis ────────────────────────────────────────
    sentiment_trajectory = "stable"
    contact_count = len([h for h in history if h["id"] != event["id"]])

    if prior:
        # Check if author has unresolved prior contacts
        unresolved = [
            h for h in prior
            if h.get("status") not in ("sent", "auto_handled", "rejected")
        ]
        if len(unresolved) >= 1 and contact_count >= 2:
            sentiment_trajectory = "escalating"

        # Check if prior events had escalating urgency
        urgent_prior = [
            h for h in prior
            if h.get("urgency") in ("high", "critical")
        ]
        if urgent_prior:
            sentiment_trajectory = "escalating"

    # ── Multi-signal risk boost ───────────────────────────────────────────────
    author_followers = event.get("author_followers", 0) or 0
    author_verified  = event.get("author_verified", 0) or 0
    follower_boost   = author_followers >= FOLLOWER_BOOST_THRESHOLD or author_verified

    # ── Hard legal block pre-check ────────────────────────────────────────────
    pre_legal_block = _check_legal_block_keywords(event["content"])

    # ── History block for prompt ──────────────────────────────────────────────
    history_block = ""
    if prior:
        lines = []
        for h in prior:
            lines.append(
                f"  - [{h.get('tier', '?')}] {h.get('intent', '?')}: "
                f"\"{h['content'][:60]}\"  → {h.get('status', '?')}"
            )
        history_block = f"\nPrior contacts from this author (total: {contact_count}):\n" + "\n".join(lines)
        if sentiment_trajectory == "escalating":
            history_block += "\n⚠️ ESCALATING: This author has unresolved prior contacts — bump risk accordingly."

    # Follower context injection
    follower_context = ""
    if author_followers > 10_000:
        follower_context = f"\n⚠️ HIGH-INFLUENCE ACCOUNT: {author_followers:,} followers"
        if author_verified:
            follower_context += " · VERIFIED ✓"
        follower_context += " — treat as elevated risk."

    user_message = (
        f"Platform:    {event['platform']}\n"
        f"Event type:  {event['event_type']}\n"
        f"Author:      {event['author']}\n"
        f"Message:     {event['content']}"
        + history_block
        + follower_context
    )

    models = [
        (MODEL_PRIMARY,  0.2),
        (MODEL_PRIMARY,  0.3),
        (MODEL_FALLBACK, 0.4),
    ]

    last_error = None
    for attempt, (model, temp) in enumerate(models, start=1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_message},
                ],
                tools=[CLASSIFY_TOOL],
                tool_choice={"type": "function", "function": {"name": "classify_and_route"}},
                temperature=temp,
                timeout=30,
            )
            tool_call = response.choices[0].message.tool_calls[0]
            result = json.loads(tool_call.function.arguments)

            # ── Post-processing: apply boosts ──────────────────────────────
            risk = float(result.get("risk_score", 0))

            # Follower/verified boost
            if follower_boost:
                risk = min(1.0, risk + FOLLOWER_BOOST_AMOUNT)

            # Escalating trajectory boost
            if sentiment_trajectory == "escalating":
                risk = min(1.0, risk + ESCALATION_TRAJECTORY_BOOST)

            # Hard legal block override (from model or pre-check)
            model_legal_block = result.get("legal_block", False)
            final_legal_block = bool(model_legal_block or pre_legal_block)
            if final_legal_block:
                risk = max(risk, 0.90)
                result["tier"] = "escalate"

            # Sarcasm: don't auto-send
            if result.get("sarcasm_flag"):
                if result.get("tier") == "auto":
                    result["tier"] = "draft_approve"
                risk = min(1.0, risk + 0.10)

            # Confidence-linked tier adjustment
            confidence = float(result.get("confidence_score", 0.8))
            if confidence < 0.55 and result.get("tier") == "auto":
                result["tier"] = "draft_approve"

            result["risk_score"]           = round(risk, 3)
            result["legal_block"]          = final_legal_block
            result["_model_used"]          = model
            result["_retry_count"]         = attempt - 1
            result["_sentiment_trajectory"] = sentiment_trajectory
            result["_contact_count"]        = contact_count

            log.info(
                "Triaged %s: intent=%s cluster=%s tier=%s risk=%.2f conf=%.2f "
                "lang=%s sarcasm=%s legal=%s route=%s model=%s attempt=%d",
                event["id"][:8], result.get("intent"), result.get("intent_cluster"),
                result.get("tier"), result.get("risk_score", 0),
                result.get("confidence_score", 0),
                result.get("language", "?"),
                result.get("sarcasm_flag", False), final_legal_block,
                result.get("routing_team", "general"),
                model, attempt
            )
            return result

        except Exception as e:
            last_error = e
            wait = 2 ** (attempt - 1)   # 1s, 2s, 4s
            log.warning("Attempt %d failed for %s: %s — retrying in %ds",
                        attempt, event["id"][:8], e, wait)
            if attempt < len(models):
                time.sleep(wait)

    log.error("All attempts failed for %s: %s", event["id"][:8], last_error)
    raise RuntimeError(f"All triage attempts exhausted: {last_error}")


# ---------------------------------------------------------------------------
# Batch triage loop
# ---------------------------------------------------------------------------

def triage_all(verbose: bool = True, max_workers: int = 6) -> int:
    """
    Process all pending_triage events concurrently.

    Each API call is I/O-bound, so ThreadPoolExecutor gives near-linear
    speedup up to the pool size (or the API's concurrency limit).

    Typical improvement over sequential:
      52 events, ~2s avg API latency → serial ≈ 120s, parallel (6) ≈ 20–25s

    Args:
        max_workers: parallel API calls in flight. 6 is safe for DashScope's
                     default rate limit; raise to 10 for high-throughput accounts.
    """
    import time as _time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    init_db()
    pending = get_by_status(STATUS_PENDING_TRIAGE)

    if not pending:
        if verbose:
            _safe_print("No pending events to triage.")
        return 0

    t0 = _time.perf_counter()
    if verbose:
        _safe_print(f"Triaging {len(pending)} event(s) — {max_workers} concurrent workers...\n")

    # ── Thread-safe counters ──────────────────────────────────────────────────
    import threading
    _lock   = threading.Lock()
    success = 0
    failed  = 0

    def _triage_one(event: dict) -> tuple[bool, str]:
        """Triage a single event and write result to DB. Returns (ok, short_msg)."""
        nonlocal success, failed
        event_id = event["id"]
        short    = event["content"][:60].replace("\n", " ")

        try:
            result = triage_event(event)

            draft = result.get("draft_reply") or None
            if draft == "SPAM_NO_REPLY":
                draft = None

            update_triage(
                event_id              = event_id,
                intent                = result["intent"],
                risk_score            = result["risk_score"],
                tier                  = result["tier"],
                reasoning             = result["reasoning"],
                draft_reply           = draft,
                language              = result.get("language", "en"),
                triage_model          = result.get("_model_used", MODEL_PRIMARY),
                retry_count           = result.get("_retry_count", 0),
                urgency               = result.get("urgency", "medium"),
                content_en            = result.get("content_en"),
                draft_reply_en        = result.get("draft_reply_en"),
                # v3 fields
                sentiment_trajectory  = result.get("_sentiment_trajectory", "stable"),
                contact_count         = result.get("_contact_count", 0),
                intent_cluster        = result.get("intent_cluster"),
                sarcasm_flag          = 1 if result.get("sarcasm_flag") else 0,
                draft_reply_alt       = result.get("draft_reply_alt"),
                routing_team          = result.get("routing_team", "general"),
                legal_block           = 1 if result.get("legal_block") else 0,
                confidence_score      = result.get("confidence_score"),
                # AI Assistor fields
                ai_assist_analysis    = result.get("ai_assist_analysis"),
                ai_assist_steps       = result.get("ai_assist_steps"),
                ai_assist_suggested_reply = result.get("ai_assist_suggested_reply"),
                # v3.1 fields
                sentiment             = result.get("sentiment", "neutral"),
            )

            if verbose:
                icon     = {"auto": "✅", "draft_approve": "📋", "escalate": "🚨"}.get(result["tier"], "❓")
                lang     = result.get("language", "?")
                urg      = result.get("urgency", "?")
                conf     = result.get("confidence_score", 0)
                sarc     = "🎭" if result.get("sarcasm_flag") else ""
                legal    = "⚖️" if result.get("legal_block") else ""
                route    = result.get("routing_team", "general")
                cluster  = result.get("intent_cluster", "?")
                fallback = " [FALLBACK]" if result.get("_model_used") != MODEL_PRIMARY else ""
                with _lock:
                    _safe_print(
                        f"  {icon} [{result['tier'].upper():14s}] "
                        f"risk={result['risk_score']:.2f}  conf={conf:.2f}  "
                        f"lang={lang}  urg={urg}  "
                        f"cluster={cluster:18s}  route={route:12s}  "
                        f"{sarc}{legal}{fallback}  "
                        f"\"{short}\""
                    )

            with _lock:
                success += 1
            return True, short

        except Exception as e:
            log.error("Permanently failed %s: %s", event_id[:8], e)
            mark_triage_failed(event_id, str(e))
            with _lock:
                failed += 1
                if verbose:
                    _safe_print(f"  ❌ FAILED \"{short}\" — {e}")
            return False, short

    # ── Dispatch concurrently ─────────────────────────────────────────────────
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_triage_one, ev): ev for ev in pending}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as e:
                log.error("Unhandled future exception: %s", e)

    elapsed = _time.perf_counter() - t0
    if verbose:
        rate = len(pending) / elapsed if elapsed > 0 else 0
        _safe_print(
            f"\nTriaged {success}/{len(pending)} events in {elapsed:.1f}s "
            f"({rate:.1f} events/sec) — {failed} failed."
        )

    return success


def generate_ai_assist_on_demand(event: dict) -> dict:
    """
    Generate AI Assist guidance and suggested reply on-demand for an event.
    """
    history = get_by_author(event["author"])
    prior = [h for h in history if h["id"] != event["id"]][:3]
    contact_count = len([h for h in history if h["id"] != event["id"]])
    
    context = (
        f"Platform: {event['platform']}\n"
        f"Event Type: {event['event_type']}\n"
        f"Author: {event['author']} ({event.get('author_followers', 0):,} followers)\n"
        f"Message Content: {event['content']}\n"
        f"Urgency: {event.get('urgency', 'medium')}\n"
        f"Intent Cluster: {event.get('intent_cluster', 'unknown')}\n"
        f"Prior Contacts: {contact_count}\n"
    )
    if prior:
        context += "Prior History:\n"
        for h in prior:
            context += f"- {h.get('created_at', '')[:10]} [{h.get('status')}]: {h.get('content')[:60]}\n"

    ai_assist_prompt = """You are the Senior AI Copilot and Resolution Advisor for LoopBack.
Analyze this social media interaction and provide guidance to help a human customer support agent resolve it.

Provide your response in JSON format matching this schema:
{
  "analysis": "A concise explanation of the situation, the customer's sentiment, and any risks (sarcasm, legal, high-influence account).",
  "steps": [
    "Step 1: ...",
    "Step 2: ...",
    "Step 3: ..."
  ],
  "suggested_reply": "A professional, empathetic, and platform-specific reply draft in the customer's language. Omit generic greetings unless appropriate. Never make concrete financial promises."
}

Platform-specific tone guidance:
- Twitter/X: Concise, minimal punctuation, direct, <=280 chars.
- Instagram: Warm, friendly, casual, 1 emoji.
- Facebook: Professional, friendly.
- LinkedIn: Formal, professional.
- TikTok: Casual, empathetic.
- DM (any platform): Warm, personal.
"""

    response = client.chat.completions.create(
        model=MODEL_PRIMARY,
        messages=[
            {"role": "system", "content": ai_assist_prompt},
            {"role": "user", "content": context}
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
        timeout=20
    )
    res_dict = json.loads(response.choices[0].message.content)
    return res_dict


def refine_draft_with_ai(customer_msg: str, current_draft: str, instruction: str) -> str:
    """
    Refine a draft response based on user instructions in real time.
    """
    prompt = (
        f"Customer Message: \"{customer_msg}\"\n"
        f"Current Draft: \"{current_draft}\"\n"
        f"Instruction: Please refine the current draft to follow this guidance: \"{instruction}\".\n"
        f"Return ONLY the refined response draft, in the same language as the customer's message. Do not include any chat wrappers, notes, or quotes."
    )
    
    response = client.chat.completions.create(
        model=MODEL_PRIMARY,
        messages=[
            {"role": "system", "content": "You are a professional customer support agent refining a response template."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        timeout=15
    )
    return response.choices[0].message.content.strip().strip('"').strip("'")


if __name__ == "__main__":
    if not API_KEY:
        print("DASHSCOPE_API_KEY not set. Check .env file.")
        raise SystemExit(1)
    triage_all(verbose=True)