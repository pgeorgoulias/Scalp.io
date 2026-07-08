#!/usr/bin/env python3
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PROJECT_DIR = Path(__file__).resolve().parent
GUI_DIR = PROJECT_DIR / "gui"
CONFIG_FILE = PROJECT_DIR / "public_monitor_config.json"
STATE_FILE = PROJECT_DIR / "public_product_state.json"
MONITOR_FILE = PROJECT_DIR / "public1.py"

LOG_LINES = deque(maxlen=800)
LOG_LOCK = threading.Lock()
PROCESS_LOCK = threading.Lock()
MONITOR_PROCESS = None
MONITOR_STARTED_AT = None


def now_label():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def append_log(line):
    clean_line = line.rstrip("\n")
    with LOG_LOCK:
        LOG_LINES.append(f"[{now_label()}] {clean_line}")


def read_json_file(path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Could not read {path.name}: {exc}", **fallback}


def write_json_file(path, data):
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp_path.replace(path)


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("Config must be a JSON object.")
    settings = config.get("settings")
    products = config.get("watchlist_products")
    if not isinstance(settings, dict):
        raise ValueError("settings must be an object.")
    if not isinstance(products, list):
        raise ValueError("watchlist_products must be a list.")

    numeric_keys = {
        "check_interval", "check_interval_jitter", "product_check_delay",
        "watchlist_check_interval", "shallow_listing_scan_interval",
        "deep_listing_scan_interval", "listing_backoff_initial", "listing_backoff_max",
        "listing_action_delay", "full_verify_interval", "shallow_listing_pages",
        "max_listing_pages", "max_expand_clicks", "discord_timeout", "api_timeout",
        "store_availability_timeout", "page_load_timeout", "selector_wait_timeout",
    }
    for key in numeric_keys:
        if key in settings:
            value = settings[key]
            if not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"{key} must be a non-negative number.")

    if "first_run_notify" in settings and not isinstance(settings["first_run_notify"], bool):
        raise ValueError("first_run_notify must be true or false.")

    cleaned_products = []
    for index, product in enumerate(products, start=1):
        if not isinstance(product, dict):
            raise ValueError(f"Product #{index} must be an object.")
        url = str(product.get("url", "")).strip()
        name = str(product.get("name", "")).strip()
        if not url:
            raise ValueError(f"Product #{index} is missing a URL.")
        if "/product/" not in url:
            raise ValueError(f"Product #{index} does not look like a Public product URL.")
        if not name:
            name = url.rstrip("/").split("/")[-2].replace("-", " ").title()
        cleaned_products.append({"url": url, "name": name})

    config["watchlist_products"] = cleaned_products
    return config


def monitor_status_unlocked():
    running = MONITOR_PROCESS is not None and MONITOR_PROCESS.poll() is None
    return {
        "running": running,
        "pid": MONITOR_PROCESS.pid if running else None,
        "started_at": MONITOR_STARTED_AT if running else None,
    }


def monitor_status():
    with PROCESS_LOCK:
        return monitor_status_unlocked()


def pump_output(process):
    try:
        for raw_line in iter(process.stdout.readline, ""):
            if not raw_line:
                break
            append_log(raw_line)
    except Exception as exc:
        append_log(f"Log reader stopped: {exc}")
    finally:
        code = process.poll()
        append_log(f"Monitor process exited with code {code}.")


def start_monitor():
    global MONITOR_PROCESS, MONITOR_STARTED_AT
    with PROCESS_LOCK:
        if MONITOR_PROCESS is not None and MONITOR_PROCESS.poll() is None:
            return monitor_status_unlocked()

        append_log("Starting Public monitor...")
        MONITOR_PROCESS = subprocess.Popen(
            [sys.executable, "-u", str(MONITOR_FILE)],
            cwd=str(PROJECT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        MONITOR_STARTED_AT = now_label()
        threading.Thread(target=pump_output, args=(MONITOR_PROCESS,), daemon=True).start()
        return monitor_status_unlocked()


def stop_monitor():
    global MONITOR_PROCESS, MONITOR_STARTED_AT
    with PROCESS_LOCK:
        process = MONITOR_PROCESS
        if process is None or process.poll() is not None:
            MONITOR_PROCESS = None
            MONITOR_STARTED_AT = None
            return monitor_status()

        append_log("Stopping Public monitor...")
        process.terminate()

    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        append_log("Monitor did not stop in time; killing process.")
        process.kill()
        process.wait(timeout=5)

    with PROCESS_LOCK:
        MONITOR_PROCESS = None
        MONITOR_STARTED_AT = None
    return monitor_status()


class GuiHandler(SimpleHTTPRequestHandler):
    server_version = "PublicMonitorHUD/1.0"

    def log_message(self, format, *args):
        return

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return None
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/config":
            self.send_json(read_json_file(CONFIG_FILE, {"settings": {}, "watchlist_products": []}))
            return
        if path == "/api/state":
            self.send_json(read_json_file(STATE_FILE, {"products": {}}))
            return
        if path == "/api/status":
            self.send_json(monitor_status())
            return
        if path == "/api/logs":
            with LOG_LOCK:
                lines = list(LOG_LINES)
            self.send_json({"lines": lines})
            return
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/config":
                config = validate_config(self.read_body_json())
                write_json_file(CONFIG_FILE, config)
                append_log("Saved GUI configuration. public1.py will reload it on the next monitor cycle.")
                self.send_json(config)
                return
            if parsed.path == "/api/start":
                self.send_json(start_monitor())
                return
            if parsed.path == "/api/stop":
                self.send_json(stop_monitor())
                return
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)



def hud_healthcheck(url, timeout=2):
    try:
        with urllib.request.urlopen(f"{url}/api/status", timeout=timeout) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def open_hud_url(url, open_browser):
    print(f"Public Monitor HUD: {url}")
    if open_browser:
        webbrowser.open(url)


def bind_server(host, port, open_browser):
    url = f"http://{host}:{port}"
    if hud_healthcheck(url):
        print(f"HUD is already running at {url}")
        open_hud_url(url, open_browser)
        return None, url

    try:
        return ThreadingHTTPServer((host, port), GuiHandler), url
    except OSError as exc:
        if exc.errno != 48:
            raise

        for candidate_port in range(port + 1, port + 20):
            candidate_url = f"http://{host}:{candidate_port}"
            if hud_healthcheck(candidate_url):
                print(f"HUD is already running at {candidate_url}")
                open_hud_url(candidate_url, open_browser)
                return None, candidate_url
            try:
                print(f"Port {port} is busy; using {candidate_port} instead.")
                return ThreadingHTTPServer((host, candidate_port), GuiHandler), candidate_url
            except OSError:
                continue

        raise OSError(f"Could not find a free HUD port near {port}.")

def run_server(host, port, open_browser):
    os.chdir(GUI_DIR)
    server, url = bind_server(host, port, open_browser)
    if server is None:
        return

    append_log(f"HUD server listening at {url}")
    open_hud_url(url, open_browser)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_monitor()
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Public monitor HUD control panel")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically")
    args = parser.parse_args()
    run_server(args.host, args.port, not args.no_open)


if __name__ == "__main__":
    main()
