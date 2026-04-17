"""
Bookker Login + Desk Booking Automation
Logs in, clicks Desk, configures the booking form, and searches for sites.

2FA: Detects the Microsoft number-matching prompt, sends the number to you
     via Telegram (and/or email), then waits for you to tap it on your phone.
"""

import os
import time
import smtplib
import requests
import urllib3
from datetime import datetime, timedelta
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from dotenv import load_dotenv, dotenv_values

# Corporate proxies inject self-signed certs — suppress the noisy warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv(Path(__file__).parent / ".env")

# ── Credentials ────────────────────────────────────────────────────────────────
EMAIL    = os.environ["EMAIL"]
PASSWORD = os.environ["PASSWORD"]

# ── 2FA Notification config ────────────────────────────────────────────────────
# Set whichever channels you want to use in your .env file.
# At least one should be configured.

# Telegram — create a bot via @BotFather, get your chat_id via @userinfobot
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]   # e.g. "123456:ABCdef..."
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]     # e.g. "987654321"

# Email (Gmail example — use an App Password, not your real password)
EMAIL_SENDER   = os.environ["NOTIF_EMAIL_SENDER"]       # e.g. "you@gmail.com"
EMAIL_PASSWORD = os.environ["NOTIF_EMAIL_PASSWORD"]     # Gmail App Password
EMAIL_RECEIVER = os.environ["NOTIF_EMAIL_RECEIVER"]     # where to receive alert

# Slack — create an Incoming Webhook at api.slack.com/apps
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]     # e.g. "https://hooks.slack.com/..."

# ── Config ─────────────────────────────────────────────────────────────────────
URL         = "https://webapp.bookkercorp.com/#/login"
TIMEOUT     = 15
HEADLESS    = os.getenv("HEADLESS", "false").lower() == "true"
SCREENSHOTS = "screenshots"

BOOKING_DATE = (datetime.today() + timedelta(days=14)).strftime("%Y-%m-%d")


# ── Screenshot helper ──────────────────────────────────────────────────────────
def screenshot(driver: webdriver.Chrome, label: str) -> str:
    os.makedirs(SCREENSHOTS, exist_ok=True)
    screenshot.counter += 1
    path = os.path.join(SCREENSHOTS, f"{screenshot.counter:03d}_{label}.png")
    driver.save_screenshot(path)
    print(f"  [📷] {path}")
    return path

screenshot.counter = 0


# ── 2FA Notification helpers ───────────────────────────────────────────────────
def notify_telegram(number: str) -> bool:
    """Send auth number via Telegram bot. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": (
                f"🔐 *Microsoft Auth Required*\n\n"
                f"Tap *{number}* in Microsoft Authenticator\n\n"
                f"_(Script is waiting…)_"
            ),
            "parse_mode": "Markdown",
        }
        # verify=False bypasses corporate proxy self-signed certificate
        resp = requests.post(url, json=payload, timeout=10, verify=False)
        if resp.ok:
            print(f"  [✓] Telegram notified — tap {number} on your phone")
            return True
        else:
            print(f"  [!] Telegram error: {resp.text}")
    except Exception as e:
        print(f"  [!] Telegram exception: {e}")
    return False


# def notify_email(number: str) -> bool:
#     """Send auth number via email. Returns True on success."""
#     if not EMAIL_SENDER or not EMAIL_PASSWORD or not EMAIL_RECEIVER:
#         return False
#     try:
#         subject = "Microsoft Auth Required"
#         body    = f"Tap {number} in Microsoft Authenticator.\n\nThe script is waiting for your approval."
#         message = f"Subject: {subject}\n\n{body}"
#         with smtplib.SMTP("smtp.gmail.com", 587) as server:
#             server.starttls()
#             server.login(EMAIL_SENDER, EMAIL_PASSWORD)
#             server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, message)
#         print(f"  [✓] Email sent to {EMAIL_RECEIVER} — tap {number} on your phone")
#         return True
#     except Exception as e:
#         print(f"  [!] Email exception: {e}")
#     return False


def notify_slack(number: str) -> bool:
    """Send auth number via Slack webhook. Returns True on success."""
    if not SLACK_WEBHOOK_URL:
        return False
    try:
        payload = {"text": f":key: *Microsoft Auth Required* — tap *{number}* in Authenticator"}
        # verify=False bypasses corporate proxy self-signed certificate
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10, verify=False)
        if resp.ok:
            print(f"  [✓] Slack notified — tap {number} on your phone")
            return True
        else:
            print(f"  [!] Slack error: {resp.text}")
    except Exception as e:
        print(f"  [!] Slack exception: {e}")
    return False


def send_auth_number(number: str):
    """
    Broadcast the auth number across all configured channels.
    Falls back to a console prompt if nothing is configured.
    """
    sent = False
    sent |= notify_telegram(number)
    # sent |= notify_email(number)
    sent |= notify_slack(number)

    if not sent:
        # No channels configured — just print loudly
        print("\n" + "═" * 60)
        print(f"  🔐  TAP  →  {number}  ←  IN MICROSOFT AUTHENTICATOR")
        print("═" * 60 + "\n")


# ── 2FA detection ──────────────────────────────────────────────────────────────

# Selectors that Microsoft uses for the number-matching display
# (these can change with Microsoft UI updates)
_NUMBER_SELECTORS = [
    "#idRichContext_DisplaySign",           # classic number-match
    "[data-testid='displaySign']",
    ".displaySign",
    "#idDiv_SAOTCC_OTC_ElementContainer",
    "div.display-sign",
    "[aria-label*='number']",
]

def _try_get_auth_number(driver) -> str | None:
    """
    Return the 2-digit number shown on the Microsoft number-match screen,
    or None if the screen isn't visible yet.
    """
    for sel in _NUMBER_SELECTORS:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            text = el.text.strip()
            if text and text.isdigit() and len(text) <= 3:
                return text
        except NoSuchElementException:
            continue
    return None


def _is_on_home(driver) -> bool:
    try:
        ensure_main_window(driver)
        return "/home" in driver.current_url
    except Exception:
        return False


# ── Driver factory ─────────────────────────────────────────────────────────────
def build_driver(headless: bool = False) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=options)
    return driver


# ── Wait helpers ───────────────────────────────────────────────────────────────
def wait_visible(driver, by, selector, timeout=TIMEOUT):
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((by, selector))
    )

def wait_clickable(driver, by, selector, timeout=TIMEOUT):
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, selector))
    )

def ensure_main_window(driver):
    """Switch back to first tab if a new one was opened."""
    if len(driver.window_handles) > 1:
        print("  [!] Extra window detected — switching back to main")
        driver.switch_to.window(driver.window_handles[0])


# ── Step helpers ───────────────────────────────────────────────────────────────
def dismiss_cookie_banner(driver):
    try:
        btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-testid='cookie-consent-button']"))
        )
        btn.click()
        print("  [✓] Cookie banner dismissed")
        screenshot(driver, "cookie_dismissed")
    except TimeoutException:
        print("  [i] No cookie banner")


def select_mat_option(driver, select_testid, value_text):
    trigger = wait_clickable(driver, By.CSS_SELECTOR, f"[data-testid='{select_testid}']")
    trigger.click()
    time.sleep(0.5)
    options = WebDriverWait(driver, TIMEOUT).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "mat-option .mdc-list-item__primary-text"))
    )
    for opt in options:
        if opt.text.strip() == value_text:
            opt.click()
            return
    for opt in options:
        if value_text in opt.text:
            opt.click()
            return
    raise ValueError(f"Option '{value_text}' not found in select '{select_testid}'")


def set_date_via_js(driver, date_str):
    inp = wait_visible(driver, By.CSS_SELECTOR, "[data-testid='form-workstation-date-picker']")
    driver.execute_script("""
        var input = arguments[0];
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value').set;
        nativeInputValueSetter.call(input, arguments[1]);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        input.dispatchEvent(new Event('blur',   { bubbles: true }));
    """, inp, date_str)
    try:
        inp.click()
        time.sleep(0.4)
        from selenium.webdriver.common.keys import Keys
        inp.send_keys(Keys.ESCAPE)
    except Exception:
        pass


# ── Login ──────────────────────────────────────────────────────────────────────
def login(driver, email, password):
    """
    3-step login: email → password → 2FA (number match) → #/home.

    When the Microsoft number-match screen appears the script:
      1. Reads the 2-digit number from the page.
      2. Sends it to you via Telegram / Slack.
      3. Waits up to 120 s for you to tap the matching number on your phone.
    """
    print(f"\n[→] Opening {URL}")
    driver.get(URL)
    time.sleep(1.5)
    screenshot(driver, "page_loaded")

    # ── Step 1: Email ──────────────────────────────────────────────────────────
    print("[→] Waiting for email field …")
    email_input = wait_visible(driver, By.CSS_SELECTOR, "input[data-testid='login-email']")
    email_input.clear()
    email_input.send_keys(email)
    screenshot(driver, "email_entered")
    print(f"  [✓] Email entered: {email}")

    wait_clickable(driver, By.CSS_SELECTOR, "button[type='submit'].mat-mdc-unelevated-button").click()
    time.sleep(1.5)
    ensure_main_window(driver)
    screenshot(driver, "next_clicked")

    # ── Step 2: Password ───────────────────────────────────────────────────────
    print("[→] Looking for password field …")
    pwd = None
    for sel in [
        "input[type='password']",
        "input[name='password']",
        "input[autocomplete='current-password']",
        "input[data-testid='login-password']",
    ]:
        try:
            pwd = WebDriverWait(driver, 8).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, sel))
            )
            print(f"  [✓] Password field found: {sel}")
            break
        except TimeoutException:
            continue

    if pwd:
        pwd.clear()
        pwd.send_keys(password)
        screenshot(driver, "password_entered")
        try:
            wait_clickable(
                driver, By.CSS_SELECTOR,
                "button[type='submit'].mat-mdc-unelevated-button", timeout=8
            ).click()
        except TimeoutException:
            from selenium.webdriver.common.keys import Keys
            pwd.send_keys(Keys.RETURN)
        time.sleep(1)
        ensure_main_window(driver)
        screenshot(driver, "password_submitted")
    else:
        print("  [!] Password field not found — may have gone straight to 2FA")
        screenshot(driver, "no_password_field")

    # ── Step 3: 2FA — detect number, notify user, wait for approval ───────────
    print("\n[→] Watching for Microsoft 2FA screen …")

    MAX_WAIT        = 120   # total seconds to wait for home
    POLL_INTERVAL   = 1     # seconds between checks
    notified        = False
    elapsed         = 0

    while elapsed < MAX_WAIT:
        ensure_main_window(driver)

        # Success — already on home
        if _is_on_home(driver):
            break

        # Try to read the number-match digit
        auth_number = _try_get_auth_number(driver)

        if auth_number and not notified:
            screenshot(driver, "2fa_number_screen")
            print(f"\n  [🔑] Number match detected: {auth_number}")
            send_auth_number(auth_number)
            notified = True

        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    else:
        # Loop exhausted without reaching home
        screenshot(driver, "login_timeout")
        raise RuntimeError(
            f"2FA not completed within {MAX_WAIT} seconds, "
            f"still on: {driver.current_url}"
        )

    # ── Home page stabilisation ────────────────────────────────────────────────
    time.sleep(2)
    ensure_main_window(driver)

    try:
        wait_visible(
            driver, By.CSS_SELECTOR,
            "[data-testid='home-add-booking-workstation']",
            timeout=20
        )
        print("  [✓] Home page ready")
    except TimeoutException:
        print("  [!] Desk card not yet visible — continuing anyway")

    screenshot(driver, "login_success")
    print(f"  [✓] Authenticated — on: {driver.current_url}")


# ── Book a Desk ────────────────────────────────────────────────────────────────
def book_desk(driver):
    dismiss_cookie_banner(driver)

    print("[→] Clicking Desk (Lloc) card …")
    desk_card = wait_clickable(driver, By.CSS_SELECTOR, "[data-testid='home-add-booking-workstation']")
    desk_card.click()
    ensure_main_window(driver)
    time.sleep(0.8)
    screenshot(driver, "desk_card_clicked")
    print("  [✓] Desk card clicked")

    print("[→] Enabling 'Llocs de reserva única' toggle …")
    toggle_btn = wait_clickable(
        driver, By.CSS_SELECTOR,
        "button[id='mat-mdc-slide-toggle-1-button'], "
        "mat-slide-toggle button, "
        ".mat-mdc-slide-toggle button"
    )
    is_checked = toggle_btn.get_attribute("aria-checked") == "true"
    if not is_checked:
        toggle_btn.click()
        time.sleep(0.4)
        print("  [✓] Toggle enabled")
    else:
        print("  [i] Toggle already enabled")
    screenshot(driver, "toggle_enabled")

    print(f"[→] Setting date to {BOOKING_DATE} …")
    set_date_via_js(driver, BOOKING_DATE)
    time.sleep(0.5)
    screenshot(driver, "date_set")
    print(f"  [✓] Date: {BOOKING_DATE}")

    print("[→] Clicking Search Sites …")
    search_btn = None
    for selector in [
        "[data-testid='form-workstation-search-button']",
        "button[type='submit'].mat-mdc-unelevated-button",
        "button.mat-mdc-unelevated-button",
    ]:
        try:
            search_btn = wait_clickable(driver, By.CSS_SELECTOR, selector, timeout=5)
            break
        except TimeoutException:
            continue

    if search_btn:
        search_btn.click()
        ensure_main_window(driver)
        time.sleep(1)
        screenshot(driver, "search_clicked")
        print("  [✓] Search clicked")
    else:
        try:
            search_btn = wait_clickable(
                driver, By.XPATH,
                "//button[contains(., 'Cerca') or contains(., 'Search') or contains(., 'Buscar')]",
                timeout=5
            )
            search_btn.click()
            time.sleep(1)
            screenshot(driver, "search_clicked_xpath")
            print("  [✓] Search clicked (XPath)")
        except TimeoutException:
            screenshot(driver, "search_button_not_found")
            print("  [!] Search button not found — screenshot saved")

    screenshot(driver, "results_page")


# ── High-demand modal dismissal ───────────────────────────────────────────────
def wait_for_high_demand_modal(driver, max_wait: int = 120):
    """
    Detects the 'Please wait… high demand' loading modal and waits for it
    to disappear before continuing. Safe to call even if the modal never appears.

    The modal is identified by its text content — multiple selectors are tried
    so it keeps working if the app updates its markup.
    """
    MODAL_SELECTORS = [
        # Text-based: look for the spinner overlay container
        "//*[contains(text(),'Please wait') or contains(text(),'high demand') or contains(text(),'refining your search')]",
        # Class-based fallbacks
        ".cdk-overlay-container mat-dialog-container",
        "mat-dialog-container",
        ".mat-mdc-dialog-container",
    ]

    modal_found = False

    # ── 1. Detect whether the modal is present ────────────────────────────────
    for sel in MODAL_SELECTORS:
        try:
            by = By.XPATH if sel.startswith("/") else By.CSS_SELECTOR
            driver.find_element(by, sel)
            modal_found = True
            print(f"  [⏳] High-demand modal detected — waiting up to {max_wait}s …")
            screenshot(driver, "high_demand_modal")
            break
        except NoSuchElementException:
            continue

    if not modal_found:
        print("  [i] No high-demand modal — proceeding immediately")
        return

    # ── 2. Wait for the modal to vanish ──────────────────────────────────────
    # Strategy A: wait for the XPath text to disappear
    try:
        WebDriverWait(driver, max_wait).until_not(
            EC.presence_of_element_located((
                By.XPATH,
                "//*[contains(text(),'Please wait') or contains(text(),'high demand') or contains(text(),'refining your search')]"
            ))
        )
        print("  [✓] High-demand modal dismissed — map should be ready")
        screenshot(driver, "high_demand_modal_gone")
        return
    except TimeoutException:
        pass

    # Strategy B: wait for mat-dialog-container to disappear
    try:
        WebDriverWait(driver, max_wait).until_not(
            EC.presence_of_element_located((By.CSS_SELECTOR, "mat-dialog-container"))
        )
        print("  [✓] High-demand modal dismissed (dialog container gone)")
        screenshot(driver, "high_demand_modal_gone")
        return
    except TimeoutException:
        screenshot(driver, "high_demand_modal_timeout")
        raise RuntimeError(
            f"High-demand modal did not disappear within {max_wait} seconds. "
            "The site may still be searching — check the screenshot."
        )


# ── Map: find and click BCN 21, then confirm ──────────────────────────────────
def select_desk_and_confirm(driver, desk_name="BCN 21"):
    print("[→] Waiting for Leaflet map to load …")
    time.sleep(2)

    # Handle the 'Please wait… high demand' modal before touching the map
    wait_for_high_demand_modal(driver)

    screenshot(driver, "map_loaded")
    print(f"[→] Searching for desk '{desk_name}' …")

    JS_CLICK = r"""
        var target = arguments[0];
        var norm = function(s){ return s.replace(/\s+/g,' ').trim(); };
        var tgt  = norm(target);

        var containers = document.querySelectorAll('.leaflet-container');
        for (var ci = 0; ci < containers.length; ci++) {
            var container = containers[ci];
            var mapObj = null;
            for (var key in container) {
                if (key.startsWith('_leaflet') &&
                        container[key] &&
                        typeof container[key].eachLayer === 'function') {
                    mapObj = container[key];
                    break;
                }
            }
            if (!mapObj) continue;

            var found = false;
            mapObj.eachLayer(function(layer) {
                if (found) return;
                try {
                    var tt = layer.getTooltip && layer.getTooltip();
                    if (tt) {
                        var c = tt.getContent ? tt.getContent() : '';
                        if (typeof c === 'string' &&
                                (norm(c) === tgt || norm(c).indexOf(tgt) !== -1)) {
                            layer.fire('click');
                            found = true;
                            return;
                        }
                    }
                } catch(e) {}
                try {
                    var opts = layer.options || {};
                    var n = norm(opts.title || opts.name || opts.label || '');
                    if (n && (n === tgt || n.indexOf(tgt) !== -1)) {
                        layer.fire('click');
                        found = true;
                    }
                } catch(e) {}
            });
            if (found) return true;
        }
        return false;
    """

    clicked = driver.execute_script(JS_CLICK, desk_name)

    if clicked:
        print("  [✓] Desk clicked via Leaflet JS API")
    else:
        print("  [!] JS API did not fire — falling back to hover scan …")
        paths = driver.find_elements(By.CSS_SELECTOR, "path.resource.leaflet-interactive")
        print(f"      Found {len(paths)} desk circles on the map")

        desk_element = None
        tgt_norm = " ".join(desk_name.split())

        for i, path in enumerate(paths):
            try:
                ActionChains(driver).move_to_element(path).perform()
                time.sleep(0.35)
                tooltips = driver.find_elements(By.CSS_SELECTOR, ".leaflet-tooltip")
                for tip in tooltips:
                    if tgt_norm in " ".join(tip.text.split()):
                        desk_element = path
                        print(f"  [✓] Desk found (circle #{i+1}) via tooltip hover")
                        break
                if desk_element:
                    break
            except Exception:
                continue

        if desk_element:
            desk_element.click()
            ensure_main_window(driver)
        else:
            screenshot(driver, "desk_not_found")
            raise RuntimeError(
                f"Could not locate desk '{desk_name}' on the map. "
                "See 'desk_not_found.png' and inspect the SVG / Leaflet layers."
            )

    time.sleep(0.8)
    screenshot(driver, "desk_clicked")

    print("[→] Waiting for confirmation modal …")
    try:
        modal_title = wait_visible(driver, By.CSS_SELECTOR, "[data-testid='resource-title']")
        print(f"  [✓] Modal — resource: '{modal_title.text.strip()}'")
        screenshot(driver, "confirm_modal_open")
    except TimeoutException:
        screenshot(driver, "modal_not_found")
        raise RuntimeError("Confirmation modal did not appear after clicking the desk")

    print("[→] Clicking 'Reserva' (Book) …")
    confirm_btn = wait_clickable(driver, By.CSS_SELECTOR, "[data-testid='confirm-button']")
    confirm_btn.click()
    ensure_main_window(driver)
    time.sleep(1.5)
    screenshot(driver, "booking_confirmed")
    print("  [✓] Booking confirmed! ✅")


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"[i] Screenshots → ./{SCREENSHOTS}/")
    driver = build_driver(HEADLESS)
    try:
        login(driver, EMAIL, PASSWORD)
        book_desk(driver)
        select_desk_and_confirm(driver, desk_name="BCN 21")
        time.sleep(3)
    except Exception as e:
        print(f"[✗] Fatal error: {e}")
        screenshot(driver, "fatal_error")
        raise
    finally:
        driver.quit()
        print(f"\n[✓] Done — {screenshot.counter} screenshots in ./{SCREENSHOTS}/")