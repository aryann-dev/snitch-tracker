# Snitch Sale Tracker (V1: website)

Har ghante Snitch ka poora catalog check karta hai, har change (price, MRP, sale, stock, naye/hataye products,
sizes, tags, photo, description) database mein save karta hai, aur ek grouped summary Telegram pe bhejta hai.

Project andar se kaise kaam karta hai, woh aasan bhasha mein [PROJECT_SAMJHO.md](PROJECT_SAMJHO.md) mein hai.

## Kaise chalta hai
- GitHub Actions pe har ghante minute 17 pe (UTC) apne aap chalta hai (`.github/workflows/track.yml`).
  GitHub schedule ko kabhi-kabhi late karta hai ya skip kar deta hai, isliye har ghante run ki guarantee nahi hai.
- Actions tab → "Snitch tracker" → "Run workflow" se kabhi bhi manually chala sakte ho.
- Pehla run sirf "baseline" save karta hai (koi change alert nahi), kyunki compare karne ke liye purana data chahiye.

## Storage
- **Neon Postgres** = permanent record (`change_log`, `products`, `variants`, `runs`)
- **data/state.db** = sirf compare karne ke liye abhi ka state. GitHub pe Actions cache mein rehta hai, repo mein commit nahi hota.
- `DATABASE_URL` set na ho toh sab local SQLite mein jaata hai (testing ke liye).

## Files
- `check_site.py` — STEP 1: check karo products.json khula hai ya nahi
- `tracker.py` — main tracker
- `.github/workflows/track.yml` — har ghante GitHub pe chalane ke liye
- `.env.example` — local `.env` file ka namuna
- `data/state.db` — local state (pehle run ke baad banega)

## Setup

**1. Site check (apne laptop pe)**
```
pip install -r requirements.txt
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
- Local test: `.env.example` ko copy karke naam `.env` rakho aur usmein `DATABASE_URL` (aur chaho toh
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) bharo. `tracker.py` ise apne aap padh leta hai.
  `.env` `.gitignore` mein hai, GitHub pe upload nahi hogi.
  (Ya PowerShell mein: `$env:DATABASE_URL="<string>"` phir `python tracker.py`)
- Neon SQL Editor mein `SELECT count(*) FROM variants;` se check karo data aaya

**5. GitHub**
- Repo banao, saari files push karo
- Settings → Secrets and variables → Actions:
  - Secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL`
  - Variables: `STORE_URL` (step 1 wala URL)
- Actions tab → "Snitch tracker" → "Run workflow" se pehla run manually chalao

> ⚠️ Token, chat id ya database string kabhi code, README ya commit mein mat likho — sirf GitHub Secrets
> aur local `.env` mein. Public repo ke Actions logs bhi sab dekh sakte hain; GitHub secrets ko `***` se chhupa deta hai.

## Data dekhna
Neon SQL Editor mein, jaise:
```sql
SELECT c.ts, p.title, v.title AS size, c.field, c.old_value, c.new_value
FROM change_log c
JOIN products p ON p.id = c.product_id
LEFT JOIN variants v ON v.id = c.entity_id AND c.entity = 'variant'
ORDER BY c.ts DESC LIMIT 50;
```

## Run RED (fail) ho gaya?
Actions tab mein run kholo → "Run tracker" step ka log dekho:
- `❌ Fetch fail` — Snitch site ne jawab nahi diya (3 baar retry ke baad bhi). Agla run apne aap try karega.
- `❌ Neon save fail` — database tak nahi pahunch paya. Kuch save nahi hua, agla run yahi changes dobara pakdega.
  Bar-bar aaye toh `DATABASE_URL` secret check karo.
- `❌ Telegram error: 401` — bot token galat hai. `404` — token ka format galat hai (aksar copy-paste mein gadbad).
  `400 chat not found` — CHAT_ID galat hai, ya bot ko pehle message nahi bheja. Data phir bhi save ho chuka hota hai.
- `❌ GitHub pe TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID secret missing hai` — Secrets mein yeh dono daalo.
