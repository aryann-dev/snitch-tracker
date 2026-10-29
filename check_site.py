"""
STEP 1: Check whether Snitch's products.json is publicly available, and which fields it returns.
Run:  python check_site.py
For another site:  python check_site.py https://example.com
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
        print("  Request failed:", e)
        continue

    print("  Status:", r.status_code)
    print("  Final URL (after redirects):", r.url)
    print("  Content-Type:", r.headers.get("Content-Type"))

    try:
        data = r.json()
    except ValueError:
        print("  Response is not JSON -> probably an HTML page, a block page, or the site is not on Shopify.")
        continue

    products = data.get("products")
    if not products:
        print("  Got JSON, but 'products' is empty or missing. Keys:", list(data.keys()))
        continue

    p = products[0]
    print("  ✅ products.json IS WORKING")
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
            print("  ⚡ inventory_quantity is available (exact stock count!)")
        else:
            print("  inventory_quantity is not available -> only in-stock yes/no")
    print("  Use this URL as STORE_URL:", r.url.split("/products.json")[0])
