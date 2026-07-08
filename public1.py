import hashlib
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


SEARCH_URL = "https://www.public.gr/search?q=pokemon%20tcg"
PRODUCT_DETAILS_URL_TEMPLATE = "https://www.public.gr/public/v2/sku/{sku_id}"
PRODUCT_STOCK_URL = "https://www.public.gr/public/v1/mm/productPage"
STORE_AVAILABILITY_URL = "https://www.public.gr/public/v1/mm/stores"
STATE_FILE = Path(__file__).with_name("public_product_state.json")
SECRETS_FILE = Path(__file__).with_name("secrets.json")
CONFIG_FILE = Path(__file__).with_name("public_monitor_config.json")
LOCAL_TIMEZONE = ZoneInfo("Europe/Athens")

CHECK_INTERVAL = 5  # seconds between monitor cycles
CHECK_INTERVAL_JITTER = 3  # extra random seconds between cycles
PRODUCT_CHECK_DELAY = 10  # seconds between sequential product API checks
WATCHLIST_CHECK_INTERVAL = 20  # seconds between direct checks of known product URLs
SHALLOW_LISTING_SCAN_INTERVAL = 180  # seconds between first-page listing scans
DEEP_LISTING_SCAN_INTERVAL = 900  # seconds between full listing scans
LISTING_BACKOFF_INITIAL = 300  # seconds to pause listing scans after a failure
LISTING_BACKOFF_MAX = 3600  # maximum seconds to pause listing scans after repeated failures
LISTING_ACTION_DELAY = 2  # seconds after scrolling/clicking listing controls
FULL_VERIFY_INTERVAL = 3600  # seconds between slow safety checks of every product
SHALLOW_LISTING_PAGES = 3
MAX_LISTING_PAGES = 20
MAX_EXPAND_CLICKS = 20
FIRST_RUN_NOTIFY = False
DISCORD_ALERT_COLOR = 0x2ECC71
DISCORD_TIMEOUT = 5
API_TIMEOUT = 10
STORE_AVAILABILITY_TIMEOUT = 10
PAGE_LOAD_TIMEOUT = 30000
SELECTOR_WAIT_TIMEOUT = 8000
PRODUCT_LINK_SELECTOR = 'a[href*="/product/"]'
BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
STORE_ONLY_TEXT = "Αγορά μόνο από κατάστημα"
TARGET_STORE_AREA = "Athens"

CONFIG_SETTING_MAP = {
    "search_url": "SEARCH_URL",
    "check_interval": "CHECK_INTERVAL",
    "check_interval_jitter": "CHECK_INTERVAL_JITTER",
    "product_check_delay": "PRODUCT_CHECK_DELAY",
    "watchlist_check_interval": "WATCHLIST_CHECK_INTERVAL",
    "shallow_listing_scan_interval": "SHALLOW_LISTING_SCAN_INTERVAL",
    "deep_listing_scan_interval": "DEEP_LISTING_SCAN_INTERVAL",
    "listing_backoff_initial": "LISTING_BACKOFF_INITIAL",
    "listing_backoff_max": "LISTING_BACKOFF_MAX",
    "listing_action_delay": "LISTING_ACTION_DELAY",
    "full_verify_interval": "FULL_VERIFY_INTERVAL",
    "shallow_listing_pages": "SHALLOW_LISTING_PAGES",
    "max_listing_pages": "MAX_LISTING_PAGES",
    "max_expand_clicks": "MAX_EXPAND_CLICKS",
    "first_run_notify": "FIRST_RUN_NOTIFY",
    "discord_timeout": "DISCORD_TIMEOUT",
    "api_timeout": "API_TIMEOUT",
    "store_availability_timeout": "STORE_AVAILABILITY_TIMEOUT",
    "page_load_timeout": "PAGE_LOAD_TIMEOUT",
    "selector_wait_timeout": "SELECTOR_WAIT_TIMEOUT",
    "target_store_area": "TARGET_STORE_AREA",
}


def load_monitor_config():
    if not CONFIG_FILE.exists():
        return {}

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Could not read config file. Using built-in settings: {e}")
        return {}

    if not isinstance(config, dict):
        print("Config file root must be a JSON object. Using built-in settings.")
        return {}

    return config


def apply_monitor_config(config):
    settings = config.get("settings") if isinstance(config.get("settings"), dict) else {}
    for setting_name, global_name in CONFIG_SETTING_MAP.items():
        if setting_name in settings:
            globals()[global_name] = settings[setting_name]

    products = config.get("watchlist_products")
    if isinstance(products, list):
        globals()["WATCHLIST_PRODUCTS"] = [
            product for product in products
            if isinstance(product, dict) and product.get("url")
        ]

    return config


def reload_monitor_config():
    return apply_monitor_config(load_monitor_config())

WATCHLIST_PRODUCTS = [
        {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-mega-evolution--ascended-heroes-25-tech-sticker-collection--tuxaia-epilogi-sxediou/2104845",
        "name": "Ascended Heroes 2.5 Tech Sticker Collection"
    },
    {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-mega-evolution--ascended-heroes-25-elite-trainer-box/2111316",
        "name": "Ascended Heroes 2.5 Elite Trainer Box"
    },
    {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-mega-evolution-elite-trainer-box-1-tmx--tuxaia-epilogi-sxediou/2088741",
        "name": "Mega Evolution Elite Trainer Box"
    },
    {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-scarlet-violet-85-prismatic-evolutions-premium-figure-collection/2094853",
        "name": "Prismatic Evolutions Premium Figure Collection"
    },
    {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/kaissa-pokemon-sv85-prismatic-evolutions-surprise-box-collection/1996547",
        "name": "Prismatic Evolutions Surprise Box"
    },
    {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokemon-kartes-sv85-prismatic-evolutions-tech-sticker-collection/1996522",
        "name": "Prismatic Evolutions Tech Sticker Collection"
    },
    {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokemon-kartes-sv85-prismatic-evolutions-elite-trainer-box/1996524",
        "name": "Prismatic Evolutions Elite Trainer Box"
    },
    {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-scarlet-violet--destined-rivals-booster/2033114",
        "name": "Pokémon TCG: Scarlet & Violet - Destined Rivals Booster"
    },
    {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-scarlet-violet--prismatic-evolutions-accessory-pouch-special-collection/2033109",
        "name": "Prismatic Evolutions Accessory Pouch"
    },
     {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokemon-kartes-sv85-prismatic-evolutions-binder-collection/1996523",
        "name": "Prismatic Evolutions Binder Collection"
    },
    {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-mega-evolution--ascended-heroes-25-2-pack-blister-collection--tuxaia-epilogi-sxediou/2104846",
        "name": "Ascended Heroes 2.5 2 Pack Blister Collection"
    },
    {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-scarlet-violet-105-black-bolt-elite-trainer-box/2060939",
        "name": "Black Bolt Elite Trainer Box"
    },
    {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-mega-evolution--phantasmal-flames-elite-trainer-box/2094847",
        "name": "Phantasmal Flames Elite Trainer Box"
    },
     {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-scarlet-violet-105-black-bolt-booster-bundle/2060949",
        "name": "Black Bolt Booster Bundle"
    },
     {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-illustrationcollectionseries1/2121163",
        "name": "Illustration Collection Series 1"
    },
     {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-mega-evolution--ascended-heroes-25-mini-tin/2111315",
        "name": "Ascended Heroes 2.5 Mini Tin"
    },
     {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/ascendedheroespostercollection-kaissa-me25/2121162",
        "name": "Ascended Heroes Poster Collection"
    },
     {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-scarlet-violet-105-black-bolt-white-flare-unova-victini-illustratation-collection/2060946",
        "name": "Black Bolt & White Flare Unova Victini Illustratation"
    },
     {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-mega-evolution--ascended-heroes-25-booster-bundle/2132001",
        "name": "Ascended Heroes Booster Bundle"
    },
     {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-mega-evolution--ascended-heroes-25-mega-meganium-exmega-emboar-exmega-feraligatr-ex--tuxaia-epilogi/2132002",
        "name": "Ascended Heroes 2.5 Mega Meganium ex/Mega Emboar ex/Mega Feraligatr ex"
    },
     {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-mega-evolution--phantasmal-flames-booster-1-fakelaki--tuxaia-epilogi-sxediou/2094845",
        "name": "Phantasmal Flames Booster"
    },
     {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-scarlet-violet-105-white-flare-booster-bundle/2060948",
        "name": "White Flare Booster Bundle"
    },
     {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcg-scarlet-violet-105-white-flare-elite-trainer-box/2060940",
        "name": "White Flare Elite Trainer Box"
    },
     {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokmon-tcgascendedheroesdeluxepincollection-me25/2121164",
        "name": "Ascended Heroes Deluxe Pin Collection"
    },
]

reload_monitor_config()

ADD_TO_CART_SELECTORS = [
    '[data-testid="btn-add-to-cart"]',
    '[data-testid*="add-to-cart"]',
    'button:has-text("Add to cart")',
    'button:has-text("Προσθήκη στο καλάθι")',
    'button:has-text("Στο καλάθι")',
    'button:has-text("Αγορά")',
    'button:has-text("Buy")',
    'button:has-text("Cart")',
    'button[class*="cart" i]',
    'button[class*="basket" i]',
    'button[aria-label*="καλάθι" i]',
    'button[aria-label*="cart" i]',
    '[role="button"]:has-text("Προσθήκη στο καλάθι")',
    '[role="button"]:has-text("Στο καλάθι")',
    '[role="button"]:has-text("Add to cart")',
]

OUT_OF_STOCK_SELECTORS = [
    'text=/Δεν είναι διαθέσιμο/i',
    'text=/Μη διαθέσιμο/i',
    'text=/Εξαντλήθηκε/i',
    'text=/Προσωρινά μη διαθέσιμο/i',
    'text=/Sold out/i',
    'text=/Out of stock/i',
    'text=/Unavailable/i',
]

PRODUCT_READY_SELECTORS = ADD_TO_CART_SELECTORS + OUT_OF_STOCK_SELECTORS + ["h1"]

def load_discord_webhook_url():
    try:
        with SECRETS_FILE.open("r", encoding="utf-8") as secrets_file:
            secrets = json.load(secrets_file)
    except FileNotFoundError:
        raise RuntimeError(f"Missing secrets file: {SECRETS_FILE}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON in secrets file: {e}")

    webhook_url = secrets.get("discord_webhook_url")
    if not webhook_url:
        raise RuntimeError('Missing "discord_webhook_url" in secrets.json')

    return webhook_url


DISCORD_WEBHOOK_URL = load_discord_webhook_url()
HTTP_SESSION = requests.Session()
HTTP_SESSION.headers.update({
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0",
})


def block_unneeded_resources(route):
    if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
        route.abort()
        return

    route.continue_()


def wait_for_any_selector(page, selectors, timeout_ms=SELECTOR_WAIT_TIMEOUT):
    deadline = time.monotonic() + timeout_ms / 1000

    while time.monotonic() < deadline:
        for selector in selectors:
            try:
                if page.locator(selector).first.count() > 0:
                    return True
            except Exception:
                continue
        page.wait_for_timeout(100)

    return False


def wait_for_network_idle_if_possible(page, timeout_ms=10000):
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass


def load_state():
    if not STATE_FILE.exists():
        return {"products": {}}

    try:
        with STATE_FILE.open("r", encoding="utf-8") as state_file:
            state = json.load(state_file)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Could not read state file. Starting with empty state: {e}")
        return {"products": {}}

    if "products" not in state or not isinstance(state["products"], dict):
        return {"products": {}}

    return state


def save_state(state):
    temp_file = STATE_FILE.with_suffix(".tmp")
    with temp_file.open("w", encoding="utf-8") as state_file:
        json.dump(state, state_file, indent=2, ensure_ascii=False)
    temp_file.replace(STATE_FILE)


def product_name_from_url(product_url):
    slug = product_url.rstrip("/").split("/")[-2]
    name = re.sub(r"[-_]+", " ", slug).strip()
    return name.title() if name else "Unknown Product"


def clean_product_name(raw_name, product_url):
    lines = [line.strip() for line in raw_name.splitlines() if line.strip()]
    for line in lines:
        if len(line) > 3 and not line.endswith("€"):
            return line
    return product_name_from_url(product_url)


def fingerprint_text(text):
    normalized_text = re.sub(r"\s+", " ", text or "").strip().lower()
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def normalize_product_url(href):
    if not href:
        return None

    product_url = urljoin(SEARCH_URL, href).split("?")[0].split("#")[0]
    if "/product/" not in product_url:
        return None
    return product_url.rstrip("/")


def watchlist_listing_hash(product_url):
    return fingerprint_text(f"watchlist:{product_url}")


def normalize_watchlist_product(product):
    product_url = normalize_product_url(product.get("url"))
    if not product_url:
        return None

    product_name = product.get("name") or product_name_from_url(product_url)
    return {
        "name": product_name,
        "url": product_url,
        "listing_text": "Direct watchlist product",
        "listing_hash": watchlist_listing_hash(product_url),
        "watchlist": True,
    }


def state_products_for_fast_cycle(state):
    products = []
    for product_url, saved_product in state.get("products", {}).items():
        if saved_product.get("watchlist"):
            continue

        normalized_url = normalize_product_url(saved_product.get("url") or product_url)
        if not normalized_url:
            continue

        products.append({
            "name": saved_product.get("name") or product_name_from_url(normalized_url),
            "url": normalized_url,
            "listing_text": saved_product.get("listing_text") or "Previously discovered listing product",
            "listing_hash": saved_product.get("listing_hash") or fingerprint_text(normalized_url),
            "watchlist": False,
        })

    return products


def merge_products(*product_groups):
    products_by_url = {}

    for product_group in product_groups:
        for product in product_group:
            if not product:
                continue

            existing = products_by_url.get(product["url"])
            if existing:
                products_by_url[product["url"]] = {
                    **existing,
                    **product,
                    "watchlist": existing.get("watchlist", False) or product.get("watchlist", False),
                }
            else:
                products_by_url[product["url"]] = product

    return list(products_by_url.values())


def watchlist_products():
    return [
        product
        for product in (normalize_watchlist_product(product) for product in WATCHLIST_PRODUCTS)
        if product
    ]


class MonitorScheduler:
    def __init__(self, state):
        self.state = state

    def listing_backoff_until(self):
        return self.state.get("listing_backoff_until", 0)

    def listing_backoff_remaining(self, now):
        return max(0, self.listing_backoff_until() - now)

    def due_listing_scan(self, now):
        if now < self.listing_backoff_until():
            return None

        last_deep_scan = self.state.get("last_deep_listing_scan", 0)
        if now - last_deep_scan >= DEEP_LISTING_SCAN_INTERVAL:
            return {
                "name": "deep",
                "max_pages": MAX_LISTING_PAGES,
                "last_scan_key": "last_deep_listing_scan",
            }

        last_shallow_scan = self.state.get("last_shallow_listing_scan", 0)
        if now - last_shallow_scan >= SHALLOW_LISTING_SCAN_INTERVAL:
            return {
                "name": "shallow",
                "max_pages": SHALLOW_LISTING_PAGES,
                "last_scan_key": "last_shallow_listing_scan",
            }

        return None

    def seconds_until_next_listing_scan(self, now):
        if now < self.listing_backoff_until():
            return self.listing_backoff_remaining(now)

        next_shallow_scan = self.state.get("last_shallow_listing_scan", 0) + SHALLOW_LISTING_SCAN_INTERVAL
        next_deep_scan = self.state.get("last_deep_listing_scan", 0) + DEEP_LISTING_SCAN_INTERVAL
        return max(0, min(next_shallow_scan, next_deep_scan) - now)

    def record_listing_success(self, scan, now):
        self.state[scan["last_scan_key"]] = now
        self.state["last_listing_scan"] = now
        self.state["listing_failures"] = 0
        self.state.pop("listing_backoff_until", None)

        if scan["name"] == "deep":
            self.state["last_shallow_listing_scan"] = now

    def record_listing_failure(self, now):
        failures = self.state.get("listing_failures", 0) + 1
        self.state["listing_failures"] = failures
        backoff_seconds = min(LISTING_BACKOFF_INITIAL * (2 ** (failures - 1)), LISTING_BACKOFF_MAX)
        jitter = random.uniform(0, min(60, backoff_seconds * 0.2))
        self.state["listing_backoff_until"] = int(now + backoff_seconds + jitter)
        return backoff_seconds


def format_found_time(timestamp):
    return datetime.fromtimestamp(timestamp, LOCAL_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")


def send_discord_notification(title, product_name, product_url, available=None, details=None, found_at=None, source=None):
    details = details or {}
    display_name = details.get("title") or product_name
    found_time = format_found_time(found_at or time.time())
    fields = [
        {"name": "Status", "value": "In stock" if available else "Availability changed", "inline": True},
        {"name": "Found at", "value": found_time, "inline": True},
    ]

    if details.get("price"):
        fields.append({"name": "Price", "value": details["price"], "inline": True})

    if source:
        fields.append({"name": "Source", "value": source, "inline": True})

    if details.get("available_stores"):
        store_names = "\n".join(details["available_stores"][:10])
        fields.append({"name": "Available Athens stores", "value": store_names, "inline": False})

    embed = {
        "title": title,
        "description": f"**{display_name}**",
        "url": product_url,
        "color": DISCORD_ALERT_COLOR,
        "fields": fields,
        "footer": {"text": "Public.gr Pokemon TCG monitor"},
        "timestamp": datetime.fromtimestamp(found_at or time.time(), LOCAL_TIMEZONE).isoformat(),
    }

    if details.get("image_url"):
        embed["thumbnail"] = {"url": details["image_url"]}

    payload = {
        "content": "Pokemon TCG stock alert",
        "username": "Stock Monitor Bot",
        "embeds": [embed],
    }

    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=DISCORD_TIMEOUT)
        response.raise_for_status()
    except Exception as e:
        print(f"Failed to send Discord notification: {e}")


def accept_cookies_if_present(page):
    cookie_selectors = [
        'button:has-text("Accept")',
        'button:has-text("Accept all")',
        'button:has-text("Αποδοχή")',
        'button:has-text("Αποδοχή όλων")',
        '[data-testid="accept-all"]',
        '[id*="accept"]',
    ]

    for selector in cookie_selectors:
        try:
            button = page.locator(selector).first
            if button.count() > 0 and button.is_visible():
                button.click(timeout=3000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            continue


def collect_products_from_current_page(page):
    raw_products = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href*="/product/"]')).map((anchor) => {
            let card = anchor.closest('article, li, [data-testid*="product"], [class*="product-card"], [class*="ProductCard"]');

            if (!card) {
                card = anchor;
                for (let i = 0; i < 4 && card.parentElement; i += 1) {
                    card = card.parentElement;
                    const cardText = (card.innerText || "").trim();
                    if (cardText.length > 40 && cardText.length < 1200) {
                        break;
                    }
                }
            }

            return {
                href: anchor.href,
                text: (anchor.innerText || anchor.getAttribute("title") || anchor.getAttribute("aria-label") || "").trim(),
                cardText: ((card && card.innerText) || anchor.innerText || "").trim()
            };
        })"""
    )

    products_by_url = {}
    for raw_product in raw_products:
        product_url = normalize_product_url(raw_product.get("href"))
        if not product_url:
            continue

        if product_url not in products_by_url:
            card_text = re.sub(r"\s+", " ", raw_product.get("cardText", "")).strip()
            products_by_url[product_url] = {
                "name": clean_product_name(raw_product.get("text", ""), product_url),
                "url": product_url,
                "listing_text": card_text,
                "listing_hash": fingerprint_text(card_text),
            }

    return list(products_by_url.values())


def product_count_on_current_page(page):
    return len(collect_products_from_current_page(page))


def click_first_visible(page, selectors):
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible() and locator.is_enabled():
                locator.click(timeout=5000)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(LISTING_ACTION_DELAY * 1000)
                return True
        except Exception:
            continue
    return False


def expand_current_listing_page(page):
    load_more_selectors = [
        'button:has-text("Load more")',
        'button:has-text("Show more")',
        'button:has-text("Περισσότερα")',
        'button:has-text("Εμφάνιση περισσότερων")',
        'a:has-text("Περισσότερα")',
        '[data-testid*="load-more"]',
        '[class*="load-more"]',
    ]

    previous_count = -1
    stable_rounds = 0

    for _ in range(MAX_EXPAND_CLICKS):
        current_count = product_count_on_current_page(page)
        if current_count == previous_count:
            stable_rounds += 1
        else:
            stable_rounds = 0

        previous_count = current_count
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(LISTING_ACTION_DELAY * 1000)

        clicked = click_first_visible(page, load_more_selectors)
        new_count = product_count_on_current_page(page)

        if new_count > previous_count:
            continue

        if not clicked and stable_rounds >= 2:
            break


def go_to_next_listing_page(page):
    next_selectors = [
        'a[rel="next"]',
        'a[aria-label*="next" i]',
        'button[aria-label*="next" i]',
        'a[aria-label*="επόμε" i]',
        'button[aria-label*="επόμε" i]',
        'a:has-text("Next")',
        'button:has-text("Next")',
        'a:has-text("Δες περισσότερα")',
        'button:has-text("Δες περισσότερα")',
        '[data-testid*="pagination-next"]',
    ]

    old_url = page.url
    old_products = {product["url"] for product in collect_products_from_current_page(page)}
    if not click_first_visible(page, next_selectors):
        return False

    try:
        page.wait_for_timeout(LISTING_ACTION_DELAY * 1000)
    except PlaywrightTimeoutError:
        pass

    new_products = {product["url"] for product in collect_products_from_current_page(page)}
    return page.url != old_url or new_products != old_products


def discover_products(page, max_pages=MAX_LISTING_PAGES):
    products_by_url = {}
    visited_listing_pages = set()

    print(f"Opening product listing: {SEARCH_URL}")
    page.goto(SEARCH_URL, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
    wait_for_any_selector(page, [PRODUCT_LINK_SELECTOR], SELECTOR_WAIT_TIMEOUT)
    accept_cookies_if_present(page)

    for page_number in range(1, max_pages + 1):
        current_url = page.url
        if current_url in visited_listing_pages:
            break

        visited_listing_pages.add(current_url)
        print(f"Scanning listing page {page_number}: {current_url}")
        expand_current_listing_page(page)

        products = collect_products_from_current_page(page)
        for product in products:
            products_by_url[product["url"]] = product

        print(f"Found {len(products_by_url)} unique products so far.")

        if not go_to_next_listing_page(page):
            break

    return list(products_by_url.values())


def normalize_page_asset_url(asset_url, product_url):
    if not asset_url:
        return None
    return urljoin(product_url, asset_url)


def fetch_public_json(url, params=None, timeout=API_TIMEOUT):
    response = HTTP_SESSION.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def format_api_price(price):
    if price is None:
        return None

    try:
        return f"{float(price):.2f}".replace(".", ",") + "€"
    except (TypeError, ValueError):
        return str(price)


def api_product_image_url(sku):
    hero_image = (sku.get("media") or {}).get("heroImage") or {}
    return hero_image.get("thumbnail") or hero_image.get("url1") or hero_image.get("large")


def api_product_price(sku, stock_payload):
    price_info = sku.get("priceInfoDto") or {}
    price = price_info.get("salePrice") or price_info.get("listPrice")
    if price is not None:
        return format_api_price(price)

    prices = stock_payload.get("prices") or []
    if prices:
        price = prices[0].get("salePrice") or prices[0].get("listPrice")
        return format_api_price(price)

    return None


def availability_text_is_out_of_stock(availability_text):
    normalized_text = (availability_text or "").strip().lower()
    return any(token in normalized_text for token in [
        "δεν είναι διαθέσιμο",
        "μη διαθέσιμο",
        "εξαντλήθηκε",
        "προσωρινά μη διαθέσιμο",
        "sold out",
        "out of stock",
        "unavailable",
    ])


def api_product_is_store_only(delivery_rule, sku):
    availability_text = (
        delivery_rule.get("displayText")
        or delivery_rule.get("pdpDisplayText")
        or delivery_rule.get("deliveryPromiseText")
        or sku.get("availability")
        or ""
    )
    return STORE_ONLY_TEXT in availability_text or delivery_rule.get("uniqueStoreAssortment") is True


def check_product_api(product_url, product_name="Unknown Product"):
    sku_id = sku_id_from_product_url(product_url)
    if not sku_id:
        return None

    try:
        sku_payload = fetch_public_json(
            PRODUCT_DETAILS_URL_TEMPLATE.format(sku_id=sku_id),
            params={"locale": "el"},
        )
        stock_payload = fetch_public_json(
            PRODUCT_STOCK_URL,
            params={"sku": sku_id, "locale": "el"},
        )
    except Exception as e:
        print(f"API check failed for {product_name}: {e}")
        return None

    sku = sku_payload.get("sku") or {}
    stock_rule = stock_payload.get("stockRule") or {}
    delivery_rule = stock_rule.get("deliveryRule") or {}

    details = {
        "title": sku.get("displayName") or product_name,
        "image_url": api_product_image_url(sku),
        "price": api_product_price(sku, stock_payload),
    }

    if api_product_is_store_only(delivery_rule, sku):
        available_stores = find_available_athens_stores(product_url)
        available = len(available_stores) > 0
        print(f"Availability for {product_name}: {available}")
        if available_stores:
            print(f"Available Athens stores: {', '.join(available_stores)}")
        details["available"] = available
        details["available_stores"] = available_stores
        return details

    availability_text = (
        delivery_rule.get("displayText")
        or delivery_rule.get("pdpDisplayText")
        or delivery_rule.get("deliveryPromiseText")
        or sku.get("availability")
        or ""
    )
    available = (
        delivery_rule.get("allowPurchases") is True
        and delivery_rule.get("inStock") is not False
        and not availability_text_is_out_of_stock(availability_text)
    )

    print(f"Availability for {product_name}: {available}")
    details["available"] = available
    return details


def extract_product_details(page, product_url, fallback_name):
    try:
        details = page.evaluate(
            """() => {
                const firstContent = (selectors) => {
                    for (const selector of selectors) {
                        const element = document.querySelector(selector);
                        const value = element && (element.content || element.src || element.textContent || "");
                        if (value && value.trim()) {
                            return value.trim();
                        }
                    }
                    return null;
                };

                const title = firstContent([
                    "h1",
                    'meta[property="og:title"]',
                    'meta[name="twitter:title"]',
                    "title"
                ]);

                const imageUrl = firstContent([
                    'meta[property="og:image"]',
                    'meta[name="twitter:image"]',
                    'img[alt*="Pokemon" i]',
                    'img[alt*="Pokémon" i]',
                    'img[src*="/product"]',
                    "main img"
                ]);

                const priceMeta = firstContent([
                    'meta[property="product:price:amount"]',
                    'meta[itemprop="price"]'
                ]);
                const currency = firstContent([
                    'meta[property="product:price:currency"]',
                    'meta[itemprop="priceCurrency"]'
                ]);

                let price = priceMeta ? `${priceMeta}${currency ? ` ${currency}` : ""}` : null;
                if (!price) {
                    const priceElements = Array.from(document.querySelectorAll(
                        '[data-testid*="price"], [class*="price"], [class*="Price"]'
                    ));
                    const priceElement = priceElements.find((element) => /\\d+[,.]?\\d*\\s*€/.test(element.textContent || ""));
                    price = priceElement ? priceElement.textContent.replace(/\\s+/g, " ").trim() : null;
                }

                return { title, imageUrl, price };
            }"""
        )
    except Exception as e:
        print(f"Could not extract product details for {fallback_name}: {e}")
        details = {}

    return {
        "title": details.get("title") or fallback_name,
        "image_url": normalize_page_asset_url(details.get("imageUrl"), product_url),
        "price": details.get("price"),
    }


def locator_exists_visible(page, selector):
    try:
        locator = page.locator(selector).first
        return locator.count() > 0 and locator.is_visible()
    except Exception:
        return False


def page_has_out_of_stock_text(page):
    for selector in OUT_OF_STOCK_SELECTORS:
        if locator_exists_visible(page, selector):
            return True
    return False


def page_has_store_only_purchase_text(page):
    try:
        return page.locator(f"text={STORE_ONLY_TEXT}").first.count() > 0
    except Exception:
        return False


def sku_id_from_product_url(product_url):
    match = re.search(r"/(\d+)(?:[/?#]|$)", product_url)
    return match.group(1) if match else None


def store_is_available(store):
    if store.get("enabledStore") is False or store.get("acs"):
        return False

    if store.get("inStock") is True:
        return True

    availability_text = (
        store.get("stockAccuracyAvailability")
        or store.get("storeInventoryInfoDto", {}).get("displayText")
        or ""
    ).strip().lower()

    if "μη διαθέσιμο" in availability_text:
        return False

    return any(token in availability_text for token in [
        "διαθέσιμο στο κατάστημα",
        "περιορισμένη διαθεσιμότητα",
    ])


def find_available_athens_stores(product_url):
    sku_id = sku_id_from_product_url(product_url)
    if not sku_id:
        return []

    try:
        response = HTTP_SESSION.get(
            STORE_AVAILABILITY_URL,
            params={
                "acs": "false",
                "isCheckout": "false",
                "area": TARGET_STORE_AREA,
                "skuId": sku_id,
            },
            timeout=STORE_AVAILABILITY_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as e:
        print(f"Could not check Athens store availability for {product_url}: {e}")
        return []

    stores = payload.get("storesDto", {}).get("stores", [])
    return [
        store.get("name") or store.get("storeSlug") or store.get("externalLocationId")
        for store in stores
        if store.get("area") == TARGET_STORE_AREA and store_is_available(store)
    ]


def find_add_to_cart_button(page):
    for selector in ADD_TO_CART_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible():
                return locator
        except Exception:
            continue

    # Fallback for Public pages where the buy control is rendered without stable data-testid text.
    try:
        candidates = page.locator(
            'button, [role="button"], a[class*="button" i], div[class*="button" i]'
        )
        for index in range(min(candidates.count(), 80)):
            candidate = candidates.nth(index)
            try:
                if not candidate.is_visible():
                    continue
                text = re.sub(r"\s+", " ", candidate.inner_text(timeout=1000) or "").strip().lower()
                aria = (candidate.get_attribute("aria-label") or "").lower()
                classes = (candidate.get_attribute("class") or "").lower()
                combined = f"{text} {aria} {classes}"
                if any(token in combined for token in [
                    "καλάθι", "cart", "basket", "addtocart", "add-to-cart", "buy-button"
                ]):
                    return candidate
            except Exception:
                continue
    except Exception:
        pass

    return None


def check_product(page, product_url, product_name="Unknown Product"):
    try:
        page.goto(product_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        accept_cookies_if_present(page)
        wait_for_any_selector(page, PRODUCT_READY_SELECTORS, SELECTOR_WAIT_TIMEOUT)
        wait_for_network_idle_if_possible(page)
        page.wait_for_timeout(1500)

        details = extract_product_details(page, product_url, product_name)

        if page_has_store_only_purchase_text(page):
            available_stores = find_available_athens_stores(product_url)
            available = len(available_stores) > 0
            print(f"Availability for {product_name}: {available}")
            if available_stores:
                print(f"Available Athens stores: {', '.join(available_stores)}")
            details["available"] = available
            details["available_stores"] = available_stores
            return details

        button = find_add_to_cart_button(page)
        if button is not None:
            available = button.is_enabled() and not page_has_out_of_stock_text(page)
            print(f"Availability for {product_name}: {available}")
            details["available"] = available
            return details

        # Some Public products do not render a cart button at all when they are unavailable.
        # Treat that exactly like the other out-of-stock listings instead of printing a special error.
        available = False
        print(f"Availability for {product_name}: {available}")
        details["available"] = available
        return details

    except Exception as e:
        print(f"Error checking {product_name} ({product_url}): {e}")
        return {
            "title": product_name,
            "image_url": None,
            "price": None,
            "available": False,
        }


def should_verify_product(product, previous, first_run, scan_started_at):
    if previous is None:
        return True

    if product.get("watchlist"):
        last_verified = previous.get("last_verified", 0)
        return scan_started_at - last_verified >= WATCHLIST_CHECK_INTERVAL

    if previous.get("listing_hash") != product.get("listing_hash"):
        return True

    last_verified = previous.get("last_verified", 0)
    if scan_started_at - last_verified >= FULL_VERIFY_INTERVAL:
        return True

    return first_run and previous.get("available") is None


def handle_product_change(product, previous, details, first_run, found_at):
    product_name = product["name"]
    product_url = product["url"]
    available = details.get("available", False)
    source = "Direct watchlist" if product.get("watchlist") else "Search listing"

    if previous is None:
        print(f"New product detected: {product_name}")
        if available and (product.get("watchlist") or FIRST_RUN_NOTIFY or not first_run):
            send_discord_notification(
                "New Pokemon TCG product detected",
                product_name,
                product_url,
                available,
                details,
                found_at,
                source,
            )
        elif not available:
            print(f"{product_name} is out of stock. Skipping Discord notification.")
        return

    if previous.get("available") != available:
        print(f"Availability changed for {product_name}: {previous.get('available')} -> {available}")
        if available:
            send_discord_notification(
                "Pokemon TCG availability changed",
                product_name,
                product_url,
                available,
                details,
                found_at,
                source,
            )
        else:
            print(f"{product_name} changed to out of stock. Skipping Discord notification.")
        return

    if previous.get("listing_hash") != product.get("listing_hash"):
        print(f"Listing changed for {product_name}, but availability is unchanged.")


def monitor_products():
    state = load_state()
    scheduler = MonitorScheduler(state)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.route("**/*", block_unneeded_resources)
        listing_page = context.new_page()

        while True:
            reload_monitor_config()
            scan_started_at = int(time.time())
            first_run = len(state["products"]) == 0
            previous_products = state["products"].copy()

            try:
                listing_products = []
                listing_scan = scheduler.due_listing_scan(scan_started_at)
                if listing_scan:
                    try:
                        print(
                            f"Running {listing_scan['name']} listing scan "
                            f"({listing_scan['max_pages']} page limit)."
                        )
                        listing_products = discover_products(
                            listing_page,
                            max_pages=listing_scan["max_pages"],
                        )
                        scheduler.record_listing_success(listing_scan, scan_started_at)
                    except Exception as e:
                        backoff_seconds = scheduler.record_listing_failure(scan_started_at)
                        print(
                            f"Listing scan failed: {e}. "
                            f"Backing off listing scans for about {int(backoff_seconds)} seconds."
                        )
                        try:
                            listing_page.close()
                        except Exception:
                            pass
                        listing_page = context.new_page()
                else:
                    wait_for_listing = scheduler.seconds_until_next_listing_scan(scan_started_at)
                    print(f"Skipping listing scan. Next listing scan in {int(wait_for_listing)} seconds.")

                products = merge_products(
                    watchlist_products(),
                    state_products_for_fast_cycle(state),
                    listing_products,
                )
                products_to_verify = []

                for product in products:
                    previous = previous_products.get(product["url"])
                    state["products"][product["url"]] = {
                        **(previous or {}),
                        "name": product["name"],
                        "url": product["url"],
                        "listing_text": product["listing_text"],
                        "listing_hash": product["listing_hash"],
                        "watchlist": product.get("watchlist", False),
                        "last_seen": scan_started_at,
                    }

                    if should_verify_product(product, previous, first_run, scan_started_at):
                        products_to_verify.append(product)

                save_state(state)

                print(
                    f"Discovered {len(listing_products)} listing products this cycle and "
                    f"tracking {len(WATCHLIST_PRODUCTS)} watchlist products. "
                    f"Checking {len(products_to_verify)} due products."
                )

                for product in products_to_verify:
                    product_name = product["name"]
                    product_url = product["url"]
                    previous = previous_products.get(product_url)
                    print(f"\nVerifying: {product_name}")

                    details = check_product_api(product_url, product_name)
                    if details is None:
                        details = {
                            "title": product_name,
                            "image_url": None,
                            "price": None,
                            "available": False,
                            "available_stores": [],
                        }
                    available = details.get("available", False)
                    handle_product_change(product, previous, details, first_run, scan_started_at)

                    state["products"][product_url] = {
                        **(previous or {}),
                        "name": product_name,
                        "url": product_url,
                        "listing_text": product["listing_text"],
                        "listing_hash": product["listing_hash"],
                        "watchlist": product.get("watchlist", False),
                        "available": available,
                        "detail_title": details.get("title"),
                        "image_url": details.get("image_url"),
                        "price": details.get("price"),
                        "available_stores": details.get("available_stores", []),
                        "last_seen": scan_started_at,
                        "last_verified": scan_started_at,
                    }
                    save_state(state)
                    time.sleep(PRODUCT_CHECK_DELAY)

            except Exception as e:
                print(f"Monitor cycle failed: {e}")
                try:
                    listing_page.close()
                except Exception:
                    pass
                listing_page = context.new_page()

            wait_seconds = CHECK_INTERVAL + random.uniform(0, CHECK_INTERVAL_JITTER)
            print(f"\nWaiting {wait_seconds:.1f} seconds before next monitor cycle...")
            time.sleep(wait_seconds)


if __name__ == "__main__":
    monitor_products()
