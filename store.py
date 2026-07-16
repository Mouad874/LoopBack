"""
Shared data store for LoopBack.

Both the backend agent loop (ingestion -> triage -> routing) and the
Streamlit approval dashboard read/write to this same SQLite file.

    backend  --writes-->  events.db  <--reads/writes--  streamlit dashboard
       ^                                                       |
       '------------------- picks up approved items -----------'

SQLite gives us atomic writes and safe multi-process access without any
infrastructure overhead.

Schema v3 additions (intelligence upgrades):
  - sentiment_trajectory : "stable" | "escalating" | "de-escalating"
  - contact_count        : how many times this author has contacted before
  - intent_cluster       : normalised issue tag ("order_delay", "damaged_item", ...)
  - author_followers     : injected from webhook/seed for multi-signal risk
  - author_verified      : 0/1 verified account flag
  - sarcasm_flag         : 0/1 sarcasm/irony detected
  - draft_reply_alt      : A/B alternate tone draft
  - routing_team         : "billing" | "support_eng" | "comms_lead" | "general"
  - legal_block          : 0/1 — never auto-send, hard-escalate
  - pii_flagged          : 0/1 — PII found in draft reply
  - edit_diff            : JSON diff of AI draft → human-edited final
  - confidence_score     : model self-reported confidence 0–1
"""

import sqlite3
import json
import uuid
import threading
import time
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
from pathlib import Path

# Always resolve DB path relative to this file, regardless of CWD
DB_PATH = str(Path(__file__).parent / "events.db")
TRAINING_SIGNALS_PATH = str(Path(__file__).parent / "training_signals.jsonl")

# ---------------------------------------------------------------------------
# Lifecycle states — core state machine
# ---------------------------------------------------------------------------
STATUS_PENDING_TRIAGE    = "pending_triage"     # just ingested
STATUS_AUTO_HANDLED      = "auto_handled"        # low risk, agent replied
STATUS_AWAITING_APPROVAL = "awaiting_approval"   # drafted, waiting on human
STATUS_APPROVED          = "approved"            # human approved the draft
STATUS_REJECTED          = "rejected"            # human rejected
STATUS_ESCALATED         = "escalated"           # too risky, human handles
STATUS_SENT              = "sent"                # reply sent / action done
STATUS_TRIAGE_FAILED     = "triage_failed"       # all retries exhausted

# SLA windows (how long until a human must act)
SLA_HOURS = {
    "auto":          None,   # auto-handled, no human needed
    "draft_approve": 2,      # 2 hours to approve/reject
    "escalate":      1,      # 1 hour for critical escalations
}


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # safe concurrent access
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sla_deadline(tier: str) -> str | None:
    hours = SLA_HOURS.get(tier)
    if hours is None:
        return None
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------------------
# Settings Table Helpers
# ---------------------------------------------------------------------------
def get_setting(key: str, default: str = "") -> str:
    try:
        with get_conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default
    except Exception:
        return default


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


# ---------------------------------------------------------------------------
# Time-Decay Urgency Score Calculations
# ---------------------------------------------------------------------------
def compute_urgency(created_at_str: str, intent_cluster: str | None, sentiment: str | None, sla_threshold_minutes: int = 120) -> tuple[float, dict]:
    # category_weight
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
    category_weight = category_weights.get(intent_cluster, 0.3) if intent_cluster else 0.3

    # sentiment_severity
    sentiment_severities = {
        "positive": 0.0,
        "neutral": 0.25,
        "negative": 0.75,
        "very_negative": 1.0
    }
    sentiment_severity = sentiment_severities.get(sentiment, 0.5) if sentiment else 0.5

    # time factor
    try:
        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        minutes_waiting = max(0.0, (now - created_at).total_seconds() / 60.0)
    except Exception:
        minutes_waiting = 0.0

    time_factor = min(1.0, minutes_waiting / max(1, sla_threshold_minutes))

    urgency_score = (category_weight * 0.4) + (sentiment_severity * 0.3) + (time_factor * 0.3)
    
    explainability = {
        "category_weight": round(category_weight, 3),
        "sentiment_severity": round(sentiment_severity, 3),
        "time_factor": round(time_factor, 3),
        "minutes_waiting": round(minutes_waiting, 1),
        "sla_threshold_minutes": sla_threshold_minutes,
        "category_contribution": round(category_weight * 0.4, 3),
        "sentiment_contribution": round(sentiment_severity * 0.3, 3),
        "time_contribution": round(time_factor * 0.3, 3)
    }
    
    return round(urgency_score, 3), explainability


def update_all_urgency_scores():
    active_statuses = (STATUS_PENDING_TRIAGE, STATUS_AWAITING_APPROVAL, STATUS_ESCALATED, STATUS_APPROVED)
    try:
        with get_conn() as conn:
            rows = conn.execute(
                f"""SELECT id, created_at, intent_cluster, sentiment, sla_threshold_minutes, urgency 
                    FROM events 
                    WHERE status IN (?, ?, ?, ?)""",
                active_statuses
            ).fetchall()
            
            for r in rows:
                sla_thresh = r["sla_threshold_minutes"]
                if not sla_thresh or sla_thresh == 120:
                    sla_thresh = 60 if r["urgency"] in ("high", "critical") else 120
                
                score, exp = compute_urgency(
                    created_at_str=r["created_at"],
                    intent_cluster=r["intent_cluster"],
                    sentiment=r["sentiment"],
                    sla_threshold_minutes=sla_thresh
                )
                
                urg_text = "low"
                if score >= 0.75:
                    urg_text = "critical"
                elif score >= 0.55:
                    urg_text = "high"
                elif score >= 0.35:
                    urg_text = "medium"
                    
                conn.execute(
                    """UPDATE events 
                       SET urgency_score = ?, urgency_explainability = ?, urgency = ?, sla_threshold_minutes = ?
                       WHERE id = ?""",
                    (score, json.dumps(exp), urg_text, sla_thresh, r["id"])
                )
    except sqlite3.OperationalError:
        # Settings or columns might not exist yet during initial DB init
        pass


_scheduler_started = False
_scheduler_lock = threading.Lock()

import logging as _logging
_sched_log = _logging.getLogger("store.urgency_scheduler")

def start_urgency_scheduler():
    global _scheduler_started
    with _scheduler_lock:
        if _scheduler_started:
            return
        _scheduler_started = True
    
    def run():
        while True:
            try:
                update_all_urgency_scores()
            except Exception as e:
                _sched_log.warning("Urgency scheduler error: %s", e)
            time.sleep(60)
            
    t = threading.Thread(target=run, daemon=True)
    t.start()



# ---------------------------------------------------------------------------
# Schema initialisation — safe to call multiple times (IF NOT EXISTS)
# ---------------------------------------------------------------------------
def init_db():
    with get_conn() as conn:
        # Main events table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id             TEXT PRIMARY KEY,
                platform       TEXT NOT NULL,
                event_type     TEXT NOT NULL,
                author         TEXT NOT NULL,
                content        TEXT NOT NULL,
                created_at     TEXT NOT NULL,

                -- triage output
                intent         TEXT,
                risk_score     REAL,
                tier           TEXT,
                reasoning      TEXT,
                language       TEXT DEFAULT 'en',
                triage_model   TEXT,
                retry_count    INTEGER DEFAULT 0,

                 -- replies
                draft_reply    TEXT,
                final_reply    TEXT,

                -- translations
                content_en     TEXT,
                draft_reply_en TEXT,

                -- CRM metadata (JSON blob)
                crm_tags       TEXT,

                -- SLA
                sla_deadline   TEXT,
                sla_breached   INTEGER DEFAULT 0,

                -- urgency (low/medium/high/critical)
                urgency        TEXT DEFAULT 'medium',

                -- lifecycle
                status         TEXT NOT NULL DEFAULT 'pending_triage',
                updated_at     TEXT NOT NULL,
                sent_at        TEXT
            )
        """)

        # v2 migrations
        _add_column_if_missing(conn, "events", "language",     "TEXT DEFAULT 'en'")
        _add_column_if_missing(conn, "events", "triage_model", "TEXT")
        _add_column_if_missing(conn, "events", "retry_count",  "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "events", "crm_tags",     "TEXT")
        _add_column_if_missing(conn, "events", "sla_deadline", "TEXT")
        _add_column_if_missing(conn, "events", "sla_breached", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "events", "sent_at",      "TEXT")
        _add_column_if_missing(conn, "events", "urgency",      "TEXT DEFAULT 'medium'")
        _add_column_if_missing(conn, "events", "content_en",     "TEXT")
        _add_column_if_missing(conn, "events", "draft_reply_en", "TEXT")

        # v3 migrations — intelligence upgrades
        _add_column_if_missing(conn, "events", "sentiment_trajectory", "TEXT DEFAULT 'stable'")
        _add_column_if_missing(conn, "events", "contact_count",        "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "events", "intent_cluster",       "TEXT")
        _add_column_if_missing(conn, "events", "author_followers",     "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "events", "author_verified",      "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "events", "sarcasm_flag",         "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "events", "draft_reply_alt",      "TEXT")
        _add_column_if_missing(conn, "events", "routing_team",         "TEXT DEFAULT 'general'")
        _add_column_if_missing(conn, "events", "legal_block",          "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "events", "pii_flagged",          "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "events", "edit_diff",            "TEXT")
        _add_column_if_missing(conn, "events", "confidence_score",     "REAL")
        _add_column_if_missing(conn, "events", "ai_assist_analysis",        "TEXT")
        _add_column_if_missing(conn, "events", "ai_assist_steps",           "TEXT")
        _add_column_if_missing(conn, "events", "ai_assist_suggested_reply",  "TEXT")

        # v3.1 migrations
        _add_column_if_missing(conn, "events", "urgency_score",        "REAL DEFAULT 0.0")
        _add_column_if_missing(conn, "events", "sla_threshold_minutes","INTEGER DEFAULT 120")
        _add_column_if_missing(conn, "events", "sentiment",            "TEXT DEFAULT 'neutral'")
        _add_column_if_missing(conn, "events", "autopilot_decision",   "TEXT")
        _add_column_if_missing(conn, "events", "autopilot_reason",     "TEXT")
        _add_column_if_missing(conn, "events", "urgency_explainability","TEXT")

        # v4 migrations — production upgrade
        _add_column_if_missing(conn, "events", "source_url", "TEXT")   # direct link to original post/comment

        # Settings table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('autopilot_confidence_threshold', '0.95')")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('autopilot_escalation_threshold', '0.7')")

        # Brand crisis log
        conn.execute("""
            CREATE TABLE IF NOT EXISTS crisis_log (
                id           TEXT PRIMARY KEY,
                detected_at  TEXT NOT NULL,
                window_mins  INTEGER NOT NULL,
                event_count  INTEGER NOT NULL,
                event_ids    TEXT NOT NULL,   -- JSON array of event IDs
                resolved     INTEGER DEFAULT 0,
                resolved_at  TEXT,
                cluster_name TEXT             -- v3: intent cluster that spiked (if any)
            )
        """)
        _add_column_if_missing(conn, "crisis_log", "cluster_name", "TEXT")

        # Immutable audit log — one row per state transition
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id         TEXT PRIMARY KEY,
                event_id   TEXT NOT NULL,
                from_status TEXT,
                to_status  TEXT NOT NULL,
                actor      TEXT NOT NULL,   -- 'system' | 'triage' | 'human' | 'executor'
                note       TEXT,
                ts         TEXT NOT NULL
            )
        """)

        # Webhook source log — track where events came from
        conn.execute("""
            CREATE TABLE IF NOT EXISTS webhook_log (
                id          TEXT PRIMARY KEY,
                event_id    TEXT,
                source_ip   TEXT,
                raw_payload TEXT,
                received_at TEXT NOT NULL,
                status      TEXT DEFAULT 'accepted'
            )
        """)

        # Indexes for common query patterns
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_status ON events(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_author ON events(author)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_cluster ON events(intent_cluster)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_sla ON events(sla_deadline)")

    # Start the background urgency scheduler thread
    start_urgency_scheduler()


def _add_column_if_missing(conn, table, column, col_def):
    """Safe migration helper — adds a column only if it doesn't exist yet."""
    existing = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


# ---------------------------------------------------------------------------
# Core CRUD helpers
# ---------------------------------------------------------------------------

def insert_event(platform, event_type, author, content, created_at=None,
                 source_ip=None, raw_payload=None,
                 author_followers=0, author_verified=0,
                 source_url=None) -> str:
    """Insert a new social event into the DB.

    Args:
        source_url: Direct URL to the original post/comment on the platform
                    (e.g. https://www.instagram.com/p/ABC123/).
                    Stored so agents can click through to the real post.
    """
    event_id = str(uuid.uuid4())
    ts = created_at or _now()
    # Compute initial urgency score
    score, exp = compute_urgency(
        created_at_str=ts,
        intent_cluster=None,
        sentiment=None,
        sla_threshold_minutes=120
    )
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO events
               (id, platform, event_type, author, content, created_at,
                author_followers, author_verified, status, updated_at,
                urgency_score, urgency_explainability, source_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, platform, event_type, author, content, ts,
             author_followers, author_verified, STATUS_PENDING_TRIAGE, _now(),
             score, json.dumps(exp), source_url)
        )
        # Log webhook source if metadata provided
        if source_ip or raw_payload:
            conn.execute(
                """INSERT INTO webhook_log
                   (id, event_id, source_ip, raw_payload, received_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), event_id, source_ip,
                 raw_payload, _now())
            )
        _write_audit(conn, event_id, None, STATUS_PENDING_TRIAGE, "system",
                     f"Ingested from {platform}/{event_type}")
    return event_id


def update_triage(event_id, intent, risk_score, tier, reasoning,
                  draft_reply=None, language="en",
                  triage_model="qwen-plus", retry_count=0,
                  urgency="medium", content_en=None, draft_reply_en=None,
                  # v3 fields
                  sentiment_trajectory="stable", contact_count=0,
                  intent_cluster=None, sarcasm_flag=0, draft_reply_alt=None,
                  routing_team="general", legal_block=0, confidence_score=None,
                  ai_assist_analysis=None, ai_assist_steps=None, ai_assist_suggested_reply=None,
                  # v3.1 fields
                  sentiment="neutral"):
    """Called after the Qwen triage step classifies an event."""
    new_status = {
        "auto":         STATUS_AUTO_HANDLED,
        "draft_approve": STATUS_AWAITING_APPROVAL,
        "escalate":     STATUS_ESCALATED,
    }[tier]

    sla = _sla_deadline(tier)
    sla_thresh = 60 if tier == "escalate" or urgency in ("high", "critical") else 120

    with get_conn() as conn:
        old = conn.execute("SELECT status, created_at FROM events WHERE id = ?", (event_id,)).fetchone()
        old_status = old["status"] if old else None
        created_at_str = old["created_at"] if old else _now()

        score, exp = compute_urgency(
            created_at_str=created_at_str,
            intent_cluster=intent_cluster,
            sentiment=sentiment,
            sla_threshold_minutes=sla_thresh
        )

        urg_text = "low"
        if score >= 0.75:
            urg_text = "critical"
        elif score >= 0.55:
            urg_text = "high"
        elif score >= 0.35:
            urg_text = "medium"

        conn.execute(
            """UPDATE events
               SET intent = ?, risk_score = ?, tier = ?, reasoning = ?,
                   draft_reply = ?, language = ?, triage_model = ?,
                   retry_count = ?, sla_deadline = ?, urgency = ?,
                   content_en = ?, draft_reply_en = ?,
                   sentiment_trajectory = ?, contact_count = ?,
                   intent_cluster = ?, sarcasm_flag = ?, draft_reply_alt = ?,
                   routing_team = ?, legal_block = ?, confidence_score = ?,
                   ai_assist_analysis = ?, ai_assist_steps = ?, ai_assist_suggested_reply = ?,
                   urgency_score = ?, urgency_explainability = ?, sentiment = ?, sla_threshold_minutes = ?,
                   status = ?, updated_at = ?
               WHERE id = ?""",
            (intent, risk_score, tier, reasoning, draft_reply,
             language, triage_model, retry_count, sla, urg_text,
             content_en, draft_reply_en,
             sentiment_trajectory, contact_count,
             intent_cluster, sarcasm_flag, draft_reply_alt,
             routing_team, legal_block, confidence_score,
             ai_assist_analysis, json.dumps(ai_assist_steps) if isinstance(ai_assist_steps, list) else ai_assist_steps, ai_assist_suggested_reply,
             score, json.dumps(exp), sentiment, sla_thresh,
             new_status, _now(), event_id)
        )
        _write_audit(conn, event_id, old_status, new_status, "triage",
                     f"intent={intent} risk={risk_score:.2f} tier={tier} lang={language} "
                     f"urgency={urg_text} urgency_score={score:.2f} cluster={intent_cluster} sarcasm={sarcasm_flag} "
                     f"legal_block={legal_block} confidence={confidence_score} sentiment={sentiment}")


def save_ai_assist(event_id, analysis, steps, suggested_reply):
    """Save AI assist details on-demand or during refinement."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE events
               SET ai_assist_analysis = ?,
                   ai_assist_steps = ?,
                   ai_assist_suggested_reply = ?,
                   updated_at = ?
               WHERE id = ?""",
            (analysis, json.dumps(steps) if isinstance(steps, list) else steps, suggested_reply, _now(), event_id)
        )


def set_decision(event_id, decision, edited_reply=None):
    """Called from the dashboard when a human approves/rejects."""
    assert decision in (STATUS_APPROVED, STATUS_REJECTED)
    with get_conn() as conn:
        old = conn.execute("SELECT status, draft_reply FROM events WHERE id = ?", (event_id,)).fetchone()
        old_draft = old["draft_reply"] if old else None

        # Compute edit_diff if human changed the draft
        edit_diff_json = None
        if edited_reply and old_draft and edited_reply != old_draft:
            edit_diff_json = json.dumps({
                "original": old_draft,
                "edited": edited_reply,
                "changed": True,
            })

        # Set autopilot decision
        if decision == STATUS_APPROVED:
            auto_dec = "approved_with_edits" if (edit_diff_json is not None) else "approved"
            auto_reas = "Human edited and approved" if (edit_diff_json is not None) else "Human approved draft"
        else:
            auto_dec = "rejected"
            auto_reas = "Human rejected draft"

        conn.execute(
            """UPDATE events 
               SET status = ?, final_reply = ?, edit_diff = ?, 
                   autopilot_decision = ?, autopilot_reason = ?, updated_at = ? 
               WHERE id = ?""",
            (decision, edited_reply, edit_diff_json, auto_dec, auto_reas, _now(), event_id)
        )
        _write_audit(conn, event_id, old["status"] if old else None, decision,
                     "human", f"Decision: {decision}" + (" (edited)" if edit_diff_json else ""))


def mark_sent(event_id, final_reply, crm_tags=None, pii_flagged=0):
    with get_conn() as conn:
        old = conn.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()
        conn.execute(
            """UPDATE events
               SET status = ?, final_reply = ?, crm_tags = ?,
                   pii_flagged = ?, sent_at = ?, updated_at = ?
               WHERE id = ?""",
            (STATUS_SENT, final_reply,
             json.dumps(crm_tags) if crm_tags else None,
             pii_flagged, _now(), _now(), event_id)
        )
        _write_audit(conn, event_id, old["status"] if old else None, STATUS_SENT,
                     "executor", "Reply sent")


def mark_triage_failed(event_id, reason):
    with get_conn() as conn:
        old = conn.execute("SELECT status FROM events WHERE id = ?", (event_id,)).fetchone()
        conn.execute(
            """UPDATE events SET status = ?, reasoning = ?, updated_at = ? WHERE id = ?""",
            (STATUS_TRIAGE_FAILED, f"FAILED: {reason}", _now(), event_id)
        )
        _write_audit(conn, event_id, old["status"] if old else None,
                     STATUS_TRIAGE_FAILED, "triage", reason)


def check_sla_breaches():
    """Mark events whose SLA deadline has passed. Called periodically."""
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """UPDATE events
               SET sla_breached = 1, updated_at = ?
               WHERE sla_deadline IS NOT NULL
                 AND sla_deadline < ?
                 AND sla_breached = 0
                 AND status IN (?, ?)""",
            (_now(), now, STATUS_AWAITING_APPROVAL, STATUS_ESCALATED)
        )


# ---------------------------------------------------------------------------
# v3 Intelligence Queries
# ---------------------------------------------------------------------------

def get_sla_at_risk(minutes: int = 30) -> list[dict]:
    """Events that will breach SLA within `minutes` from now (but haven't yet)."""
    now = datetime.now(timezone.utc)
    cutoff = (now + timedelta(minutes=minutes)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM events
               WHERE sla_deadline IS NOT NULL
                 AND sla_deadline <= ?
                 AND sla_breached = 0
                 AND status IN (?, ?)
               ORDER BY sla_deadline""",
            (cutoff, STATUS_AWAITING_APPROVAL, STATUS_ESCALATED)
        ).fetchall()
        return [dict(r) for r in rows]


def get_intent_cluster_counts(window_hours: int = 1) -> dict:
    """Returns intent_cluster → count for events in the last `window_hours`."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT intent_cluster, COUNT(*) as n
               FROM events
               WHERE intent_cluster IS NOT NULL
                 AND created_at >= ?
               GROUP BY intent_cluster
               ORDER BY n DESC""",
            (cutoff,)
        ).fetchall()
        return {r["intent_cluster"]: r["n"] for r in rows}


def get_authors_with_multiple_contacts(min_contacts: int = 2) -> list[dict]:
    """Authors who have contacted support >= min_contacts times."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT author, COUNT(*) as contact_count,
                      MAX(created_at) as last_contact,
                      SUM(CASE WHEN status = 'sent' OR status = 'auto_handled' THEN 1 ELSE 0 END) as resolved_count
               FROM events
               GROUP BY author
               HAVING COUNT(*) >= ?
               ORDER BY contact_count DESC""",
            (min_contacts,)
        ).fetchall()
        return [dict(r) for r in rows]


def save_training_signal(event_id: str, original_draft: str, human_edit: str,
                         platform: str, intent: str) -> None:
    """Append a fine-tuning signal to training_signals.jsonl when human edits an AI draft."""
    import difflib
    ratio = difflib.SequenceMatcher(None, original_draft, human_edit).ratio()
    if ratio >= 0.9:
        return  # Less than 10% change — not worth logging

    record = {
        "event_id": event_id,
        "platform": platform,
        "intent": intent,
        "original_draft": original_draft,
        "human_edit": human_edit,
        "edit_ratio": round(1 - ratio, 3),
        "ts": _now(),
    }
    with open(TRAINING_SIGNALS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def get_weekly_digest_data(days: int = 7) -> dict:
    """Aggregate top themes, pain points, and trends for weekly voice-of-customer digest."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        # Top intent clusters
        clusters = conn.execute(
            """SELECT intent_cluster, COUNT(*) as n
               FROM events
               WHERE intent_cluster IS NOT NULL AND created_at >= ?
               GROUP BY intent_cluster ORDER BY n DESC LIMIT 10""",
            (cutoff,)
        ).fetchall()

        # Sentiment breakdown from CRM tags
        sentiments = conn.execute(
            """SELECT json_extract(crm_tags, '$.sentiment') as sentiment, COUNT(*) as n
               FROM events
               WHERE crm_tags IS NOT NULL AND created_at >= ?
               GROUP BY sentiment""",
            (cutoff,)
        ).fetchall()

        # Escalation breakdown by intent
        escalations = conn.execute(
            """SELECT intent, COUNT(*) as n
               FROM events
               WHERE status = 'escalated' AND created_at >= ?
               GROUP BY intent ORDER BY n DESC LIMIT 5""",
            (cutoff,)
        ).fetchall()

        # Platform breakdown
        platforms = conn.execute(
            """SELECT platform, COUNT(*) as n FROM events
               WHERE created_at >= ? GROUP BY platform""",
            (cutoff,)
        ).fetchall()

        # Sarcasm rate
        total = conn.execute(
            "SELECT COUNT(*) as n FROM events WHERE created_at >= ?", (cutoff,)
        ).fetchone()["n"] or 1
        sarcasm = conn.execute(
            "SELECT COUNT(*) as n FROM events WHERE sarcasm_flag = 1 AND created_at >= ?",
            (cutoff,)
        ).fetchone()["n"]

        # Average risk
        avg_risk = conn.execute(
            "SELECT AVG(risk_score) FROM events WHERE risk_score IS NOT NULL AND created_at >= ?",
            (cutoff,)
        ).fetchone()[0]

        # Legal blocks
        legal = conn.execute(
            "SELECT COUNT(*) as n FROM events WHERE legal_block = 1 AND created_at >= ?",
            (cutoff,)
        ).fetchone()["n"]

    return {
        "period_days": days,
        "top_clusters": [{"cluster": r["intent_cluster"], "count": r["n"]} for r in clusters],
        "sentiment_breakdown": {r["sentiment"]: r["n"] for r in sentiments if r["sentiment"]},
        "top_escalation_intents": [{"intent": r["intent"], "count": r["n"]} for r in escalations],
        "platform_breakdown": {r["platform"]: r["n"] for r in platforms},
        "sarcasm_rate": round(sarcasm / total * 100, 1),
        "avg_risk_score": round(avg_risk, 3) if avg_risk else 0,
        "legal_escalations": legal,
        "total_events": total,
    }


def get_resolved_escalations_for_followup(hours_min: int = 48) -> list[dict]:
    """Resolved escalations that haven't had a follow-up yet (for emotion recovery)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours_min)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM events
               WHERE status IN ('sent', 'auto_handled')
                 AND tier = 'escalate'
                 AND sent_at <= ?
               ORDER BY sent_at""",
            (cutoff,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_trending_complaints(window_hours: int = 2, min_count: int = 3) -> list[dict]:
    """Intent clusters spiking above min_count in the last window_hours."""
    counts = get_intent_cluster_counts(window_hours)
    trending = [
        {"cluster": k, "count": v}
        for k, v in sorted(counts.items(), key=lambda x: -x[1])
        if v >= min_count
    ]
    return trending


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_by_status(status) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE status = ? ORDER BY created_at",
            (status,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_by_author(author, limit=10) -> list[dict]:
    """Return the most recent events from a specific author (for context injection)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE author = ? ORDER BY created_at DESC LIMIT ?",
            (author, limit)
        ).fetchall()
        return [dict(r) for r in rows]


def get_all(limit=500) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_stats() -> dict:
    """Aggregate stats for the analytics dashboard."""
    with get_conn() as conn:
        totals = {}
        for status in [STATUS_PENDING_TRIAGE, STATUS_AUTO_HANDLED, STATUS_AWAITING_APPROVAL,
                        STATUS_APPROVED, STATUS_REJECTED, STATUS_ESCALATED, STATUS_SENT,
                        STATUS_TRIAGE_FAILED]:
            count = conn.execute(
                "SELECT COUNT(*) FROM events WHERE status = ?", (status,)
            ).fetchone()[0]
            totals[status] = count

        intent_dist = conn.execute(
            "SELECT intent, COUNT(*) as n FROM events WHERE intent IS NOT NULL GROUP BY intent"
        ).fetchall()

        platform_dist = conn.execute(
            "SELECT platform, COUNT(*) as n FROM events GROUP BY platform"
        ).fetchall()

        lang_dist = conn.execute(
            "SELECT language, COUNT(*) as n FROM events WHERE language IS NOT NULL GROUP BY language"
        ).fetchall()

        sla_breached = conn.execute(
            "SELECT COUNT(*) FROM events WHERE sla_breached = 1"
        ).fetchone()[0]

        avg_risk = conn.execute(
            "SELECT AVG(risk_score) FROM events WHERE risk_score IS NOT NULL"
        ).fetchone()[0]

        fallback_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE triage_model != 'qwen-plus' AND triage_model IS NOT NULL"
        ).fetchone()[0]

        # v3 stats
        sarcasm_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE sarcasm_flag = 1"
        ).fetchone()[0]

        legal_block_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE legal_block = 1"
        ).fetchone()[0]

        pii_flagged_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE pii_flagged = 1"
        ).fetchone()[0]

        escalating_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE sentiment_trajectory = 'escalating'"
        ).fetchone()[0]

        cluster_dist = conn.execute(
            "SELECT intent_cluster, COUNT(*) as n FROM events WHERE intent_cluster IS NOT NULL GROUP BY intent_cluster"
        ).fetchall()

        routing_dist = conn.execute(
            "SELECT routing_team, COUNT(*) as n FROM events WHERE routing_team IS NOT NULL GROUP BY routing_team"
        ).fetchall()

        # CRM sentiment breakdown
        crm_sentiments = conn.execute(
            """SELECT json_extract(crm_tags, '$.sentiment') as sentiment, COUNT(*) as n
               FROM events WHERE crm_tags IS NOT NULL
               GROUP BY sentiment"""
        ).fetchall()

    return {
        "by_status":      totals,
        "by_intent":      {r["intent"]: r["n"] for r in intent_dist},
        "by_platform":    {r["platform"]: r["n"] for r in platform_dist},
        "by_language":    {r["language"]: r["n"] for r in lang_dist},
        "sla_breached":   sla_breached,
        "avg_risk_score": round(avg_risk, 3) if avg_risk else 0,
        "fallback_used":  fallback_count,
        # v3
        "sarcasm_count":     sarcasm_count,
        "legal_block_count": legal_block_count,
        "pii_flagged_count": pii_flagged_count,
        "escalating_count":  escalating_count,
        "by_cluster":        {r["intent_cluster"]: r["n"] for r in cluster_dist},
        "by_routing_team":   {r["routing_team"]: r["n"] for r in routing_dist},
        "crm_sentiments":    {r["sentiment"]: r["n"] for r in crm_sentiments if r["sentiment"]},
    }


def get_audit_log(event_id) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE event_id = ? ORDER BY ts",
            (event_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_recent_crises(limit=5) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM crisis_log ORDER BY detected_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def log_crisis(window_mins, event_count, event_ids: list[str],
               cluster_name: str = None) -> str:
    crisis_id = str(uuid.uuid4())
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO crisis_log (id, detected_at, window_mins, event_count, event_ids, cluster_name)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (crisis_id, _now(), window_mins, event_count,
             json.dumps(event_ids), cluster_name)
        )
    return crisis_id


def resolve_crisis(crisis_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE crisis_log SET resolved = 1, resolved_at = ? WHERE id = ?",
            (_now(), crisis_id)
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _write_audit(conn, event_id, from_status, to_status, actor, note=None):
    conn.execute(
        """INSERT INTO audit_log (id, event_id, from_status, to_status, actor, note, ts)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), event_id, from_status, to_status, actor, note, _now())
    )


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH} (schema v3)")
