"""
social_poller.py — Real Instagram & TikTok comment poller.

Fetches real comments from your social accounts and pushes them into
the LoopBack pipeline via the local webhook server.

Usage:
    # Demo mode — inject realistic fake events (no API keys needed)
    python social_poller.py --demo

    # Real polling — one cycle then exit (used by dashboard buttons)
    python social_poller.py --once

    # Real polling — continuous loop (run in background terminal)
    python social_poller.py

Setup for real Instagram integration:
    1. Go to https://developers.facebook.com/ and create an app (Business type)
    2. Add "Instagram Graph API" product
    3. Generate a User Access Token with instagram_basic, instagram_manage_comments
    4. Add to .env:
        INSTAGRAM_ACCESS_TOKEN=your_long_lived_token
        INSTAGRAM_USER_ID=your_numeric_user_id

Setup for real TikTok integration:
    1. Go to https://developers.tiktok.com/ and create an app
    2. Add "Display API" scope
    3. Authorize and get an access token
    4. Add to .env:
        TIKTOK_ACCESS_TOKEN=your_access_token
"""

import os
import sys
import json
import time
import random
import argparse
import requests
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WEBHOOK_URL        = os.getenv("WEBHOOK_URL", "http://localhost:8001/webhook/social")
POLL_INTERVAL_SEC  = int(os.getenv("POLL_INTERVAL", "60"))
SEEN_IDS_FILE      = Path(__file__).parent / "seen_ids.json"
WEBHOOK_SECRET     = os.getenv("WEBHOOK_SECRET", "hackathon_secret_2026")

def get_instagram_config():
    try:
        from store import get_setting
        token = get_setting("instagram_access_token", "")
        uid   = get_setting("instagram_user_id", "")
    except Exception:
        token, uid = "", ""
    return token or os.getenv("INSTAGRAM_ACCESS_TOKEN", ""), uid or os.getenv("INSTAGRAM_USER_ID", "")

def get_tiktok_config():
    try:
        from store import get_setting
        token = get_setting("tiktok_access_token", "")
    except Exception:
        token = ""
    return token or os.getenv("TIKTOK_ACCESS_TOKEN", "")

def get_twitter_config():
    try:
        from store import get_setting
        token = get_setting("twitter_bearer_token", "")
    except Exception:
        token = ""
    return token or os.getenv("TWITTER_BEARER_TOKEN", "")

INSTAGRAM_API_BASE = "https://graph.instagram.com/v21.0"
TIKTOK_API_BASE    = "https://open.tiktokapis.com/v2"

# ---------------------------------------------------------------------------
# Seen-ID tracking (deduplication)
# ---------------------------------------------------------------------------
def load_seen_ids():
    if SEEN_IDS_FILE.exists():
        try:
            data = json.loads(SEEN_IDS_FILE.read_text(encoding="utf-8"))
            return set(data.get("ids", []))
        except Exception:
            pass
    return set()


def save_seen_ids(ids):
    SEEN_IDS_FILE.write_text(
        json.dumps({"ids": list(ids)[-5000:]}),
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Push event to webhook
# ---------------------------------------------------------------------------
def push_event(platform, event_type, author, content, created_at=None, source_url=None):
    payload = {
        "platform":   platform,
        "type":       event_type,
        "author":     author,
        "content":    content,
    }
    if created_at:
        payload["created_at"] = created_at
    if source_url:
        payload["source_url"] = source_url

    headers = {"X-Webhook-Secret": WEBHOOK_SECRET}
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            print(f"  Queued [{platform}] @{author}: \"{content[:60]}\" => id={data.get('event_id','?')[:8]}")
            return True
        else:
            print(f"  WARNING Webhook rejected [{platform}]: HTTP {resp.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"  ERROR Webhook unreachable at {WEBHOOK_URL}")
        print("     Start the webhook server: uvicorn webhook:app --port 8001")
        return False
    except Exception as e:
        print(f"  ERROR pushing event: {e}")
        return False


# ---------------------------------------------------------------------------
# Instagram polling
# ---------------------------------------------------------------------------
def poll_instagram(seen_ids):
    token, user_id = get_instagram_config()
    if not token or not user_id:
        return 0

    count = 0
    try:
        media_resp = requests.get(
            f"{INSTAGRAM_API_BASE}/{user_id}/media",
            params={
                "fields": "id,caption,timestamp,permalink",
                "limit": "10",
                "access_token": token,
            },
            timeout=15,
        )
        media_resp.raise_for_status()
        media_items = media_resp.json().get("data", [])

        for media in media_items[:5]:
            media_id   = media["id"]
            # Instagram Graph API returns a permalink field for the post URL
            post_url   = media.get("permalink", f"https://www.instagram.com/p/{media_id}/")

            comments_resp = requests.get(
                f"{INSTAGRAM_API_BASE}/{media_id}/comments",
                params={
                    "fields": "id,text,username,timestamp",
                    "limit": "25",
                    "access_token": token,
                },
                timeout=15,
            )
            comments_resp.raise_for_status()
            comments = comments_resp.json().get("data", [])

            for comment in comments:
                cid = comment.get("id", "")
                if cid in seen_ids:
                    continue
                author  = "@" + comment.get("username", "unknown")
                content = comment.get("text", "")
                ts      = comment.get("timestamp", "")
                # Link directly to the parent post (comment-level deep links aren't
                # available via the Graph API, so we link to the post)
                if content.strip():
                    ok = push_event("instagram", "comment", author, content, ts,
                                    source_url=post_url)
                    if ok:
                        seen_ids.add(cid)
                        count += 1

    except requests.exceptions.HTTPError as e:
        print(f"  WARNING Instagram API error: {e.response.status_code}")
    except Exception as e:
        print(f"  WARNING Instagram polling error: {e}")

    return count


# ---------------------------------------------------------------------------
# TikTok polling
# ---------------------------------------------------------------------------
def poll_tiktok(seen_ids):
    token = get_tiktok_config()
    if not token:
        return 0

    count = 0
    try:
        video_resp = requests.post(
            f"{TIKTOK_API_BASE}/video/list/",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "max_count": 10,
                "fields": ["id", "create_time", "desc", "share_url"],
            },
            timeout=15,
        )
        video_resp.raise_for_status()
        videos = video_resp.json().get("data", {}).get("videos", [])

        for video in videos[:5]:
            video_id  = video.get("id", "")
            # TikTok share_url is the direct video link; fall back to constructed URL
            video_url = video.get("share_url") or f"https://www.tiktok.com/video/{video_id}"

            comments_resp = requests.post(
                f"{TIKTOK_API_BASE}/comment/list/",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "video_id":  video_id,
                    "max_count": 20,
                    "fields":    ["id", "text", "create_time", "username"],
                },
                timeout=15,
            )
            if comments_resp.status_code != 200:
                continue

            comments = comments_resp.json().get("data", {}).get("comments", [])
            for comment in comments:
                cid = str(comment.get("id", ""))
                if cid in seen_ids:
                    continue
                author  = "@" + comment.get("username", "tiktok_user")
                content = comment.get("text", "")
                ts_unix = comment.get("create_time", 0)
                ts      = datetime.fromtimestamp(ts_unix, tz=timezone.utc).isoformat() if ts_unix else ""
                if content.strip():
                    ok = push_event("tiktok", "comment", author, content, ts,
                                    source_url=video_url)
                    if ok:
                        seen_ids.add(cid)
                        count += 1

    except requests.exceptions.HTTPError as e:
        print(f"  WARNING TikTok API error: {e.response.status_code}")
    except Exception as e:
        print(f"  WARNING TikTok polling error: {e}")

    return count


# ---------------------------------------------------------------------------
# Twitter/X polling
# ---------------------------------------------------------------------------
def poll_twitter(seen_ids):
    token = get_twitter_config()
    if not token:
        return 0

    count = 0
    try:
        url = "https://api.twitter.com/2/tweets/search/recent"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        params = {
            "query": "LoopBack OR @loopback_ai",
            "tweet.fields": "created_at,author_id,text",
            "expansions": "author_id",
            "user.fields": "username,name",
            "max_results": 10
        }
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        
        data = resp.json()
        tweets = data.get("data", [])
        users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

        for tweet in tweets:
            tid = str(tweet["id"])
            if tid in seen_ids:
                continue
            
            author_id = tweet.get("author_id")
            user_info = users.get(author_id, {})
            author = "@" + user_info.get("username", "twitter_user")
            content = tweet.get("text", "")
            ts = tweet.get("created_at", "")
            tweet_url = f"https://x.com/{user_info.get('username', 'twitter_user')}/status/{tid}"
            
            if content.strip():
                ok = push_event("twitter", "mention", author, content, ts, source_url=tweet_url)
                if ok:
                    seen_ids.add(tid)
                    count += 1

    except requests.exceptions.HTTPError as e:
        print(f"  WARNING Twitter API error: {e.response.status_code}")
    except Exception as e:
        print(f"  WARNING Twitter polling error: {e}")

    return count


# ---------------------------------------------------------------------------
# Demo mode — realistic fake events
# ---------------------------------------------------------------------------
# Demo mode post URLs — realistic placeholder links
_DEMO_POST_URLS = {
    "instagram": [
        "https://www.instagram.com/p/C8xKdemo1/",
        "https://www.instagram.com/p/C8xKdemo2/",
        "https://www.instagram.com/p/C8xKdemo3/",
    ],
    "tiktok": [
        "https://www.tiktok.com/@yourbrand/video/7380000000001",
        "https://www.tiktok.com/@yourbrand/video/7380000000002",
        "https://www.tiktok.com/@yourbrand/video/7380000000003",
    ],
}

_DEMO_EVENTS = [
    ("instagram", "comment", "@sara.m92",         "Love the new collection!! When does the blue one restock?"),
    ("instagram", "comment", "@carlos_dev",       "my package hasn't arrived and it's been 3 weeks. Order #48213"),
    ("instagram", "comment", "@fatima.kh",        "منتجاتكم رائعة جداً! متى يصل الطلب الخاص بي؟"),
    ("instagram", "comment", "@legal_eagle_99",   "I'm consulting my attorney about this defective product. Expect to hear from us."),
    ("instagram", "comment", "@happy_customer01", "Best purchase I've made this year!! 5 stars"),
    ("instagram", "comment", "@jenny.t",          "The sizing runs really small. Can I exchange without paying shipping?"),
    ("instagram", "comment", "@promo_bot_9182",   "FREE IPHONE CLICK LINK IN BIO"),
    ("instagram", "mention", "@influencer.brand", "We'd love to partner with you for our summer campaign. DM us!"),
    ("instagram", "comment", "@sophie_fr",        "J'ai recu le mauvais article dans ma commande. Que faire?"),
    ("instagram", "comment", "@mike_angry",       "This is the WORST customer service I've ever experienced. Shame on you!"),
    ("instagram", "dm",      "@wholesale_buyer",  "Hi, interested in bulk orders (500+ units). What's your wholesale price?"),
    ("instagram", "comment", "@zhang.wei",        "我的包裹在哪里？已经等了两周了，订单号92841"),
    ("tiktok",    "comment", "@tiktoker_xo",      "omg this product changed my life no cap"),
    ("tiktok",    "comment", "@skeptical_user",   "is this actually legit or just another scam?? my order never came"),
    ("tiktok",    "comment", "@angry_buyer_22",   "DO NOT BUY. Got a used item in new packaging. Reported to FTC."),
    ("tiktok",    "comment", "@curious_shopper",  "what material is this? safe for sensitive skin?"),
    ("tiktok",    "comment", "@hater_anon",       "your brand is trash and everyone knows it lmao"),
    ("tiktok",    "comment", "@media_reporter",   "Hi, journalist from TechCrunch writing about AI in retail. Would you comment?"),
    ("tiktok",    "comment", "@regular_fan",      "been using this for 6 months. absolute game changer"),
    ("tiktok",    "comment", "@concerned_parent", "Is this product safe for children under 12? I need to know before buying."),
]


def poll_demo(seen_ids, count=5):
    candidates = [e for e in _DEMO_EVENTS if f"demo_{e[2]}_{e[3][:20]}" not in seen_ids]
    if not candidates:
        candidates = _DEMO_EVENTS

    sample = random.sample(candidates, min(count, len(candidates)))
    pushed = 0
    for platform, event_type, author, content in sample:
        fake_id  = f"demo_{author}_{content[:20]}"
        ts       = datetime.now(timezone.utc).isoformat()
        # Pick a realistic demo post URL for the platform
        urls     = _DEMO_POST_URLS.get(platform, [])
        demo_url = random.choice(urls) if urls else None
        ok = push_event(platform, event_type, author, content, ts,
                        source_url=demo_url)
        if ok:
            seen_ids.add(fake_id)
            pushed += 1
        time.sleep(0.1)
    return pushed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_once(demo=False):
    seen_ids = load_seen_ids()
    total = 0

    if demo:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Demo mode — injecting realistic events...")
        total += poll_demo(seen_ids, count=random.randint(3, 6))
    else:
        ts = datetime.now().strftime('%H:%M:%S')
        print(f"[{ts}] Polling social APIs...")
        ig = poll_instagram(seen_ids)
        tk = poll_tiktok(seen_ids)
        tw = poll_twitter(seen_ids)
        total = ig + tk + tw
        
        ig_token, _ = get_instagram_config()
        tok_token   = get_tiktok_config()
        tw_token    = get_twitter_config()
        if not ig_token and not tok_token and not tw_token:
            print("  No API tokens configured. Connect accounts in the dashboard or run with --demo.")

    save_seen_ids(seen_ids)
    print(f"  -> {total} new event(s) queued for triage.")
    return total


def run_loop(demo=False):
    print(f"Social Poller started (interval={POLL_INTERVAL_SEC}s, demo={demo})")
    print(f"   Webhook: {WEBHOOK_URL}")
    print(f"   Press Ctrl+C to stop.\n")
    while True:
        try:
            run_once(demo=demo)
        except KeyboardInterrupt:
            print("\nPoller stopped.")
            break
        except Exception as e:
            print(f"  ERROR: {e}")
        print(f"   Sleeping {POLL_INTERVAL_SEC}s...\n")
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LoopBack - Social Media Poller")
    parser.add_argument("--demo", action="store_true", help="Inject realistic demo events (no API keys needed)")
    parser.add_argument("--once", action="store_true", help="Run a single poll cycle then exit")
    args = parser.parse_args()

    if args.once:
        run_once(demo=args.demo)
    else:
        run_loop(demo=args.demo)
