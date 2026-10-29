# Project samjho: Snitch Sale Tracker

Yeh file un logon ke liye hai jo code padhe bina samajhna chahte hain ki yeh project kya karta hai aur kaise.
Setup ke steps [README.md](README.md) mein hain.

## Ek line mein
Har ghante Snitch ki website se saare products ki list laata hai, pichhli baar se compare karta hai,
jo bhi badla (price, sale, stock, naye products...) use hamesha ke liye database mein likhta hai, aur
Telegram pe ek summary bhej deta hai.

## Ek run mein kya hota hai

```
GitHub Actions (har ghante)
   │
   ├─ 1. Pichhli baar ka state (data/state.db) cache se wapas laao
   ├─ 2. Snitch se poora catalog laao (products.json, 250 products ek page mein)
   ├─ 3. Naye data ko purane state se compare karo → changes ki list
   ├─ 4. Changes Neon database mein permanently save karo
   ├─ 5. Naya state cache mein save karo (agle run ke compare ke liye)
   └─ 6. Telegram pe summary bhejo
```

**1. Purana state laana** — GitHub har run naye, khaali computer pe chalata hai. Isliye pichhle run ka
`data/state.db` (ek chhota SQLite database) Actions cache mein rakha jaata hai aur har run ki shuruaat mein wapas laaya jaata hai.

**2. Catalog laana** — Snitch Shopify pe bana hai, aur Shopify stores `/products.json` pe saare products ki
list dete hain. Tracker page 1, 2, 3... tab tak maangta hai jab tak khaali page na aa jaaye. Har page ke beech
2 second rukta hai taaki site pe load na pade.

**3. Compare karna** — Har product aur har variant (size/colour) ke kuch fields dekhe jaate hain:

| Kya | Fields |
|---|---|
| Product | naam, URL, category, tags, launch date, pehli photo, description |
| Variant (size) | naam, SKU, price, MRP, stock (available), sale status |

"Sale status" tracker khud nikalta hai: agar MRP price se zyada hai toh discount % (jaise `40%`), warna `No`.
Isi se pata chalta hai ki sale kab shuru hui aur kab khatam.

Inke alawa yeh bhi pakde jaate hain: naya product, product hataya gaya, product wapas aaya, naya size, size hataya gaya.

**4. Neon mein save** — Har change `change_log` table mein ek row ban jaata hai (kab, kaunsa product, kya badla,
purani value, nayi value). Yeh record kabhi delete nahi hota, toh baad mein history dekh sakte ho.

**5. State save** — Naya state cache mein chala jaata hai, taaki agla run isse compare kare.

**6. Telegram** — Saare changes ek message mein, upar ginti aur phir list. Price/sale wale changes sabse upar.
Jaise:
```
🛍 Snitch: 3 changes (29 Oct, 02:17 PM)
• Sale status: 1
• Price: 1
• Stock: 1

🔥 Sale shuru: Oversized Shirt [M] (40% off)
📉 Oversized Shirt [M]: ₹1999.00 → ₹1199.00
❌ Sold out: Cargo Pants [32]
```
Bahut saare changes hon toh max 5 messages jaate hain; baaki sirf database mein rehte hain.

## Galtiyon se bachne ke intezaam
- **Pehla run = baseline**: Pehli baar compare karne ko kuch nahi hota, isliye sirf data save hota hai, alerts nahi.
- **Retry**: Site ne 429/5xx error ya network problem di toh 15s, 45s, 90s ruk ke dobara try. Phir bhi fail toh
  run wahin ruk jaata hai — adhoori list se galat "product hata diya" alerts nahi aate.
- **Achanak kam products**: Agar is baar pichhli baar se aadhe se bhi kam products mile, toh "hataya gaya"
  wali checking skip ho jaati hai (shayad site ne poori list nahi di).
- **Sab ya kuch nahi**: Neon mein sab ek transaction mein likha jaata hai. Neon fail hua toh local state bhi
  save nahi hota, toh agla run wahi changes dobara pakad leta hai — kuch chhootta nahi.
- **Telegram fail = RED run**: Message nahi gaya toh data toh save ho jaata hai, par GitHub run laal (fail)
  dikhata hai taaki tumhe pata chale.
- **Secrets saaf karna**: Secret paste karte waqt quotes, spaces ya `TELEGRAM_BOT_TOKEN=` bhi aa jaaye toh
  tracker unhe apne aap hata deta hai.

## Files

| File | Kaam |
|---|---|
| `tracker.py` | Poora tracker: fetch, compare, Neon, Telegram |
| `check_site.py` | Setup ke time ek baar: check karo ki products.json khula hai aur kaunse fields milte hain |
| `.github/workflows/track.yml` | GitHub ko batata hai kab aur kaise chalana hai, aur secrets dena |
| `requirements.txt` | Python libraries: `requests` (website/Telegram) aur `psycopg` (Neon) |
| `.env.example` | Local `.env` file ka namuna |
| `.gitignore` | `.env`, `data/` wagairah ko GitHub pe jaane se rokta hai |

## Database tables (Neon)

| Table | Kya hai |
|---|---|
| `products` | Har product ki abhi ki jaankari (naam, URL, tags...) aur kab pehli baar dikha, hata ya nahi |
| `variants` | Har size/colour ka price, MRP, stock, sale status |
| `change_log` | Har change ka permanent record — yahi asli history hai |
| `runs` | Har run ka hisaab: kitne products, kitne changes, list poori aayi ya nahi |

`DATABASE_URL` set na ho toh yahi tables `data/state.db` (SQLite) mein ban jaati hain — laptop pe testing ke liye.

## Secrets kahan rehte hain
Teen cheezein secret hain: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATABASE_URL`.
- GitHub pe: Settings → Secrets and variables → Actions → Secrets. Logs mein yeh `***` dikhte hain.
- Laptop pe: `.env` file mein (jo GitHub pe upload nahi hoti).

Code mein sirf inke **naam** hain, value kabhi nahi. Ise aise hi rakhna.

## Chhote badlav kahan karein (`tracker.py` mein upar "Settings" wala hissa)
- `PAGE_DELAY_SEC` — har page ke beech kitne second rukna hai
- `MAX_TELEGRAM_MSGS` — ek run mein max kitne Telegram messages
- `PRODUCT_FIELDS` / `VARIANT_FIELDS` — kaunse fields ke change track honge
- Kitni baar chale: `.github/workflows/track.yml` mein `cron: "17 * * * *"` (UTC time, har ghante minute 17)
