import json
import time
import requests
import traceback
import sys
import os
from datetime import datetime, timezone, timedelta
from playwright.sync_api import sync_playwright, TimeoutError
from typing import Optional


os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/home/codespace/.cache/ms-playwright"

# Configuration
PHONE = os.getenv("PHONE")
PASSWORD = os.getenv("PASSWORD")
BOT_TOKEN = os.getenv("BOT_TOKEN")
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID")
FILE_CHAT_ID = os.getenv("FILE_CHAT_ID")


ICE_URL = (
    "https://evo.wcentertainments.com/frontend/evo/r2/"
    "#game=icefishing"
    "&table_id=IceFishing000001"
    "&vt_id=tbm6dbieeo4qbedu"
)

# Timezone for IST (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# Global flag to signal script completion
script_completed = False

# Global flag to signal script completion
script_completed = False

# ================= RATE LIMITER =================
class RateLimiter:
    """Rate limiter to prevent Telegram API rate limiting"""
    def __init__(self):
        self.last_call = {}
        self.min_interval = 2  # Minimum 2 seconds between messages to same chat
        self.global_interval = 1  # Minimum 1 second between any Telegram calls
        
    def wait_if_needed(self, chat_id=None):
        current_time = time.time()
        
        # Check global rate limit
        if 'global' in self.last_call:
            time_since_last = current_time - self.last_call['global']
            if time_since_last < self.global_interval:
                time.sleep(self.global_interval - time_since_last)
        
        # Check chat-specific rate limit
        if chat_id and chat_id in self.last_call:
            time_since_last = current_time - self.last_call[chat_id]
            if time_since_last < self.min_interval:
                time.sleep(self.min_interval - time_since_last)
        
        self.last_call['global'] = time.time()
        if chat_id:
            self.last_call[chat_id] = time.time()

# ================= TIME HELPER FUNCTIONS =================
def get_ist_time():
    """Get current time in IST timezone"""
    return datetime.now(IST)

def format_ist_time(timestamp=None, format_str="%Y-%m-%d %H:%M:%S"):
    """Format time in IST"""
    if timestamp is None:
        timestamp = get_ist_time()
    return timestamp.strftime(format_str)

def format_ist_date(timestamp=None):
    """Format date in IST (DD-MM-YYYY)"""
    if timestamp is None:
        timestamp = get_ist_time()
    return timestamp.strftime("%d-%m-%Y")

def format_ist_time_12hr(timestamp=None):
    """Format time in IST (12-hour format with AM/PM)"""
    if timestamp is None:
        timestamp = get_ist_time()
    return timestamp.strftime("%I:%M:%S %p")

def get_filename_timestamp():
    """Get timestamp for filename in YYYYMMDD_HHMMSS format"""
    return get_ist_time().strftime("%Y%m%d_%H%M%S")

# ================= IMPROVED DUAL TELEGRAM MANAGER =================
class DualTelegramNotifier:
    """Handles Telegram communications with rate limiting"""
    
    def __init__(self, bot_token: str, log_chat_id: str, file_chat_id: str):
        self.bot_token = bot_token
        self.log_chat_id = log_chat_id
        self.file_chat_id = file_chat_id
        self.rate_limiter = RateLimiter()
        self.max_retries = 3
        self.retry_delay = 5  # seconds
        
    def send_message(self, text: str, parse_mode: str = "HTML", 
                    is_file_notification: bool = False, 
                    chat_id_override: str = None) -> Optional[dict]:
        
        # Determine chat ID
        if chat_id_override:
            chat_id = chat_id_override
        elif is_file_notification:
            chat_id = self.file_chat_id
        else:
            chat_id = self.log_chat_id
        
        # Apply rate limiting
        self.rate_limiter.wait_if_needed(chat_id)
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        
        for attempt in range(self.max_retries):
            try:
                response = requests.post(url, json=payload, timeout=15)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    # Rate limited - wait and retry
                    retry_after = response.json().get('parameters', {}).get('retry_after', self.retry_delay)
                    if attempt < self.max_retries - 1:
                        time.sleep(retry_after)
                        continue
                    else:
                        print(f"❌ Telegram API rate limit exceeded after {self.max_retries} attempts")
                        return None
                else:
                    print(f"❌ Telegram API error {response.status_code}: {response.text[:100]}")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay)
                        continue
                    return None
                    
            except Exception as e:
                print(f"❌ Telegram connection error: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
        
        return None
    
    def send_file(self, filename: str, caption: str = "", chat_id_override: str = None) -> Optional[dict]:
        """Send file to Telegram with rate limiting"""
        
        # Apply rate limiting
        chat_id = chat_id_override or self.file_chat_id
        self.rate_limiter.wait_if_needed(chat_id)
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendDocument"
        
        for attempt in range(self.max_retries):
            try:
                with open(filename, 'rb') as f:
                    files = {'document': f}
                    data = {
                        'chat_id': chat_id,
                        'caption': caption[:1024],
                        'parse_mode': 'HTML'
                    }
                    response = requests.post(url, files=files, data=data, timeout=30)
                    
                    if response.status_code == 200:
                        return response.json()
                    elif response.status_code == 429:
                        retry_after = response.json().get('parameters', {}).get('retry_after', self.retry_delay)
                        if attempt < self.max_retries - 1:
                            time.sleep(retry_after)
                            continue
                        else:
                            print(f"❌ Telegram API rate limit exceeded when sending file")
                            return None
                    else:
                        print(f"❌ Telegram file error {response.status_code}")
                        if attempt < self.max_retries - 1:
                            time.sleep(self.retry_delay)
                            continue
                            
            except Exception as e:
                print(f"❌ Telegram file connection error: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
        
        return None

# Initialize dual Telegram notifier
tg = DualTelegramNotifier(BOT_TOKEN, LOG_CHAT_ID, FILE_CHAT_ID)

# ================= ENHANCED PRINT FUNCTION =================
def print_and_notify(message: str, level: str = "INFO", send_to_telegram: bool = True, 
                    is_file_notification: bool = False, chat_id_override: str = None):
    """Print to console and optionally send to Telegram with rate limiting"""
    
    colors = {
        "INFO": "\033[94m",
        "SUCCESS": "\033[92m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
        "DEBUG": "\033[90m",
    }
    reset = "\033[0m"
    
    # Use IST time for all timestamps
    timestamp = format_ist_time()
    
    level_icon = {
        "INFO": "ℹ️",
        "SUCCESS": "✅",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "DEBUG": "🔍",
    }
    
    console_msg = f"{colors.get(level, '')}[{timestamp} IST] [{level}] {message}{reset}"
    print(console_msg)
    
    # Skip Telegram for DEBUG messages to reduce API calls
    if level == "DEBUG":
        send_to_telegram = False
    
    if send_to_telegram:
        tg_message = f"{level_icon.get(level, '📝')} <b>{level}</b>\n{message}"
        
        if len(tg_message) > 4000:
            tg_message = tg_message[:4000] + "..."
        
        tg.send_message(tg_message, is_file_notification=is_file_notification, 
                       chat_id_override=chat_id_override)

# ================= BATCH MESSAGE SENDER =================
def send_batch_messages(messages, delay=2):
    """Send multiple messages with delays to avoid rate limiting"""
    for message, level, send_to_tg in messages:
        print_and_notify(message, level, send_to_tg)
        time.sleep(delay)

# ================= SPIN HISTORY MANAGER =================
class SpinHistoryManager:
    """Manages spin history JSON files with IST timestamp in filename"""
    
    def __init__(self):
        self.latest_file = None
        self.last_send_time = 0
        self.min_send_interval = 30  # Minimum 30 seconds between file sends
        
    def save_spin_data(self, data):
        """Save spin data to JSON file with IST timestamp in filename"""
        try:
            # Create filename with IST timestamp
            timestamp = get_filename_timestamp()
            self.latest_file = f"spinHistory_{timestamp}.json"
            
            with open(self.latest_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            print_and_notify(f"Spin history saved to {self.latest_file}", "SUCCESS")
            return self.latest_file
            
        except Exception as e:
            print_and_notify(f"Error saving spin data: {str(e)[:100]}", "ERROR")
            return None
    
    def send_to_telegram(self, filename, summary=None):
        """Send file to Telegram with rate limiting"""
        current_time = time.time()
        
        # Check if enough time has passed since last send
        if current_time - self.last_send_time < self.min_send_interval:
            print_and_notify(f"Rate limiting: Waiting before sending next file", "DEBUG")
            return False
            
        if not os.path.exists(filename):
            print_and_notify(f"File not found: {filename}", "ERROR")
            return False
            
        try:
            # Extract summary for log
            if summary is None:
                summary = "🎣 Spin History Captured"
            
            # Format caption with IST time
            ist_date = format_ist_date()
            ist_time = format_ist_time_12hr()
            
            file_caption = f"""🎰 <b>Spin History</b>
━━━━━━━━━━━━━━━━━━━━
{summary}
• Date: {ist_date}
• Time: {ist_time} IST
━━━━━━━━━━━━━━━━━━━━"""
            
            # Send file
            result = tg.send_file(filename, file_caption)
            
            if result:
                self.last_send_time = current_time
                print_and_notify(f"Spin history file sent: {filename}", "SUCCESS")
                
                # Also send notification to log channel
                log_notification = f"""📤 <b>Spin History File Sent</b>
━━━━━━━━━━━━━━━━━━━━
• File: {os.path.basename(filename)}
• Size: {os.path.getsize(filename)} bytes
• Time: {ist_time} IST
━━━━━━━━━━━━━━━━━━━━"""
                print_and_notify(log_notification, "INFO", chat_id_override=LOG_CHAT_ID)
                return True
            else:
                print_and_notify(f"Failed to send file: {filename}", "WARNING")
                return False
                
        except Exception as e:
            print_and_notify(f"Error sending file: {str(e)[:100]}", "ERROR")
            return False
    
    def get_latest_file(self):
        """Get the latest spin history file"""
        return self.latest_file if self.latest_file and os.path.exists(self.latest_file) else None
    
    def cleanup(self):
        """Cleanup JSON file on exit"""
        if self.latest_file and os.path.exists(self.latest_file):
            try:
                os.remove(self.latest_file)
                print_and_notify(f"Cleaned up JSON file: {self.latest_file}", "DEBUG", send_to_telegram=False)
            except:
                pass

# Initialize spin history manager
spin_manager = SpinHistoryManager()

# ================= IMPROVED LOGIN FUNCTION =================
def step1_login(page):
    print_and_notify("Starting login process...", "INFO")
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print_and_notify(f"Login attempt {attempt + 1}/{max_retries}", "DEBUG", send_to_telegram=False)
            
            page.goto("https://ind.55ace.com/login", timeout=180000, wait_until="domcontentloaded")
            print_and_notify("Login page loaded", "DEBUG", send_to_telegram=False)
            
            page.wait_for_selector('input[autocomplete="username"]', timeout=30000)
            page.wait_for_selector('input[autocomplete="current-password"]', timeout=30000)
            
            page.fill('input[autocomplete="username"]', '', force=True)
            page.fill('input[autocomplete="username"]', PHONE, force=True)
            
            page.fill('input[autocomplete="current-password"]', '', force=True)
            page.fill('input[autocomplete="current-password"]', PASSWORD, force=True)
            
            print_and_notify("Credentials entered", "DEBUG", send_to_telegram=False)
            
            login_button = page.locator('button:has-text("Login")')
            login_button.scroll_into_view_if_needed()
            login_button.click(force=True)
            
            print_and_notify("Login button clicked", "DEBUG", send_to_telegram=False)
            
            try:
                page.wait_for_url("**/home**", timeout=45000, wait_until="domcontentloaded")
                print_and_notify("Redirected to home page", "SUCCESS")
                break
                
            except TimeoutError:
                try:
                    page.wait_for_selector('img[src*="avatar"]', timeout=10000)
                    print_and_notify("User avatar detected - login successful", "SUCCESS")
                    break
                    
                except TimeoutError:
                    error_msg = page.locator('.error-message, .alert-danger, .text-danger').first
                    if error_msg.count() > 0:
                        error_text = error_msg.text_content()[:100]
                        print_and_notify(f"Login error: {error_text}", "ERROR")
                        if attempt < max_retries - 1:
                            time.sleep(5)
                            continue
                    else:
                        current_url = page.url
                        if "login" not in current_url:
                            print_and_notify(f"Redirected to: {current_url[:50]}...", "SUCCESS")
                            break
                        
                        if attempt < max_retries - 1:
                            print_and_notify(f"Retrying login... ({attempt + 1}/{max_retries})", "WARNING")
                            page.reload()
                            time.sleep(3)
                            continue
                        else:
                            raise Exception("Login failed after multiple attempts")
                            
        except Exception as e:
            if attempt < max_retries - 1:
                print_and_notify(f"Login attempt {attempt + 1} failed: {str(e)[:100]}", "WARNING")
                time.sleep(5)
                continue
            else:
                raise
    
    print_and_notify("Login completed", "SUCCESS")

# ================= OTHER STEPS =================
def step2_close_popup(page, times=2):
    print_and_notify("Checking for popups...", "INFO")
    closed_count = 0
    for i in range(times):
        page.wait_for_timeout(1200)
        btn = page.locator("button.popout-close")
        if btn.count():
            btn.first.click(force=True)
            closed_count += 1
            print_and_notify(f"Popup closed ({closed_count})", "DEBUG", send_to_telegram=False)
        else:
            break
    
    if closed_count > 0:
        print_and_notify(f"Closed {closed_count} popup(s)", "SUCCESS")
    else:
        print_and_notify("No popups found", "DEBUG", send_to_telegram=False)

def step3_click_casino(page):
    print_and_notify("Navigating to Casino section...", "INFO")
    page.wait_for_selector(".cat-selection-item", timeout=60000)
    print_and_notify("Category items loaded", "DEBUG", send_to_telegram=False)
    
    result = page.evaluate("""
    () => {
        const items = [...document.querySelectorAll('.cat-selection-item')];
        const casino = items.find(el =>
            el.querySelector('.cat-title') &&
            el.querySelector('.cat-title').innerText.trim() === 'Casino'
        );
        
        if (!casino) {
            console.log('Casino not found. Available categories:');
            items.forEach(item => {
                const title = item.querySelector('.cat-title');
                if (title) console.log('- ' + title.innerText.trim());
            });
            return false;
        }
        
        casino.scrollIntoView({block:'center'});
        ['mousedown','mouseup','click'].forEach(t =>
            casino.dispatchEvent(new MouseEvent(t,{bubbles:true}))
        );
        return true;
    }
    """)
    
    if result:
        print_and_notify("Casino section clicked", "SUCCESS")
    else:
        print_and_notify("Casino section not found!", "ERROR")
        raise Exception("Casino section not found")

def step4_click_evolution(page):
    print_and_notify("Selecting Evolution games...", "INFO")
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print_and_notify(f"Evolution selection attempt {attempt + 1}/{max_retries}", "DEBUG", send_to_telegram=False)
            
            # Wait for ANY live provider card with longer timeout
            try:
                page.wait_for_selector("[class*='platform-live']", timeout=30000)
            except:
                # Fallback: wait for any platform card
                page.wait_for_selector("[class*='platform'], [class*='provider']", timeout=30000)
            
            page.wait_for_timeout(2000)  # Allow for animations/loading
            
            # Execute JavaScript to find and click Evolution
            result = page.evaluate("""
            () => {
                try {
                    // Method 1: Try original selector first
                    const cards = [...document.querySelectorAll('[class*="platform-live"]')];
                    
                    if (cards.length > 0) {
                        const evo = cards.find(el => {
                            const text = el.innerText?.toLowerCase() || "";
                            const img  = el.querySelector("img")?.src || "";
                            const bg   = el.style.backgroundImage || "";
                            
                            return text.includes("evolution")
                                || text.includes("evo")
                                || img.includes("evo")
                                || img.includes("evolution")
                                || bg.includes("evo")
                                || bg.includes("evolution");
                        });
                        
                        if (evo) {
                            console.log("Found Evolution using platform-live selector");
                            evo.scrollIntoView({ block: "center", behavior: "smooth" });
                            
                            // Force all click events
                            evo.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                            evo.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                            evo.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                            
                            return { success: true, method: "platform-live" };
                        }
                    }
                    
                    // Method 2: Try broader selectors for headless mode
                    const allCards = [...document.querySelectorAll('[class*="platform"], [class*="provider"], [class*="card"]')];
                    
                    if (allCards.length > 0) {
                        const evo = allCards.find(el => {
                            const text = el.innerText?.toLowerCase() || "";
                            const img = el.querySelector("img")?.src || "";
                            const bg = el.style.backgroundImage || "";
                            const cls = el.className?.toLowerCase() || "";
                            
                            return text.includes("evolution")
                                || text.includes("evo")
                                || img.includes("evo")
                                || img.includes("evolution")
                                || bg.includes("evo")
                                || bg.includes("evolution")
                                || cls.includes("evo")
                                || cls.includes("evolution");
                        });
                        
                        if (evo) {
                            console.log("Found Evolution using broader selector");
                            evo.scrollIntoView({ block: "center", behavior: "smooth" });
                            
                            // Try multiple click methods
                            evo.click();
                            evo.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                            
                            return { success: true, method: "broader-selector" };
                        }
                    }
                    
                    // Method 3: Search for Evolution text in any element
                    const allElements = document.querySelectorAll('*');
                    for (let el of allElements) {
                        const text = el.innerText?.toLowerCase() || "";
                        if (text.includes("evolution") && text.length < 100) {
                            console.log("Found Evolution by text:", text.substring(0, 50));
                            el.scrollIntoView({ block: "center", behavior: "smooth" });
                            
                            // Create a click at the center of the element
                            const rect = el.getBoundingClientRect();
                            const x = rect.left + rect.width / 2;
                            const y = rect.top + rect.height / 2;
                            
                            el.dispatchEvent(new MouseEvent('mousedown', {
                                bubbles: true,
                                clientX: x,
                                clientY: y
                            }));
                            
                            el.dispatchEvent(new MouseEvent('mouseup', {
                                bubbles: true,
                                clientX: x,
                                clientY: y
                            }));
                            
                            el.dispatchEvent(new MouseEvent('click', {
                                bubbles: true,
                                clientX: x,
                                clientY: y
                            }));
                            
                            return { success: true, method: "text-search" };
                        }
                    }
                    
                    // Debug: Log available cards
                    console.log("Available cards found:", allCards.length);
                    allCards.forEach((card, i) => {
                        console.log(`Card ${i + 1}:`, {
                            text: card.innerText?.substring(0, 50) || "No text",
                            className: card.className,
                            hasImg: !!card.querySelector("img")
                        });
                    });
                    
                    return { 
                        success: false, 
                        error: "Evolution not found",
                        cardsFound: allCards.length
                    };
                    
                } catch (error) {
                    return { 
                        success: false, 
                        error: error.message,
                        jsError: true
                    };
                }
            }
            """)
            
            if result.get("success"):
                print_and_notify(f"Evolution clicked via {result.get('method', 'unknown method')}", "SUCCESS")
                
                # Wait for page to respond
                page.wait_for_timeout(3000)
                
                # Verify we're on Evolution platform
                try:
                    # Check URL or page content
                    current_url = page.url
                    page_content = page.content().lower()
                    
                    if ("evolution" in current_url.lower() or 
                        "evo" in current_url.lower() or
                        "evolution" in page_content or
                        "evo" in page_content):
                        print_and_notify("Evolution platform confirmed", "SUCCESS")
                        return True
                    else:
                        # Check for game lobby
                        page.wait_for_selector(":has-text('Live Casino'), :has-text('Game Lobby')", timeout=10000)
                        print_and_notify("Evolution game lobby loaded", "SUCCESS")
                        return True
                        
                except Exception as verify_error:
                    print_and_notify(f"Platform verification failed: {str(verify_error)[:50]}", "WARNING")
                    # Continue anyway - might still be on correct page
                    return True
                    
            else:
                error_msg = result.get("error", "Unknown error")
                cards_found = result.get("cardsFound", 0)
                
                if attempt < max_retries - 1:
                    print_and_notify(f"Evolution not found. Attempt {attempt + 1} failed: {error_msg}. Cards found: {cards_found}", "WARNING")
                    
                    # Take screenshot for debugging on last retry
                    if attempt == max_retries - 2:
                        screenshot_path = f"debug_evolution_{get_filename_timestamp()}.png"
                        page.screenshot(path=screenshot_path, full_page=True)
                        print_and_notify(f"Saved screenshot: {screenshot_path}", "DEBUG", send_to_telegram=False)
                    
                    # Reload or go back
                    page.reload()
                    page.wait_for_timeout(3000)
                    continue
                else:
                    raise Exception(f"Evolution not found after {max_retries} attempts. {error_msg}")
                    
        except Exception as e:
            if attempt < max_retries - 1:
                print_and_notify(f"Attempt {attempt + 1} failed: {str(e)[:100]}", "WARNING")
                time.sleep(3)
                continue
            else:
                raise Exception(f"Failed to select Evolution: {str(e)}")

def step5_wait_evolution(page, timeout=90):
    print_and_notify("Waiting for Evolution platform to load...", "INFO")
    start = time.time()
    
    while time.time() - start < timeout:
        urls = page.evaluate("""
        () => {
            try {
                return performance.getEntriesByType('resource')
                    .map(e => e.name)
                    .filter(name => name.includes('launcher.php'));
            } catch (e) {
                return [];
            }
        }
        """)
        
        for u in urls:
            if "/script/php/launcher.php?token=" in u:
                elapsed = int(time.time() - start)
                print_and_notify(f"Evolution platform loaded in {elapsed}s", "SUCCESS")
                return True
        
        elapsed = int(time.time() - start)
        if elapsed % 10 == 0 and elapsed > 0:
            print_and_notify(f"Still waiting... ({elapsed}s)", "DEBUG", send_to_telegram=False)
        
        time.sleep(1)
    
    raise Exception("Evolution platform timeout - launcher.php not detected")

def step6_attach_ws(page):
    print_and_notify("Attaching WebSocket listener...", "INFO")
    
    def handle_ws(ws):
        ws_url = ws.url.split('?')[0] if '?' in ws.url else ws.url
        print_and_notify(f"WebSocket connected → {ws_url}", "SUCCESS")
        
        def on_frame(frame):
            global script_completed
            try:
                # Convert bytes to string for checking
                if isinstance(frame, bytes):
                    frame_str = frame.decode('utf-8', errors='ignore')
                else:
                    frame_str = str(frame)
                
                if not frame_str or len(frame_str) < 100:
                    return
                
                # Check if script should exit (already sent first file)
                global script_completed
                if script_completed:
                    return
                
                if "icefishing.spinHistory" in frame_str:
                    print_and_notify("🎣 Spin history data detected!", "SUCCESS")
                    
                    try:
                        # Try to parse as JSON
                        data = json.loads(frame_str)
                        
                        # Save to JSON file with IST timestamp
                        saved_file = spin_manager.save_spin_data(data)
                        
                        if saved_file:
                            # Extract summary for log
                            summary = extract_spin_summary(data)
                            print_and_notify(summary, "INFO")
                            
                            # Send file with rate limiting
                            spin_manager.send_to_telegram(saved_file, summary)
                            
                            # Set completion flag instead of sys.exit(0)
                            script_completed = True
                            print_and_notify("✅ First spin history sent - exiting script", "SUCCESS")
                            return  # Exit the frame handler
                        
                    except json.JSONDecodeError as e:
                        print_and_notify(f"JSON decode error: {str(e)[:100]}", "WARNING")
                    except Exception as e:
                        error_msg = f"Error processing spinHistory: {str(e)[:200]}"
                        print_and_notify(error_msg, "ERROR")
                        
            except Exception as e:
                error_msg = f"Error processing WebSocket frame: {str(e)[:200]}"
                print_and_notify(error_msg, "ERROR")
        
        ws.on("framereceived", on_frame)
    
    page.on("websocket", handle_ws)
    print_and_notify("WebSocket listener ready", "SUCCESS")

def step7_open_ice_fishing(page):
    print_and_notify("Loading Ice Fishing game...", "INFO")
    page.goto(ICE_URL, timeout=120000, wait_until="domcontentloaded")
    
    for i in range(1, 11):
        page.wait_for_timeout(2000)
        if i % 3 == 0:
            print_and_notify(f"Game loading... ({i*2}s)", "DEBUG", send_to_telegram=False)
    
    game_state = page.evaluate("""
    () => {
        return {
            url: window.location.href,
            title: document.title,
            gameLoaded: document.body.innerText.includes('Ice Fishing') || 
                       document.body.innerHTML.includes('icefishing')
        };
    }
    """)
    
    print_and_notify("Ice Fishing game loaded successfully", "SUCCESS")
    print_and_notify(f"URL: {game_state['url'][:50]}...", "DEBUG", send_to_telegram=False)
    print_and_notify("⏳ Waiting 10s for WebSocket handshake...", "INFO")
   

    


def extract_spin_summary(data):
    try:
        if isinstance(data, dict):
            spin_data = None
            
            if 'data' in data and 'spinHistory' in data['data']:
                spin_data = data['data']['spinHistory']
            elif 'spinHistory' in data:
                spin_data = data['spinHistory']
            elif 'history' in data:
                spin_data = data['history']
            
            if spin_data and isinstance(spin_data, list) and len(spin_data) > 0:
                latest = spin_data[0]
                summary = f"🎣 <b>Latest Spin Summary</b>\n"
                summary += f"━━━━━━━━━━━━━━━━━━━━\n"
                
                fields = [
                    ('💰 Bet', 'bet', 'stake', 'wager'),
                    ('🎁 Win', 'win', 'payout', 'winnings'),
                    ('🎣 Fish', 'fishCaught', 'fish', 'catch'),
                    ('⭐ Multiplier', 'multiplier', 'mult'),
                ]
                
                for display_name, *possible_keys in fields:
                    value = None
                    for key in possible_keys:
                        if key in latest:
                            value = latest[key]
                            break
                    
                    if value is not None:
                        summary += f"• <b>{display_name}:</b> {value}\n"
                
                if len(summary.split('\n')) <= 3:
                    summary += f"• <b>Data:</b> Full JSON saved\n"
                
                # Use IST time
                ist_timestamp = format_ist_time()
                summary += f"━━━━━━━━━━━━━━━━━━━━\n"
                summary += f"🕒 {ist_timestamp} IST"
                return summary
                
        return "📊 Spin data received (awaiting analysis)"
        
    except Exception as e:
        return f"📄 Data saved (parse error: {str(e)[:50]})"

def attach_context_ws(context):
    print_and_notify("🧠 Context WebSocket listener attached", "SUCCESS")

    def on_ws(ws):
        ws_url = ws.url.split("?")[0]

        # 🔥 WS URL log
        if "icefishing" in ws_url.lower():
            print_and_notify(f"🎯 ICEFISH WS CONNECTED → {ws_url}", "SUCCESS")
        else:
            print_and_notify(f"🌐 WS → {ws_url}", "DEBUG", send_to_telegram=False)

        def on_frame(frame):
            try:
                data = frame.decode("utf-8", "ignore") if isinstance(frame, bytes) else str(frame)
                if "icefishing.spinHistory" in data:
                    print_and_notify("🎣 [CTX] Spin history detected!", "SUCCESS")
            except:
                pass

        ws.on("framereceived", on_frame)

    context.on("websocket", on_ws)



# ================= MODIFIED MAIN EXECUTION =================
def main():
    # Use IST time for startup - send as batch
    startup_time = format_ist_time()
    
    # Send startup messages as a batch with delays
    startup_messages = [
        (f"🚀 <b>Ice Fishing Monitor Started</b>", "INFO", True),
        (f"• Start Time: {startup_time} IST", "INFO", True),
        (f"• Mode: Headless Browser", "INFO", True),
        (f"• Log Channel: @{LOG_CHAT_ID.replace('-100', '')}", "INFO", True),
        (f"• File Channel: @{FILE_CHAT_ID.replace('-100', '')}", "INFO", True),
    ]
    
    print_and_notify("━━━━━━━━━━━━━━━━━━━━", "INFO", False)
    send_batch_messages(startup_messages, delay=2)
    print_and_notify("━━━━━━━━━━━━━━━━━━━━", "INFO", False)
    
    try:
        with sync_playwright() as p:
            print_and_notify("Launching Chromium browser...", "INFO")
            
            browser = None
            for headless_attempt in [True]:
                try:
                    browser = p.chromium.launch(
    headless=headless_attempt,
    # proxy={
    #     "server": "socks5://64.227.131.240:1080"
    # },
    args=[
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-quic",
        "--disable-http3",
        "--disable-features=NetworkService",
        "--window-size=1920,1080",
        "--mute-audio",
        "--disable-web-security",
        "--allow-running-insecure-content"
    ],
    slow_mo=100)

                    break
                except:
                    if not headless_attempt:
                        raise
            
            if browser is None:
                raise Exception("Failed to launch browser in any mode")
            
            # Set timezone to Asia/Kolkata (IST) for browser context
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                locale='en-US',
                timezone_id='Asia/Kolkata',  # Changed to IST timezone
                ignore_https_errors=True
            )
            attach_context_ws(context)

            print_and_notify("🧠 Context WebSocket listener attached", "SUCCESS")


            page = context.new_page()
            page.set_default_timeout(90000)
            
            try:
                steps = [
    ("1. Login", step1_login),
    ("2. Close Popups", step2_close_popup),
    ("3. Open Casino", step3_click_casino),
    ("4. Select Evolution", step4_click_evolution),

    # 🔥 MOVE THIS UP
    ("6. Setup WebSocket", step6_attach_ws),

    ("5. Load Platform", step5_wait_evolution),
    ("7. Launch Game", step7_open_ice_fishing),]

                
                for step_name, step_func in steps:
                    print_and_notify(f"Starting {step_name}...", "INFO")
                    step_func(page)
                    print_and_notify(f"Completed {step_name}", "SUCCESS")
                    
                    # Add delay between steps to reduce Telegram messages
                    if step_name != "7. Launch Game":
                        time.sleep(3)  # Increased from 2 to 3 seconds
                
                # Send monitoring active message
                monitoring_msg = f"""
🎯 <b>MONITORING ACTIVE</b>
━━━━━━━━━━━━━━━━━━━━
• Listening for game data...
• WebSocket connection ready
• Spin history will be captured
• Timezone: IST (UTC+5:30)
• Rate limiting: Enabled
━━━━━━━━━━━━━━━━━━━━"""
                print_and_notify(monitoring_msg, "SUCCESS")
                
                # Script will exit automatically after first spin history is sent
                # Keep running until first spin history is captured
                while True:
                    time.sleep(1)  # Just keep the script alive until WebSocket captures data
                    
                    # Check if script should exit
                    global script_completed
                    if script_completed:
                        print_and_notify("🛑 Script completed successfully - exiting", "INFO")
                        return
                    
            except KeyboardInterrupt:
                print_and_notify("\n🛑 Monitor stopped by user", "INFO")
            except Exception as e:
                error_details = f"""
🔥 <b>EXECUTION ERROR</b>
━━━━━━━━━━━━━━━━━━━━
• Error: {str(e)[:200]}
• Time: {format_ist_time()} IST
━━━━━━━━━━━━━━━━━━━━"""
                print_and_notify(error_details, "ERROR")
                
            finally:
                print_and_notify("Cleaning up browser resources...", "INFO")
                spin_manager.cleanup()  # Cleanup JSON file
                try:
                    context.close()
                    if browser:
                        browser.close()
                except:
                    pass
                
    except Exception as e:
        print_and_notify(f"Failed to initialize browser: {e}", "ERROR")
        sys.exit(1)
    
    # Use IST time for shutdown
    shutdown_msg = f"""
🛑 <b>MONITOR STOPPED</b>
━━━━━━━━━━━━━━━━━━━━
• End Time: {format_ist_time()} IST
━━━━━━━━━━━━━━━━━━━━"""
    print_and_notify(shutdown_msg, "INFO")

if __name__ == "__main__":
    main()	
