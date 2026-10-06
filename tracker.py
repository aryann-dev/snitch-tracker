"""
Snitch Sale Tracker - V1 (sirf website)

Storage design:
  - data/state.db (SQLite)  = sirf "abhi ka state", compare karne ke liye. GitHub pe Actions cache mein rehta hai.
  - Neon Postgres (DATABASE_URL) = permanent record: change_log + products + variants + runs.
  DATABASE_URL na ho toh sab kuch local SQLite mein (testing ke liye).

Har run mein:
  1. Poora catalog products.json se fetch
  2. Database ke purane state se compare
  3. Har change (chahe ₹1 ka ho) change_log table mein permanently save
  4. Saare changes ka ek grouped summary Telegram pe

Pehla run sirf "baseline" save karta hai (koi alert nahi), kyunki compare karne ke liye
purana data hona chahiye.
"""
import hashlib
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

# ---------------- .env file (local use ke liye) ----------------
def load_dotenv(path=".env"):
    """`.env` file se KEY=VALUE padho. Jo variable pehle se set hai, use nahi chhedta."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


load_dotenv()

# ---------------- Settings ----------------
STORE_URL = (os.environ.get("STORE_URL") or "https://www.snitch.co.in").rstrip("/")  # check_site.py se confirm
DB_PATH = os.environ.get("DB_PATH") or "data/state.db"
DATABASE_URL = os.environ.get("DATABASE_URL", "")  # Neon connection string
def _clean_secret(name):
    """Paste karte waqt aksar quotes, spaces ya "NAME=" bhi chala jaata hai. Use hata do."""
    v = (os.environ.get(name) or "").strip().strip('"').strip("'").strip()
    if v.upper().startswith(name + "="):
        v = v[len(name) + 1:].strip().strip('"').strip("'")
    return v


BOT_TOKEN = _clean_secret("TELEGRAM_BOT_TOKEN")
CHAT_ID = _clean_secret("TELEGRAM_CHAT_ID")

PAGE_DELAY_SEC = 2          # har page ke beech ruko, site pe load kam
MAX_PAGES = 400             # safety limit (400 x 250 = 1,00,000 products). Snitch ~23k products = ~94 pages
MAX_TELEGRAM_MSGS = 5       # ek run mein max itne messages, baaki DB mein
IST = timezone(timedelta(hours=5, minutes=30))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal price tracker; low frequency)",
    "Accept": "application/json",
}

# Kaunse fields ke change record honge
PRODUCT_FIELDS = ["title", "handle", "product_type", "tags", "published_at", "image", "desc_hash"]
VARIANT_FIELDS = ["title", "sku", "price", "compare_at_price", "available", "on_sale"]


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------- 1. Fetch ----------------
RETRY_WAITS_SEC = [15, 45, 90]  # 503/429 jaisi temporary errors pe itna ruk ke dobara try


def get_page_with_retry(url):
    """Ek page laao. Temporary error (429, 5xx, network) pe thoda ruk ke dobara try karo.
    Sab tries fail hue toh error raise -> poora run ruk jayega (galat "removed" alerts nahi aayenge)."""
    for attempt in range(len(RETRY_WAITS_SEC) + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code} {r.reason}", response=r)
            r.raise_for_status()  # 403/404 jaisi errors pe retry ka faayda nahi
            return r.json()
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as e:
            resp = getattr(e, "response", None)
            retryable = resp is None or resp.status_code == 429 or resp.status_code >= 500
            if not retryable or attempt == len(RETRY_WAITS_SEC):
                raise
            wait = RETRY_WAITS_SEC[attempt]
            ra = resp.headers.get("Retry-After") if resp is not None else None
            if ra and ra.isdigit():
                wait = max(wait, min(int(ra), 300))
            print(f"⚠️ {e} -> {wait}s ruk ke dobara try ({attempt + 1}/{len(RETRY_WAITS_SEC)})")
            time.sleep(wait)


def fetch_catalog():
    """Saare products laao. Returns (products, complete). complete=False matlab list adhuri ho sakti hai."""
    products = []
    for page in range(1, MAX_PAGES + 1):
        url = f"{STORE_URL}/products.json?limit=250&page={page}"
        batch = get_page_with_retry(url).get("products", [])
        if not batch:
            return products, True
        products.extend(batch)
        time.sleep(PAGE_DELAY_SEC)
    return products, False


def normalize(raw_products):
    """Shopify ke raw data ko simple dicts mein badlo."""
    prods, variants = {}, {}
    for p in raw_products:
        pid = str(p["id"])
        tags = p.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        images = p.get("images") or []
        first_img = images[0].get("src", "").split("?")[0] if images else None  # ?v=123 hatao, warna faltu changes
        prods[pid] = {
            "title": p.get("title"),
            "handle": p.get("handle"),
            "product_type": p.get("product_type"),
            "tags": ",".join(sorted(tags)),
            "published_at": p.get("published_at"),
            "image": first_img,
            "desc_hash": hashlib.md5((p.get("body_html") or "").encode()).hexdigest(),
        }
        for v in p.get("variants") or []:
            price = _num(v.get("price"))
            mrp = _num(v.get("compare_at_price"))
            # Snitch discount na ho tab MRP "0.00" bhejta hai -> use "MRP nahi hai" (None) maano
            if mrp is not None and mrp <= 0:
                mrp = None
            # on_sale: "No" ya discount %, jaise "40%". Sale shuru/khatam isi se pakda jayega.
            if mrp and price is not None and mrp > price:
                on_sale = f"{round((mrp - price) / mrp * 100)}%"
            else:
                on_sale = "No"
            variants[str(v["id"])] = {
                "product_id": pid,
                "title": v.get("title"),
                "sku": v.get("sku"),
                "price": v.get("price"),
                "compare_at_price": f"{mrp:.2f}" if mrp else None,
                "available": str(v.get("available")),
                "on_sale": on_sale,
            }
    return prods, variants


# ---------------- 2. Database ----------------
def init_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS products (
        id TEXT PRIMARY KEY, data TEXT NOT NULL,
        first_seen TEXT, last_seen TEXT, removed INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS variants (
        id TEXT PRIMARY KEY, product_id TEXT, data TEXT NOT NULL,
        first_seen TEXT, last_seen TEXT, removed INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS change_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, source TEXT, entity TEXT, entity_id TEXT,
        product_id TEXT, product_title TEXT, variant_title TEXT,
        field TEXT, old_value TEXT, new_value TEXT);
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, products INTEGER, variants INTEGER, changes INTEGER, complete INTEGER);
    CREATE INDEX IF NOT EXISTS idx_log_product ON change_log(product_id);
    CREATE INDEX IF NOT EXISTS idx_log_ts ON change_log(ts);
    """)


def upsert(conn, table, rid, data, now, product_id=None):
    if table == "products":
        conn.execute("""INSERT INTO products (id, data, first_seen, last_seen, removed) VALUES (?,?,?,?,0)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data, last_seen=excluded.last_seen, removed=0""",
                     (rid, json.dumps(data), now, now))
    else:
        conn.execute("""INSERT INTO variants (id, product_id, data, first_seen, last_seen, removed) VALUES (?,?,?,?,?,0)
            ON CONFLICT(id) DO UPDATE SET data=excluded.data, last_seen=excluded.last_seen, removed=0""",
                     (rid, product_id, json.dumps(data), now, now))


# ---------------- 3. Compare ----------------
def find_changes(conn, prods, variants, complete, now, log_locally=True):
    old_p = {r[0]: (json.loads(r[1]), r[2]) for r in conn.execute("SELECT id, data, removed FROM products")}
    old_v = {r[0]: (json.loads(r[1]), r[2]) for r in conn.execute("SELECT id, data, removed FROM variants")}
    first_run = not old_p
    changes = []

    def title_of(pid):
        if pid in prods:
            return prods[pid]["title"]
        return old_p.get(pid, ({}, 0))[0].get("title")

    def log(entity, eid, pid, field, old, new, vtitle=None):
        changes.append((now, "website", entity, eid, pid, title_of(pid), vtitle, field,
                        None if old is None else str(old), None if new is None else str(new)))

    # Agar is baar products achanak bahut kam aaye, toh fetch par bharosa mat karo (galat "removed" se bacho)
    active_old = sum(1 for _, (_, rem) in old_p.items() if not rem)
    if active_old and len(prods) < 0.5 * active_old:
        print(f"⚠️ Sirf {len(prods)} products mile (pehle {active_old}). Removal detection skip.")
        complete = False

    # --- Products ---
    for pid, data in prods.items():
        if not first_run:
            if pid not in old_p:
                log("product", pid, pid, "NEW_PRODUCT", None, data["title"])
            else:
                od, removed = old_p[pid]
                if removed:
                    log("product", pid, pid, "BACK_ON_SITE", None, data["title"])
                for f in PRODUCT_FIELDS:
                    if f in od and od.get(f) != data.get(f):  # naya field add hua ho toh purane rows pe false alert nahi
                        log("product", pid, pid, f, od.get(f), data.get(f))
        upsert(conn, "products", pid, data, now)

    # --- Variants (har size/colour) ---
    for vid, data in variants.items():
        pid = data["product_id"]
        if not first_run:
            if vid not in old_v:
                if pid in old_p:  # naye product ke variants alag se log nahi karte
                    log("variant", vid, pid, "NEW_VARIANT", None, data["title"], data["title"])
            else:
                od, removed = old_v[vid]
                for f in VARIANT_FIELDS:
                    if f in od and od.get(f) != data.get(f):
                        log("variant", vid, pid, f, od.get(f), data.get(f), data["title"])
        upsert(conn, "variants", vid, data, now, pid)

    # --- Removed (sirf tab jab fetch poora hua ho) ---
    if complete and not first_run:
        for pid, (od, removed) in old_p.items():
            if pid not in prods and not removed:
                log("product", pid, pid, "REMOVED_PRODUCT", od.get("title"), None)
                conn.execute("UPDATE products SET removed=1 WHERE id=?", (pid,))
        for vid, (od, removed) in old_v.items():
            if vid not in variants and not removed:
                if od.get("product_id") in prods:  # poora product gaya toh upar log ho chuka
                    log("variant", vid, od.get("product_id"), "REMOVED_VARIANT", od.get("title"), None, od.get("title"))
                conn.execute("UPDATE variants SET removed=1 WHERE id=?", (vid,))

    if log_locally:
        conn.executemany("""INSERT INTO change_log
        (ts, source, entity, entity_id, product_id, product_title, variant_title, field, old_value, new_value)
        VALUES (?,?,?,?,?,?,?,?,?,?)""", changes)
    return changes, first_run, complete


# ---------------- 3b. Neon (permanent storage) ----------------
NEON_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS products (
        id BIGINT PRIMARY KEY, title TEXT, handle TEXT, product_type TEXT, tags TEXT,
        published_at TEXT, image TEXT, desc_hash TEXT,
        first_seen TIMESTAMPTZ NOT NULL, removed BOOLEAN NOT NULL DEFAULT FALSE)""",
    """CREATE TABLE IF NOT EXISTS variants (
        id BIGINT PRIMARY KEY, product_id BIGINT NOT NULL, title TEXT, sku TEXT,
        price NUMERIC(10,2), compare_at_price NUMERIC(10,2), available BOOLEAN, on_sale TEXT,
        first_seen TIMESTAMPTZ NOT NULL, removed BOOLEAN NOT NULL DEFAULT FALSE)""",
    "CREATE INDEX IF NOT EXISTS idx_variants_product ON variants(product_id)",
    """CREATE TABLE IF NOT EXISTS change_log (
        id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL, source TEXT NOT NULL, entity TEXT NOT NULL,
        entity_id BIGINT NOT NULL, product_id BIGINT NOT NULL, field TEXT NOT NULL,
        old_value TEXT, new_value TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_change_ts ON change_log(ts)",
    "CREATE INDEX IF NOT EXISTS idx_change_product ON change_log(product_id)",
    """CREATE TABLE IF NOT EXISTS runs (
        id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL, products INT, variants INT,
        changes INT, complete BOOLEAN)""",
]

UPSERT_PRODUCT = """INSERT INTO products
    (id, title, handle, product_type, tags, published_at, image, desc_hash, first_seen, removed)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE)
    ON CONFLICT (id) DO UPDATE SET title=EXCLUDED.title, handle=EXCLUDED.handle,
        product_type=EXCLUDED.product_type, tags=EXCLUDED.tags, published_at=EXCLUDED.published_at,
        image=EXCLUDED.image, desc_hash=EXCLUDED.desc_hash, removed=FALSE"""

UPSERT_VARIANT = """INSERT INTO variants
    (id, product_id, title, sku, price, compare_at_price, available, on_sale, first_seen, removed)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE)
    ON CONFLICT (id) DO UPDATE SET product_id=EXCLUDED.product_id, title=EXCLUDED.title, sku=EXCLUDED.sku,
        price=EXCLUDED.price, compare_at_price=EXCLUDED.compare_at_price, available=EXCLUDED.available,
        on_sale=EXCLUDED.on_sale, removed=FALSE"""


def neon_rows(changes, prods, variants, first_run, now_dt):
    """Neon mein kya likhna hai, woh tayyar karo. Sirf badle hue rows bhejte hain (baseline ke alawa)."""
    if first_run:
        p_ids, v_ids = set(prods), set(variants)
        removed_pids, removed_vids = [], []
    else:
        touched = {c[4] for c in changes}  # jin products mein kuch bhi badla
        p_ids = {pid for pid in touched if pid in prods}
        v_ids = {vid for vid, d in variants.items() if d["product_id"] in touched}
        removed_pids = [int(c[3]) for c in changes if c[7] == "REMOVED_PRODUCT"]
        removed_vids = [int(c[3]) for c in changes if c[7] == "REMOVED_VARIANT"]

    p_rows = [(int(pid), d["title"], d["handle"], d["product_type"], d["tags"], d["published_at"],
               d["image"], d["desc_hash"], now_dt) for pid, d in ((i, prods[i]) for i in p_ids)]
    v_rows = [(int(vid), int(d["product_id"]), d["title"], d["sku"], _num(d["price"]),
               _num(d["compare_at_price"]), d["available"] == "True", d["on_sale"], now_dt)
              for vid, d in ((i, variants[i]) for i in v_ids)]
    log_rows = [(now_dt, c[1], c[2], int(c[3]), int(c[4]), c[7], c[8], c[9]) for c in changes]
    return p_rows, v_rows, removed_pids, removed_vids, log_rows


def sync_to_neon(changes, prods, variants, first_run, complete, now_dt):
    import psycopg  # sirf tab chahiye jab DATABASE_URL set ho

    p_rows, v_rows, removed_pids, removed_vids, log_rows = neon_rows(changes, prods, variants, first_run, now_dt)
    # Ek hi transaction: ya sab save hoga, ya kuch nahi
    with psycopg.connect(DATABASE_URL, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            for stmt in NEON_SCHEMA:
                cur.execute(stmt)
            if p_rows:
                cur.executemany(UPSERT_PRODUCT, p_rows)
            if v_rows:
                cur.executemany(UPSERT_VARIANT, v_rows)
            if removed_pids:
                cur.execute("UPDATE products SET removed=TRUE WHERE id = ANY(%s)", (removed_pids,))
                cur.execute("UPDATE variants SET removed=TRUE WHERE product_id = ANY(%s)", (removed_pids,))
            if removed_vids:
                cur.execute("UPDATE variants SET removed=TRUE WHERE id = ANY(%s)", (removed_vids,))
            if log_rows:
                cur.executemany("""INSERT INTO change_log
                    (ts, source, entity, entity_id, product_id, field, old_value, new_value)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", log_rows)
            cur.execute("INSERT INTO runs (ts, products, variants, changes, complete) VALUES (%s,%s,%s,%s,%s)",
                        (now_dt, len(prods), len(variants), len(changes), complete))
    print(f"Neon: {len(p_rows)} products, {len(v_rows)} variants upsert, {len(log_rows)} changes save.")


# ---------------- 4. Telegram ----------------
FIELD_LABEL = {
    "on_sale": "Sale status", "price": "Price", "compare_at_price": "MRP", "available": "Stock",
    "title": "Naam", "handle": "URL", "product_type": "Category", "tags": "Tags",
    "published_at": "Launch date", "image": "Photo", "desc_hash": "Description", "sku": "SKU",
    "NEW_PRODUCT": "Naye products", "REMOVED_PRODUCT": "Hataye gaye products",
    "BACK_ON_SITE": "Wapas aaye products", "NEW_VARIANT": "Naye sizes", "REMOVED_VARIANT": "Hataye gaye sizes",
}


def format_change(c):
    _, _, _, _, _, ptitle, vtitle, field, old, new = c
    name = ptitle or "?"
    if vtitle and vtitle != "Default Title":
        name += f" [{vtitle}]"
    if field == "price":
        o, n = _num(old), _num(new)
        arrow = "📉" if (o is not None and n is not None and n < o) else "📈"
        return f"{arrow} {name}: ₹{old} → ₹{new}"
    if field == "on_sale":
        if old == "No":
            return f"🔥 Sale shuru: {name} ({new} off)"
        if new == "No":
            return f"⏹ Sale khatam: {name}"
        return f"🔥 Discount badla: {name}: {old} → {new}"
    if field == "compare_at_price":
        return f"🏷 {name}: MRP {old or '-'} → {new or '-'}"
    if field == "available":
        return f"{'✅ Stock wapas' if new == 'True' else '❌ Sold out'}: {name}"
    if field == "NEW_PRODUCT":
        return f"🆕 Naya product: {name}"
    if field == "REMOVED_PRODUCT":
        return f"🗑 Hata diya: {name}"
    if field == "BACK_ON_SITE":
        return f"↩️ Wapas site pe: {name}"
    if field == "NEW_VARIANT":
        return f"➕ Naya size: {name}"
    if field == "REMOVED_VARIANT":
        return f"➖ Size hataya: {name}"
    return f"✏️ {name}: {FIELD_LABEL.get(field, field)} badla"


def build_messages(changes, now_ist):
    counts = Counter(c[7] for c in changes)
    header = [f"🛍 Snitch: {len(changes)} changes ({now_ist.strftime('%d %b, %I:%M %p')})"]
    header += [f"• {FIELD_LABEL.get(f, f)}: {n}" for f, n in counts.most_common()]
    header.append("")

    # Price wale changes sabse upar
    order = {"on_sale": 0, "price": 1, "compare_at_price": 2, "available": 3, "NEW_PRODUCT": 4}
    lines = [format_change(c) for c in sorted(changes, key=lambda c: order.get(c[7], 9))]

    messages, current = [], "\n".join(header)
    for i, line in enumerate(lines):
        if len(current) + len(line) + 1 > 3800:  # Telegram limit 4096 chars
            messages.append(current)
            if len(messages) == MAX_TELEGRAM_MSGS - 1:
                rest = len(lines) - i
                current = f"... aur {rest} changes database (change_log) mein save hain."
                break
            current = line
        else:
            current += "\n" + line
    messages.append(current)
    return messages


TELEGRAM_FAILED = False  # True hua toh run ke end mein GitHub run RED ho jayega


def send_telegram(messages):
    global TELEGRAM_FAILED
    if not BOT_TOKEN or not CHAT_ID:
        print("(Telegram token/chat id nahi mila, console pe print kar raha hoon)\n")
        for m in messages:
            print(m, "\n---")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            print("❌ GitHub pe TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secret missing hai.")
            TELEGRAM_FAILED = True
        return
    print(f"Telegram: token {len(BOT_TOKEN)} chars, ':' {'hai' if ':' in BOT_TOKEN else 'NAHI hai'}, "
          f"chat id {CHAT_ID[:3]}... ({len(CHAT_ID)} digits)")
    for m in messages:
        try:
            r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                              data={"chat_id": CHAT_ID, "text": m, "disable_web_page_preview": True}, timeout=20)
            if not r.ok:
                print("❌ Telegram error:", r.status_code, r.text[:200])
                TELEGRAM_FAILED = True
        except requests.RequestException as e:
            print("❌ Telegram error:", e)
            TELEGRAM_FAILED = True
        time.sleep(1.1)  # Telegram rate limit se bacho


# ---------------- Main ----------------
def main():
    now_utc = datetime.now(timezone.utc)
    now = now_utc.isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

    try:
        raw, complete = fetch_catalog()
    except Exception as e:
        print("❌ Fetch fail:", e)
        sys.exit(1)

    prods, variants = normalize(raw)
    print("Mode:", "Neon (DATABASE_URL mila)" if DATABASE_URL else "SIRF LOCAL (DATABASE_URL nahi mila)")
    print(f"Fetched {len(prods)} products, {len(variants)} variants (complete={complete})")
    if len(raw) != len(prods):
        print(f"⚠️ {len(raw)} rows aaye lekin unique products {len(prods)} -> pages repeat ho rahe hain, pagination check karo.")
    if len(raw) and len(raw) % 250 == 0:
        print("⚠️ Products ki ginti 250 ka exact multiple hai. Check karo ki pagination sahi chal raha hai.")

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    changes, first_run, complete = find_changes(conn, prods, variants, complete, now,
                                                log_locally=not DATABASE_URL)
    if DATABASE_URL:
        try:
            sync_to_neon(changes, prods, variants, first_run, complete, now_utc)
        except Exception as e:
            # Neon fail hua toh local state bhi save mat karo -> agla run yahi changes dobara pakdega
            conn.rollback()
            conn.close()
            print("❌ Neon save fail:", e)
            sys.exit(1)
    conn.execute("INSERT INTO runs (ts, products, variants, changes, complete) VALUES (?,?,?,?,?)",
                 (now, len(prods), len(variants), len(changes), int(complete)))
    conn.commit()
    conn.close()

    if first_run:
        send_telegram([f"✅ Tracker shuru! Baseline save hua: {len(prods)} products, {len(variants)} sizes/variants. "
                       f"Ab se har change yahan aayega."])
    elif changes:
        send_telegram(build_messages(changes, now_utc.astimezone(IST)))
    else:
        print("Koi change nahi.")

    # Data pehle hi save ho chuka hai; ab sirf GitHub ko batana hai ki alert nahi pahuncha
    if TELEGRAM_FAILED:
        sys.exit(1)


if __name__ == "__main__":
    main()