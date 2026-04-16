"""
Bookker Login + Desk Booking Automation
Logs in, clicks Desk, configures the booking form, and searches for sites.
"""

import os
import time
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

load_dotenv(Path(__file__).parent / ".env")

# ── Credentials ────────────────────────────────────────────────────────────────
EMAIL    = os.environ["EMAIL"]
PASSWORD = os.environ["PASSWORD"]

# ── Config ─────────────────────────────────────────────────────────────────────
URL         = "https://webapp.bookkercorp.com/#/login"
TIMEOUT     = 15
HEADLESS    = os.getenv("HEADLESS", "false").lower() == "true"
SCREENSHOTS = "screenshots"

# Booking config — date must be in the future; times as they appear in the dropdown
BOOKING_DATE       = (datetime.today() + timedelta(days=7)).strftime("%Y-%m-%d")  # tomorrow

# ── Screenshot helper ──────────────────────────────────────────────────────────
def screenshot(driver: webdriver.Chrome, label: str) -> str:
    os.makedirs(SCREENSHOTS, exist_ok=True)
    screenshot.counter += 1
    path = os.path.join(SCREENSHOTS, f"{screenshot.counter:03d}_{label}.png")
    driver.save_screenshot(path)
    print(f"  [📷] {path}")
    return path

screenshot.counter = 0


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
    """Accept cookie banner if present."""
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
    """
    Open a mat-select by data-testid and pick the option matching value_text.
    Falls back to partial match if exact match not found.
    """
    trigger = wait_clickable(driver, By.CSS_SELECTOR, f"[data-testid='{select_testid}']")
    trigger.click()
    time.sleep(0.5)

    # Options appear in an overlay panel
    options = WebDriverWait(driver, TIMEOUT).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "mat-option .mdc-list-item__primary-text"))
    )
    for opt in options:
        if opt.text.strip() == value_text:
            opt.click()
            return
    # Fallback: partial match
    for opt in options:
        if value_text in opt.text:
            opt.click()
            return
    raise ValueError(f"Option '{value_text}' not found in select '{select_testid}'")


def set_date_via_js(driver, date_str):
    """
    The date input is readonly + uses mat-datepicker.
    Inject the value via JS and fire Angular/DOM events so the framework
    picks it up, then close the calendar if it opened.
    """
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

    # Also try clicking the input to open the picker and then close it
    # so Angular registers the change
    try:
        inp.click()
        time.sleep(0.4)
        # Press Escape to close the calendar overlay without changing anything
        from selenium.webdriver.common.keys import Keys
        inp.send_keys(Keys.ESCAPE)
    except Exception:
        pass


# ── Login ──────────────────────────────────────────────────────────────────────
def login(driver, email, password):
    """
    3-step login: email → password → 2FA phone app → #/home.

    The 2FA is approved entirely on the user's phone; the script waits up to
    120 seconds for the URL to become .../home before continuing.
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
    time.sleep(1.5)          # let the page transition settle
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
            # Some builds submit on Enter
            from selenium.webdriver.common.keys import Keys
            pwd.send_keys(Keys.RETURN)
        time.sleep(1)
        ensure_main_window(driver)
        screenshot(driver, "password_submitted")
    else:
        print("  [!] Password field not found — may have gone straight to 2FA")
        screenshot(driver, "no_password_field")

    # ── Step 3: 2FA — wait for user to approve on phone ───────────────────────
    print("\n" + "─" * 60)
    print("  ⚠️  Complete 2FA on your phone now.")
    print("      Waiting up to 120 seconds for #/home …")
    print("─" * 60 + "\n")

    def _at_home(d):
        """Return True only once the app has fully landed on the home page."""
        try:
            ensure_main_window(d)
            url = d.current_url
            return "/home" in url
        except Exception:
            return False

    try:
        WebDriverWait(driver, 120).until(_at_home)
    except TimeoutException:
        screenshot(driver, "login_timeout")
        raise RuntimeError(
            "2FA not completed within 120 seconds, "
            f"still on: {driver.current_url}"
        )

    # ── Home page stabilisation ────────────────────────────────────────────────
    time.sleep(2)                    # let Angular finish rendering
    ensure_main_window(driver)

    # Wait until at least the desk-booking card is in the DOM
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
    # Dismiss cookie banner if shown
    dismiss_cookie_banner(driver)

    # ── 1. Click "Lloc" (Desk) card ────────────────────────────────────────────
    print("[→] Clicking Desk (Lloc) card …")
    desk_card = wait_clickable(driver, By.CSS_SELECTOR, "[data-testid='home-add-booking-workstation']")
    desk_card.click()
    ensure_main_window(driver)
    time.sleep(0.8)
    screenshot(driver, "desk_card_clicked")
    print("  [✓] Desk card clicked")

    # ── 2. Enable "Llocs de reserva única" toggle ──────────────────────────────
    print("[→] Enabling 'Llocs de reserva única' toggle …")
    # The toggle label id is mat-mdc-slide-toggle-1-label; click its button
    toggle_btn = wait_clickable(
        driver, By.CSS_SELECTOR,
        "button[id='mat-mdc-slide-toggle-1-button'], "
        "mat-slide-toggle button, "
        ".mat-mdc-slide-toggle button"
    )
    # Only click if not already checked
    is_checked = toggle_btn.get_attribute("aria-checked") == "true"
    if not is_checked:
        toggle_btn.click()
        time.sleep(0.4)
        print("  [✓] Toggle enabled")
    else:
        print("  [i] Toggle already enabled")
    screenshot(driver, "toggle_enabled")

    # ── 3. Set date ────────────────────────────────────────────────────────────
    print(f"[→] Setting date to {BOOKING_DATE} …")
    set_date_via_js(driver, BOOKING_DATE)
    time.sleep(0.5)
    screenshot(driver, "date_set")
    print(f"  [✓] Date: {BOOKING_DATE}")

    # ── 6. Click "Search Sites" ────────────────────────────────────────────────
    print("[→] Clicking Search Sites …")
    # Try data-testid first, then fall back to text content
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
        # XPath fallback — button containing "Cerca" or "Search"
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

# ── Map: find and click BCN 21, then confirm ──────────────────────────────────
def select_desk_and_confirm(driver, desk_name="BCN 21"):
    """
    Click the target desk on the Leaflet interactive floor-plan map.
    Desks are SVG <path class="resource leaflet-interactive"> elements with
    NO name attributes — we identify BCN 21 through its Leaflet tooltip.

    Strategy 1 — Leaflet JS API:
        Iterate every layer on the map; if its tooltip content matches
        desk_name (whitespace-normalised), fire a click event on that layer.

    Strategy 2 — hover scan:
        Move the mouse over every .resource path; read the tooltip that
        appears; stop when it matches desk_name, then click.
    """

    # ── 1. Wait for the map to fully render ────────────────────────────────────
    print("[→] Waiting for Leaflet map to load …")
    time.sleep(2)
    screenshot(driver, "map_loaded")
    print(f"[→] Searching for desk '{desk_name}' …")

    # ── 2a. Strategy 1 — Leaflet JavaScript API ────────────────────────────────
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
        # ── 2b. Strategy 2 — hover every circle, read tooltip ─────────────────
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

    # ── 3. Wait for the confirmation modal ────────────────────────────────────
    print("[→] Waiting for confirmation modal …")
    try:
        modal_title = wait_visible(driver, By.CSS_SELECTOR, "[data-testid='resource-title']")
        print(f"  [✓] Modal — resource: '{modal_title.text.strip()}'")
        screenshot(driver, "confirm_modal_open")
    except TimeoutException:
        screenshot(driver, "modal_not_found")
        raise RuntimeError("Confirmation modal did not appear after clicking the desk")

    # ── 4. Click 'Reserva' ────────────────────────────────────────────────────
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