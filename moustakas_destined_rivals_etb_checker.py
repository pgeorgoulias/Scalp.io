import argparse
import html
import json
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests


BASE_URL = "https://www.moustakastoys.gr"
DEFAULT_SEARCH_QUERY = "pokemon tcg destined rivals elite trainer box"
DEFAULT_REQUIRED_TERMS = ["pokemon", "destined", "rivals", "elite", "trainer", "box", "ETB", "Destined Rivals"]
DEFAULT_BRAND_ID = "56"
DEFAULT_MIN_STOCK = "5"
DEFAULT_CACHE_FILE = Path(__file__).with_name("moustakas_destined_rivals_etb_cache.json")
DEFAULT_INTERVAL_SECONDS = 600
DEFAULT_SECRETS_FILE = Path(__file__).with_name("secrets.json")
REQUEST_TIMEOUT = 20
DISCORD_TIMEOUT = 10
DISCORD_ALERT_COLOR = 0x2ECC71
USER_AGENT = "Mozilla/5.0"


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.current_href = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs_by_name = dict(attrs)
            self.current_href = attrs_by_name.get("href")
            self.current_text = []

    def handle_data(self, data):
        if self.current_href is not None:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current_href is not None:
            text = " ".join(" ".join(self.current_text).split())
            self.links.append((text, self.current_href))
            self.current_href = None
            self.current_text = []


class StoreAvailabilityParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.in_row = False
        self.in_cell = False
        self.current_cells = []
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag == "div" and "availabilityTable__row" in classes:
            self.in_row = True
            self.current_cells = []
        elif self.in_row and tag == "div" and "availabilityTable__cell" in classes:
            self.in_cell = True
            self.current_text = []

    def handle_data(self, data):
        if self.in_cell:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "div" and self.in_cell:
            text = " ".join(" ".join(self.current_text).split())
            self.current_cells.append(text)
            self.in_cell = False
            self.current_text = []
        elif tag == "div" and self.in_row:
            if len(self.current_cells) >= 2:
                self.rows.append(
                    {
                        "store": self.current_cells[0],
                        "availability": self.current_cells[1],
                    }
                )
            self.in_row = False


def make_session():
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": USER_AGENT,
        }
    )
    return session


def fetch_text(session, url, params=None, referer=None):
    headers = {}
    if referer:
        headers["Referer"] = referer

    response = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text, response.url


def load_cache(cache_file):
    if not cache_file.exists():
        return {}

    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(cache_file, cache):
    cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def load_discord_webhook_url(args):
    if args.discord_webhook_url:
        return args.discord_webhook_url

    env_webhook_url = os.environ.get("MOUSTAKAS_DISCORD_WEBHOOK_URL")
    if env_webhook_url:
        return env_webhook_url

    if not args.secrets_file.exists():
        return None

    try:
        secrets = json.loads(args.secrets_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    return secrets.get("moustakas_discord_webhook_url") or secrets.get("discord_webhook_url")


def normalize_text(value):
    return " ".join(html.unescape(value or "").lower().split())


def product_matches(text, href, required_terms):
    haystack = normalize_text(f"{text} {href}")
    return all(term.lower() in haystack for term in required_terms)


def find_product_url(session, search_query, required_terms):
    search_html, _ = fetch_text(
        session,
        urljoin(BASE_URL, "/apotelesmata-anazitisis/"),
        params={
            "profile": "Default",
            "section": "Products",
            "q": search_query,
        },
    )

    parser = LinkParser()
    parser.feed(search_html)

    for text, href in parser.links:
        if product_matches(text, href, required_terms):
            return urljoin(BASE_URL, href), text

    return None, None


def extract_json_ld_product(page_html):
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    for script in scripts:
        try:
            payload = json.loads(html.unescape(script).strip())
        except json.JSONDecodeError:
            continue

        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "Product":
                return item

    return {}


def extract_store_stock_url(page_html):
    match = re.search(
        r'data-plugin-updatemodal=[\'"](?P<payload>\{.*?StockPerStore.*?\})[\'"]',
        page_html,
        flags=re.DOTALL,
    )
    if not match:
        return None

    try:
        payload = json.loads(html.unescape(match.group("payload")))
    except json.JSONDecodeError:
        return None

    stock_url = payload.get("url")
    return urljoin(BASE_URL, stock_url) if stock_url else None


def extract_product_summary(page_html, product_url):
    product = extract_json_ld_product(page_html)
    stock_url = extract_store_stock_url(page_html)
    cart_match = re.search(r"&quot;RemainingStock&quot;:([0-9.]+)", page_html)

    return {
        "url": product_url,
        "name": product.get("name"),
        "sku": product.get("sku"),
        "product_id": product.get("productID"),
        "page_availability": (product.get("offers") or {}).get("availability"),
        "price": (product.get("offers") or {}).get("price"),
        "remaining_stock": float(cart_match.group(1)) if cart_match else None,
        "store_stock_url": stock_url,
    }


def build_stock_url(sku, brand_id=DEFAULT_BRAND_ID, min_stock=DEFAULT_MIN_STOCK):
    return urljoin(
        BASE_URL,
        (
            "/$component/StockPerStore/"
            f"?sku={sku}&brandID={brand_id}&minStock={min_stock}"
            "&View=../Products/GetStoreStocksBySKU"
        ),
    )


def sku_candidates_from_pok_code(pok_code):
    digits = re.sub(r"\D+", "", pok_code or "")
    if not digits:
        return []

    candidates = [digits]
    if len(digits) <= 6:
        padded = digits.zfill(6)
        last_five_padded = digits[-5:].zfill(6)
        candidates.extend([
            f"546922{padded}",
            f"546923{padded}",
            f"546924{padded}",
            f"546922{last_five_padded}",
            f"546923{last_five_padded}",
            f"546924{last_five_padded}",
        ])

    deduped = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def fetch_store_availability(session, stock_url, product_url):
    if not stock_url:
        return []

    stock_html, _ = fetch_text(
        session,
        stock_url,
        referer=product_url,
    )
    parser = StoreAvailabilityParser()
    parser.feed(stock_html)
    return parser.rows


def fetch_store_availability_for_sku(session, sku, brand_id=DEFAULT_BRAND_ID, min_stock=DEFAULT_MIN_STOCK):
    stock_url = build_stock_url(sku, brand_id, min_stock)
    rows = fetch_store_availability(session, stock_url, BASE_URL)
    return stock_url, rows


def is_available_store(row):
    availability_text = normalize_text(row.get("availability"))
    return "διαθέσιμο" in availability_text and "μη διαθέσιμο" not in availability_text


def store_key(row):
    return normalize_text(row.get("store"))


def summarize_store_rows(rows, product=None, matched_title=None):
    available_stores = [row for row in rows if is_available_store(row)]
    return {
        "found": True,
        "matched_title": matched_title,
        "product": product or {},
        "store_count": len(rows),
        "available_store_count": len(available_stores),
        "available_stores": available_stores,
    }


def check_stock_url(session, stock_url, product_url=BASE_URL, product=None):
    stores = fetch_store_availability(session, stock_url, product_url)
    product = product or {}
    product.setdefault("store_stock_url", stock_url)
    return summarize_store_rows(stores, product=product)


def check_sku_candidates(session, sku_candidates, brand_id=DEFAULT_BRAND_ID, min_stock=DEFAULT_MIN_STOCK):
    for sku in sku_candidates:
        stock_url = build_stock_url(sku, brand_id, min_stock)
        stores = fetch_store_availability(session, stock_url, BASE_URL)
        if stores:
            return summarize_store_rows(
                stores,
                product={
                    "sku": sku,
                    "store_stock_url": stock_url,
                },
            )

    return {
        "found": False,
        "message": "No store availability endpoint returned rows for the provided SKU candidates.",
        "sku_candidates": sku_candidates,
    }


def check_product(product_url=None, search_query=DEFAULT_SEARCH_QUERY, required_terms=None):
    required_terms = required_terms or DEFAULT_REQUIRED_TERMS
    session = make_session()

    discovered_title = None
    if not product_url:
        product_url, discovered_title = find_product_url(session, search_query, required_terms)

    if not product_url:
        return {
            "found": False,
            "search_query": search_query,
            "required_terms": required_terms,
            "message": "Product URL was not found in Moustakas search results.",
        }

    page_html, final_url = fetch_text(session, product_url)
    summary = extract_product_summary(page_html, final_url)
    stores = fetch_store_availability(session, summary.get("store_stock_url"), final_url)
    return summarize_store_rows(stores, product=summary, matched_title=discovered_title)


def resolve_initial_result(args, cache):
    session = make_session()

    if args.stock_url:
        return check_stock_url(session, args.stock_url)

    if args.sku:
        return check_sku_candidates(session, [args.sku], args.brand_id, args.min_stock)

    if args.pok_code:
        return check_sku_candidates(
            session,
            sku_candidates_from_pok_code(args.pok_code),
            args.brand_id,
            args.min_stock,
        )

    cached_stock_url = cache.get("store_stock_url")
    if cached_stock_url:
        return check_stock_url(
            session,
            cached_stock_url,
            product_url=cache.get("product_url") or BASE_URL,
            product=cache.get("product") or {},
        )

    return check_product(
        product_url=args.product_url,
        search_query=args.search_query,
        required_terms=args.required_terms,
    )


def refresh_from_cached_endpoint(args, cache):
    session = make_session()
    stock_url = cache.get("store_stock_url")
    if not stock_url:
        return resolve_initial_result(args, cache)

    return check_stock_url(
        session,
        stock_url,
        product_url=cache.get("product_url") or BASE_URL,
        product=cache.get("product") or {},
    )


def update_cache_from_result(cache, result):
    if not result.get("found"):
        return cache

    product = result.get("product") or {}
    stock_url = product.get("store_stock_url")
    if not stock_url:
        return cache

    cache["store_stock_url"] = stock_url
    if product.get("url"):
        cache["product_url"] = product["url"]
    cache["product"] = product
    cache["updated_at"] = int(time.time())
    return cache


def available_store_keys(result):
    return sorted(store_key(store) for store in result.get("available_stores", []))


def should_send_discord_notification(cache, result):
    if not result.get("found") or result.get("available_store_count", 0) <= 0:
        return False

    current_keys = available_store_keys(result)
    previous_keys = cache.get("last_notified_available_store_keys") or []
    return current_keys != previous_keys


def mark_discord_notification_sent(cache, result):
    cache["last_notified_available_store_keys"] = available_store_keys(result)
    cache["last_notified_at"] = int(time.time())
    return cache


def discord_product_name(result):
    product = result.get("product") or {}
    return product.get("name") or result.get("matched_title") or product.get("sku") or "Moustakas product"


def build_discord_payload(result):
    product = result.get("product") or {}
    product_name = discord_product_name(result)
    product_url = product.get("url") or product.get("store_stock_url") or BASE_URL
    stores = result.get("available_stores", [])
    store_lines = [f"- {store['store']}: {store['availability']}" for store in stores[:12]]

    fields = [
        {"name": "Available stores", "value": str(result.get("available_store_count", 0)), "inline": True},
        {"name": "Stores checked", "value": str(result.get("store_count", 0)), "inline": True},
    ]

    if product.get("sku"):
        fields.append({"name": "SKU", "value": str(product["sku"]), "inline": True})

    if product.get("price"):
        fields.append({"name": "Price", "value": str(product["price"]), "inline": True})

    if store_lines:
        fields.append({"name": "Available at", "value": "\n".join(store_lines), "inline": False})

    return {
        "content": "Moustakas Pokemon TCG stock alert",
        "username": "Stock Monitor Bot",
        "embeds": [
            {
                "title": "Moustakas availability discovered",
                "description": f"**{product_name}**",
                "url": product_url,
                "color": DISCORD_ALERT_COLOR,
                "fields": fields,
            }
        ],
    }


def send_discord_notification(webhook_url, result):
    if not webhook_url:
        return False

    try:
        response = requests.post(
            webhook_url,
            json=build_discord_payload(result),
            timeout=DISCORD_TIMEOUT,
        )
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to send Discord notification: {e}")
        return False

    print("Discord notification sent.")
    return True


def print_result(result):
    if not result.get("found"):
        print(result["message"])
        if result.get("search_query"):
            print(f"Search query: {result['search_query']}")
        if result.get("required_terms"):
            print(f"Required terms: {', '.join(result['required_terms'])}")
        if result.get("sku_candidates"):
            print(f"SKU candidates: {', '.join(result['sku_candidates'])}")
        return

    product = result["product"]
    print(f"Product: {product.get('name') or result.get('matched_title') or 'Unknown'}")
    print(f"URL: {product.get('url') or 'unknown'}")
    print(f"SKU: {product.get('sku') or 'unknown'}")
    print(f"Page availability: {product.get('page_availability') or 'unknown'}")
    print(f"Price: {product.get('price') or 'unknown'}")
    print(f"Remaining stock: {product.get('remaining_stock')}")
    print(f"Stores checked: {result['store_count']}")
    print(f"Available stores: {result['available_store_count']}")

    for store in result["available_stores"]:
        print(f"- {store['store']}: {store['availability']}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Check Moustakas store availability for Pokemon TCG Destined Rivals ETB."
    )
    parser.add_argument("--product-url", help="Direct Moustakas product URL. Best when known.")
    parser.add_argument("--stock-url", help="Direct StockPerStore endpoint. Fastest and lowest-noise option.")
    parser.add_argument("--sku", help="Moustakas backend SKU, if known.")
    parser.add_argument("--pok-code", help="Visible product code such as POK809064. Tries a small candidate set.")
    parser.add_argument("--brand-id", default=DEFAULT_BRAND_ID)
    parser.add_argument("--min-stock", default=DEFAULT_MIN_STOCK)
    parser.add_argument("--search-query", default=DEFAULT_SEARCH_QUERY)
    parser.add_argument("--cache-file", type=Path, default=DEFAULT_CACHE_FILE)
    parser.add_argument("--secrets-file", type=Path, default=DEFAULT_SECRETS_FILE)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--discord-webhook-url", help="Discord webhook URL for availability alerts.")
    parser.add_argument("--notify-discord", action="store_true", help="Send Discord alert when availability is discovered.")
    parser.add_argument(
        "--required-term",
        action="append",
        dest="required_terms",
        help="Term that must appear in the search-result product text or URL. Can be repeated.",
    )
    parser.add_argument("--once", action="store_true", help="Run one check and exit.")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS, help="Seconds between loop checks. Default: 600 (10 minutes).")
    return parser.parse_args()


def main():
    args = parse_args()
    cache = {} if args.no_cache else load_cache(args.cache_file)
    webhook_url = load_discord_webhook_url(args)

    while True:
        result = refresh_from_cached_endpoint(args, cache)
        print_result(result)

        if args.notify_discord:
            if not webhook_url:
                print("Discord notification requested, but no webhook URL was provided.")
            elif should_send_discord_notification(cache, result):
                if send_discord_notification(webhook_url, result):
                    cache = mark_discord_notification_sent(cache, result)

        if not args.no_cache:
            cache = update_cache_from_result(cache, result)
            save_cache(args.cache_file, cache)

        if args.once:
            break

        print(f"\nWaiting {args.interval} seconds before next check...")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
