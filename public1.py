import asyncio
import random
import time
import requests
from playwright.async_api import async_playwright

PRODUCTS = [
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
        "url": "https://www.public.gr/product/books/english/literature/classical-literature/animal-farm/0334039",
        "name": "Animal Farm"
    },
    {
        "url": "https://www.public.gr/product/kids-and-toys/trading-collectable-cards/pokemon-kartes-sv85-prismatic-evolutions-tech-sticker-collection/1996522",
        "name": "Prismatic Evolutions Tech Sticker Collection"
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
    }
    
    
    
]

CHECK_INTERVAL = 60  # seconds
NOTIFICATION_INTERVAL = 3600  # seconds (1 hour)
# Track last browser restart time
last_browser_restart = time.time()
BROWSER_RESTART_INTERVAL = 60  #in seconds

# Discord settings
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1514971520185667594/NfViZZ458kx8yI7xN_JunaufXV1CdACp6M5r_9Ly6D5OlQSzoyi1MNPrhKWrZLi8fYMd"

# List of common User-Agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/91.0.864.59 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 10; SM-A505FN) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
]

# Track last notification time for each product
last_notification = {}

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def send_discord_notification(product_name: str, product_url: str):
    message = f"🚀 **STOCK ALERT!** 🚀\n\n{product_name} is now available!\n\n{product_url}"
    payload = {
        "content": message,
        "username": "Stock Monitor Bot"
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"Failed to send Discord notification: {e}")

def send_discord_file(file_path: str, filename: str, product_name: str):
    files = {"file": (filename, open(file_path, "rb"))}
    payload = {
        "content": f"📸 Screenshot for {product_name}",
        "username": "Stock Monitor Bot"
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, files=files, data=payload)
    except Exception as e:
        print(f"Failed to send Discord file: {e}")

async def check_stock(page, product_url: str, product_name: str = "Unknown Product") -> bool:
    try:
        user_agent = get_random_user_agent()
        await page.set_extra_http_headers({"User-Agent": user_agent})
        await page.goto(product_url, wait_until="networkidle")
        button = page.locator('[data-testid="btn-add-to-cart"]')

        if await button.count() == 0:
            print(f"Button not found for {product_name} ({product_url})")
            return False

        enabled = await button.is_enabled()
        print(f"Button enabled for {product_name}: {enabled}")
        return enabled

    except Exception as e:
        print(f"Error checking {product_name} ({product_url}): {e}")
        return False

async def monitor_products():
    global last_browser_restart

    while True:
        # Check if it's time to restart the browser
        current_time = time.time()
        if current_time - last_browser_restart >= BROWSER_RESTART_INTERVAL:
            print("\n--- Restarting browser to prevent memory leaks ---")
            last_browser_restart = current_time

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()  # Single page for sequential checks

            print(f"Starting sequential monitoring for {len(PRODUCTS)} products every {CHECK_INTERVAL} seconds")

            while True:
                # Check if it's time to restart the browser again
                if time.time() - last_browser_restart >= BROWSER_RESTART_INTERVAL:
                    break

                for product in PRODUCTS:
                    product_name = product.get("name", "Unknown Product")
                    product_url = product["url"]
                    print(f"\nChecking: {product_name}")

                    in_stock = await check_stock(page, product_url, product_name)

                    if in_stock:
                        current_time = time.time()
                        if product_name not in last_notification or (current_time - last_notification[product_name] >= NOTIFICATION_INTERVAL):
                            print(f"STOCK DETECTED: {product_name}")
                            screenshot_path = f"stock_detected_{product_name.replace(' ', '_')}.png"
                            await page.screenshot(
                                path=screenshot_path,
                                full_page=True,
                            )
                            send_discord_notification(product_name, product_url)
                            send_discord_file(screenshot_path, f"stock_{product_name.replace(' ', '_')}.png", product_name)
                            last_notification[product_name] = current_time
                        else:
                            print(f"Notification for {product_name} was already sent recently. Skipping.")

                print(f"\nWaiting {CHECK_INTERVAL} seconds before next check...")
                await asyncio.sleep(CHECK_INTERVAL)

            # Close the browser before restarting
            await browser.close()

if __name__ == "__main__":
    asyncio.run(monitor_products())
