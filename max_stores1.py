import asyncio
import random
import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

PRODUCTS = [
    {
        "url": "https://www.maxstores.gr/paichnidia/epitrapezia/me-kartes/kaissa-2-pokemon-tcg-me2.5-ascended-heroes-elite-trainer-box-pok103151_1335145/",
        "name": "Pokémon TCG ME2.5 Ascended Heroes Elite Trainer Box"
    },
    {
        "url": "https://www.maxstores.gr/paichnidia/epitrapezia/oikogeneiaka/giochi-preziosi-games-epitrapezio-fanzone-fae02000_1348772/",
        "name": "Poulos1"
    }
]

CHECK_INTERVAL = 60  # seconds
MAX_RETRIES = 3
TIMEOUT_MS = 60000  # 60 seconds

# Discord settings
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1514971520185667594/NfViZZ458kx8yI7xN_JunaufXV1CdACp6M5r_9Ly6D5OlQSzoyi1MNPrhKWrZLi8fYMd"

# List of common User-Agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 10; SM-A505FN) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def send_discord_notification(product_name: str, product_url: str):
    message = f"🚀 **STOCK ALERT!** 🚀\n\n{product_name} is now available!\n\n{product_url}"
    payload = {
        "content": message,
        "username": "MaxStores Stock Monitor"
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"Failed to send Discord notification: {e}")

def send_discord_file(file_path: str, filename: str, product_name: str):
    files = {"file": (filename, open(file_path, "rb"))}
    payload = {
        "content": f"📸 Screenshot for {product_name}",
        "username": "MaxStores Stock Monitor"
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, files=files, data=payload)
    except Exception as e:
        print(f"Failed to send Discord file: {e}")

async def check_stock(page, product_url: str, retries: int = MAX_RETRIES) -> bool:
    for attempt in range(retries):
        try:
            user_agent = get_random_user_agent()
            await page.set_extra_http_headers({"User-Agent": user_agent})
            await page.goto(product_url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

            # Locate the button inside the parent div
            button_wrapper = page.locator('.button-wrapper.cart-button a')
            if await button_wrapper.count() == 0:
                print(f"Button not found for {product_url}")
                return False

            # Check if the button is enabled (no 'disabled' class)
            classes = await button_wrapper.get_attribute("class")
            if "disabled" not in classes:
                print(f"Button is ENABLED for {product_url}")
                return True
            else:
                print(f"Button is still disabled for {product_url}")
                return False

        except PlaywrightTimeoutError:
            print(f"Timeout on attempt {attempt + 1} for {product_url}, retrying...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Error checking {product_url} (attempt {attempt + 1}): {e}")
            await asyncio.sleep(5)
    return False

async def monitor_products():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ]
        )
        page = await browser.new_page()

        print(f"Starting monitoring for {len(PRODUCTS)} products every {CHECK_INTERVAL} seconds")

        while True:
            for product in PRODUCTS:
                product_name = product.get("name", "Unknown Product")
                product_url = product["url"]

                print(f"\nChecking: {product_name}")
                try:
                    available = await check_stock(page, product_url)

                    if available:
                        print(f"STOCK DETECTED: {product_name}")
                        screenshot_path = f"stock_detected_{product_name.replace(' ', '_')}.png"
                        await page.screenshot(
                            path=screenshot_path,
                            full_page=True,
                        )
                        send_discord_notification(product_name, product_url)
                        send_discord_file(screenshot_path, f"stock_{product_name.replace(' ', '_')}.png", product_name)

                except Exception as e:
                    print(f"Unexpected error with {product_name}: {e}")

            print(f"\nWaiting {CHECK_INTERVAL} seconds before next check...")
            await asyncio.sleep(CHECK_INTERVAL)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(monitor_products())
