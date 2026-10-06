# Snitch Sale Tracker (V1: website)

Har ghante Snitch ka poora catalog check karta hai, har change (price, MRP, stock, naye/hataye products,
tags, photo, description) database mein save karta hai, aur ek grouped summary Telegram pe bhejta hai.

## Storage
- **Neon Postgres** = permanent record (`change_log`, `products`, `variants`, `runs`)
- **data/state.db** = sirf compare karne ke liye abhi ka state. GitHub pe Actions cache mein rehta hai, repo mein commit nahi hota.
- `DATABASE_URL` set na ho toh sab local SQLite mein jaata hai (testing ke liye).

## Files
- `check_site.py` — STEP 1: check karo products.json khula hai ya nahi
- `tracker.py` — main tracker
- `.github/workflows/track.yml` — har ghante GitHub pe chalane ke liye
- `data/state.db` — local state (pehle run ke baad banega)

## Setup

**1. Site check (apne laptop pe)**
```
pip install requests
python check_site.py
```
Jis URL pe "✅ products.json KAAM KAR RAHA HAI" aaye, wahi tumhara STORE_URL hai.
Agar sab pe fail aaye, toh ruk jao aur output share karo — tab dusra tareeka lagega.

**2. Local test (bina Telegram ke)**
```
python tracker.py      # pehla run: baseline
python tracker.py      # dusra run: changes (shayad 0)
```
Telegram token na ho toh output console pe print hoga.

**3. Telegram bot**
- Telegram pe @BotFather → `/newbot` → token copy karo
- Apne bot ko koi bhi message bhejo
- Browser mein kholo: `https://api.telegram.org/bot<TOKEN>/getUpdates` → `"chat":{"id": ...}` wala number = CHAT_ID

**4. Neon**
- neon.com pe free account banao → New project (region: AWS US East, kyunki GitHub runners zyada tar US mein hain)
- Dashboard → Connect → connection string copy karo (`postgresql://...sslmode=require`)
- Local test (PowerShell): `$env:DATABASE_URL="<string>"` phir `python tracker.py`
- Neon SQL Editor mein `SELECT count(*) FROM variants;` se check karo data aaya

**5. GitHub**
- Naya **public** repo banao, saari files push karo
- Settings → Secrets and variables → Actions:
  - Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL`
  - Variables: `STORE_URL` (step 1 wala URL)
- Actions tab → "Snitch tracker" → "Run workflow" se pehla run manually chalao

## Data dekhna
Neon SQL Editor mein, jaise:
```sql
SELECT c.ts, p.title, v.title AS size, c.field, c.old_value, c.new_value
FROM change_log c
JOIN products p ON p.id = c.product_id
LEFT JOIN variants v ON v.id = c.entity_id AND c.entity = 'variant'
ORDER BY c.ts DESC LIMIT 50;
```
