"""
Seeds the database with a rich, realistic set of social interactions.

v4 additions:
  - source_url: direct clickable links to real social profiles (no API key needed)

v3 additions:
  - author_followers and author_verified fields
  - Sarcastic messages (tone that LLMs often misclassify)
  - Multi-contact author scenarios (repeat complainers, unresolved issues)
  - High-follower accounts (trigger multi-signal risk boost)
  - Legal/PR trigger word messages (hard legal block)
  - Intent cluster spike scenario (5x damaged_item messages)
  - Platform variety to demo tone adaptation

Deliberately spans the three tiers so the demo can show all three
paths (auto-handle / draft+approve / escalate) without relying on a
live platform API.
"""

from store import init_db, insert_event
import sys


def _safe_print(*args, **kwargs):
    """Print that silently ignores broken-pipe errors (e.g. when called from Streamlit)."""
    try:
        print(*args, **kwargs)
        if sys.stdout and hasattr(sys.stdout, 'flush'):
            sys.stdout.flush()
    except (OSError, BrokenPipeError, AttributeError):
        pass



# ---------------------------------------------------------------------------
# Platform profile URL builder (no API key needed)
# ---------------------------------------------------------------------------
def _profile_url(platform: str, author: str) -> str | None:
    """Build a public profile URL from platform name + author handle."""
    handle = author.lstrip("@").strip()
    if not handle or handle.lower() in ("anonymous", ""):
        return None
    urls = {
        "instagram": f"https://www.instagram.com/{handle}/",
        "tiktok":    f"https://www.tiktok.com/@{handle}",
        "twitter":   f"https://x.com/{handle}",
        "linkedin":  f"https://www.linkedin.com/in/{handle}/",
        "facebook":  None,   # Facebook profile URLs require numeric IDs
        "email":     None,
    }
    return urls.get(platform.lower())

SEED_EVENTS = [
    # ── AUTO tier (low risk, clear intent) ──────────────────────────────────
    dict(
        platform="instagram", event_type="comment", author="@sara.k",
        content="Do you ship to Canada?",
        author_followers=1200, author_verified=0,
    ),
    dict(
        platform="twitter", event_type="mention", author="@buy_now_bot99",
        content="MAKE MONEY FAST visit my page!!! link in bio",
        author_followers=0, author_verified=0,
    ),
    dict(
        platform="instagram", event_type="comment", author="@marcus_t",
        content="Love this! What's the price?",
        author_followers=850, author_verified=0,
    ),
    dict(
        platform="tiktok", event_type="comment", author="@happyshopper99",
        content="Just received my order and I'm obsessed with it! 🎉",
        author_followers=3400, author_verified=0,
    ),
    dict(
        platform="facebook", event_type="comment", author="@regular_user",
        content="What are your store hours?",
        author_followers=200, author_verified=0,
    ),

    # ── DRAFT + APPROVE tier (needs judgment / brand voice / money) ──────────
    dict(
        platform="twitter", event_type="dm", author="@jenny_ordered",
        content="Hi, I ordered on the 28th and it still says processing. Order #48213. Can you check?",
        author_followers=540, author_verified=0,
    ),
    dict(
        platform="facebook", event_type="review", author="Tom R.",
        content="Product broke after 2 weeks. Not happy. Considering a refund.",
        author_followers=0, author_verified=0,
    ),
    dict(
        platform="instagram", event_type="dm", author="@potential_partner",
        content="Hey! We run a page with 500k followers in your niche, interested in a collab?",
        author_followers=510000, author_verified=1,
    ),
    dict(
        platform="linkedin", event_type="comment", author="@b2b_prospect",
        content="Hi, we're a retail chain of 80 stores looking for a bulk supply deal. Who should we contact?",
        author_followers=2100, author_verified=0,
    ),

    # ── SARCASM DETECTION scenarios ──────────────────────────────────────────
    dict(
        platform="twitter", event_type="mention", author="@sarcastic_shopper",
        content="wow, love waiting 3 weeks for my order 🙃 amazing service as always",
        author_followers=1800, author_verified=0,
    ),
    dict(
        platform="instagram", event_type="comment", author="@ironic_user42",
        content="great customer support, really feeling the love after 5 ignored DMs 😒",
        author_followers=6700, author_verified=0,
    ),
    dict(
        platform="tiktok", event_type="comment", author="@pretend_happy",
        content="Oh totally normal to receive a completely different item than what I ordered, no big deal 🙃",
        author_followers=900, author_verified=0,
    ),

    # ── HIGH-FOLLOWER ACCOUNT (multi-signal risk boost) ──────────────────────
    dict(
        platform="twitter", event_type="mention", author="@influencer_kate",
        content="@brand really disappointed with my recent purchase. This isn't the quality I expected.",
        author_followers=520000, author_verified=1,
    ),
    dict(
        platform="instagram", event_type="comment", author="@megablogger_james",
        content="Ordered 2 items, received only 1. No response from support in 48 hours.",
        author_followers=180000, author_verified=0,
    ),

    # ── INTENT CLUSTER SPIKE: damaged_item × 5 ──────────────────────────────
    dict(
        platform="instagram", event_type="comment", author="@user_dmg1",
        content="My package arrived completely crushed, the item inside is broken!",
        author_followers=310, author_verified=0,
    ),
    dict(
        platform="twitter", event_type="mention", author="@user_dmg2",
        content="Received a damaged product, the box was dented and the item cracked.",
        author_followers=230, author_verified=0,
    ),
    dict(
        platform="facebook", event_type="review", author="user_dmg3",
        content="Terrible packaging — product was broken on arrival. Second time this happened.",
        author_followers=0, author_verified=0,
    ),
    dict(
        platform="instagram", event_type="dm", author="@user_dmg4",
        content="Just received my order and the glass part is shattered. Packaging was way too thin.",
        author_followers=550, author_verified=0,
    ),
    dict(
        platform="tiktok", event_type="comment", author="@user_dmg5",
        content="Damaged item on arrival. This is the 3rd complaint I've seen about this today!",
        author_followers=4200, author_verified=0,
    ),

    # ── MULTI-CONTACT AUTHOR (sentiment trajectory) ──────────────────────────
    # Note: repeat author @repeat_complainer appears across multiple events
    dict(
        platform="twitter", event_type="mention", author="@repeat_complainer",
        content="Still no update on my refund from 2 weeks ago. This is unacceptable.",
        author_followers=890, author_verified=0,
    ),
    dict(
        platform="twitter", event_type="dm", author="@repeat_complainer",
        content="I've now contacted you 3 times about order #92841. Nobody is responding. HELP.",
        author_followers=890, author_verified=0,
    ),

    # ── LEGAL / PR HARD BLOCK scenarios ─────────────────────────────────────
    dict(
        platform="twitter", event_type="mention", author="@furious_customer22",
        content="Your product caused an allergic reaction and nobody on your support line will call me back. My lawyer will be in touch.",
        author_followers=1400, author_verified=0,
    ),
    dict(
        platform="facebook", event_type="comment", author="Anonymous",
        content="I heard your factory workers are treated terribly, is this true??",
        author_followers=0, author_verified=0,
    ),
    dict(
        platform="twitter", event_type="mention", author="@press_reporter_nyt",
        content="Hi, I'm a journalist at a major outlet investigating customer complaints about your shipping practices. Can you comment?",
        author_followers=45000, author_verified=1,
    ),
    dict(
        platform="instagram", event_type="comment", author="@legal_eagle99",
        content="I'm filing a lawsuit over the false advertising on your website. Save all your records.",
        author_followers=720, author_verified=0,
    ),

    # ── DELIBERATELY AMBIGUOUS ───────────────────────────────────────────────
    dict(
        platform="instagram", event_type="comment", author="@quiet_user",
        content="wow.",
        author_followers=180, author_verified=0,
    ),
    dict(
        platform="twitter", event_type="dm", author="@confused_buyer",
        content="this is not what i expected at all",
        author_followers=430, author_verified=0,
    ),
]


MULTILINGUAL_EVENTS = [
    # ── French 🇫🇷 ─────────────────────────────────────────────────────────────
    dict(
        platform="instagram", event_type="comment", author="@claire_paris",
        content="Bonjour ! J'ai passé une commande il y a 3 semaines et je n'ai toujours rien reçu. Pouvez-vous m'aider ?",
        author_followers=1800, author_verified=0,
    ),
    dict(
        platform="twitter", event_type="mention", author="@jeremie_fr",
        content="Wow, super service… on attend 3 semaines pour rien recevoir 🙃 Bravo pour l'efficacité.",
        author_followers=4200, author_verified=0,
    ),

    # ── Spanish 🇪🇸 ────────────────────────────────────────────────────────────
    dict(
        platform="facebook", event_type="review", author="Carlos M.",
        content="¡Hola! Recibí mi pedido pero el producto llegó completamente roto. ¿Qué puedo hacer para obtener un reembolso?",
        author_followers=0, author_verified=0,
    ),
    dict(
        platform="instagram", event_type="comment", author="@sofia_madrid",
        content="¡Me encanta este producto! ¿Tienen envío a México?",
        author_followers=920, author_verified=0,
    ),

    # ── German 🇩🇪 ─────────────────────────────────────────────────────────────
    dict(
        platform="twitter", event_type="mention", author="@max_berlin",
        content="Guten Tag, mein Paket ist beschädigt angekommen. Das ist nicht das erste Mal passiert! Ich erwarte eine sofortige Lösung.",
        author_followers=3100, author_verified=0,
    ),
    dict(
        platform="instagram", event_type="comment", author="@lena_de",
        content="Liefert ihr auch nach Österreich? Ich interessiere mich für eure neue Kollektion.",
        author_followers=560, author_verified=0,
    ),

    # ── Chinese (Simplified) 🇨🇳 ───────────────────────────────────────────────
    dict(
        platform="twitter", event_type="dm", author="@wei_zhang_cn",
        content="你好，我的订单 #48213 已经等了三周了，到底什么时候能收到？请帮我查一下！",
        author_followers=2300, author_verified=0,
    ),
    dict(
        platform="instagram", event_type="comment", author="@li_mei_shop",
        content="收到商品了，非常满意！请问你们有更多颜色可选吗？",
        author_followers=780, author_verified=0,
    ),

    # ── Japanese 🇯🇵 ───────────────────────────────────────────────────────────
    dict(
        platform="instagram", event_type="dm", author="@tanaka_jp",
        content="こんにちは。注文した商品が届きましたが、破損していました。返金対応をお願いしたいのですが、どうすればよいですか？",
        author_followers=1500, author_verified=0,
    ),

    # ── Arabic 🇸🇦 ────────────────────────────────────────────────────────────
    dict(
        platform="facebook", event_type="comment", author="@ahmed_ksa",
        content="مرحبا، لقد طلبت منذ أسبوعين ولم أستلم طلبي بعد. هل يمكنكم المساعدة في تتبع الشحنة؟",
        author_followers=0, author_verified=0,
    ),
    dict(
        platform="twitter", event_type="mention", author="@sara_uae",
        content="المنتج وصل مكسور والتغليف كان سيئاً جداً. هذا غير مقبول على الإطلاق!",
        author_followers=8900, author_verified=0,
    ),

    # ── Portuguese (Brazil) 🇧🇷 ────────────────────────────────────────────────
    dict(
        platform="instagram", event_type="comment", author="@ana_brasil",
        content="Olá! Meu pedido chegou com o produto danificado. Quero meu dinheiro de volta! Já tentei contato 2 vezes.",
        author_followers=2100, author_verified=0,
    ),

    # ── Italian 🇮🇹 ────────────────────────────────────────────────────────────
    dict(
        platform="facebook", event_type="review", author="Marco R.",
        content="Ciao! Ho ordinato il mese scorso e non ho ancora ricevuto niente. Quando arriva il mio pacco? Ordine #92841.",
        author_followers=0, author_verified=0,
    ),

    # ── Dutch 🇳🇱 ─────────────────────────────────────────────────────────────
    dict(
        platform="twitter", event_type="mention", author="@jan_amsterdam",
        content="Hallo! Ik heb mijn bestelling ontvangen maar het product is helemaal kapot. Kunnen jullie dit oplossen?",
        author_followers=1400, author_verified=0,
    ),

    # ── Russian 🇷🇺 ────────────────────────────────────────────────────────────
    dict(
        platform="instagram", event_type="comment", author="@olga_msk",
        content="Здравствуйте! Заказ пришёл повреждённым. Это уже второй раз! Хочу возврат денег. Это неприемлемо.",
        author_followers=3600, author_verified=0,
    ),

    # ── Korean 🇰🇷 ────────────────────────────────────────────────────────────
    dict(
        platform="instagram", event_type="dm", author="@minjun_kr",
        content="안녕하세요! 주문한 상품이 파손된 채로 배송됐어요. 환불 받을 수 있을까요? 사진도 찍어뒀습니다.",
        author_followers=5200, author_verified=0,
    ),

    # ── Turkish 🇹🇷 ────────────────────────────────────────────────────────────
    dict(
        platform="twitter", event_type="mention", author="@emre_istanbul",
        content="Merhaba! Siparişim hasar görmüş geldi, bu kesinlikle kabul edilemez! Para iadesi talep ediyorum.",
        author_followers=2700, author_verified=0,
    ),

    # ── Hindi 🇮🇳 ─────────────────────────────────────────────────────────────
    dict(
        platform="facebook", event_type="comment", author="Priya S.",
        content="नमस्ते! मेरा ऑर्डर अभी तक नहीं आया है। मैंने 2 हफ्ते पहले ऑर्डर किया था। कृपया मदद करें।",
        author_followers=0, author_verified=0,
    ),

    # ── Indonesian 🇮🇩 ────────────────────────────────────────────────────────
    dict(
        platform="tiktok", event_type="comment", author="@budi_jakarta",
        content="Halo! Pesanan saya sudah 2 minggu belum sampai. Tolong bantu saya cek status pengirimannya.",
        author_followers=6800, author_verified=0,
    ),

    # ── Polish 🇵🇱 ────────────────────────────────────────────────────────────
    dict(
        platform="instagram", event_type="comment", author="@agnieszka_pl",
        content="Cześć! Moje zamówienie dotarło uszkodzone. To jest nieakceptowalne! Proszę o zwrot pieniędzy.",
        author_followers=1100, author_verified=0,
    ),

    # ── Swedish 🇸🇪 ────────────────────────────────────────────────────────────
    dict(
        platform="twitter", event_type="mention", author="@erik_stockholm",
        content="Hej! Jag fick min beställning men produkten var trasig. Kan ni hjälpa mig med en retur?",
        author_followers=980, author_verified=0,
    ),

    # ── Thai 🇹🇭 ──────────────────────────────────────────────────────────────
    dict(
        platform="instagram", event_type="comment", author="@nattaya_th",
        content="สวัสดีค่ะ สินค้าที่ได้รับมาเสียหาย ไม่เป็นไปตามที่คาดหวัง ขอคืนเงินได้ไหมคะ?",
        author_followers=3300, author_verified=0,
    ),

    # ── Vietnamese 🇻🇳 ────────────────────────────────────────────────────────
    dict(
        platform="facebook", event_type="review", author="Nguyen Van A.",
        content="Xin chào! Đơn hàng của tôi đến bị hỏng và bao bì bị móp méo hoàn toàn. Tôi muốn được hoàn tiền.",
        author_followers=0, author_verified=0,
    ),

    # ── Ukrainian 🇺🇦 ─────────────────────────────────────────────────────────
    dict(
        platform="instagram", event_type="comment", author="@olena_ua",
        content="Привіт! Замовлення прийшло пошкодженим. Це вже другий раз поспіль. Хочу повернення коштів!",
        author_followers=1900, author_verified=0,
    ),

    # ── Hebrew 🇮🇱 ────────────────────────────────────────────────────────────
    dict(
        platform="twitter", event_type="mention", author="@yael_tel_aviv",
        content="שלום! ההזמנה שלי הגיעה שבורה לגמרי. אני דורשת החזר כספי מיידי!",
        author_followers=2400, author_verified=0,
    ),
]

# Combine both lists
SEED_EVENTS = SEED_EVENTS + MULTILINGUAL_EVENTS


def main():
    init_db()
    for e in SEED_EVENTS:
        # Auto-generate profile URL for each seeded event (no API key needed)
        ev = dict(e)
        if "source_url" not in ev:
            ev["source_url"] = _profile_url(ev.get("platform", ""), ev.get("author", ""))
        insert_event(**ev)
    _safe_print(f"Seeded {len(SEED_EVENTS)} events into events.db")
    en_count = len([e for e in SEED_EVENTS if e not in MULTILINGUAL_EVENTS])
    ml_count = len(MULTILINGUAL_EVENTS)
    _safe_print(f"\nEvent breakdown:")
    _safe_print(f"  English scenarios:       {en_count}")
    _safe_print(f"  Multilingual events:     {ml_count}")
    _safe_print(f"    🇫🇷 French:             2")
    _safe_print(f"    🇪🇸 Spanish:            2")
    _safe_print(f"    🇩🇪 German:             2")
    _safe_print(f"    🇨🇳 Chinese:            2")
    _safe_print(f"    🇯🇵 Japanese:           1")
    _safe_print(f"    🇸🇦 Arabic:             2")
    _safe_print(f"    🇧🇷 Portuguese (BR):    1")
    _safe_print(f"    🇮🇹 Italian:            1")
    _safe_print(f"    🇳🇱 Dutch:              1")
    _safe_print(f"    🇷🇺 Russian:            1")
    _safe_print(f"    🇰🇷 Korean:             1")
    _safe_print(f"    🇹🇷 Turkish:            1")
    _safe_print(f"    🇮🇳 Hindi:              1")
    _safe_print(f"    🇮🇩 Indonesian:         1")
    _safe_print(f"    🇵🇱 Polish:             1")
    _safe_print(f"    🇸🇪 Swedish:            1")
    _safe_print(f"    🇹🇭 Thai:               1")
    _safe_print(f"    🇻🇳 Vietnamese:         1")
    _safe_print(f"    🇺🇦 Ukrainian:          1")
    _safe_print(f"    🇮🇱 Hebrew:             1")
    _safe_print(f"  Total:                   {len(SEED_EVENTS)}")


if __name__ == "__main__":
    main()
