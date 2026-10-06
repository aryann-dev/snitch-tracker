"""
STEP 1: Check karo ki Snitch ka products.json khula hai ya nahi, aur kaunse fields milte hain.
Chalao:  python check_site.py
Kisi aur site ke liye:  python check_site.py https://example.com
"""
import sys
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal price tracker; low frequency)",
    "Accept": "application/json",
}
CANDIDATES = sys.argv[1:] or [
    "https://www.snitch.co.in",
    "https://snitch.co.in",
    "https://www.snitch.com",
    "https://snitch.com",
]

for base in CANDIDATES:
    url = base.rstrip("/") + "/products.json?limit=1"
    print("=" * 60)
    print("Checking:", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
    except requests.RequestException as e:
        print("  Request fail:", e)
        continue

    print("  Status:", r.status_code)
    print("  Final URL (redirect ke baad):", r.url)
    print("  Content-Type:", r.headers.get("Content-Type"))

    try:
        data = r.json()
    except ValueError:
        print("  JSON nahi aaya -> shayad HTML page, block page, ya site Shopify pe nahi hai.")
        continue

    products = data.get("products")
    if not products:
        print("  JSON aaya, lekin 'products' khali hai ya nahi mila. Keys:", list(data.keys()))
        continue

    p = products[0]
    print("  ✅ products.json KAAM KAR RAHA HAI")
    print("  Product fields:", sorted(p.keys()))
    variants = p.get("variants") or []
    if variants:
        v = variants[0]
        print("  Variant fields:", sorted(v.keys()))
        print("  Sample -> product:", p.get("title"))
        print("            variant:", v.get("title"),
              "| price:", v.get("price"),
              "| MRP (compare_at_price):", v.get("compare_at_price"),
              "| available:", v.get("available"))
        if "inventory_quantity" in v:
            print("  ⚡ inventory_quantity mil raha hai (exact stock number!)")
        else:
            print("  inventory_quantity nahi hai -> sirf in-stock haan/na milega")
    print("  Is URL ko STORE_URL ki tarah use karo:", r.url.split("/products.json")[0])
