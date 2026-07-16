"""
Executor — v3 (intelligence upgrades).

Responsibilities:
  1. Auto-execute AUTO-tier events (no human needed).
  2. Post-approval execution for APPROVED events, with a two-step tool chain:
       Step 1 – Model calls lookup_order() if an order number is present.
       Step 2 – Model generates a personalized reply using the real order data.
  3. CRM tagging — after sending, calls the tag_for_crm tool to classify the
     interaction for downstream CRM systems.
  4. Brand crisis detection — checks if a spike of escalations signals a PR crisis.

New in v3:
  - Confidence-linked routing: low-confidence events never auto-send
  - Hard legal block enforcement: legal_block=1 events always escalate
  - PII redaction check before sending any public reply
  - Auto-learn from edits: saves training signal when human edits AI draft
  - Intent cluster spike detection in crisis check

All outcomes are written back to events.db via store helpers.
"""

import os
import re
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
        _safe_print(*args, **kwargs)
        sys.stdout.flush()
    except (OSError, BrokenPipeError, AttributeError):
        pass


from openai import OpenAI
from dotenv import load_dotenv
from store import (
    init_db, get_by_status, mark_sent, log_crisis,
    save_training_signal, get_intent_cluster_counts, update_triage,
    STATUS_AUTO_HANDLED, STATUS_APPROVED, STATUS_ESCALATED,
    STATUS_AWAITING_APPROVAL, get_setting, get_conn,
)

load_dotenv()

API_KEY = os.getenv("DASHSCOPE_API_KEY")
MODEL   = os.getenv("QWEN_PRIMARY_MODEL", "qwen-turbo")

client = OpenAI(
    api_key=API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
)

logging.basicConfig(
    filename="executor.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("executor")

# ---------------------------------------------------------------------------
# PII detection patterns — public replies only
# ---------------------------------------------------------------------------
PII_PATTERNS = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # email
    re.compile(r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),  # US phone
    re.compile(r"\+\d{1,3}[\s\-]?\(?\d{1,4}\)?[\s\-]?\d{2,4}[\s\-]?\d{2,4}[\s\-]?\d{0,4}"),  # intl phone (+XX…)
    re.compile(r"\b\d{1,5}\s+\w[\w\s]+\b(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr)\b", re.I),  # address
    re.compile(r"\b\d{16}\b"),   # card number (16 digits)
    re.compile(r"\b\d{9}\b"),    # SSN-ish
]

# DM platforms — PII acceptable in DM context
DM_PLATFORMS = {"email", "dm"}

# Confidence threshold for auto-send
AUTO_SEND_CONFIDENCE_MIN = 0.80

# Intent cluster spike threshold
CLUSTER_SPIKE_COUNT = 10   # same cluster >= 10 times in 60 min = crisis


def _check_pii(text: str, platform: str) -> bool:
    """Return True if PII is detected in a public-channel reply."""
    if not text:
        return False
    if platform.lower() in DM_PLATFORMS:
        return False   # PII OK in DM context
    for pattern in PII_PATTERNS:
        if pattern.search(text):
            return True
    return False


# ---------------------------------------------------------------------------
# Tool 1: Order / refund lookup (mocked — swap in your OMS API call here)
# ---------------------------------------------------------------------------
ORDER_LOOKUP_TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_order",
        "description": "Look up an order by order number and return current status and details.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_number": {
                    "type": "string",
                    "description": "The order number (digits only, e.g. '48213').",
                },
            },
            "required": ["order_number"],
        },
    },
}

# ---------------------------------------------------------------------------
# Tool 2: CRM categorisation — called after every sent reply
# ---------------------------------------------------------------------------
CRM_TAG_TOOL = {
    "type": "function",
    "function": {
        "name": "tag_for_crm",
        "description": "Categorize a resolved customer interaction for CRM logging.",
        "parameters": {
            "type": "object",
            "properties": {
                "crm_category": {
                    "type": "string",
                    "enum": [
                        "shipping_delay", "product_defect", "billing_issue",
                        "general_inquiry", "spam_ignored", "partnership_lead",
                        "positive_feedback", "safety_escalated", "legal_escalated", "other",
                    ],
                    "description": "CRM category for the interaction.",
                },
                "follow_up_required": {
                    "type": "boolean",
                    "description": "True if a follow-up action is needed within follow_up_days.",
                },
                "follow_up_days": {
                    "type": "integer",
                    "description": "Number of days until follow-up is due. 0 if no follow-up needed.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "CRM ticket priority.",
                },
                "sentiment": {
                    "type": "string",
                    "enum": ["positive", "neutral", "negative", "very_negative"],
                },
            },
            "required": ["crm_category", "follow_up_required", "follow_up_days", "priority", "sentiment"],
        },
    },
}


# ---------------------------------------------------------------------------
# Mock order database (replace with real API call in production)
# ---------------------------------------------------------------------------
MOCK_ORDERS = {
    "48213": {
        "order_number":       "48213",
        "status":             "In Transit",
        "carrier":            "FedEx",
        "tracking_number":    "748923498237",
        "estimated_delivery": "2026-07-08",
        "items":              ["Blue Denim Jacket (M)"],
        "delay_reason":       "Weather disruption at Memphis hub",
        "order_date":         "2026-06-28",
    },
    "92841": {
        "order_number":       "92841",
        "status":             "Delivered",
        "carrier":            "UPS",
        "tracking_number":    "1Z999AA10123456784",
        "delivered_at":       "2026-07-01",
        "items":              ["Running Shoes (EU 42)"],
        "delay_reason":       None,
        "order_date":         "2026-06-25",
    },
}


def _mock_lookup_order(order_number: str) -> dict:
    """
    Mocked order lookup.
    In production: replace this with a real OMS/ERP API call.
    """
    return MOCK_ORDERS.get(
        order_number,
        {
            "order_number": order_number,
            "status":       "Not Found",
            "note":         "No order with this number found in our system.",
        },
    )


def _extract_order_number(text: str) -> str | None:
    """Heuristic: extract first 4–6 digit order reference from text."""
    m = re.search(r"#?(\d{4,6})", text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# CRM tagging tool chain
# ---------------------------------------------------------------------------

def _tag_for_crm(event: dict, sent_reply: str) -> dict | None:
    """
    After sending a reply, call Qwen with the CRM tagging tool to classify
    the interaction for downstream CRM systems.
    Returns the CRM tags dict, or None if the call fails.
    """
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a CRM analyst. Given a resolved customer interaction, "
                        "classify it for CRM logging using the tag_for_crm tool."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Customer message: {event['content']}\n"
                        f"Intent: {event.get('intent', 'unknown')}\n"
                        f"Risk score: {event.get('risk_score', 0)}\n"
                        f"Reply sent: {sent_reply[:200]}"
                    ),
                },
            ],
            tools=[CRM_TAG_TOOL],
            tool_choice={"type": "function", "function": {"name": "tag_for_crm"}},
            temperature=0.1,
            timeout=20,
        )
        tc = response.choices[0].message.tool_calls[0]
        tags = json.loads(tc.function.arguments)
        log.info("CRM tagged %s: %s", event["id"][:8], tags)
        return tags
    except Exception as e:
        log.warning("CRM tagging failed for %s: %s", event["id"][:8], e)
        return None


# ---------------------------------------------------------------------------
# Order lookup + personalized reply tool chain
# ---------------------------------------------------------------------------

def _tool_call_reply(event: dict, verbose: bool = False) -> str:
    """
    Two-step tool chain:
      1. Model calls lookup_order with the extracted order number.
      2. We execute the mock lookup and return the result.
      3. Model generates a personalized reply using the real order data.

    Falls back to draft_reply if anything goes wrong.
    """
    order_number = _extract_order_number(event["content"])
    if not order_number:
        return event.get("draft_reply") or ""

    if verbose:
        _safe_print(f"       Running order lookup for #{order_number}...")

    messages = [
        {
            "role": "system",
            "content": (
                "You are a customer support agent. A human has approved handling this message. "
                "Use lookup_order to fetch the customer's order status, then write a warm, "
                "helpful reply using the actual data. 2-3 sentences max. "
                "Translate any order details, carrier names, and status descriptions (e.g. 'In Transit', 'Weather disruption') "
                "into the target language so the entire reply is 100% in that language. "
                f"Reply in the same language as the customer's message: "
                f"{event.get('language', 'en')}."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Customer ({event['author']}) on {event['platform']}: {event['content']}"
            ),
        },
    ]

    try:
        # Step 1: Model decides to call lookup_order
        r1 = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=[ORDER_LOOKUP_TOOL],
            tool_choice="auto",
            temperature=0.3,
            timeout=25,
        )
        msg1 = r1.choices[0].message

        if not msg1.tool_calls:
            return msg1.content or event.get("draft_reply", "")

        # Step 2: Execute mock tool
        tc      = msg1.tool_calls[0]
        ord_num = json.loads(tc.function.arguments).get("order_number", order_number)
        data    = _mock_lookup_order(ord_num)

        if verbose:
            _safe_print(f"       Order data: status={data.get('status')} carrier={data.get('carrier')}")

        messages.append(msg1)
        messages.append({
            "role":         "tool",
            "tool_call_id": tc.id,
            "content":      json.dumps(data),
        })

        # Step 3: Model generates personalized reply
        r2 = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.4,
            timeout=25,
        )
        return r2.choices[0].message.content or event.get("draft_reply", "")

    except Exception as e:
        log.warning("Tool chain failed for %s: %s — falling back to draft", event["id"][:8], e)
        return event.get("draft_reply") or ""


# ---------------------------------------------------------------------------
# Auto-execute
# ---------------------------------------------------------------------------

def execute_auto_events(verbose: bool = True) -> int:
    """Mark all auto_handled events as sent using their draft_reply."""
    events = get_by_status(STATUS_AUTO_HANDLED)
    if not events:
        if verbose:
            _safe_print("No auto-handled events to execute.")
        return 0

    count = 0
    for ev in events:
        intent     = ev.get("intent", "")
        draft      = ev.get("draft_reply") or ""

        # Hard legal block — never auto-send even in auto tier
        if ev.get("legal_block"):
            log.warning("Legal block prevented auto-send for %s — re-escalating", ev["id"][:8])
            if verbose:
                _safe_print(f"  ⚖️ LEGAL BLOCK — escalated (was auto): {ev['author']}")
            # Re-route to escalated via store directly
            from store import get_conn, _now, STATUS_ESCALATED
            from store import _write_audit
            with get_conn() as conn:
                conn.execute(
                    "UPDATE events SET status = ?, updated_at = ? WHERE id = ?",
                    (STATUS_ESCALATED, _now(), ev["id"])
                )
                _write_audit(conn, ev["id"], STATUS_AUTO_HANDLED, STATUS_ESCALATED,
                             "executor", "Legal block override — escalated from auto")
            continue

        # Confidence check — don't auto-send if confidence is too low or category weight is too high
        min_conf = float(get_setting("autopilot_confidence_threshold", "0.95"))
        esc_thresh = float(get_setting("autopilot_escalation_threshold", "0.7"))

        confidence = ev.get("confidence_score") or 1.0
        category_weights = {
            "damaged_item": 0.9,
            "refund_request": 0.8,
            "billing_issue": 0.7,
            "order_delay": 0.6,
            "general_complaint": 0.5,
            "site_down": 0.9,
            "product_question": 0.3,
            "shipping_query": 0.3,
            "return_request": 0.5,
            "partnership": 0.3,
            "praise": 0.1,
            "spam": 0.0,
            "legal_pr": 0.95,
            "other": 0.3
        }
        category_weight = category_weights.get(ev.get("intent_cluster"), 0.3)

        if not (confidence >= min_conf and category_weight < esc_thresh) and not (intent == "spam"):
            reason = ""
            if confidence < min_conf:
                reason += f"confidence {confidence:.2f} < {min_conf:.2f}"
            if category_weight >= esc_thresh:
                if reason: reason += " and "
                reason += f"category weight {category_weight:.2f} >= {esc_thresh:.2f}"

            log.info("Autopilot gating prevented auto-send for %s (%s) — moving to inbox",
                     ev["id"][:8], reason)
            if verbose:
                _safe_print(f"  📋 GATED AUTOPILOT ({reason}) → moved to inbox: {ev['author']}")
            from store import get_conn, _now
            with get_conn() as conn:
                conn.execute(
                    """UPDATE events 
                       SET status = ?, autopilot_decision = ?, autopilot_reason = ?, updated_at = ? 
                       WHERE id = ?""",
                    (STATUS_AWAITING_APPROVAL, "escalated", f"Gated: {reason}", _now(), ev["id"])
                )
            continue

        if intent == "spam" or not draft:
            final_reply = "[SPAM — logged, no reply sent]"
            crm = None
            pii = 0
            auto_dec = "approved"
            auto_reas = "Spam auto-ignored"
        else:
            # PII check before public auto-send
            pii = 1 if _check_pii(draft, ev.get("platform", "")) else 0
            if pii:
                log.warning("PII detected in auto-reply for %s — routing to inbox", ev["id"][:8])
                if verbose:
                    _safe_print(f"  🔒 PII DETECTED — moved to inbox for review: {ev['author']}")
                from store import get_conn, _now
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE events SET status = ?, pii_flagged = 1, updated_at = ? WHERE id = ?",
                        (STATUS_AWAITING_APPROVAL, _now(), ev["id"])
                    )
                continue

            final_reply = draft
            crm = _tag_for_crm(ev, final_reply) if API_KEY else None
            auto_dec = "approved"
            auto_reas = f"Confidence {confidence:.2f} >= {min_conf:.2f} and category weight {category_weight:.2f} < {esc_thresh:.2f}"

        # Write decision to DB
        from store import get_conn
        with get_conn() as conn:
            conn.execute(
                "UPDATE events SET autopilot_decision = ?, autopilot_reason = ? WHERE id = ?",
                (auto_dec, auto_reas, ev["id"])
            )

        mark_sent(ev["id"], final_reply, crm_tags=crm, pii_flagged=pii)
        count += 1

        if verbose:
            _safe_print(f"  Sent (auto)  {ev['author']}  \"{ev['content'][:50]}\"")

    if verbose:
        _safe_print(f"Auto-executed {count} event(s).")
    return count


# ---------------------------------------------------------------------------
# Post-approval execute
# ---------------------------------------------------------------------------

def execute_approved_events(verbose: bool = True) -> int:
    """
    Pick up APPROVED events. For order/complaint types, run the full
    tool-call chain. Others use the human-approved final_reply or draft.
    """
    events = get_by_status(STATUS_APPROVED)
    if not events:
        if verbose:
            _safe_print("No approved events to execute.")
        return 0

    count = 0
    for ev in events:
        # Human may have edited the reply; use final_reply if set
        reply = ev.get("final_reply") or ev.get("draft_reply") or ""

        # Hard legal block — never send even if approved (edge-case safety)
        if ev.get("legal_block"):
            log.warning("Legal block prevented approved send for %s", ev["id"][:8])
            if verbose:
                _safe_print(f"  ⚖️ LEGAL BLOCK on approved event — skipping: {ev['author']}")
            continue

        # Run tool chain for order-related messages
        if ev.get("intent") in ("complaint", "question"):
            if _extract_order_number(ev["content"]):
                reply = _tool_call_reply(ev, verbose=verbose)

        # PII check before any public send
        pii = 1 if _check_pii(reply, ev.get("platform", "")) else 0
        if pii:
            log.warning("PII detected in approved reply for %s — not sending", ev["id"][:8])
            if verbose:
                _safe_print(f"  🔒 PII in approved reply — flagged, not sent: {ev['author']}")
            from store import get_conn, _now
            with get_conn() as conn:
                conn.execute(
                    "UPDATE events SET pii_flagged = 1, updated_at = ? WHERE id = ?",
                    (_now(), ev["id"])
                )
            continue

        crm = _tag_for_crm(ev, reply) if API_KEY else None

        mark_sent(ev["id"], reply or "[No reply — escalated to manual handling]",
                  crm_tags=crm, pii_flagged=pii)

        # ── Auto-learn from edits ────────────────────────────────────────────
        original_draft = ev.get("draft_reply") or ""
        final_reply    = reply
        if original_draft and final_reply and original_draft != final_reply and API_KEY:
            try:
                save_training_signal(
                    event_id=ev["id"],
                    original_draft=original_draft,
                    human_edit=final_reply,
                    platform=ev.get("platform", ""),
                    intent=ev.get("intent", ""),
                )
                log.info("Training signal saved for %s", ev["id"][:8])
            except Exception as e:
                log.warning("Failed to save training signal for %s: %s", ev["id"][:8], e)

        count += 1

        if verbose:
            _safe_print(f"  Sent (approved) {ev['author']}  \"{ev['content'][:50]}\"")
            if reply:
                _safe_print(f"     Reply: {reply[:100]}")

    if verbose:
        _safe_print(f"Executed {count} approved event(s).")
    return count


# ---------------------------------------------------------------------------
# Brand crisis detector — v3: adds intent cluster spike detection
# ---------------------------------------------------------------------------

def check_for_crisis(window_minutes: int = 10, threshold: int = 3,
                     verbose: bool = True) -> bool:
    """
    Detects a brand crisis in two ways:
      1. Classic: >= threshold escalated events in the last window_minutes
      2. Cluster spike: a single intent_cluster appears >= CLUSTER_SPIKE_COUNT times in 60 min
    """
    from datetime import datetime, timezone, timedelta

    crisis_detected = False

    # ── Classic escalation spike ───────────────────────────────────────────────
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat()

    # Targeted SQL query — avoids full table scan and bypasses the 500-row get_all() cap
    with get_conn() as _conn:
        _rows = _conn.execute(
            """SELECT id FROM events
               WHERE status = ? AND created_at >= ?""",
            (STATUS_ESCALATED, cutoff)
        ).fetchall()
    recent_escalations = [dict(r) for r in _rows]

    if len(recent_escalations) >= threshold:
        ids = [e["id"] for e in recent_escalations]
        crisis_id = log_crisis(window_minutes, len(recent_escalations), ids)
        if verbose:
            _safe_print(
                f"  🚨 BRAND CRISIS DETECTED: {len(recent_escalations)} escalations "
                f"in {window_minutes}min window (crisis_id={crisis_id[:8]})"
            )
        log.error(
            "BRAND CRISIS: %d escalations in %dmin — crisis_id=%s",
            len(recent_escalations), window_minutes, crisis_id
        )
        crisis_detected = True

    # ── Intent cluster spike detection ────────────────────────────────────────
    cluster_counts = get_intent_cluster_counts(window_hours=1)
    for cluster, count in cluster_counts.items():
        if count >= CLUSTER_SPIKE_COUNT:
            # Targeted query for spike IDs — no all_events scan needed
            with get_conn() as _conn:
                _spike_rows = _conn.execute(
                    "SELECT id FROM events WHERE intent_cluster = ? LIMIT 20",
                    (cluster,)
                ).fetchall()
            spike_ids = [r["id"] for r in _spike_rows]
            crisis_id = log_crisis(60, count, spike_ids, cluster_name=cluster)
            if verbose:
                _safe_print(
                    f"  🔥 CLUSTER SPIKE DETECTED: '{cluster}' × {count} in last 60min "
                    f"(crisis_id={crisis_id[:8]})"
                )
            log.error(
                "CLUSTER SPIKE: cluster=%s count=%d — crisis_id=%s",
                cluster, count, crisis_id
            )
            crisis_detected = True

    return crisis_detected


# ---------------------------------------------------------------------------
# Convenience: run all executors
# ---------------------------------------------------------------------------

def execute_all(verbose: bool = True):
    init_db()
    _safe_print("\n=== Auto-Execute ===")
    execute_auto_events(verbose=verbose)
    _safe_print("\n=== Post-Approval Execute ===")
    execute_approved_events(verbose=verbose)
    _safe_print("\n=== Crisis Check ===")
    check_for_crisis(verbose=verbose)


if __name__ == "__main__":
    if not API_KEY:
        _safe_print("DASHSCOPE_API_KEY not set.")
        raise SystemExit(1)
    execute_all(verbose=True)
