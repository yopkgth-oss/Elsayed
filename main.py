#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Slot Bot - النسخة النهائية المدمجة
- farm_ads من القديم (شغالة)
- Recovery system من الجديد
- بدون سحب
"""

import os
import sys
import json
import time
import random
import re
import sqlite3
import threading
import logging
import asyncio
from datetime import datetime
from urllib.parse import urlparse, urlencode, urlunparse, parse_qs

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
from telegram.warnings import PTBUserWarning
import warnings

warnings.filterwarnings("ignore", category=PTBUserWarning)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ============================================================
# الإعدادات
# ============================================================
def load_config():
    config_file = "config.json"
    default_config = {
        "bot_token": "YOUR_BOT_TOKEN_HERE",
        "base_url": "https://slotfruits.com",
        "mail_tm_api": "https://api.mail.tm",
        "mail_tm_domain": "@uberip.com",
        "timeout": 30,
        "use_proxies": True,
        "session_based_proxy": True,
        "session_prefix": "acc",
        "database_file": "accounts.db",
        "items_per_page": 25,
        "notify_on_error": True,
        "register_timeout": 90
    }

    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            for key, value in default_config.items():
                if key not in config:
                    config[key] = value
            print("✅ تم تحميل الإعدادات")
            return config
        except Exception as e:
            print(f"❌ خطأ في config.json: {e}")
            return default_config
    else:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        print("✅ تم إنشاء config.json — عدّل التوكن")
        sys.exit(1)


CONFIG = load_config()

BOT_TOKEN = CONFIG.get("bot_token")
if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    print("❌ لم يتم تعيين BOT_TOKEN")
    sys.exit(1)

BASE_URL = CONFIG.get("base_url")
MAIL_TM_API = CONFIG.get("mail_tm_api")
MAIL_TM_DOMAIN = CONFIG.get("mail_tm_domain")
TO = CONFIG.get("timeout", 30)
USE_PROXIES = CONFIG.get("use_proxies", True)
SESSION_BASED_PROXY = CONFIG.get("session_based_proxy", True)
SESSION_PREFIX = CONFIG.get("session_prefix", "acc")
DATABASE_FILE = CONFIG.get("database_file", "accounts.db")
ITEMS_PER_PAGE = CONFIG.get("items_per_page", 25)
NOTIFY_ON_ERROR = CONFIG.get("notify_on_error", True)
REGISTER_TIMEOUT = CONFIG.get("register_timeout", 90)

API_URL = f"{BASE_URL}/api/v1"

FAKE_NUMBERS = {
    "2018", "2019", "2020", "2021", "2022", "2023",
    "2024", "2025", "2026", "2027", "2028", "2029", "2030",
    "1234", "0000", "1111", "2222", "3333", "4444",
    "5555", "6666", "7777", "8888", "9999"
}

bot_application = None
bot_chat_id = None
main_event_loop = None
is_shutting_down = False
pending_emails = {}

mail_lock = threading.Lock()
proxy_lock = threading.Lock()
ip_cache_lock = threading.Lock()
worker_lock = threading.Lock()

ip_cache = {}
proxy_failures = {}


def safe_notify(message):
    global main_event_loop
    if not NOTIFY_ON_ERROR:
        return
    if not bot_application or not main_event_loop:
        return
    chat_id = bot_manager.chat_id or bot_chat_id
    if not chat_id:
        return
    try:
        asyncio.run_coroutine_threadsafe(
            bot_application.bot.send_message(
                chat_id=chat_id, text=message, parse_mode="HTML"
            ),
            main_event_loop
        )
    except Exception as e:
        logger.error(f"فشل الإشعار: {e}")


# ============================================================
# قاعدة البيانات
# ============================================================
def init_database():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            token TEXT,
            user_id TEXT,
            balance REAL DEFAULT 0,
            credits INTEGER DEFAULT 0,
            total_earned REAL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_login TEXT,
            is_active INTEGER DEFAULT 1,
            proxy TEXT,
            spin_count INTEGER DEFAULT 0,
            proxy_index INTEGER DEFAULT 0,
            mail_ok INTEGER DEFAULT 0,
            account_type TEXT DEFAULT 'existing',
            last_error TEXT DEFAULT '',
            last_spin_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS spin_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            spin_number INTEGER NOT NULL,
            reward REAL DEFAULT 0,
            balance REAL DEFAULT 0,
            credits INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()
    logger.info("✅ تم تهيئة قاعدة البيانات")


def _row_to_account(row):
    if not row:
        return None
    columns = [
        'id', 'email', 'password', 'token', 'user_id', 'balance', 'credits',
        'total_earned', 'created_at', 'last_login', 'is_active', 'proxy',
        'spin_count', 'proxy_index', 'mail_ok', 'account_type',
        'last_error', 'last_spin_at'
    ]
    return dict(zip(columns, row))


def get_account_by_id(account_id):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        row = cursor.fetchone()
        conn.close()
        return _row_to_account(row)
    except Exception as e:
        logger.error(f"خطأ get_account_by_id: {e}")
        return None


def get_account_by_email(email):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE email = ?", (email,))
        row = cursor.fetchone()
        conn.close()
        return _row_to_account(row)
    except:
        return None


def get_all_accounts(active_only=False):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        query = "SELECT * FROM accounts"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY id ASC"
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        return [_row_to_account(row) for row in rows]
    except:
        return []


def add_account(email, password, token=None, user_id=None, balance=0,
                credits=0, proxy=None, proxy_index=0, mail_ok=0,
                account_type='existing'):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO accounts (email, password, token, user_id, balance, credits,
                                 created_at, proxy, proxy_index, mail_ok, account_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (email, password, token, user_id, balance, credits,
              datetime.now().isoformat(), proxy, proxy_index, mail_ok, account_type))
        conn.commit()
        account_id = cursor.lastrowid
        conn.close()
        return account_id
    except Exception as e:
        logger.error(f"خطأ في إضافة حساب: {e}")
        return None


def update_account(account_id, **kwargs):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [account_id]
        cursor.execute(f"UPDATE accounts SET {set_clause} WHERE id = ?", values)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"خطأ في تحديث الحساب: {e}")
        return False


def delete_account(account_id):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        cursor.execute("DELETE FROM spin_history WHERE account_id = ?", (account_id,))
        conn.commit()
        conn.close()
        return True
    except:
        return False


def add_spin(account_id, spin_number, reward, balance, credits):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO spin_history (account_id, spin_number, reward, balance, credits, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (account_id, spin_number, reward, balance, credits, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return True
    except:
        return False


# ============================================================
# البروكسيات
# ============================================================
def load_proxies(proxy_file="proxy.txt"):
    proxies = []
    if not os.path.exists(proxy_file):
        return proxies
    try:
        with open(proxy_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if not line.startswith("http://") and not line.startswith("https://") and not line.startswith("socks"):
                        line = f"http://{line}"
                    proxies.append(line)
    except Exception as e:
        logger.error(f"خطأ تحميل البروكسيات: {e}")
    return proxies


def save_proxies(proxies, proxy_file="proxy.txt"):
    try:
        with open(proxy_file, "w", encoding="utf-8") as f:
            f.write("# قائمة البروكسيات\n")
            for p in proxies:
                f.write(f"{p}\n")
        return True
    except Exception as e:
        logger.error(f"خطأ حفظ البروكسيات: {e}")
        return False


def is_session_proxy(proxy):
    if not proxy:
        return False
    proxy_lower = proxy.lower()
    return (
        "brd.superproxy.io" in proxy_lower or
        "brightdata" in proxy_lower or
        "luminati" in proxy_lower or
        "-session-" in proxy_lower
    )


def build_session_proxy(account_id, base_proxy, session_prefix="acc"):
    if not base_proxy:
        return None
    try:
        proxy_clean = base_proxy.strip()
        if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://"):
            proxy_clean = f"http://{proxy_clean}"

        parsed = urlparse(proxy_clean)
        if not parsed.username or not parsed.password:
            return proxy_clean

        username = parsed.username
        password = parsed.password
        hostname = parsed.hostname
        port = parsed.port

        if "-session-" in username:
            username = username.split("-session-")[0]

        new_username = f"{username}-session-{session_prefix}{account_id}"
        new_netloc = f"{new_username}:{password}@{hostname}:{port}"
        new_proxy = urlunparse((
            parsed.scheme or "http", new_netloc, parsed.path or "",
            parsed.params or "", parsed.query or "", parsed.fragment or ""
        ))
        return new_proxy
    except Exception as e:
        logger.error(f"خطأ build_session_proxy: {e}")
        return base_proxy


def get_ip(proxy, timeout=10):
    if not proxy:
        return "بدون بروكسي"

    session_proxy = is_session_proxy(proxy)

    if not session_proxy:
        with ip_cache_lock:
            if proxy in ip_cache:
                cached_time, cached_ip = ip_cache[proxy]
                if (time.time() - cached_time) < 300:
                    return cached_ip

    try:
        proxy_clean = proxy.strip()
        if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://"):
            proxy_clean = f"http://{proxy_clean}"

        response = requests.get(
            "https://api.ipify.org?format=json",
            proxies={"http": proxy_clean, "https": proxy_clean},
            timeout=timeout
        )
        if response.status_code == 200:
            ip = response.json().get("ip", "Unknown")
            if not session_proxy:
                with ip_cache_lock:
                    ip_cache[proxy] = (time.time(), ip)
            return ip
    except Exception as e:
        logger.debug(f"فشل جلب IP: {e}")
    return "Unknown"


def get_cached_ip(proxy, force_refresh=False):
    if not proxy:
        return "بدون بروكسي"
    session_proxy = is_session_proxy(proxy)
    max_age = 30 if session_proxy else 300
    with ip_cache_lock:
        if not force_refresh and proxy in ip_cache:
            cached_time, cached_ip = ip_cache[proxy]
            if (time.time() - cached_time) < max_age:
                return cached_ip
    ip = get_ip(proxy, timeout=15)
    with ip_cache_lock:
        ip_cache[proxy] = (time.time(), ip)
    return ip


def test_proxy_detailed(proxy):
    if not proxy:
        return {"status": "failed", "error": "لا يوجد بروكسي"}
    try:
        proxy_clean = proxy.strip()
        if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://"):
            proxy_clean = f"http://{proxy_clean}"
        start_time = time.time()
        response = requests.get(
            "https://api.ipify.org?format=json",
            proxies={"http": proxy_clean, "https": proxy_clean},
            timeout=15
        )
        response_time = time.time() - start_time
        if response.status_code == 200:
            ip = response.json().get("ip", "Unknown")
            return {"status": "working", "ip": ip, "speed": round(response_time, 2), "proxy": proxy}
    except:
        pass
    return {"status": "failed"}


def test_proxy(proxy):
    result = test_proxy_detailed(proxy)
    if result["status"] == "working":
        return result["ip"]
    return None


def mark_proxy_failed(proxy):
    with proxy_lock:
        if proxy:
            proxy_failures[proxy] = proxy_failures.get(proxy, 0) + 1
            if proxy_failures[proxy] >= 5:
                if not is_session_proxy(proxy):
                    proxies = load_proxies()
                    if proxy in proxies:
                        proxies.remove(proxy)
                        save_proxies(proxies)
                    if proxy in proxy_failures:
                        del proxy_failures[proxy]


def get_working_proxy(current_proxy=None):
    with proxy_lock:
        proxies = load_proxies()
        if not proxies:
            return None
        available = [p for p in proxies if p not in proxy_failures or proxy_failures[p] < 3]
        if not available:
            proxy_failures.clear()
            available = proxies
        if current_proxy and current_proxy in available:
            if test_proxy(current_proxy):
                return current_proxy
            else:
                mark_proxy_failed(current_proxy)
                if current_proxy in available:
                    available.remove(current_proxy)
                if not available:
                    proxy_failures.clear()
                    available = proxies
        return random.choice(available) if available else None


# ============================================================
# Mail.tm — للاستخدام المؤقت بس
# ============================================================
mail_monitors = {}
seen_messages = {}
registration_codes = {}


def safe_str(value):
    if value is None:
        return ""
    if isinstance(value, list):
        try:
            return " ".join(str(item) for item in value)
        except:
            return str(value)
    if isinstance(value, dict):
        try:
            return json.dumps(value)
        except:
            return str(value)
    return str(value)


def clean_html(raw_html):
    if not raw_html:
        return ""
    return re.sub('<.*?>', " ", safe_str(raw_html)).strip()


def get_mail_token(email, password):
    try:
        res = requests.post(f"{MAIL_TM_API}/token",
                            json={"address": email, "password": password}, timeout=15)
        if res.status_code == 200:
            return res.json().get("token")
        return None
    except:
        return None


def create_mail_account(email=None, password=None):
    if not email:
        import uuid
        email = f"{str(uuid.uuid4())[:8]}{MAIL_TM_DOMAIN}"
    if not password:
        import string
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    try:
        res = requests.post(f"{MAIL_TM_API}/accounts",
                            json={"address": email, "password": password}, timeout=15)
        if res.status_code == 201:
            return email, password, True
        return email, password, False
    except:
        return email, password, False


def ensure_mail_account(email, password):
    try:
        domains_res = requests.get(f"{MAIL_TM_API}/domains", timeout=15)
        if domains_res.status_code == 200:
            domains = domains_res.json().get("hydra:member", [])
            active = [d["domain"] for d in domains if d.get("isActive")]
            email_domain = email.split("@")[-1]
            if email_domain not in active:
                return False, None
    except:
        return False, None

    token = get_mail_token(email, password)
    if token:
        return True, token

    created_email, created_pass, success = create_mail_account(email, password)
    if not success:
        return False, None

    time.sleep(2)
    token = get_mail_token(email, password)
    if token:
        return True, token
    return False, None


def get_mail_messages(token, limit=10):
    try:
        res = requests.get(f"{MAIL_TM_API}/messages",
                           headers={"Authorization": f"Bearer {token}"},
                           params={"page": 1, "limit": limit}, timeout=15)
        if res.status_code == 200:
            return res.json().get("hydra:member", [])
        return None
    except:
        return None


def get_mail_message(token, message_id):
    try:
        res = requests.get(f"{MAIL_TM_API}/messages/{message_id}",
                           headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if res.status_code == 200:
            return res.json()
        return None
    except:
        return None


def extract_code_filtered(email_data):
    if not email_data:
        return None, None

    from_data = email_data.get("from", {})
    sender = from_data.get("address", "") if isinstance(from_data, dict) else ""
    sender = safe_str(sender).lower()

    subject = safe_str(email_data.get("subject", ""))
    subject_lower = subject.lower()

    body_text = safe_str(email_data.get("text", ""))
    body_html = safe_str(email_data.get("html", ""))
    full_text = body_text if body_text.strip() else clean_html(body_html)

    if "faucetpay" in sender or "faucetpay" in subject_lower:
        return None, "faucetpay"

    is_verification = (
        "email verification" in subject_lower or
        "verify your email" in subject_lower or
        "confirm your email" in subject_lower or
        "verification code" in subject_lower or
        "email confirm" in subject_lower
    )
    is_2fa = "2fa" in subject_lower or "authorization" in subject_lower or "two factor" in subject_lower
    is_login = "login notification" in subject_lower or "new login" in subject_lower or "sign-in" in subject_lower

    if is_2fa:
        return None, "2fa"
    if is_login:
        return None, "login"
    if not is_verification:
        return None, "unknown"

    patterns = [
        r"verification\s+code\s*[:\-]\s*([0-9]{4,10})",
        r"code\s*[:\-]\s*([0-9]{4,10})",
        r"رمز\s+التحقق\s*[:\-]\s*([0-9]{4,10})",
        r"كود\s+التأكيد\s*[:\-]\s*([0-9]{4,10})",
        r"\b([0-9]{6})\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, full_text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            code = match.group(1)
            if code in FAKE_NUMBERS:
                continue
            if 4 <= len(code) <= 10 and code.isdigit():
                return code, "verification"
    return None, None


def start_mail_monitor(email, password):
    with mail_lock:
        if email in mail_monitors and mail_monitors[email].get("running", False):
            return True

        success, token = ensure_mail_account(email, password)
        if not success:
            return False

        if email not in seen_messages:
            seen_messages[email] = set()

        mail_monitors[email] = {
            "token": token, "running": True,
            "email": email, "password": password,
            "consecutive_fails": 0,
        }

    def monitor_loop():
        consecutive_fails = 0
        poll_interval = 10
        max_fails = 3

        while mail_monitors.get(email, {}).get("running", False):
            try:
                with mail_lock:
                    if email not in mail_monitors:
                        break
                    token = mail_monitors[email]["token"]

                messages = get_mail_messages(token, limit=10)

                if messages is None:
                    consecutive_fails += 1
                    if consecutive_fails >= max_fails:
                        with mail_lock:
                            if email in mail_monitors:
                                success, new_token = ensure_mail_account(
                                    email, mail_monitors[email]["password"]
                                )
                                if success:
                                    mail_monitors[email]["token"] = new_token
                                    consecutive_fails = 0
                                    continue
                        logger.warning(f"⏹️ إيقاف mail monitor لـ {email}")
                        with mail_lock:
                            if email in mail_monitors:
                                mail_monitors[email]["running"] = False
                        break
                    time.sleep(poll_interval)
                    continue

                consecutive_fails = 0

                for msg in messages:
                    msg_id = msg.get("id")
                    if msg_id not in seen_messages[email]:
                        subject = safe_str(msg.get("subject", ""))
                        from_addr = msg.get("from", {})
                        if isinstance(from_addr, dict):
                            from_addr = from_addr.get("address", "")
                        from_addr = safe_str(from_addr)
                        subject_lower = subject.lower()
                        from_lower = from_addr.lower()

                        if "faucetpay" in from_lower or "faucetpay" in subject_lower:
                            seen_messages[email].add(msg_id)
                            continue

                        if not ("slotfruits" in from_lower or "slotfruits" in subject_lower):
                            seen_messages[email].add(msg_id)
                            continue

                        seen_messages[email].add(msg_id)

                        detail = get_mail_message(token, msg_id)
                        if detail:
                            code_reg, msg_type = extract_code_filtered(detail)
                            if code_reg and msg_type == "verification":
                                with mail_lock:
                                    if email not in registration_codes:
                                        registration_codes[email] = []
                                    registration_codes[email].append({
                                        "code": code_reg, "type": msg_type,
                                        "subject": subject[:60], "timestamp": time.time(),
                                    })
                                    if len(registration_codes[email]) > 3:
                                        registration_codes[email] = registration_codes[email][-3:]
                                logger.info(f"✅ كود مخزن: {code_reg}")

                time.sleep(poll_interval)

            except Exception as e:
                logger.debug(f"mail_monitor خطأ {email}: {str(e)[:80]}")
                consecutive_fails += 1
                time.sleep(poll_interval)

    thread = threading.Thread(target=monitor_loop, daemon=True, name=f"mail-{email[:10]}")
    thread.start()
    mail_monitors[email]["thread"] = thread
    return True


def stop_mail_monitor(email):
    with mail_lock:
        if email in mail_monitors:
            mail_monitors[email]["running"] = False


def wait_for_code_registration(email, password, timeout=None):
    if timeout is None:
        timeout = REGISTER_TIMEOUT

    if email not in mail_monitors or not mail_monitors[email].get("running", False):
        if not start_mail_monitor(email, password):
            return None

    start_time = time.time()

    while time.time() - start_time < timeout:
        with mail_lock:
            if email in registration_codes and registration_codes[email]:
                for i, code_data in enumerate(registration_codes[email]):
                    if code_data.get("type") == "verification":
                        code = code_data["code"]
                        registration_codes[email].pop(i)
                        return code

        time.sleep(2)

    return None


# ============================================================
# SlotFruits API — safe_request البسيط (زي القديم)
# ============================================================
def safe_request(method, url, **kw):
    """الطلب البسيط — 3 محاولات بدون تعقيد"""
    kw.setdefault("timeout", TO)
    for attempt in range(3):
        try:
            response = requests.request(method, url, **kw)
            if response.status_code < 500:
                return response
            time.sleep(1)
        except Exception as e:
            logger.debug(f"Request attempt {attempt+1} failed: {e}")
            time.sleep(0.5)
    return None


def do_register(email, password, proxy=None):
    try:
        url = f"{API_URL}/users/registerFaucetPay"
        payload = {"email": email, "password": password}
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }
        kw = {"headers": headers, "data": json.dumps(payload)}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}

        res = safe_request("POST", url, **kw)
        if not res:
            return False, "لا يوجد استجابة"

        data = res.json()
        if data.get("success") or data.get("needsConfirmation") == True:
            return True, "تم التسجيل"
        return False, data.get("message", "فشل التسجيل")
    except Exception as e:
        return False, str(e)


def do_login(email, password, proxy=None):
    try:
        url = f"{API_URL}/users/signupFaucetPayLogin"
        payload = {"email": email, "password": password}
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }
        kw = {"headers": headers, "data": json.dumps(payload)}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}

        res = safe_request("POST", url, **kw)
        if not res:
            return None, None, 0, 0, "لا يوجد استجابة"

        data = res.json()
        user = data.get("user")
        if not user:
            return None, None, 0, 0, "فشل تسجيل الدخول"

        return (data.get("token"), user.get("_id"),
                user.get("balance", 0), user.get("credits", 0), "نجاح")
    except Exception as e:
        return None, None, 0, 0, str(e)


def check_account_exists_in_slotfruits(email, password, proxy=None):
    try:
        url = f"{API_URL}/users/signupFaucetPayLogin"
        payload = {"email": email, "password": password}
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }
        kw = {"headers": headers, "data": json.dumps(payload)}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}

        res = safe_request("POST", url, **kw)
        if not res:
            return {"exists": False, "error": "البروكسي مش شغال"}

        try:
            data = res.json()
        except:
            return {"exists": False, "error": "رد غير صالح"}

        user = data.get("user")
        token = data.get("token")

        if user and token:
            return {
                "exists": True, "token": token,
                "user_id": user.get("_id"),
                "balance": user.get("balance", 0),
                "credits": user.get("credits", 0),
                "message": "الحساب موجود"
            }

        if data.get("needsConfirmation") == True:
            return {"exists": False, "needs_confirmation": True, "email": email}

        msg = data.get("msg", "") or data.get("message", "") or ""
        msg_lower = msg.lower()
        not_found_keywords = [
            "not found", "not exist", "does not exist",
            "invalid credentials", "incorrect password",
            "user not", "no user", "account not", "register"
        ]
        if any(kw in msg_lower for kw in not_found_keywords):
            return {"exists": False, "not_found": True, "message": msg}

        return {"exists": False, "not_found": True, "message": msg or "حساب جديد"}
    except Exception as e:
        return {"exists": False, "error": str(e)}


def do_confirm(email, code, proxy=None):
    try:
        url = f"{API_URL}/users/confirmFaucetPay"
        payload = {"email": email, "code": code}
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }
        kw = {"headers": headers, "data": json.dumps(payload)}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}

        res = safe_request("POST", url, **kw)
        if not res:
            return False, None, "لا يوجد استجابة"

        data = res.json()
        if data.get("token") or data.get("user") or data.get("success"):
            return True, data.get("token"), "تم التأكيد"
        return False, None, data.get("message", "فشل التأكيد")
    except Exception as e:
        return False, None, str(e)


def get_user_info(token, proxy=None):
    try:
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {token}"
        }
        kw = {"headers": headers}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}

        res = safe_request("GET", f"{API_URL}/users/me", **kw)
        if res and res.status_code == 200:
            return res.json().get("user", {})
        return None
    except:
        return None


# ============================================================
# spin_once — من القديم (lowercase authorization + gzip)
# ============================================================
def spin_once(token, proxy=None):
    try:
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip",
            "authorization": f"Bearer {token}",   # ✅ lowercase زي القديم
        }
        kw = {"headers": headers}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}

        r = safe_request("GET", f"{API_URL}/users/earnRoll", **kw)
        if not r or r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None
    except:
        return None


# ============================================================
# farm_ads — من القديم (headers كاملة)
# ============================================================
def farm_ads(userid, proxy=None):
    FARM_ADS_URL = (
        "https://googleads.g.doubleclick.net/mads/gma?submodel=SM-A217F&adid_p=1&format=interstitial_mb"
        "&ini_pn=com.google.android.packageinstaller&ins_pn=com.google.android.packageinstaller"
        "&omid_v=a.1.5.2-google_20241009&dv=254380203&ev=24.6.0&gl=ID&hl=in"
        "&js=afma-sdk-a-v254380999.253410000.1&kw=clothing%2Cfashion&lv=253410000"
        "&ms=CqgFmsA_ATEaQQHY5dWIJ1nnZI0TXJOCrRjxy3oie3ZsfYBDue5jJF2CTFQQuf7W9C9KnP8xbLx0FI_PC-5wIrw0itcrK2KvDP4iEt0E6Yp1pn72NO8vWhbzh19JnXz5v7gGWsohjScUvkVohNO_jbecHUPYSmqy4T-WuJZ2EFv8_r-2HeMQg4ZPiq_jwKyeOrQjsiRXsU8vcZpKSMI0Z7Pn6iha94ABhZW_FbLysDgYt2ox4f_FIffLSbr_vjYntwKQpTg44MpacMRJ2_Ch0aplBuEzXYGkOTHBpg58oZtEw_3nZ8wsO9jE5lLVvx_cmKmOEpfemdesE_wTXvV0Hv5MWrZQ2I4ulXfQrY_gKRBI5ivJJLh3XYIzgBBRhoZastP7yEVFBT7Y8iunIsK3VrABvtw9RWUDkE2lETA0ezNEzwFoAhoGTGHuS2JaZ68x68KZGPFPR1CX4CXbMf1DDtzECiUr12lOsiuPUQ2WWtrjma3PKtkBk-0B5HoTVviRRPOHqgth3x80sbtwMn4G95El7JP079-e_jUT0oa75oJQC-Ph3zmllppvqq3dJN_RCGbyELdXc042fsR1fi3Syd6w1SJROO_t2sP3o2Bdzn2_jv1aokWO8NAzbtrWUs64BUiv1-XMv3k6CReZ91Ac9T28vbfulD8b_t8WSPrIHmXCGEC4h50U74SHhRxUcOmlR7sWpB2y8WfC7NlfoGCG5r6vXzVpG1oFOvTYscbEq1GPl1SjpnwS00RVM5_wfwa6GKc53oRubkV-CBhU_KMXUN115FELhAaNab2qn8reOKeN6xdg_OkZjGgHml1GIlVQity3vBcbzP2yE898LCwcwXVc9oLcH_WHL1eb7K19Zf6kpquk35qGtTP3xrSzDcw6t-GAxGg1lTCxlMgBA"
        "&mv=84923430.com.android.vending&lft=1&vnm=1.1.6&plbs=0&plcs=0&u_sd=1.75&request_id=1267448703"
        "&target_api=35&carrier=51011&request_agent=rn-invertase-15.8.0&seq_num=2"
        "&eid=318500618,318486317,318491267,318503826,318509511,318509849,318515546,318518927,318527162"
        "&sdk_apis=7%2C8&omid_p=Google%2Fafma-sdk-a-v260480999.253410000.1&cap=m&u_w=412&u_h=828"
        "&msid=com.piratebaixe.slotMobile&an=17.android.com.spincoin.appmobile.top&u_audio=3&net=ed&u_so=p"
        "&rbv=1&loeid=44766145%2C318502926&preqs_in_session=1&preqs=1&time_in_session=70&pcc=0"
        "&sst=1766181420000&output=html&region=mobile_app&u_tz=420&client=ca-app-pub-5674874137587223"
        "&slotname=7114498212&kw_type=broad&gsb=4g&lite=0&app_wp_code=ca-app-pub-5674874137587223"
        "&app_code=5186053460&num_ads=1&vpt=8&vfmt=18&vst=0&sdkv=o.254380999.253410000.1&sdmax=0&dmax=1"
        "&sdki=3c4d&stbg=1&bisch=true&blev=0.16&canm=true&_mv=84923430.com.android.vending"
        "&heap_free=35837248&heap_max=268435456&heap_total=67108864&wv_count=0&rdps=5500"
        "&caps=inlineVideo_interactiveVideo_mraid1_mraid2_mraid3_sdkVideo_exo3_th_autoplay_mediation_scroll_av_transparentBackground_sdkAdmobApiForAds_di_aso_sfv_dinm_dim_nav_navc_dinmo_ipdof_gls_gcache_saiMacro_sai_demuxedGcache_xSeconds"
        "&is_lat=false&blob=ABPQqLFPLHz2k6c8n6CqX1sW26j7BjCjFG5-MaUl0CxgLB41Sc1B8kpJWaikL2C_Gp9pl25Xd46LPjDMkuzcNeNk1dvygLdxMwK-Y6rlwJbBvC5njmNuysN-8h288vPObPEuoucf6F2FyhorQbQv9YbRKuFGXNMnm3mLs9x1FneK3ofa6gCK_UTEhPBLeTogM4C8tHMwO2a7T816OsKSD0JYRvo61pYUj8Rx-RsJMnAhHhTzRs3ktQdg-BbwRWiEaPEswxrDeM_GpknK8GoDLzwQ_wuTxQDlAIhl0WIPz9VciYotTXJ86Pe3mMuMwqNeQhZ_qFNQWL_Rncwnb9idfxUEGM5ucxxK_zjofg8F"
    )

    # ✅ headers كاملة زي القديم
    FARM_ADS_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 12; SM-A217F Build/SP1A.210812.016; wv) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/147.0.7727.111 "
            "Mobile Safari/537.36 (Mobile; afma-sdk-a-v260480999.253410000.1)"
        ),
        "sec-ch-ua-platform": '"Android"',
        "sec-ch-ua": '"Android WebView";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
        "sec-ch-ua-mobile": "?1",
        "x-requested-with": "com.piratebaixe.slotMobile",
    }

    hit = False
    for _ in range(1):
        kw = {"headers": FARM_ADS_HEADERS}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}

        resp = safe_request("GET", FARM_ADS_URL, **kw)
        if not resp:
            continue
        try:
            nets = resp.json().get("ad_networks", [])
            for net in nets:
                for vid in net.get("video_reward_urls", []):
                    p = urlparse(vid)
                    qs = parse_qs(p.query, keep_blank_values=True)
                    qs["rwd_userid"] = [str(userid)]
                    new = p._replace(query=urlencode(qs, doseq=True))
                    kw2 = {"headers": FARM_ADS_HEADERS}
                    if proxy:
                        proxy_clean = proxy.strip()
                        if not proxy_clean.startswith("http://"):
                            proxy_clean = f"http://{proxy_clean}"
                        kw2["proxies"] = {"http": proxy_clean, "https": proxy_clean}
                    safe_request("GET", urlunparse(new), **kw2)
                    hit = True
        except Exception:
            pass
        time.sleep(0.3)
    return hit
    # ============================================================
# AccountWorker — مع Recovery + farm_ads القديمة
# ============================================================
class AccountWorker:
    def __init__(self, email, password, proxy=None, index=0, account_id=None):
        self.email = email
        self.password = password
        self.index = index
        self.raw_proxy = proxy
        self.proxy = proxy
        self.account_id = account_id

        self.token = None
        self.user_id = None
        self.balance = 0
        self.credits = 0
        self.total_earned = 0
        self.spin_count = 0
        self.fail_count = 0
        self.max_fails = 5

        self.running = False
        self.stopped = False
        self.stop_event = threading.Event()
        self.current_ip = "جاري الجلب..."
        self.mail_ok = False
        self.last_error = ""

        self.account = get_account_by_id(account_id) if account_id else None
        if self.account:
            self.balance = self.account.get('balance', 0)
            self.credits = self.account.get('credits', 0)
            self.total_earned = self.account.get('total_earned', 0)
            self.token = self.account.get('token')
            self.user_id = self.account.get('user_id')
            self.spin_count = self.account.get('spin_count', 0)
            self.mail_ok = bool(self.account.get('mail_ok', 0))
            if not self.proxy:
                self.proxy = self.account.get('proxy')
                self.raw_proxy = self.proxy

        self.setup_proxy()

    def setup_proxy(self):
        if not USE_PROXIES:
            return

        if not self.raw_proxy and USE_PROXIES:
            proxies = load_proxies()
            if proxies:
                base_proxy = proxies[0]
                if SESSION_BASED_PROXY and is_session_proxy(base_proxy):
                    acc_id = self.account_id or self.index
                    self.raw_proxy = build_session_proxy(acc_id, base_proxy, SESSION_PREFIX)
                else:
                    self.raw_proxy = proxies[self.index % len(proxies)]

        if self.raw_proxy and SESSION_BASED_PROXY and is_session_proxy(self.raw_proxy):
            if "-session-" not in self.raw_proxy:
                acc_id = self.account_id or self.index
                self.raw_proxy = build_session_proxy(acc_id, self.raw_proxy, SESSION_PREFIX)

        self.proxy = self.raw_proxy

        if self.proxy:
            logger.info(f"🌐 بروكسي {self.email}: {self.proxy[:60]}...")
        else:
            logger.error(f"❌ {self.email}: لا يوجد بروكسي!")

    def change_proxy(self):
        if not USE_PROXIES:
            return False

        if SESSION_BASED_PROXY and self.raw_proxy and is_session_proxy(self.raw_proxy):
            proxies = load_proxies()
            if proxies:
                base_proxy = proxies[0]
                new_session_id = random.randint(1000000, 9999999)
                new_proxy = build_session_proxy(new_session_id, base_proxy, SESSION_PREFIX)
                self.proxy = new_proxy
                self.raw_proxy = new_proxy
                logger.info(f"🔄 session جديدة لـ {self.email}")
                return True
            return False

        new_proxy = get_working_proxy(self.proxy)
        if new_proxy and new_proxy != self.proxy:
            self.proxy = new_proxy
            self.raw_proxy = new_proxy
            if self.account_id:
                update_account(self.account_id, proxy=new_proxy)
            return True
        return False

    def init_network(self):
        self.setup_proxy()

        if not self.proxy:
            self.current_ip = "بدون بروكسي"
            return

        self.current_ip = get_ip(self.proxy, timeout=15)

        retry = 0
        while self.current_ip == "Unknown" and retry < 5:
            if self.stop_event.wait(2):
                return
            if self.change_proxy():
                self.current_ip = get_ip(self.proxy, timeout=15)
            retry += 1

        if self.current_ip == "Unknown":
            self.current_ip = "فشل البروكسي"
        else:
            logger.info(f"✅ IP {self.email}: {self.current_ip}")

    def _save_session(self, token, user_id, balance, credits):
        self.token = token
        self.user_id = user_id
        self.balance = balance
        self.credits = credits
        self.last_error = ""

        if self.account_id:
            update_account(
                self.account_id,
                token=token, user_id=user_id,
                balance=balance, credits=credits,
                last_login=datetime.now().isoformat(),
                last_error=""
            )

    def _try_register(self):
        """محاولة تسجيل جديدة بعد ما التوكن فشل"""
        logger.info(f"🆕 محاولة تسجيل {self.email}")

        mail_ok, _ = ensure_mail_account(self.email, self.password)
        if not mail_ok:
            logger.warning(f"⚠️ البريد مش شغال لـ {self.email}")
            return False

        if not start_mail_monitor(self.email, self.password):
            logger.warning(f"⚠️ mail monitor فشل لـ {self.email}")
            return False

        success, msg = do_register(self.email, self.password, self.proxy)
        if not success:
            logger.warning(f"⚠️ فشل التسجيل: {msg}")
            stop_mail_monitor(self.email)
            return False

        code = wait_for_code_registration(self.email, self.password, timeout=REGISTER_TIMEOUT)
        if not code:
            logger.warning(f"⏰ مفيش كود لـ {self.email}")
            stop_mail_monitor(self.email)
            return False

        success, token, msg = do_confirm(self.email, code, self.proxy)
        if not success:
            logger.warning(f"⚠️ فشل التأكيد: {msg}")
            stop_mail_monitor(self.email)
            return False

        user_info = get_user_info(token, self.proxy)
        if user_info:
            self._save_session(
                token,
                user_info.get("_id"),
                user_info.get("balance", 0),
                user_info.get("credits", 0)
            )
            if self.account_id:
                update_account(self.account_id, mail_ok=1)

            stop_mail_monitor(self.email)
            logger.info(f"✅ تم تسجيل {self.email}")
            return True

        stop_mail_monitor(self.email)
        return False

    def login(self, skip_register=False):
        """
        skip_register=True → مايحاولش تسجيل (للحسابات المؤكدة)
        skip_register=False → يحاول تسجيل لو فشل
        """
        for attempt in range(3):
            if self.stop_event.is_set():
                return False

            try:
                token, user_id, balance, credits, msg = do_login(
                    self.email, self.password, self.proxy
                )

                if token:
                    self._save_session(token, user_id, balance, credits)
                    logger.info(f"✅ login: {self.email}")
                    return True

                logger.warning(f"⚠️ login محاولة {attempt+1}/3 لـ {self.email}: {msg}")

                if skip_register:
                    time.sleep(2)
                    continue

                if attempt == 0:
                    if self._try_register():
                        return True

                if USE_PROXIES and attempt < 2:
                    self.change_proxy()

                if self.stop_event.wait(2):
                    return False

            except Exception as e:
                self.last_error = str(e)[:100]
                logger.error(f"❌ login exception {self.email}: {e}")
                if self.stop_event.wait(2):
                    return False

        if self.account_id:
            update_account(self.account_id, last_error=self.last_error or "فشل تسجيل الدخول")
        return False

    def _do_spin(self):
        """ترجع (result, error_type)"""
        try:
            if self.credits <= 0:
                # ⚡ نستخدم farm_ads القديمة
                farm_ads(self.user_id, self.proxy)
                # ✅ انتظار قصير زي القديم (0.5s)
                time.sleep(0.5)

                user_info = get_user_info(self.token, self.proxy)
                if user_info:
                    self.credits = user_info.get('credits', 0)
                    self.balance = user_info.get('balance', self.balance)

            if self.credits <= 0:
                return None, 'no_credits'

            data = spin_once(self.token, self.proxy)

            if data:
                return data, None

            return None, 'server'

        except Exception as e:
            logger.error(f"❌ _do_spin: {e}")
            return None, 'unknown'

    def spin(self):
        try:
            data, error = self._do_spin()

            if data:
                # ✅ نجح
                reward = data.get("total", 0) or 0
                user = data.get("user", {})
                self.balance = user.get("balance", self.balance)
                self.credits = user.get("credits", 0)

                if reward > 0:
                    self.total_earned += reward
                    self.spin_count += 1

                    if self.account_id:
                        add_spin(self.account_id, self.spin_count, reward,
                                 self.balance, self.credits)
                        update_account(
                            self.account_id,
                            spin_count=self.spin_count,
                            balance=self.balance,
                            credits=self.credits,
                            total_earned=self.total_earned,
                            last_spin_at=datetime.now().isoformat(),
                            last_error=""
                        )

                self.fail_count = 0
                return data

            # ❌ فشل
            if error == 'auth':
                logger.warning(f"🔑 التوكن انتهى لـ {self.email}")
                if self.login(skip_register=False):
                    return self.spin()

            elif error == 'network':
                logger.warning(f"🌐 مشكلة نت لـ {self.email}")
                if self.change_proxy():
                    if self.login(skip_register=True):
                        return self.spin()

            elif error == 'no_credits':
                # مش خطأ حقيقي — محاولة تانية بعد وقت قصير
                pass

            self.fail_count += 1
            return None

        except Exception as e:
            logger.error(f"❌ خطأ في spin {self.email}: {e}")
            self.fail_count += 1
            return None

    def run(self):
        self.running = True
        self.stop_event.clear()

        self.init_network()

        if self.stop_event.is_set():
            self.running = False
            return

        if not self.login(skip_register=False):
            logger.error(f"❌ {self.email}: فشل login")
            if self.account_id:
                update_account(self.account_id, is_active=0)
            self.running = False
            return

        consecutive_errors = 0

        while self.running and not is_shutting_down and not self.stop_event.is_set():
            try:
                # ✅ 10 سبنات في الحلقة (زي القديم)
                for spin_num in range(1, 11):
                    if not self.running or is_shutting_down or self.stop_event.is_set():
                        return

                    result = self.spin()

                    if result is None:
                        consecutive_errors += 1
                        self.last_error = f"فشل #{consecutive_errors}"

                        # ⚠️ 5 أخطاء → جلسة جديدة
                        if consecutive_errors == 5:
                            logger.warning(f"🔄 5 أخطاء — جلسة جديدة لـ {self.email}")
                            if self.login(skip_register=True):
                                consecutive_errors = 0

                        # ⚠️ 10 أخطاء → بروكسي جديد + جلسة
                        elif consecutive_errors == 10:
                            logger.warning(f"🔄 10 أخطاء — بروكسي جديد لـ {self.email}")
                            self.change_proxy()
                            if self.login(skip_register=True):
                                consecutive_errors = 0

                        # ⚠️ 20 خطأ → استنى 10 دقايق
                        elif consecutive_errors >= 20:
                            logger.error(f"💤 20 خطأ — استنى 10 دقايق لـ {self.email}")
                            safe_notify(
                                f"⚠️ <b>الحساب واجه مشاكل</b>\n"
                                f"📧 {self.email}\n"
                                f"⏸️ استنى 10 دقايق"
                            )

                            if self.stop_event.wait(600):
                                return

                            self.change_proxy()
                            if self.login(skip_register=True):
                                consecutive_errors = 0
                            else:
                                logger.error(f"❌ {self.email}: فشل recovery")
                                safe_notify(
                                    f"❌ <b>الحساب اتوقف</b>\n"
                                    f"📧 {self.email}"
                                )
                                self.running = False
                                if self.account_id:
                                    update_account(self.account_id, is_active=0)
                                return
                    else:
                        consecutive_errors = 0

                    # ✅ انتظار قصير زي القديم (0.3-0.7s)
                    if self.stop_event.wait(random.uniform(0.3, 0.7)):
                        return

                # تحديث DB بعد كل 10 سبنات
                if self.account_id:
                    try:
                        update_account(
                            self.account_id,
                            balance=self.balance,
                            credits=self.credits,
                            total_earned=self.total_earned
                        )
                    except:
                        pass

                # ✅ انتظار قصير بين الدورات (زي القديم)
                if self.stop_event.wait(random.uniform(2.0, 5.0)):
                    return

            except Exception as e:
                logger.error(f"❌ خطأ في حلقة {self.email}: {e}")
                if self.stop_event.wait(5):
                    return

        self.running = False
        logger.info(f"⏹️ توقف {self.email}")


# ============================================================
# BotManager
# ============================================================
class BotManager:
    def __init__(self):
        self.workers = {}
        self.threads = {}
        self.running = False
        self.chat_id = None
        self.dashboard_page = 0
        self.delete_page = 0
        self.start_time = datetime.now()

    def start_account(self, account_id):
        with worker_lock:
            if account_id in self.workers:
                old = self.workers[account_id]
                if old.running and not old.stop_event.is_set():
                    logger.warning(f"⚠️ {account_id} شغال بالفعل")
                    return False
                old.running = False
                old.stop_event.set()
                if account_id in self.threads:
                    try:
                        self.threads[account_id].join(timeout=5)
                    except:
                        pass
                    self.threads.pop(account_id, None)
                self.workers.pop(account_id, None)

        account = get_account_by_id(account_id)
        if not account:
            return False

        proxies = load_proxies()
        proxy = None
        proxy_index = 0

        if USE_PROXIES and proxies:
            base_proxy = proxies[0]
            if SESSION_BASED_PROXY and is_session_proxy(base_proxy):
                proxy = build_session_proxy(account_id, base_proxy, SESSION_PREFIX)
                proxy_index = 0
            else:
                proxy_index = account_id % len(proxies)
                proxy = proxies[proxy_index]

        worker = AccountWorker(
            email=account['email'],
            password=account['password'],
            proxy=proxy,
            index=proxy_index,
            account_id=account_id
        )

        if proxy:
            update_account(account_id, proxy=proxy, proxy_index=proxy_index)

        with worker_lock:
            self.workers[account_id] = worker

        thread = threading.Thread(target=worker.run, daemon=True,
                                  name=f"worker-{account_id}")
        thread.start()

        with worker_lock:
            self.threads[account_id] = thread

        logger.info(f"✅ تم تشغيل {account['email']}")
        return True

    def stop_account(self, account_id):
        with worker_lock:
            if account_id not in self.workers:
                return False

            worker = self.workers[account_id]
            worker.running = False
            worker.stopped = True
            worker.stop_event.set()

            if account_id in self.threads:
                try:
                    self.threads[account_id].join(timeout=10)
                except:
                    pass
                self.threads.pop(account_id, None)

            self.workers.pop(account_id, None)

        logger.info(f"⏹️ تم إيقاف {account_id}")
        return True

    def start_all(self):
        accounts = get_all_accounts(active_only=True)
        started = 0
        for acc in accounts:
            if self.start_account(acc['id']):
                started += 1
                time.sleep(0.3)
        self.running = True
        return started

    def stop_all(self):
        account_ids = list(self.workers.keys())
        stopped = 0
        for acc_id in account_ids:
            if self.stop_account(acc_id):
                stopped += 1
        self.running = False
        return stopped

    def get_status(self):
        accounts = get_all_accounts()
        total = len(accounts)
        running = 0

        total_balance = 0
        total_spins = 0
        mail_ok_count = 0
        details = []

        for acc in accounts:
            balance = acc.get('balance', 0) or 0
            total_balance += balance
            total_spins += acc.get('spin_count', 0) or 0
            if acc.get('mail_ok', 0):
                mail_ok_count += 1

            with worker_lock:
                worker = self.workers.get(acc['id'])

            mail_ok = bool(acc.get('mail_ok', 0))

            if worker and worker.running and not worker.stop_event.is_set():
                status_icon = "🟢"
                running += 1
                current_ip = worker.current_ip
                balance = worker.balance
                credits = worker.credits
            elif worker:
                status_icon = "🟡"
                current_ip = worker.current_ip
                credits = worker.credits
            else:
                status_icon = "🔴"
                proxy = acc.get('proxy')
                current_ip = get_cached_ip(proxy) if proxy else "بدون"
                credits = acc.get('credits', 0)

            details.append({
                'id': acc['id'],
                'email': acc['email'],
                'status_icon': status_icon,
                'balance': balance,
                'credits': credits,
                'spins': acc.get('spin_count', 0) or 0,
                'ip': current_ip,
                'mail_ok': mail_ok,
                'last_error': acc.get('last_error', '') or '',
            })

        avg_balance = int(total_balance / total) if total > 0 else 0

        uptime = str(datetime.now() - self.start_time).split('.')[0]

        return {
            'total_accounts': total,
            'running_accounts': running,
            'total_balance': total_balance,
            'total_spins': total_spins,
            'mail_ok_count': mail_ok_count,
            'avg_balance': avg_balance,
            'uptime': uptime,
            'details': details
        }

    def dashboard_text(self, page=0):
        status = self.get_status()
        total_accounts = status['total_accounts']
        total_pages = max(1, ((total_accounts - 1) // ITEMS_PER_PAGE) + 1)

        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0

        start = page * ITEMS_PER_PAGE
        end = min(start + ITEMS_PER_PAGE, total_accounts)

        mail_ok_count = status['mail_ok_count']
        mail_bad_count = total_accounts - mail_ok_count
        stopped_count = total_accounts - status['running_accounts']

        text = (
            f"📊 <b>لوحة التحكم</b> — صفحة {page+1}/{total_pages}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"⏱️ وقت التشغيل: {status['uptime']}\n"
            f"📧 إجمالي: <b>{total_accounts}</b>  |  "
            f"🟢 نشط: <b>{status['running_accounts']}</b>  |  "
            f"🔴 متوقف: <b>{stopped_count}</b>\n"
            f"📬 بريد شغال: {mail_ok_count}  |  📭 مش شغال: {mail_bad_count}\n"
            f"💎 الرصيد الكلي: <b>{status['total_balance']:,.0f}</b>\n"
            f"⚡ إجمالي السبنات: <b>{status['total_spins']:,}</b>\n"
            f"📈 متوسط الرصيد: {status['avg_balance']:,}\n"
            f"━━━━━━━━━━━━━━━━━\n"
        )

        if status['details']:
            for detail in status['details'][start:end]:
                mail_icon = "📬" if detail['mail_ok'] else "📭"
                text += (
                    f"{detail['status_icon']} <b>#{detail['id']}</b> {mail_icon} | "
                    f"<code>{detail['email'][:22]}</code>\n"
                    f"   💰 {detail['balance']:,.0f} | "
                    f"🎯 {detail['credits']} | "
                    f"⚡ {detail['spins']:,} spin\n"
                )
                if detail['status_icon'] == "🔴" and detail['last_error']:
                    text += f"   ⚠️ {detail['last_error'][:45]}\n"
                else:
                    text += f"   🌐 <code>{detail['ip']}</code>\n"
        else:
            text += "⚠️ لا توجد حسابات"

        text += f"\n━━━━━━━━━━━━━━━━━\n🔄 {datetime.now().strftime('%H:%M:%S')}"
        return text, page, total_pages


bot_manager = BotManager()


# ============================================================
# إضافة حساب
# ============================================================
async def add_single_account(email, password, progress_msg=None, silent=False,
                             forced_proxy=None, forced_proxy_index=None):
    try:
        if silent:
            progress_msg = None

        if forced_proxy is not None:
            proxy = forced_proxy
            proxy_index = forced_proxy_index if forced_proxy_index is not None else 0
        else:
            proxies = load_proxies()
            proxy = None
            proxy_index = 0
            if USE_PROXIES and proxies:
                base_proxy = proxies[0]
                if SESSION_BASED_PROXY and is_session_proxy(base_proxy):
                    temp_id = int(time.time()) % 100000
                    proxy = build_session_proxy(temp_id, base_proxy, SESSION_PREFIX)
                    proxy_index = 0
                else:
                    account_count = len(get_all_accounts())
                    proxy_index = account_count % len(proxies)
                    proxy = proxies[proxy_index]

        if proxy:
            real_ip = get_ip(proxy, timeout=12)
            if real_ip == "Unknown":
                logger.error(f"❌ البروكسي مش شغال لـ {email}")
                if progress_msg and not silent:
                    try:
                        await progress_msg.edit_text(
                            f"❌ <b>البروكسي مش شغال!</b>\n📧 {email}",
                            parse_mode="HTML"
                        )
                    except:
                        pass
                return False

        if progress_msg and not silent:
            try:
                await progress_msg.edit_text(
                    f"🔍 <b>التحقق من الحساب...</b>\n📧 {email}",
                    parse_mode="HTML"
                )
            except:
                pass

        account_check = check_account_exists_in_slotfruits(email, password, proxy)
        logger.info(f"📊 {email}: {account_check}")

        # حالة 1: موجود
        if account_check.get("exists"):
            logger.info(f"✅ {email} موجود")
            existing = get_account_by_email(email)

            if existing:
                update_account(
                    existing['id'],
                    token=account_check.get("token"),
                    user_id=account_check.get("user_id"),
                    balance=account_check.get("balance", 0),
                    credits=account_check.get("credits", 0),
                    last_login=datetime.now().isoformat(),
                    is_active=1,
                    proxy=proxy,
                    proxy_index=proxy_index,
                    mail_ok=1,
                    account_type='existing',
                    last_error=""
                )
                account_id = existing['id']
                action = "تحديث"
            else:
                account_id = add_account(
                    email, password,
                    account_check.get("token"),
                    account_check.get("user_id"),
                    account_check.get("balance", 0),
                    account_check.get("credits", 0),
                    proxy, proxy_index,
                    mail_ok=1,
                    account_type='existing'
                )
                action = "إضافة"

            if account_id:
                bot_manager.start_account(account_id)
                if progress_msg and not silent:
                    try:
                        await progress_msg.edit_text(
                            f"✅ <b>تم {action}!</b>\n"
                            f"🆔 ID: {account_id}\n📧 {email}\n"
                            f"💰 {account_check.get('balance', 0):,.0f}",
                            parse_mode="HTML"
                        )
                    except:
                        pass
                return True

        # حالة 2: محتاج تأكيد
        if account_check.get("needs_confirmation"):
            logger.info(f"⚠️ {email} محتاج تأكيد")

            mail_ok, _ = ensure_mail_account(email, password)
            if not mail_ok:
                return False

            if not start_mail_monitor(email, password):
                return False

            do_register(email, password, proxy)
            code = wait_for_code_registration(email, password, timeout=REGISTER_TIMEOUT)

            if not code:
                stop_mail_monitor(email)
                logger.error(f"❌ مفيش كود لـ {email}")
                return False

            success, token, confirm_msg = do_confirm(email, code, proxy)
            if not success:
                stop_mail_monitor(email)
                logger.error(f"❌ فشل التأكيد: {confirm_msg}")
                return False

            user_info = get_user_info(token, proxy)
            user_id_api = user_info.get("_id") if user_info else None
            balance = user_info.get("balance", 0) if user_info else 0
            credits = user_info.get("credits", 0) if user_info else 0

            existing = get_account_by_email(email)
            if existing:
                update_account(
                    existing['id'],
                    token=token, user_id=user_id_api,
                    balance=balance, credits=credits,
                    last_login=datetime.now().isoformat(),
                    is_active=1, proxy=proxy, proxy_index=proxy_index,
                    mail_ok=1, account_type='confirmed', last_error=""
                )
                account_id = existing['id']
            else:
                account_id = add_account(
                    email, password, token, user_id_api, balance, credits,
                    proxy, proxy_index, mail_ok=1, account_type='confirmed'
                )

            stop_mail_monitor(email)

            if account_id:
                bot_manager.start_account(account_id)
                if progress_msg and not silent:
                    try:
                        await progress_msg.edit_text(
                            f"✅ <b>تم التأكيد!</b>\n🆔 {account_id}\n📧 {email}",
                            parse_mode="HTML"
                        )
                    except:
                        pass
                return True
            return False

        # حالة 3: جديد
        if account_check.get("not_found"):
            logger.info(f"🆕 {email} جديد")

            mail_ok, _ = ensure_mail_account(email, password)
            if not mail_ok:
                return False

            if not start_mail_monitor(email, password):
                return False

            success, reg_msg = do_register(email, password, proxy)
            if not success:
                stop_mail_monitor(email)
                logger.error(f"❌ فشل التسجيل: {reg_msg}")
                return False

            code = wait_for_code_registration(email, password, timeout=REGISTER_TIMEOUT)
            if not code:
                stop_mail_monitor(email)
                logger.error(f"❌ مفيش كود لـ {email}")
                return False

            success, token, confirm_msg = do_confirm(email, code, proxy)
            if not success:
                stop_mail_monitor(email)
                logger.error(f"❌ فشل التأكيد: {confirm_msg}")
                return False

            user_info = get_user_info(token, proxy)
            user_id_api = user_info.get("_id") if user_info else None
            balance = user_info.get("balance", 0) if user_info else 0
            credits = user_info.get("credits", 0) if user_info else 0

            account_id = add_account(
                email, password, token, user_id_api, balance, credits,
                proxy, proxy_index, mail_ok=1, account_type='new'
            )

            stop_mail_monitor(email)

            if account_id:
                bot_manager.start_account(account_id)
                if progress_msg and not silent:
                    try:
                        await progress_msg.edit_text(
                            f"✅ <b>تم الإنشاء!</b>\n"
                            f"🆔 {account_id}\n📧 {email}\n"
                            f"💰 {balance:,.0f}",
                            parse_mode="HTML"
                        )
                    except:
                        pass
                return True
            return False

        error_msg = account_check.get("error") or account_check.get("message") or "غير معروف"
        if progress_msg and not silent:
            try:
                await progress_msg.edit_text(
                    f"❌ <b>خطأ</b>\n📧 {email}\n⚠️ {error_msg}",
                    parse_mode="HTML"
                )
            except:
                pass
        return False

    except Exception as e:
        logger.error(f"خطأ add_single_account: {e}")
        if progress_msg and not silent:
            try:
                await progress_msg.edit_text(f"❌ خطأ: {str(e)[:80]}")
            except:
                pass
        return False


# ============================================================
# الأزرار والواجهة
# ============================================================
def get_main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 تشغيل الكل", callback_data="start_all"),
            InlineKeyboardButton("⏹️ إيقاف الكل", callback_data="stop_all"),
        ],
        [InlineKeyboardButton("📊 لوحة التحكم", callback_data="dashboard_0")],
        [
            InlineKeyboardButton("➕ إضافة حساب", callback_data="add_account"),
            InlineKeyboardButton("➕➕ متعددة", callback_data="add_multiple_accounts"),
        ],
        [
            InlineKeyboardButton("🗑️ حذف حساب", callback_data="delete_account"),
            InlineKeyboardButton("🌐 البروكسيات", callback_data="proxies_menu"),
        ],
        [InlineKeyboardButton("🔄 تحديث الكل", callback_data="refresh_all")],
    ])


async def show_main_menu(update, context, chat_id):
    status = bot_manager.get_status()

    main_text = (
        f"🎰 <b>Slot Bot - لوحة التحكم</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"⏱️ وقت التشغيل: {status['uptime']}\n"
        f"📧 الحسابات: <b>{status['total_accounts']}</b>\n"
        f"🟢 النشطة: <b>{status['running_accounts']}</b>\n"
        f"💎 الرصيد الكلي: <b>{status['total_balance']:,.0f}</b>\n"
        f"⚡ إجمالي السبنات: <b>{status['total_spins']:,}</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"اختر الإجراء:"
    )

    if update and update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                main_text, reply_markup=get_main_keyboard(), parse_mode="HTML"
            )
        except:
            await context.bot.send_message(
                chat_id=chat_id, text=main_text,
                reply_markup=get_main_keyboard(), parse_mode="HTML"
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id, text=main_text,
            reply_markup=get_main_keyboard(), parse_mode="HTML"
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_chat_id, bot_application
    bot_chat_id = update.message.chat_id
    bot_application = context.application
    bot_manager.chat_id = update.message.chat_id
    await show_main_menu(None, context, update.message.chat_id)


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_manager.chat_id = update.message.chat_id
    text, page, total = bot_manager.dashboard_text(0)

    keyboard = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"dashboard_{page-1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"dashboard_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔄 تحديث", callback_data=f"dashboard_{page}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])

    await update.message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in pending_emails:
        del pending_emails[user_id]
    await update.message.reply_text("❌ تم إلغاء العملية!")


async def show_delete_accounts(update, context):
    query = update.callback_query
    accounts = get_all_accounts()

    if not accounts:
        await query.edit_message_text("📭 لا يوجد حسابات!")
        return

    total = len(accounts)
    per_page = ITEMS_PER_PAGE
    page = bot_manager.delete_page
    start = page * per_page
    end = min(start + per_page, total)

    if start >= total:
        bot_manager.delete_page = 0
        page = 0
        start = 0
        end = min(per_page, total)

    keyboard = []
    for i in range(start, end):
        acc = accounts[i]
        display = acc['email'][:35] + "..." if len(acc['email']) > 35 else acc['email']
        keyboard.append([InlineKeyboardButton(f"🗑️ {display}", callback_data=f"del_acc_{acc['id']}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data="del_prev"))
    if end < total:
        nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data="del_next"))
    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])

    total_pages = max(1, ((total - 1) // per_page) + 1)

    await query.edit_message_text(
        f"🗑️ <b>حذف الحسابات</b>\n"
        f"📧 إجمالي: {total}\n"
        f"📄 صفحة {page+1}/{total_pages}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_chat_id, bot_application

    query = update.callback_query
    await query.answer()

    bot_chat_id = query.message.chat_id
    bot_application = context.application
    bot_manager.chat_id = query.message.chat_id

    data = query.data
    user_id = query.from_user.id

    if data == "start_all":
        await query.edit_message_text("🚀 جاري التشغيل...")
        started = bot_manager.start_all()
        await query.edit_message_text(f"🚀 تم تشغيل {started} حساب")
        await asyncio.sleep(1)
        await show_main_menu(update, context, query.message.chat_id)

    elif data == "stop_all":
        await query.edit_message_text("⏹️ جاري الإيقاف...")
        stopped = bot_manager.stop_all()
        await query.edit_message_text(f"⏹️ تم إيقاف {stopped} حساب")
        await asyncio.sleep(1)
        await show_main_menu(update, context, query.message.chat_id)

    elif data == "refresh_all":
        await show_main_menu(update, context, query.message.chat_id)

    elif data.startswith("dashboard_"):
        try:
            page = int(data.split("_")[1])
        except:
            page = 0

        bot_manager.dashboard_page = page
        text, current_page, total_pages = bot_manager.dashboard_text(page)

        nav_buttons = []
        if current_page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"dashboard_{current_page - 1}"))
        if current_page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("التالي ➡️", callback_data=f"dashboard_{current_page + 1}"))

        keyboard = []
        if nav_buttons:
            keyboard.append(nav_buttons)
        keyboard.append([InlineKeyboardButton("🔄 تحديث", callback_data=f"dashboard_{current_page}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])

        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
        )

    elif data == "add_account":
        pending_emails[user_id] = "waiting_for_account"
        await query.edit_message_text(
            f"📝 <b>إضافة حساب</b>\n\nأرسل:\n<code>email password</code>\n\n🔙 /cancel للإلغاء",
            parse_mode="HTML"
        )

    elif data == "add_multiple_accounts":
        pending_emails[user_id] = "waiting_for_multiple_accounts"
        await query.edit_message_text(
            f"📝 <b>إضافة حسابات متعددة</b>\n\n"
            f"أرسل كل حساب في سطر:\n<code>email1 password1</code>\n<code>email2 password2</code>\n\n🔙 /cancel للإلغاء",
            parse_mode="HTML"
        )

    elif data == "delete_account":
        bot_manager.delete_page = 0
        await show_delete_accounts(update, context)

    elif data == "del_next":
        bot_manager.delete_page += 1
        await show_delete_accounts(update, context)

    elif data == "del_prev":
        if bot_manager.delete_page > 0:
            bot_manager.delete_page -= 1
        await show_delete_accounts(update, context)

    elif data.startswith("del_acc_"):
        account_id = int(data.split("_")[2])
        account = get_account_by_id(account_id)

        if account:
            if account_id in bot_manager.workers:
                bot_manager.stop_account(account_id)
            delete_account(account_id)
            await query.edit_message_text(f"✅ تم حذف: {account['email']}")
        else:
            await query.edit_message_text("❌ الحساب غير موجود")

        await asyncio.sleep(1)
        await show_delete_accounts(update, context)

    elif data == "proxies_menu":
        proxies = load_proxies()
        mode = "Session (Bright Data)" if (proxies and SESSION_BASED_PROXY and is_session_proxy(proxies[0])) else "عادي"
        keyboard = [
            [InlineKeyboardButton("📋 عرض البروكسيات", callback_data="view_proxies")],
            [InlineKeyboardButton("➕ إضافة بروكسيات", callback_data="add_proxies")],
            [InlineKeyboardButton("🧪 اختبار البروكسيات", callback_data="test_proxies")],
            [InlineKeyboardButton("🗑️ حذف بروكسي", callback_data="delete_proxy")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")],
        ]
        await query.edit_message_text(
            f"🌐 <b>البروكسيات</b>\n📊 {len(proxies)} بروكسي\n🔀 الوضع: {mode}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    elif data == "view_proxies":
        proxies = load_proxies()
        if not proxies:
            await query.edit_message_text("📭 لا يوجد بروكسيات!")
            return

        await query.edit_message_text(f"🔄 جاري جلب IP لـ {len(proxies)} بروكسي...")

        text = "🌐 <b>البروكسيات</b>\n━━━━━━━━━━━━━━━━━\n"
        for i, p in enumerate(proxies, 1):
            session_icon = "🔀" if is_session_proxy(p) else "🌐"
            ip = get_cached_ip(p)
            status = "✅" if ip and ip != "Unknown" else "❌"
            p_display = p[:70] + "..." if len(p) > 70 else p
            text += f"{i}. {status} {session_icon} <code>{p_display}</code>\n   🌐 {ip}\n\n"

        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "add_proxies":
        pending_emails[user_id] = "waiting_for_proxies"
        await query.edit_message_text(
            "📝 <b>إضافة بروكسيات</b>\n\nأرسل كل بروكسي في سطر:\n<code>http://user:pass@host:port</code>",
            parse_mode="HTML"
        )

    elif data == "test_proxies":
        proxies = load_proxies()
        if not proxies:
            await query.edit_message_text("📭 لا يوجد بروكسيات!")
            return

        await query.edit_message_text(f"🔄 جاري اختبار {len(proxies)} بروكسي...")

        text = "🧪 <b>نتيجة الاختبار</b>\n━━━━━━━━━━━━━━━━━\n"
        valid = 0
        invalid = 0
        valid_proxies = []

        for i, p in enumerate(proxies, 1):
            result = test_proxy_detailed(p)
            if result["status"] == "working":
                text += f"✅ <code>{p[:60]}</code>\n   🌐 {result['ip']} | ⚡ {result['speed']}s\n\n"
                valid += 1
                valid_proxies.append(p)
            else:
                text += f"❌ <code>{p[:60]}</code>\n\n"
                invalid += 1

            if i % 5 == 0 and i < len(proxies):
                try:
                    await query.edit_message_text(text + "\n⏳...", parse_mode="HTML")
                except:
                    pass

        if invalid > 0:
            save_proxies(valid_proxies)

        text += f"━━━━━━━━━━━━━━━━━\n📊 ✅ {valid} | ❌ {invalid}"

        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "delete_proxy":
        proxies = load_proxies()
        if not proxies:
            await query.edit_message_text("📭 لا يوجد بروكسيات!")
            return

        keyboard = []
        for i, p in enumerate(proxies[:20]):
            display = p[:40] + "..." if len(p) > 40 else p
            keyboard.append([InlineKeyboardButton(f"🗑️ {display}", callback_data=f"del_proxy_{i}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")])

        context.user_data['delete_proxies'] = {str(i): p for i, p in enumerate(proxies[:20])}

        await query.edit_message_text(
            "🗑️ <b>اختر البروكسي:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    elif data.startswith("del_proxy_"):
        idx = data.replace("del_proxy_", "")
        delete_map = context.user_data.get('delete_proxies', {})
        proxy = delete_map.get(idx)

        if proxy:
            proxies = load_proxies()
            if proxy in proxies:
                proxies.remove(proxy)
                save_proxies(proxies)
                await query.edit_message_text(f"✅ تم الحذف")

        await asyncio.sleep(1)

        proxies = load_proxies()
        if not proxies:
            await query.edit_message_text("📭 لا يوجد بروكسيات!")
            return

        keyboard = []
        for i, p in enumerate(proxies[:20]):
            display = p[:40] + "..." if len(p) > 40 else p
            keyboard.append([InlineKeyboardButton(f"🗑️ {display}", callback_data=f"del_proxy_{i}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")])

        context.user_data['delete_proxies'] = {str(i): p for i, p in enumerate(proxies[:20])}

        await query.edit_message_text(
            "🗑️ <b>اختر البروكسي:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

    elif data == "back_main":
        await show_main_menu(update, context, query.message.chat_id)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == "/cancel":
        if user_id in pending_emails:
            del pending_emails[user_id]
        await update.message.reply_text("❌ تم الإلغاء!")
        return

    action = pending_emails.get(user_id)

    if action == "waiting_for_account":
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text("❌ أرسل: <code>email password</code>", parse_mode="HTML")
            return

        email = parts[0]
        password = " ".join(parts[1:])

        if not email or not password or len(password) < 6:
            await update.message.reply_text("❌ بيانات غير صالحة")
            return

        del pending_emails[user_id]

        progress = await update.message.reply_text(
            f"🔄 <b>جاري الإضافة...</b>\n📧 {email}",
            parse_mode="HTML"
        )

        await add_single_account(email, password, progress)
        await show_main_menu(None, context, update.message.chat_id)

    elif action == "waiting_for_multiple_accounts":
        lines = text.strip().split('\n')
        accounts_data = []

        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 2:
                email = parts[0]
                password = " ".join(parts[1:])
                if email and password and len(password) >= 6:
                    accounts_data.append((email, password))

        if not accounts_data:
            await update.message.reply_text("❌ لا توجد حسابات صالحة.")
            del pending_emails[user_id]
            return

        del pending_emails[user_id]
        total = len(accounts_data)

        progress = await update.message.reply_text(
            f"🚀 <b>بدء إضافة {total} حساب</b>", parse_mode="HTML"
        )

        results = {}
        results_lock = threading.Lock()

        def process_account(idx, email, password):
            try:
                future = asyncio.run_coroutine_threadsafe(
                    add_single_account(email, password, None, silent=True),
                    main_event_loop
                )
                success = future.result(timeout=300)

                with results_lock:
                    results[idx] = {"email": email, "success": success}
            except Exception as e:
                with results_lock:
                    results[idx] = {"email": email, "success": False, "error": str(e)[:50]}

        threads = []
        for idx, (email, password) in enumerate(accounts_data):
            t = threading.Thread(target=process_account, args=(idx, email, password), daemon=True)
            t.start()
            threads.append(t)
            await asyncio.sleep(0.3)

        last_update = time.time()
        while True:
            alive = [t for t in threads if t.is_alive()]
            if not alive:
                break

            if time.time() - last_update > 3:
                with results_lock:
                    done = len(results)
                    success_count = sum(1 for r in results.values() if r.get("success"))
                    fail_count = done - success_count

                try:
                    await progress.edit_text(
                        f"🚀 <b>إضافة {total} حساب</b>\n"
                        f"⏳ {done}/{total}\n"
                        f"✅ {success_count} | ❌ {fail_count}\n"
                        f"🔄 {len(alive)} شغال",
                        parse_mode="HTML"
                    )
                except:
                    pass

                last_update = time.time()

            await asyncio.sleep(1)

        with results_lock:
            success_count = sum(1 for r in results.values() if r.get("success"))
            fail_count = total - success_count

        summary = (
            f"📊 <b>النتيجة</b>\n"
            f"✅ نجح: {success_count}\n"
            f"❌ فشل: {fail_count}\n"
            f"📝 إجمالي: {total}"
        )

        try:
            await progress.edit_text(summary, parse_mode="HTML")
        except:
            await update.message.reply_text(summary, parse_mode="HTML")

        await show_main_menu(None, context, update.message.chat_id)

    elif action == "waiting_for_proxies":
        proxies = [p.strip() for p in text.split('\n') if p.strip()]
        current = load_proxies()
        added = 0

        for p in proxies:
            if not p.startswith("http://") and not p.startswith("https://"):
                p = f"http://{p}"
            if p not in current:
                current.append(p)
                added += 1

        if added > 0:
            save_proxies(current)
            await update.message.reply_text(f"✅ تم إضافة {added} بروكسي")
        else:
            await update.message.reply_text("⚠️ لم تتم إضافة أي بروكسي")

        del pending_emails[user_id]
        await show_main_menu(None, context, update.message.chat_id)

    else:
        await update.message.reply_text("❌ أمر غير معروف. استخدم /start")


# ============================================================
# main
# ============================================================
def main():
    global bot_application, is_shutting_down, main_event_loop

    init_database()

    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ لم يتم تعيين BOT_TOKEN")
        return

    async def post_init(application):
        global main_event_loop
        main_event_loop = asyncio.get_running_loop()
        print("✅ Event loop initialized")

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    bot_application = application

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("dashboard", dashboard_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    proxies = load_proxies()
    session_mode = proxies and SESSION_BASED_PROXY and is_session_proxy(proxies[0])

    print("🎰 Slot Bot - النسخة المدمجة النهائية")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"🌐 وضع البروكسي: {'Session' if session_mode else 'عادي'}")
    print(f"📊 البروكسيات: {len(proxies)}")
    print(f"🔔 الإشعارات: {'مفعّلة' if NOTIFY_ON_ERROR else 'معطّلة'}")
    print("✅ farm_ads من القديم (headers كاملة)")
    print("✅ spin_once من القديم (lowercase auth)")
    print("✅ انتظار قصير (0.3-0.7s)")
    print("✅ بدون سحب")
    print("✅ Recovery system")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        is_shutting_down = True
        bot_manager.stop_all()
        print("👋 Goodbye!")


if __name__ == "__main__":
    main()
