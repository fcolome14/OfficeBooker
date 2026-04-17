# 🪑 Bookker Desk Booking Automation

Automates desk booking on [Bookker](https://webapp.bookkercorp.com) using Selenium. Handles Microsoft corporate login, detects the **2FA number-match prompt**, sends the code to your **Telegram**, and completes the booking on your behalf.

---

## 📋 Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| Google Chrome | Latest |
| ChromeDriver | Must match your Chrome version |

---

## ⚙️ Installation

**1. Clone the repository**
```bash
git clone https://github.com/your-username/bookker-automation.git
cd bookker-automation
```

**2. Install Python dependencies**
```bash
pip install selenium python-dotenv requests urllib3
```

**3. Install ChromeDriver**

ChromeDriver must match your installed Chrome version exactly.

- Check your Chrome version: open Chrome → `⋮` menu → Help → About Google Chrome
- Download the matching ChromeDriver from: https://googlechromelabs.github.io/chrome-for-testing/
- Place the `chromedriver` binary somewhere on your `PATH`, or in the project folder

> On Mac you may need to run `xattr -d com.apple.quarantine chromedriver` after downloading.

---

## 🔐 Telegram Bot Setup (required for 2FA notifications)

The script detects the Microsoft Authenticator number-match code and sends it to you via Telegram so you can tap it on your phone.

**Step 1 — Create a bot**
1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **token** it gives you (looks like `123456789:ABCdef...`)

**Step 2 — Get your Chat ID**
1. Search for your new bot in Telegram and press **Start** ← _mandatory_
2. Search for **@userinfobot** and press Start
3. Copy the **ID** number it replies with

**Step 3 — Verify it works** (replace the values first)
```bash
curl -k -X POST "https://api.telegram.org/bot<YOUR_TOKEN>/sendMessage" \
  -d chat_id=<YOUR_CHAT_ID> \
  -d text="Test from Bookker script"
```
You should receive the message in Telegram and see `{"ok":true}` in the terminal.

> The `-k` flag is needed if you're on a corporate network with a proxy — same reason the script uses `verify=False`.

---

## 🗂️ Environment Variables

Create a `.env` file in the project root (same folder as `bookker_automation.py`):

```env
# Bookker credentials
EMAIL=your.corporate@email.com
PASSWORD=your_password

# Telegram (required for 2FA notifications)
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNO...
TELEGRAM_CHAT_ID=987654321

# Slack (optional)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

> ⚠️ Never commit your `.env` file. Add it to `.gitignore`.

### Variable reference

| Variable | Required | Description |
|---|---|---|
| `EMAIL` | ✅ | Your Bookker / Microsoft login email |
| `PASSWORD` | ✅ | Your Microsoft password |
| `TELEGRAM_BOT_TOKEN` | ✅ | Token from @BotFather |
| `TELEGRAM_CHAT_ID` | ✅ | Your Telegram user ID |
| `SLACK_WEBHOOK_URL` | ❌ | Slack incoming webhook URL |

---

## ▶️ Running the script

```bash
python bookker_automation.py
```

### What happens step by step

```
1. Chrome opens and navigates to Bookker login
2. Your email and password are entered automatically
3. Microsoft redirects to the 2FA number-match screen
4. The script reads the 2-digit number and sends it to your Telegram
5. You open Telegram, see the number, tap it in Microsoft Authenticator
6. The script detects the successful login and navigates to the booking form
7. It fills in the date (14 days from today) and clicks Search
8. If a "high demand" loading modal appears, it waits for it to close
9. It locates the desired desk 'BCN XX' on the floor map and clicks it
10. It confirms the booking
```

### Expected console output

```
[→] Opening https://webapp.bookkercorp.com/#/login
[→] Waiting for email field …
  [✓] Email entered: your@email.com
[→] Looking for password field …
  [✓] Password field found
[→] Watching for Microsoft 2FA screen …
  [🔑] Number match detected: 42
  [✓] Telegram notified — tap 42 on your phone
  [✓] Authenticated — on: https://webapp.bookkercorp.com/#/home
[→] Clicking Desk (Lloc) card …
  [⏳] High-demand modal detected — waiting up to 120s …
  [✓] High-demand modal dismissed — map should be ready
[→] Searching for desk 'BCN 21' …
  [✓] Desk clicked via Leaflet JS API
  [✓] Booking confirmed! ✅
```

---

## 📁 Project structure

```
bookker-automation/
├── bookker_automation.py   # Main script
├── .env                    # Your credentials (never commit this)
├── .env.example            # Template — safe to commit
├── .gitignore
├── README.md
└── screenshots/            # Auto-created, one PNG per step
```

### Recommended `.gitignore`
```
.env
screenshots/
__pycache__/
*.pyc
```

### `.env.example` (safe to commit as a template)
```env
EMAIL=
PASSWORD=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
SLACK_WEBHOOK_URL=
NOTIF_EMAIL_SENDER=
NOTIF_EMAIL_PASSWORD=
NOTIF_EMAIL_RECEIVER=
HEADLESS=false
```

---

## 🛠️ Configuration

To change the desk or booking date, edit these lines at the top of `bookker_automation.py`:

```python
# Days from today to book (currently 14)
BOOKING_DATE = (datetime.today() + timedelta(days=14)).strftime("%Y-%m-%d")
```

```python
# Desk name as it appears on the floor map
select_desk_and_confirm(driver, desk_name="BCN 21")
```

---

## 🏢 Corporate network notes

If you're running this on a corporate network with an SSL-inspecting proxy (common in large companies), the script already handles this — `verify=False` is set on all outbound notification requests and SSL warnings are suppressed. No certificate installation needed.

---

## 🐛 Troubleshooting

**`KeyError: 'TELEGRAM_BOT_TOKEN'`**
Your `.env` file is missing or not in the same folder as the script. Make sure it exists and has no typos.

**`{"ok":false,"error_code":400,"description":"Bad Request: chat not found"}`**
You haven't sent a message to your bot yet. Open Telegram, find your bot, and press **Start**.

**2FA timeout after 120 seconds**
The script waited but you didn't tap in time, or the number wasn't detected. Check the `screenshots/` folder — `2fa_number_screen.png` shows what the script saw. You can increase the timeout by changing `MAX_WAIT = 120` in the `login()` function.

**`desk not found` error**
The desk name in the script doesn't match what's on the map. Check `screenshots/map_loaded.png` and compare the tooltip text with `desk_name="BCN 21"` in the script.

**Chrome crashes immediately**
Your ChromeDriver version doesn't match your Chrome version. Re-download the correct one from https://googlechromelabs.github.io/chrome-for-testing/

---

## 📸 Screenshots

Every step saves a numbered screenshot to `screenshots/` automatically, making it easy to debug what went wrong:

| File | When it's taken |
|---|---|
| `001_page_loaded.png` | After opening the login page |
| `003_email_entered.png` | After typing the email |
| `007_2fa_number_screen.png` | The Microsoft number-match screen |
| `008_login_success.png` | After successful authentication |
| `014_desk_not_found.png` | If the desk couldn't be located |
| `XXX_fatal_error.png` | If the script crashes unexpectedly |