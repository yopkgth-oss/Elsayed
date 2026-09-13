#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Slot Bot - النسخة النهائية الكاملة
مع كل التعديلات:
- get_trx_coin_id (ديناميكي)
- execute_initial_sequence
- فلترة FaucetPay + المبلغ
- مسح الرسائل القديمة
- التحقق من الرصيد بعد السحب
- Bright Data Session Proxy (IP مختلف لكل حساب)
- إيميل FaucetPay موحد للسحب
- السحب اليدوي لا يوقف الحساب
- عرض حالات السحب من API (اكتشاف تلقائي)
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
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.warnings import PTBUserWarning
import warnings

warnings.filterwarnings("ignore", category=PTBUserWarning)

# ============================================================
# إعدادات السجلات
# ============================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================================================
# تحميل الإعدادات
# ============================================================
def load_config():
    config_file = "config.json"
    default_config = {
        "bot_token": "YOUR_BOT_TOKEN_HERE",
        "base_url": "https://slotfruits.com",
        "mail_tm_api": "https://api.mail.tm",
        "mail_tm_domain": "@uberip.com",
        "timeout": 60,
        "min_withdraw": 1000,
        "min_target": 55000,
        "max_target": 65000,
        "use_proxies": True,
        "session_based_proxy": True,
        "session_prefix": "acc",
        "faucetpay_email": "amemo0536@gmail.com",
        "withdraw_coin": "trx",
        "database_file": "accounts.db",
        "items_per_page": 25
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            for key, value in default_config.items():
                if key not in config:
                    config[key] = value
            print("✅ تم تحميل الإعدادات من config.json")
            return config
        except Exception as e:
            print(f"❌ خطأ في تحميل config.json: {e}")
            return default_config
    else:
        print("⚠️ ملف config.json غير موجود، يتم إنشاؤه...")
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(default_config, f, indent=2, ensure_ascii=False)
        print("✅ تم إنشاء config.json بنجاح")
        print("📝 الرجاء تعديل التوكن ثم إعادة التشغيل")
        sys.exit(1)

CONFIG = load_config()

BOT_TOKEN = CONFIG.get("bot_token")
if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    print("❌ خطأ: لم يتم تعيين BOT_TOKEN في config.json")
    sys.exit(1)

BASE_URL = CONFIG.get("base_url")
MAIL_TM_API = CONFIG.get("mail_tm_api")
MAIL_TM_DOMAIN = CONFIG.get("mail_tm_domain")
TIMEOUT = CONFIG.get("timeout", 60)
MIN_WITHDRAW = CONFIG.get("min_withdraw", 1000)
MIN_TARGET = CONFIG.get("min_target", 55000)
MAX_TARGET = CONFIG.get("max_target", 65000)
USE_PROXIES = CONFIG.get("use_proxies", True)
SESSION_BASED_PROXY = CONFIG.get("session_based_proxy", True)
SESSION_PREFIX = CONFIG.get("session_prefix", "acc")
DATABASE_FILE = CONFIG.get("database_file", "accounts.db")
ITEMS_PER_PAGE = CONFIG.get("items_per_page", 25)
WITHDRAW_COIN = CONFIG.get("withdraw_coin", "trx").lower()

# ✅ إيميل FaucetPay الموحد للسحب
FAUCETPAY_EMAIL = CONFIG.get("faucetpay_email", "").strip()

API_URL = f"{BASE_URL}/api/v1"
GRAPHQL_URL = f"{BASE_URL}/graphql"

DEFAULT_COIN_ID = "66bd3ede56df3c77675b869d"

FAKE_NUMBERS = {
    "2018", "2019", "2020", "2021", "2022", "2023", 
    "2024", "2025", "2026", "2027", "2028", "2029", "2030",
    "1234", "0000", "1111", "2222", "3333", "4444", 
    "5555", "6666", "7777", "8888", "9999"
}

# ============================================================
# متغيرات عامة
# ============================================================
bot_application = None
bot_chat_id = None
main_event_loop = None
is_shutting_down = False
pending_emails = {}

mail_lock = threading.Lock()
worker_lock = threading.Lock()
proxy_lock = threading.Lock()
ip_cache_lock = threading.Lock()

ip_cache = {}
proxy_failures = {}
coin_id_cache = {}

# ============================================================
# إشعار آمن من أي thread
# ============================================================
def safe_notify(message):
    global main_event_loop
    if not bot_application or not main_event_loop:
        return
    chat_id = bot_manager.chat_id or bot_chat_id
    if not chat_id:
        return
    try:
        asyncio.run_coroutine_threadsafe(
            bot_application.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML"
            ),
            main_event_loop
        )
    except Exception as e:
        logger.error(f"فشل إرسال الإشعار: {e}")

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
            withdrawal_count INTEGER DEFAULT 0,
            last_withdrawal TEXT,
            proxy TEXT,
            spin_count INTEGER DEFAULT 0,
            target_amount INTEGER DEFAULT 0,
            has_withdrawn_today INTEGER DEFAULT 0,
            last_withdraw_date TEXT,
            proxy_index INTEGER DEFAULT 0,
            mail_ok INTEGER DEFAULT 0,
            account_type TEXT DEFAULT 'existing'
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            address TEXT NOT NULL,
            wallet_type TEXT DEFAULT 'FP',
            status TEXT DEFAULT 'pending',
            tx_hash TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
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
    columns = ['id', 'email', 'password', 'token', 'user_id', 'balance', 'credits', 
               'total_earned', 'created_at', 'last_login', 'is_active', 'withdrawal_count',
               'last_withdrawal', 'proxy', 'spin_count', 'target_amount', 
               'has_withdrawn_today', 'last_withdraw_date', 'proxy_index',
               'mail_ok', 'account_type']
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


def get_all_accounts(active_only=True):
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


def add_account(email, password, token=None, user_id=None, balance=0, credits=0, 
                proxy=None, proxy_index=0, mail_ok=0, account_type='existing'):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        target = random.randint(MIN_TARGET, MAX_TARGET)
        cursor.execute("""
            INSERT INTO accounts (email, password, token, user_id, balance, credits, 
                                 created_at, proxy, target_amount, proxy_index, mail_ok, account_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (email, password, token, user_id, balance, credits, datetime.now().isoformat(), 
              proxy, target, proxy_index, mail_ok, account_type))
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
        cursor.execute("DELETE FROM withdrawals WHERE account_id = ?", (account_id,))
        cursor.execute("DELETE FROM spin_history WHERE account_id = ?", (account_id,))
        conn.commit()
        conn.close()
        return True
    except:
        return False


def add_withdrawal(account_id, amount, address, wallet_type="FP", status="pending", tx_hash=None):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO withdrawals (account_id, amount, address, wallet_type, status, tx_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (account_id, amount, address, wallet_type, status, tx_hash, datetime.now().isoformat()))
        conn.commit()
        withdrawal_id = cursor.lastrowid
        conn.close()
        return withdrawal_id
    except:
        return None


def get_withdrawals(account_id, limit=10):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM withdrawals WHERE account_id = ? 
            ORDER BY created_at DESC LIMIT ?
        """, (account_id, limit))
        rows = cursor.fetchall()
        conn.close()
        columns = ['id', 'account_id', 'amount', 'address', 'wallet_type', 'status', 
                   'tx_hash', 'created_at', 'completed_at']
        return [dict(zip(columns, row)) for row in rows]
    except:
        return []


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
# نظام البروكسيات
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
        logger.error(f"خطأ في تحميل البروكسيات: {e}")
    return proxies


def save_proxies(proxies, proxy_file="proxy.txt"):
    try:
        with open(proxy_file, "w", encoding="utf-8") as f:
            f.write("# قائمة البروكسيات\n")
            for p in proxies:
                f.write(f"{p}\n")
        return True
    except Exception as e:
        logger.error(f"خطأ في حفظ البروكسيات: {e}")
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
        logger.error(f"خطأ في build_session_proxy: {e}")
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
    
    ip = get_ip(proxy, timeout=10)
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
            timeout=20
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
                logger.warning(f"⚠️ البروكسي {proxy[:50]}... فشل 5 مرات")
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
# خدمات Mail.tm
# ============================================================
mail_monitors = {}
seen_messages = {}
verification_codes = {}


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
    text = safe_str(raw_html)
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, " ", text).strip()


def get_mail_token(email, password):
    url = f"{MAIL_TM_API}/token"
    try:
        res = requests.post(url, json={"address": email, "password": password}, timeout=15)
        if res.status_code == 200:
            return res.json().get("token")
        return None
    except:
        return None


def create_mail_account(email=None, password=None):
    url = f"{MAIL_TM_API}/accounts"
    if not email:
        import uuid
        local_part = str(uuid.uuid4())[:8]
        email = f"{local_part}{MAIL_TM_DOMAIN}"
    if not password:
        import string
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    try:
        res = requests.post(url, json={"address": email, "password": password}, timeout=15)
        if res.status_code == 201:
            return email, password, True
        return email, password, False
    except:
        return email, password, False


def ensure_mail_account(email, password):
    token = get_mail_token(email, password)
    if token:
        logger.info(f"✅ البريد {email} موجود")
        return True, token
    
    logger.info(f"🆕 محاولة إنشاء البريد: {email}")
    created_email, created_pass, success = create_mail_account(email, password)
    
    if not success:
        logger.error(f"❌ فشل إنشاء البريد {email}")
        return False, None
    
    time.sleep(2)
    token = get_mail_token(email, password)
    if token:
        logger.info(f"✅ تم إنشاء البريد {email}")
        return True, token
    
    return False, None


def get_mail_messages(token, limit=10):
    url = f"{MAIL_TM_API}/messages"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(url, headers=headers, params={"page": 1, "limit": limit}, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data.get("hydra:member", [])
        elif res.status_code == 401:
            return None
        return None
    except Exception as e:
        logger.error(f"خطأ get_mail_messages: {e}")
        return None


def get_mail_message(token, message_id):
    url = f"{MAIL_TM_API}/messages/{message_id}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            return res.json()
        return None
    except:
        return None


def clear_old_slotfruits_messages(email, password):
    try:
        token = get_mail_token(email, password)
        if not token:
            return False
        
        messages = get_mail_messages(token, limit=30)
        if not messages:
            return True
        
        cleared_count = 0
        
        with mail_lock:
            if email not in seen_messages:
                seen_messages[email] = set()
            
            for msg in messages:
                msg_id = msg.get("id")
                if not msg_id:
                    continue
                
                subject = safe_str(msg.get("subject", ""))
                from_addr = msg.get("from", {})
                if isinstance(from_addr, dict):
                    from_addr = from_addr.get("address", "")
                from_addr = safe_str(from_addr)
                
                subject_lower = subject.lower()
                from_lower = from_addr.lower()
                
                if ("slotfruits" in from_lower or 
                    "slotfruits" in subject_lower or
                    "withdrawal" in subject_lower or
                    "verification" in subject_lower or
                    "faucetpay" in from_lower or
                    "faucetpay" in subject_lower):
                    
                    if msg_id not in seen_messages[email]:
                        seen_messages[email].add(msg_id)
                        cleared_count += 1
        
        logger.info(f"🧹 تم تجاهل {cleared_count} رسالة قديمة لـ {email}")
        return True
    
    except Exception as e:
        logger.error(f"خطأ في clear_old_slotfruits_messages: {e}")
        return False


def extract_code_from_mail(email_data, expected_amount=None):
    if not email_data:
        return None
    
    sender = ""
    from_data = email_data.get("from", {})
    if isinstance(from_data, dict):
        sender = from_data.get("address", "")
    sender = safe_str(sender).lower()
    
    subject = safe_str(email_data.get("subject", ""))
    subject_lower = subject.lower()
    
    body_text = safe_str(email_data.get("text", ""))
    body_html = safe_str(email_data.get("html", ""))
    
    full_text = ""
    if body_text.strip():
        full_text = body_text
    else:
        full_text = clean_html(body_html)
    
    if not full_text:
        return None
    
    if "faucetpay" in sender or "faucetpay" in subject_lower:
        return None
    
    is_slotfruits = (
        "slotfruits" in sender or
        "slotfruits" in subject_lower or
        "slotfruits" in full_text.lower()[:1000]
    )
    
    if not is_slotfruits:
        return None
    
    if expected_amount is not None:
        is_withdrawal = (
            "withdrawal" in subject_lower or
            "withdrawal" in full_text.lower()[:500] or
            "confirm your withdrawal" in full_text.lower()
        )
        if not is_withdrawal:
            return None
    
    if expected_amount is not None:
        amount_patterns = [
            r"withdrawal\s+amount\s*[:\-]?\s*([\d,]+)\s*(?:COINS|coins)?",
            r"amount\s*[:\-]?\s*([\d,]+)\s*COINS",
            r"value\s*[:\-]?\s*([\d,]+)",
        ]
        
        found_amount = None
        for pattern in amount_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                try:
                    found_amount = int(match.group(1).replace(',', ''))
                    break
                except:
                    pass
        
        if found_amount is not None:
            if abs(found_amount - expected_amount) > 5:
                logger.info(f"⏭️ تخطي رسالة (مبلغ مختلف): {found_amount} ≠ {expected_amount}")
                return None
            else:
                logger.info(f"✅ المبلغ مطابق: {found_amount} ≈ {expected_amount}")
    
    strict_patterns = [
        r"verification\s+code\s*[:\-]\s*([0-9]{4,10})",
        r"verification\s+code\s+([0-9]{4,10})",
        r"code\s*[:\-]\s*([0-9]{4,10})",
        r"رمز\s+التحقق\s*[:\-]\s*([0-9]{4,10})",
        r"كود\s+التأكيد\s*[:\-]\s*([0-9]{4,10})",
    ]
    
    for pattern in strict_patterns:
        match = re.search(pattern, full_text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            code = match.group(1)
            if code in FAKE_NUMBERS:
                continue
            if 4 <= len(code) <= 10 and code.isdigit():
                logger.info(f"✅ تم استخراج الكود: {code}")
                return code
    
    numbers = re.findall(r'\b(\d{4,6})\b', full_text)
    
    if expected_amount is not None:
        amount_variations = [str(expected_amount)]
        numbers = [n for n in numbers if n not in amount_variations]
    
    for num in numbers:
        if num in FAKE_NUMBERS:
            continue
        if 4 <= len(num) <= 6:
            logger.info(f"✅ كود محتمل: {num}")
            return num
    
    return None


def start_mail_monitor(email, password):
    with mail_lock:
        if email in mail_monitors and mail_monitors[email].get("running", False):
            return mail_monitors[email].get("token")
        
        success, token = ensure_mail_account(email, password)
        if not success:
            logger.error(f"❌ لا يمكن بدء المراقبة لـ {email}")
            return None
        
        if email not in seen_messages:
            seen_messages[email] = set()
        
        mail_monitors[email] = {
            "token": token,
            "running": True,
            "email": email,
            "password": password,
            "consecutive_fails": 0,
            "expected_amount": None
        }
    
    def monitor_loop():
        consecutive_fails = 0
        
        while mail_monitors.get(email, {}).get("running", False):
            try:
                with mail_lock:
                    if email not in mail_monitors:
                        break
                    token = mail_monitors[email]["token"]
                    expected_amount = mail_monitors[email].get("expected_amount")
                
                messages = get_mail_messages(token, limit=10)
                
                if messages is None:
                    raise Exception("فشل جلب الرسائل")
                
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
                        
                        is_slotfruits = (
                            "slotfruits" in from_lower or
                            "slotfruits" in subject_lower
                        )
                        
                        if not is_slotfruits:
                            seen_messages[email].add(msg_id)
                            continue
                        
                        seen_messages[email].add(msg_id)
                        
                        detail = get_mail_message(token, msg_id)
                        if detail:
                            code = extract_code_from_mail(detail, expected_amount)
                            if code:
                                with mail_lock:
                                    verification_codes[email] = {
                                        "code": code,
                                        "timestamp": time.time(),
                                        "subject": subject,
                                        "expected_amount": expected_amount
                                    }
                                logger.info(f"✅ تم استلام كود لـ {email}: {code}")
                
                time.sleep(3)
                
            except Exception as e:
                logger.error(f"خطأ في مراقبة البريد {email}: {e}")
                consecutive_fails += 1
                
                if consecutive_fails >= 3:
                    with mail_lock:
                        if email in mail_monitors:
                            success, new_token = ensure_mail_account(email, mail_monitors[email]["password"])
                            if success:
                                mail_monitors[email]["token"] = new_token
                                consecutive_fails = 0
                
                time.sleep(5)
        
        logger.info(f"⏹️ توقفت مراقبة البريد لـ {email}")
    
    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()
    mail_monitors[email]["thread"] = thread
    
    return token


def wait_for_code(email, password, timeout=180, expected_amount=None):
    if email not in mail_monitors or not mail_monitors[email].get("running", False):
        token = start_mail_monitor(email, password)
        if not token:
            return None
    
    with mail_lock:
        if email in mail_monitors:
            mail_monitors[email]["expected_amount"] = expected_amount
        
        if email in verification_codes:
            del verification_codes[email]
    
    wait_start_time = time.time()
    start_time = time.time()
    retry_attempts = 0
    last_retry = 0
    
    while time.time() - start_time < timeout:
        with mail_lock:
            if email in verification_codes:
                code_data = verification_codes[email]
                if code_data.get("timestamp", 0) >= wait_start_time:
                    code = code_data["code"]
                    del verification_codes[email]
                    logger.info(f"✅ تم الحصول على الكود: {code}")
                    return code
                else:
                    del verification_codes[email]
        
        elapsed = time.time() - start_time
        if elapsed > 60 and elapsed - last_retry > 60 and retry_attempts < 3:
            logger.info(f"🔄 إعادة فحص البريد لـ {email}")
            with mail_lock:
                if email in mail_monitors:
                    success, new_token = ensure_mail_account(email, password)
                    if success:
                        mail_monitors[email]["token"] = new_token
            retry_attempts += 1
            last_retry = elapsed
        
        time.sleep(3)
    
    logger.warning(f"⏰ انتهى وقت الانتظار لـ {email}")
    return None


# ============================================================
# API اللعبة
# ============================================================
def safe_request(method, url, **kw):
    kw.setdefault("timeout", TIMEOUT)
    for attempt in range(3):
        try:
            response = requests.request(method, url, **kw)
            if response.status_code < 500:
                return response
            time.sleep(1)
        except:
            time.sleep(0.5)
    return None


def do_register(email, password, proxy=None):
    try:
        token = get_mail_token(email, password)
        if not token:
            email, password, success = create_mail_account(email, password)
            if not success:
                return False, "فشل إنشاء البريد المؤقت"
        
        time.sleep(1)
        
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
            return True, "تم التسجيل بنجاح"
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
        
        token = data.get("token")
        user_id = user.get("_id")
        balance = user.get("balance", 0)
        credits = user.get("credits", 0)
        
        return token, user_id, balance, credits, "نجاح"
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
            return {"exists": False, "error": "لا يوجد استجابة من السيرفر"}
        
        try:
            data = res.json()
        except:
            return {"exists": False, "error": f"رد غير صالح: {res.text[:100]}"}
        
        user = data.get("user")
        token = data.get("token")
        
        if user and token:
            return {
                "exists": True,
                "token": token,
                "user_id": user.get("_id"),
                "balance": user.get("balance", 0),
                "credits": user.get("credits", 0),
                "message": "الحساب موجود"
            }
        
        if data.get("needsConfirmation") == True:
            return {
                "exists": False,
                "needs_confirmation": True,
                "email": data.get("email", email),
                "message": data.get("msg", "الحساب يحتاج تأكيد")
            }
        
        msg = data.get("msg", "") or data.get("message", "") or ""
        msg_lower = msg.lower()
        
        not_found_keywords = [
            "not found", "not exist", "does not exist",
            "invalid credentials", "incorrect password",
            "user not", "no user", "account not", "register"
        ]
        if any(kw in msg_lower for kw in not_found_keywords):
            return {
                "exists": False,
                "not_found": True,
                "message": msg or "الحساب غير موجود"
            }
        
        return {
            "exists": False,
            "not_found": True,
            "message": msg or "حساب جديد"
        }
    
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
        if data.get("token") or data.get("success"):
            return True, data.get("token"), "تم التأكيد بنجاح"
        return False, None, data.get("message", "فشل التأكيد")
    except Exception as e:
        return False, None, str(e)


def get_user_info(token, proxy=None):
    try:
        url = f"{API_URL}/users/me"
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
        
        res = safe_request("GET", url, **kw)
        if res and res.status_code == 200:
            return res.json().get("user", {})
        return None
    except:
        return None


def spin_once(token, proxy=None):
    try:
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {token}",
        }
        kw = {"headers": headers}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}
        
        res = safe_request("GET", f"{API_URL}/users/earnRoll", **kw)
        if not res or res.status_code != 200:
            return None
        return res.json()
    except:
        return None


def farm_ads(user_id, proxy=None):
    FARM_ADS_URL = (
        "https://googleads.g.doubleclick.net/mads/gma?submodel=SM-A217F&adid_p=1&format=interstitial_mb"
        "&ini_pn=com.google.android.packageinstaller&ins_pn=com.google.android.packageinstaller"
        "&omid_v=a.1.5.2-google_20241009&dv=254380203&ev=24.6.0&gl=ID&hl=in"
        "&js=afma-sdk-a-v254380999.253410000.1&kw=clothing%2Cfashion&lv=253410000"
        "&ms=CqgFmsA_ATEaQQHY5dWIJ1nnZI0TXJOCrRjxy3oie3ZsfYBDue5jJF2CTFQQuf7W9C9KnP8xbLx0FI_PC-5wIrw0itcrK2KvDP4iEt0E6Yp1pn72NO8vWhbzh19JnXz5v7gGWsohjScUvkVohNO_jbecHUPYSmqy4T-WuJZ2EFv8_r-2HeMQg4ZPiq_jwKyeOrQjsiRXsU8vcZpKSMI0Z7Pn6iha94ABhZW_FbLysDgYt2ox4f_FIffLSbr_vjYntwKQpTg44MpacMRJ2_Ch0aplBuEzXYGkOTHBpg58oZtEw_3nZ8wsO9jE5lLVvx_cmKmOEpfemdesE_wTXvV0Hv5MWrZQ2I4ulXfQrY_gKRBI5ivJJLh3XYIzgBBRhoZastP7yEVFBT7Y8iunIsK3VrABvtw9RWUDkE2lETA0ezNEzwFoAhoGTGHuS2JaZ68x68KZGPFPR1CX4CXbMf1DDtzECiUr12lOsiuPUQ2WWtrjma3PKtkBk-0B5HoTVviRRPOHqgth3x80sbtwMn4G95El7JP079-e_jUT0oa75oJQC-Ph3zmllppvqq3dJN_RCGbyELdXc042fsR1fi3Syd6w1SJROO_t2sP3o2Bdzn2_jv1aokWO8NAzbtrWUs64BUiv1-XMv3k6CReZ91Ac9T28vbfulD8b_t8WSPrIHmXCGEC4h50U74SHhRxUcOmlR7sWpB2y8WfC7NlfoGCG5r6vXzVpG1oFOvTYscbEq1GPl1SjpnwS00RVM5_wfwa6GKc53oRubkV-CBhU_KMXUN115FELhAaNab2qn8reOKeN6xdg_OkZjGgHml1GIlVQity3LvBcbzP2yE898LCwcwXVc9oLcH_WHL1eb7K19Zf6kpquk35qGtTP3xrSzDcw6t-GAxGg1lTCxlMgBA"
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
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 12; SM-A217F) AppleWebKit/537.36",
        "sec-ch-ua-platform": "Android",
        "x-requested-with": "com.piratebaixe.slotMobile",
    }
    
    kw = {"headers": headers, "timeout": 15}
    if proxy:
        proxy_clean = proxy.strip()
        if not proxy_clean.startswith("http://"):
            proxy_clean = f"http://{proxy_clean}"
        kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}
    
    try:
        resp = safe_request("GET", FARM_ADS_URL, **kw)
        if not resp:
            return False
        
        nets = resp.json().get("ad_networks", [])
        for net in nets:
            for vid in net.get("video_reward_urls", []):
                p = urlparse(vid)
                qs = parse_qs(p.query, keep_blank_values=True)
                qs["rwd_userid"] = [str(user_id)]
                new = p._replace(query=urlencode(qs, doseq=True))
                safe_request("GET", urlunparse(new), **kw)
        return True
    except:
        return False


# ============================================================
# دوال العملات والتسلسل
# ============================================================
def get_coin_id_by_symbol(token, symbol="trx", proxy=None):
    cache_key = f"{token[:20]}_{symbol.lower()}"
    if cache_key in coin_id_cache:
        cached_time, cached_coin_id = coin_id_cache[cache_key]
        if (time.time() - cached_time) < 3600:
            return cached_coin_id
    
    query = {
        "operationName": "getTypeCoinAll",
        "variables": {},
        "query": "query getTypeCoinAll {\n  getTypeCoinAll {\n    id\n    sigla\n  }\n}"
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "okhttp/4.12.0"
    }
    
    kw = {"headers": headers, "json": query}
    if proxy:
        proxy_clean = proxy.strip()
        if not proxy_clean.startswith("http://"):
            proxy_clean = f"http://{proxy_clean}"
        kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}
    
    try:
        res = safe_request("POST", GRAPHQL_URL, **kw)
        if not res:
            return DEFAULT_COIN_ID
        
        data = res.json()
        coins = data.get("data", {}).get("getTypeCoinAll", [])
        
        for coin in coins:
            if coin.get("sigla", "").lower() == symbol.lower():
                coin_id = coin.get("id")
                if coin_id:
                    coin_id_cache[cache_key] = (time.time(), coin_id)
                    logger.info(f"✅ تم جلب {symbol.upper()} coin_id: {coin_id}")
                    return coin_id
        
        return DEFAULT_COIN_ID
    except Exception as e:
        logger.error(f"خطأ في get_coin_id_by_symbol: {e}")
        return DEFAULT_COIN_ID


def get_trx_coin_id(token, proxy=None):
    return get_coin_id_by_symbol(token, "trx", proxy)


def execute_initial_sequence(token, user_id, proxy=None):
    try:
        okhttp_headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {token}"
        }
        
        kw_base = {"headers": okhttp_headers, "timeout": 15}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://"):
                proxy_clean = f"http://{proxy_clean}"
            kw_base["proxies"] = {"http": proxy_clean, "https": proxy_clean}
        
        safe_request("GET", f"{API_URL}/users/getClick", **kw_base)
        time.sleep(0.3)
        safe_request("GET", f"{API_URL}/checkVersion", **kw_base)
        time.sleep(0.3)
        safe_request("GET", f"{API_URL}/users/getTimeClick", **kw_base)
        time.sleep(0.3)
        
        if user_id:
            kw_mobile = {"headers": {"User-Agent": "okhttp/4.12.0"}, "timeout": 15}
            if proxy:
                kw_mobile["proxies"] = kw_base.get("proxies", {})
            safe_request("GET", f"{BASE_URL}/mobile/{user_id}", **kw_mobile)
            time.sleep(0.3)
        
        safe_request("GET", f"{BASE_URL}/dashboard", **{
            "headers": {
                "User-Agent": "okhttp/4.12.0",
                "Authorization": f"Bearer {token}"
            },
            "timeout": 15,
            **({"proxies": kw_base["proxies"]} if proxy else {})
        })
        time.sleep(0.3)
        
        gql_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "okhttp/4.12.0"
        }
        gql_kw = {"headers": gql_headers, "timeout": 15}
        if proxy:
            gql_kw["proxies"] = kw_base["proxies"]
        
        user_query = {
            "operationName": "getUser",
            "variables": {},
            "query": "query getUser {\n  getUser {\n    id\n    balance\n    credits\n    username\n    email\n    admin\n    status\n    createAt\n    log\n    xp\n    level\n    next_level\n    bonus_level\n    address_fp\n    bonus_loyalty\n    total_earn\n    ref\n    statistics_earn {\n      id\n      clicks\n      total\n      typename\n    }\n    typename\n  }\n}"
        }
        safe_request("POST", GRAPHQL_URL, json=user_query, **gql_kw)
        time.sleep(0.3)
        
        config_query = {
            "operationName": "getConfig",
            "variables": {},
            "query": "query getConfig {\n  getConfig {\n    recapcha_client_key\n    percent_earn_ref\n    percent_earn_ptc_view\n    percent_credits_ptc_view\n    minimum_withdrawal\n    minimum_withdrawal_usd\n    value_max_withdraw_today\n    status_site\n    status_email\n    adBlock\n    captcha\n    createAt\n    contact\n    token_value\n    credits_value\n    percent_swap\n    value_max_swap_today\n    minimum_swap_usd\n    minimum_swap_token\n    xp_ads\n    xp_short_link\n    xp_roll_game\n    xp_survey\n    automatic_payment\n    validate_ip\n    time_faucet\n    survey\n    adsBot\n    __typename\n  }\n}"
        }
        safe_request("POST", GRAPHQL_URL, json=config_query, **gql_kw)
        time.sleep(0.3)
        
        spin_query = {
            "operationName": "getSpin",
            "variables": {},
            "query": "query getSpin {\n  getSpin {\n    spinOne\n    spinTwo\n    __typename\n  }\n}"
        }
        safe_request("POST", GRAPHQL_URL, json=spin_query, **gql_kw)
        
        logger.info(f"✅ تم تنفيذ التسلسل الأولي")
        return True
    except Exception as e:
        logger.error(f"خطأ في execute_initial_sequence: {e}")
        return False


def request_withdrawal_code(token, address, amount, coin_id=None, proxy=None):
    try:
        if coin_id is None:
            coin_id = get_coin_id_by_symbol(token, WITHDRAW_COIN, proxy)
        
        logger.info(f"💰 طلب سحب {amount} (coin: {WITHDRAW_COIN.upper()}, id: {coin_id})")
        
        url = f"{API_URL}/users/requestWithdrawCode"
        payload = {
            "input": {
                "address": address,
                "value": amount,
                "token_recaptcha": "token_recaptcha",
                "id": coin_id,
                "type_wallet": "FP"
            }
        }
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
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
        logger.info(f"📥 رد طلب الكود: {json.dumps(data, ensure_ascii=False)[:300]}")
        
        result = data.get("result", {})
        if result.get("status") == "success" or data.get("success"):
            return True, coin_id, "تم إرسال الكود"
        return False, None, result.get("msg", "فشل طلب الكود")
    except Exception as e:
        return False, None, str(e)


def confirm_withdrawal(token, address, amount, code, coin_id=None, proxy=None):
    try:
        if coin_id is None:
            coin_id = get_coin_id_by_symbol(token, WITHDRAW_COIN, proxy)
        
        url = f"{API_URL}/users/withdraw"
        payload = {
            "input": {
                "address": address,
                "value": amount,
                "token_recaptcha": "token_recaptcha",
                "id": coin_id,
                "type_wallet": "FP",
                "code": code
            }
        }
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}"
        }
        kw = {"headers": headers, "data": json.dumps(payload)}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}
        
        res = safe_request("POST", url, **kw)
        if not res:
            return False, None, "لا يوجد استجابة من السيرفر"
        
        try:
            data = res.json()
        except:
            return False, None, f"رد غير صالح: {res.text[:100]}"
        
        logger.info(f"📥 رد تأكيد السحب: {json.dumps(data, ensure_ascii=False)[:300]}")
        
        result = data.get("result", {}) or {}
        msg = result.get("msg", "") or data.get("message", "") or ""
        msg_lower = msg.lower()
        
        error_keywords = [
            "incorrect", "invalid", "wrong", "failed", "expired",
            "not found", "already", "error", "does not exist",
            "غير صحيح", "خطأ"
        ]
        
        for keyword in error_keywords:
            if keyword in msg_lower:
                error_msg = msg or "فشل السحب"
                logger.error(f"❌ فشل السحب: {error_msg}")
                return False, None, error_msg
        
        is_success = (
            result.get("status") == "success" or 
            data.get("success") in (True, 1, "true", "success")
        ) and not result.get("needsConfirmation", False)
        
        if not is_success:
            if result.get("needsConfirmation"):
                return False, None, "السحب محتاج تأكيد إضافي"
            return False, None, msg or "فشل السحب"
        
        withdraw_info = data.get("withdraw", {}) or result.get("withdraw", {}) or {}
        
        return True, {
            "data": data,
            "withdraw_info": withdraw_info,
            "status": withdraw_info.get("status", 0),
            "hash": withdraw_info.get("hash", ""),
            "value": withdraw_info.get("value", amount)
        }, "تم قبول طلب السحب"
    
    except Exception as e:
        logger.error(f"❌ خطأ في confirm_withdrawal: {e}")
        return False, None, str(e)


# ============================================================
# ✅ دوال عرض حالات السحب من API
# ============================================================
def find_withdrawals_endpoint(token, proxy=None):
    """يجرب كل المسارات الممكنة ويطلع اللي شغال"""
    
    rest_endpoints = [
        f"{API_URL}/users/withdrawals",
        f"{API_URL}/users/withdraws",
        f"{API_URL}/users/withdraw",
        f"{API_URL}/users/history",
        f"{API_URL}/users/historic",
        f"{API_URL}/users/transactions",
        f"{API_URL}/users/payments",
        f"{API_URL}/withdrawals",
        f"{API_URL}/withdraws",
        f"{API_URL}/transactions",
    ]
    
    headers = {
        "User-Agent": "okhttp/4.12.0",
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}"
    }
    
    kw_base = {"headers": headers, "timeout": 15}
    if proxy:
        proxy_clean = proxy.strip()
        if not proxy_clean.startswith("http://"):
            proxy_clean = f"http://{proxy_clean}"
        kw_base["proxies"] = {"http": proxy_clean, "https": proxy_clean}
    
    results = []
    
    # نجرب REST API
    for url in rest_endpoints:
        try:
            res = safe_request("GET", url, **kw_base)
            if res and res.status_code == 200:
                try:
                    data = res.json()
                    for key in ["withdrawals", "withdraws", "data", "history", 
                                "items", "results", "docs", "list"]:
                        if key in data:
                            items = data[key]
                            if isinstance(items, dict):
                                items = items.get("docs") or items.get("items") or []
                            if items and len(items) > 0:
                                results.append({
                                    "url": url,
                                    "kind": "REST",
                                    "items": items,
                                    "count": len(items)
                                })
                                logger.info(f"✅ REST شغال: {url} → {len(items)}")
                                break
                except:
                    pass
        except:
            pass
    
    # نجرب GraphQL
    gql_queries = [
        ("getWithdraws", "query { getWithdraws { _id value status createAt address hash } }"),
        ("getWithdraw", "query { getWithdraw { _id value status createAt address hash } }"),
        ("getUserWithdraws", "query { getUserWithdraws { _id value status createAt address hash } }"),
        ("getHistoricWithdraws", "query { getHistoricWithdraws { _id value status createAt address hash } }"),
        ("getTransactions", "query { getTransactions { _id value status createAt address hash } }"),
    ]
    
    gql_headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "okhttp/4.12.0"
    }
    gql_kw = {"headers": gql_headers, "timeout": 15}
    if proxy:
        gql_kw["proxies"] = kw_base.get("proxies", {})
    
    for name, query in gql_queries:
        try:
            res = safe_request("POST", GRAPHQL_URL, json={"query": query}, **gql_kw)
            if res and res.status_code == 200:
                data = res.json()
                items = data.get("data", {}).get(name)
                if items and isinstance(items, list) and len(items) > 0:
                    results.append({
                        "url": f"GraphQL: {name}",
                        "kind": "GraphQL",
                        "items": items,
                        "count": len(items)
                    })
                    logger.info(f"✅ GraphQL شغال: {name} → {len(items)}")
        except:
            pass
    
    return results


def format_withdrawals(items, coin_symbol="TRX"):
    """تنسيق عرض السحوبات"""
    if not items:
        return "📭 لا توجد سحوبات\n"
    
    text = ""
    for i, wd in enumerate(items[:20], 1):
        value = wd.get('value') or wd.get('amount') or 0
        try:
            value = float(value)
            value_str = f"{value:.8f}" if value < 1 else f"{value:,.2f}"
        except:
            value_str = str(value)
        
        status = wd.get('status', 0)
        if status in [1, "1", "paid", "completed", "success"]:
            icon, stext = "✅", "مدفوع"
        elif status in [2, "2", "rejected", "failed", "canceled"]:
            icon, stext = "❌", "مرفوض"
        elif status in [0, "0", "pending", "wait"]:
            icon, stext = "⏳", "معلق"
        else:
            icon, stext = "❓", str(status)
        
        coin = wd.get('coin', {})
        wd_coin = coin.get('sigla', coin_symbol) if isinstance(coin, dict) else coin_symbol
        
        address = str(wd.get('address', ''))[:25]
        created = str(wd.get('createAt') or wd.get('created_at') or '')[:19].replace('T', ' ')
        tx = str(wd.get('hash') or wd.get('tx_hash') or '')[:20]
        
        text += f"{icon} <b>سحب #{i}</b> — <b>{stext}</b>\n"
        text += f"   💰 <code>{value_str} {wd_coin}</code>\n"
        if address:
            text += f"   📬 <code>{address}</code>\n"
        if created:
            text += f"   📅 {created}\n"
        if tx:
            text += f"   🔗 <code>{tx}...</code>\n"
        text += "   ─────────────\n"
    
    return text


# ============================================================
# AccountWorker
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
        self.coin_id = None
        
        self.running = False
        self.stopped = False
        self.current_ip = "جاري الجلب..."
        self.mail_ok = False
        
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json, text/plain, */*"})
        
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
        if not self.raw_proxy and USE_PROXIES:
            proxies = load_proxies()
            if not proxies:
                for _ in range(12):
                    time.sleep(5)
                    proxies = load_proxies()
                    if proxies:
                        break
            
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
            self.session.proxies = {
                "http": self.proxy,
                "https": self.proxy
            }
    
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
                self.session.proxies = {"http": new_proxy, "https": new_proxy}
                logger.info(f"🔄 تجديد session للحساب {self.email}")
                return True
            return False
        
        new_proxy = get_working_proxy(self.proxy)
        if new_proxy and new_proxy != self.proxy:
            self.proxy = new_proxy
            self.raw_proxy = new_proxy
            self.session.proxies = {
                "http": self.proxy,
                "https": self.proxy
            }
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
        while self.current_ip == "Unknown" and retry < 3 and self.running:
            logger.warning(f"⚠️ البروكسي لا يستجيب، إعادة محاولة...")
            time.sleep(5)
            if self.change_proxy():
                self.current_ip = get_ip(self.proxy, timeout=15)
            retry += 1
    
    def login(self):
        if not self.email or not self.password:
            return False
        
        for attempt in range(3):
            try:
                if USE_PROXIES and self.proxy:
                    self.session.proxies = {"http": self.proxy, "https": self.proxy}
                
                token, user_id, balance, credits, msg = do_login(
                    self.email, self.password, self.proxy
                )
                
                if token:
                    self.token = token
                    self.user_id = user_id
                    self.balance = balance
                    self.credits = credits
                    
                    if self.account_id:
                        update_account(
                            self.account_id,
                            token=token,
                            user_id=user_id,
                            balance=balance,
                            credits=credits,
                            last_login=datetime.now().isoformat()
                        )
                    
                    self.coin_id = get_coin_id_by_symbol(self.token, WITHDRAW_COIN, self.proxy)
                    execute_initial_sequence(self.token, self.user_id, self.proxy)
                    
                    logger.info(f"✅ تسجيل الدخول نجح: {self.email}")
                    return True
                
                logger.warning(f"⚠️ محاولة {attempt+1}/3 فشلت: {msg}")
                
                if attempt == 0:
                    logger.info(f"🆕 محاولة تسجيل حساب جديد: {self.email}")
                    success, reg_msg = do_register(self.email, self.password, self.proxy)
                    
                    if success:
                        code = wait_for_code(self.email, self.password, timeout=180)
                        if code:
                            success, token, confirm_msg = do_confirm(self.email, code, self.proxy)
                            if success:
                                user_info = get_user_info(token, self.proxy)
                                if user_info:
                                    self.user_id = user_info.get("_id")
                                    self.balance = user_info.get("balance", 0)
                                    self.credits = user_info.get("credits", 0)
                                
                                self.token = token
                                
                                if self.account_id:
                                    update_account(
                                        self.account_id,
                                        token=token,
                                        user_id=self.user_id,
                                        balance=self.balance,
                                        credits=self.credits,
                                        mail_ok=1,
                                        last_login=datetime.now().isoformat()
                                    )
                                
                                self.coin_id = get_coin_id_by_symbol(self.token, WITHDRAW_COIN, self.proxy)
                                execute_initial_sequence(self.token, self.user_id, self.proxy)
                                
                                logger.info(f"✅ تم إنشاء الحساب: {self.email}")
                                return True
                
                if USE_PROXIES:
                    mark_proxy_failed(self.proxy)
                    self.change_proxy()
                
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"❌ خطأ في تسجيل الدخول {self.email}: {e}")
                time.sleep(5)
        
        logger.error(f"❌ فشل تسجيل الدخول للحساب {self.email}")
        return False
    
    def spin(self):
        try:
            if self.credits <= 0:
                farm_ads(self.user_id, self.proxy)
                time.sleep(random.uniform(1.0, 2.0))
                
                user_info = get_user_info(self.token, self.proxy)
                if user_info:
                    self.credits = user_info.get('credits', 0)
                    self.balance = user_info.get('balance', self.balance)
            
            if self.credits <= 0:
                return None
            
            data = spin_once(self.token, self.proxy)
            if data:
                reward = data.get("total", 0) or 0
                user = data.get("user", {})
                self.balance = user.get("balance", self.balance)
                self.credits = user.get("credits", 0)
                
                if reward > 0:
                    self.total_earned += reward
                    self.spin_count += 1
                
                if self.account_id:
                    add_spin(self.account_id, self.spin_count, reward, self.balance, self.credits)
                    update_account(self.account_id, spin_count=self.spin_count)
                
                self.fail_count = 0
                return data
            
            self.fail_count += 1
            return None
        except Exception as e:
            logger.error(f"خطأ في الدوران {self.email}: {e}")
            self.fail_count += 1
            return None
    
    def check_target(self):
        if not self.account_id:
            return False
        
        self.account = get_account_by_id(self.account_id)
        if not self.account:
            return False
        
        today = datetime.now().strftime("%Y-%m-%d")
        last_date = self.account.get('last_withdraw_date', '') or ''
        
        if last_date and last_date != today:
            new_target = random.randint(MIN_TARGET, MAX_TARGET)
            update_account(
                self.account_id,
                has_withdrawn_today=0,
                target_amount=new_target
            )
            self.account['has_withdrawn_today'] = 0
            self.account['target_amount'] = new_target
            self.stopped = False
            logger.info(f"🔄 تاريخ جديد! الحساب {self.email} استأنف بهدف {new_target:,}")
            return False
        
        if self.account.get('has_withdrawn_today', 0):
            return True
        
        target = self.account.get('target_amount', MIN_TARGET)
        if self.balance >= target:
            return self.withdraw()
        
        return False
    
    def withdraw(self, is_manual=False):
        """السحب التلقائي/اليدوي - مع التحقق من الرصيد + إيميل FaucetPay موحد"""
        if self.balance < MIN_WITHDRAW:
            logger.warning(f"⚠️ الرصيد {self.balance} أقل من الحد الأدنى {MIN_WITHDRAW}")
            return False
        
        if not self.mail_ok:
            logger.warning(f"⚠️ لا يمكن السحب لـ {self.email}: البريد غير متاح")
            return False
        
        amount = int(self.balance)
        mode = "يدوي" if is_manual else "تلقائي"
        
        try:
            faucetpay_email = FAUCETPAY_EMAIL if FAUCETPAY_EMAIL else self.email
            slotfruits_email = self.email
            password = self.password
            
            logger.info(f"💰 سحب {mode}: {amount} من {slotfruits_email} → {faucetpay_email}")
            
            if not self.coin_id:
                self.coin_id = get_coin_id_by_symbol(self.token, WITHDRAW_COIN, self.proxy)
            
            logger.info(f"🔄 تنفيذ التسلسل الأولي...")
            execute_initial_sequence(self.token, self.user_id, self.proxy)
            
            logger.info(f"🧹 مسح الرسائل القديمة لـ {slotfruits_email}")
            try:
                clear_old_slotfruits_messages(slotfruits_email, password)
            except Exception as e:
                logger.warning(f"⚠️ فشل مسح الرسائل القديمة: {e}")
            
            # نطلب كود السحب
            success = False
            coin_id = None
            message = ""
            
            for attempt in range(3):
                if USE_PROXIES and self.proxy:
                    self.session.proxies = {"http": self.proxy, "https": self.proxy}
                
                success, coin_id, message = request_withdrawal_code(
                    self.token, faucetpay_email, amount, 
                    coin_id=self.coin_id,
                    proxy=self.proxy
                )
                
                if success:
                    break
                
                logger.warning(f"⚠️ محاولة {attempt+1}/3 لطلب كود السحب: {message}")
                
                if USE_PROXIES:
                    mark_proxy_failed(self.proxy)
                    self.change_proxy()
                
                time.sleep(5)
            
            if not success:
                logger.error(f"❌ فشل طلب كود السحب: {message}")
                if self.account_id:
                    add_withdrawal(self.account_id, amount, faucetpay_email, "FP", "failed")
                return False
            
            # ننتظر الكود
            logger.info(f"📬 انتظار كود السحب (مبلغ: {amount})...")
            code = wait_for_code(slotfruits_email, password, timeout=180, expected_amount=amount)
            
            if not code:
                logger.error(f"❌ انتهى وقت انتظار كود السحب")
                if self.account_id:
                    add_withdrawal(self.account_id, amount, faucetpay_email, "FP", "failed")
                return False
            
            logger.info(f"✅ تم استلام الكود: {code}")
            
            # نأكد السحب
            success, result, error = confirm_withdrawal(
                self.token, faucetpay_email, amount, code,
                coin_id=coin_id,
                proxy=self.proxy
            )
            
            if not success:
                logger.error(f"❌ فشل التأكيد: {error}")
                
                if self.account_id:
                    add_withdrawal(self.account_id, amount, faucetpay_email, "FP", "failed")
                
                safe_notify(
                    f"❌ <b>فشل السحب ({mode})</b>\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"📧 {self.email}\n"
                    f"💸 إلى: {faucetpay_email}\n"
                    f"💰 المبلغ: {amount:,.0f}\n"
                    f"⚠️ <b>السبب:</b> {error}"
                )
                return False
            
            # نتحقق من الرصيد
            logger.info(f"🔍 التحقق من الرصيد بعد السحب...")
            time.sleep(3)
            
            balance_before = self.balance
            verified_balance = None
            
            for verify_attempt in range(3):
                user_info = get_user_info(self.token, self.proxy)
                if user_info:
                    verified_balance = user_info.get("balance", balance_before)
                    break
                time.sleep(2)
            
            if verified_balance is None:
                verified_balance = balance_before
            
            balance_decreased = verified_balance < balance_before - 10
            
            if not balance_decreased:
                logger.error(f"❌ السحب مش اتم! الرصيد: {verified_balance}")
                
                if self.account_id:
                    add_withdrawal(self.account_id, amount, faucetpay_email, "FP", "failed")
                
                safe_notify(
                    f"❌ <b>فشل السحب ({mode})</b>\n"
                    f"📧 {self.email}\n"
                    f"💰 المطلوب: {amount:,.0f}\n"
                    f"💰 الحالي: {verified_balance:,.0f}\n"
                    f"⚠️ <b>السحب لم يتم</b>"
                )
                return False
            
            actual_amount = balance_before - verified_balance
            logger.info(f"✅ السحب اتم! الرصيد: {verified_balance}")
            
            # ✅ حفظ النتيجة (مختلف بين يدوي وتلقائي)
            if self.account_id:
                add_withdrawal(self.account_id, actual_amount, faucetpay_email, "FP", "completed")
                
                today = datetime.now().strftime("%Y-%m-%d")
                
                if is_manual:
                    # ✅ سحب يدوي: لا نوقف الحساب
                    update_account(
                        self.account_id,
                        balance=verified_balance,
                        withdrawal_count=(self.account.get('withdrawal_count', 0) + 1),
                        last_withdrawal=datetime.now().isoformat()
                    )
                    logger.info(f"✅ سحب يدوي - الحساب مستمر")
                else:
                    # سحب تلقائي: نوقف لحد الغد
                    update_account(
                        self.account_id,
                        balance=verified_balance,
                        withdrawal_count=(self.account.get('withdrawal_count', 0) + 1),
                        last_withdrawal=datetime.now().isoformat(),
                        has_withdrawn_today=1,
                        last_withdraw_date=today
                    )
                    logger.info(f"✅ سحب تلقائي - الحساب موقوف لليوم")
            
            self.balance = verified_balance
            
            safe_notify(
                f"💰 <b>تم السحب بنجاح ({mode})!</b>\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"📧 {self.email}\n"
                f"💸 إلى: {faucetpay_email}\n"
                f"💰 المبلغ: {actual_amount:,.0f}\n"
                f"💰 الرصيد الجديد: {verified_balance:,.0f}\n"
                f"🌐 IP: {self.current_ip}\n"
                f"{'▶️ الحساب مستمر' if is_manual else '⏸️ الحساب موقوف لليوم'}"
            )
            
            return True
        
        except Exception as e:
            logger.error(f"❌ خطأ في السحب {self.email}: {e}")
            
            if self.account_id:
                add_withdrawal(self.account_id, amount, 
                               FAUCETPAY_EMAIL if FAUCETPAY_EMAIL else self.email, 
                               "FP", "failed")
            return False
    
    def run(self):
        self.init_network()
        
        if not self.login():
            self.running = False
            return
        
        self.running = True
        
        while self.running and not is_shutting_down:
            try:
                # ✅ فحص قبل السحب التلقائي
                self.account = get_account_by_id(self.account_id)
                has_withdrawn = self.account.get('has_withdrawn_today', 0) if self.account else 0
                
                if not has_withdrawn and self.check_target():
                    self.stopped = True
                    logger.info(f"⏸️ الحساب {self.email} متوقف بعد السحب التلقائي")
                    
                    while self.stopped and self.running and not is_shutting_down:
                        time.sleep(60)
                        
                        today = datetime.now().strftime("%Y-%m-%d")
                        self.account = get_account_by_id(self.account_id)
                        if self.account:
                            last_date = self.account.get('last_withdraw_date', '') or ''
                            if last_date and last_date != today:
                                self.stopped = False
                                logger.info(f"🔄 الحساب {self.email} استأنف بيوم جديد")
                                break
                    continue
                
                for _ in range(5):
                    if not self.running or self.stopped or is_shutting_down:
                        return
                    
                    result = self.spin()
                    
                    if result is None and self.fail_count >= self.max_fails:
                        logger.warning(f"⚠️ فشل متكرر، تغيير البروكسي...")
                        if USE_PROXIES:
                            if self.change_proxy():
                                if self.login():
                                    self.fail_count = 0
                        break
                    
                    time.sleep(random.uniform(1.0, 4.0))
                
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
                
                time.sleep(random.uniform(3.0, 8.0))
            except Exception as e:
                logger.error(f"❌ خطأ في حلقة {self.email}: {e}")
                time.sleep(10)
        
        self.running = False
        logger.info(f"⏹️ توقف الحساب {self.email}")


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
    
    def start_account(self, account_id):
        with worker_lock:
            if account_id in self.workers:
                worker = self.workers[account_id]
                if worker.running:
                    return False
            
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
                    logger.info(f"🔀 Session proxy للحساب {account_id}")
                else:
                    proxy_index = account_id % len(proxies)
                    proxy = proxies[proxy_index]
                    logger.info(f"🌐 Proxy #{proxy_index} للحساب {account_id}")
            
            worker = AccountWorker(
                email=account['email'],
                password=account['password'],
                proxy=proxy,
                index=proxy_index,
                account_id=account_id
            )
            
            if proxy:
                update_account(account_id, proxy=proxy, proxy_index=proxy_index)
            
            self.workers[account_id] = worker
            
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()
            self.threads[account_id] = thread
            
            return True
    
    def stop_account(self, account_id):
        with worker_lock:
            if account_id not in self.workers:
                return False
            
            worker = self.workers[account_id]
            worker.running = False
            worker.stopped = True
            
            if account_id in self.threads:
                try:
                    self.threads[account_id].join(timeout=5)
                except:
                    pass
                del self.threads[account_id]
            
            del self.workers[account_id]
            return True
    
    def start_all(self):
        accounts = get_all_accounts(active_only=True)
        started = 0
        
        for acc in accounts:
            if self.start_account(acc['id']):
                started += 1
                time.sleep(0.5)
        
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
        running = len(self.workers)
        
        total_balance = 0
        details = []
        
        for acc in accounts:
            total_balance += acc.get('balance', 0)
            
            worker = self.workers.get(acc['id'])
            mail_ok = bool(acc.get('mail_ok', 0))
            
            if worker:
                status_icon = "🟢"
                if worker.stopped:
                    status_icon = "✅"
                current_ip = worker.current_ip
                balance = worker.balance
                credits = worker.credits
                target = worker.account.get('target_amount', 0) if worker.account else 0
            else:
                status_icon = "🔴"
                if acc.get('has_withdrawn_today', 0):
                    status_icon = "✅"
                
                proxy = acc.get('proxy')
                current_ip = get_cached_ip(proxy) if proxy else "بدون"
                balance = acc.get('balance', 0)
                credits = acc.get('credits', 0)
                target = acc.get('target_amount', 0)
            
            details.append({
                'id': acc['id'],
                'email': acc['email'],
                'status_icon': status_icon,
                'balance': balance,
                'credits': credits,
                'target': target,
                'ip': current_ip,
                'mail_ok': mail_ok
            })
        
        return {
            'total_accounts': total,
            'running_accounts': running,
            'total_balance': total_balance,
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
        
        mail_ok_count = sum(1 for d in status['details'] if d['mail_ok'])
        mail_bad_count = total_accounts - mail_ok_count
        
        fp_display = FAUCETPAY_EMAIL if FAUCETPAY_EMAIL else "غير محدد"
        
        text = (
            f"📊 <b>لوحة التحكم</b> (صفحة {page+1}/{total_pages})\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📧 إجمالي الحسابات: {status['total_accounts']}\n"
            f"🟢 النشطة: {status['running_accounts']}\n"
            f"💰 الرصيد الكلي: {status['total_balance']:,.0f}\n"
            f"💸 إيميل السحب: <code>{fp_display}</code>\n"
            f"🎯 العملة: <b>{WITHDRAW_COIN.upper()}</b>\n"
            f"📬 بريد شغال: {mail_ok_count} | 📭 مش شغال: {mail_bad_count}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"<b>تفاصيل الحسابات:</b>\n"
        )
        
        if status['details']:
            for detail in status['details'][start:end]:
                mail_icon = "📬" if detail['mail_ok'] else "📭"
                text += (
                    f"{detail['status_icon']} <b>{detail['id']}</b> {mail_icon} | "
                    f"{detail['email'][:15]}\n"
                    f"   💰{detail['balance']:,.0f} | "
                    f"🎯{detail['credits']} | "
                    f"🎯{detail['target']:,}\n"
                    f"   🌐 IP: <code>{detail['ip']}</code>\n"
                )
        else:
            text += "⚠️ لا توجد حسابات"
        
        text += f"\n━━━━━━━━━━━━━━━━━\n🔄 {datetime.now().strftime('%H:%M:%S')}"
        
        return text, page, total_pages


bot_manager = BotManager()


# ============================================================
# دالة الإضافة الذكية
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
        
        if progress_msg:
            try:
                await progress_msg.edit_text(
                    f"🔍 <b>التحقق من الحساب...</b>\n📧 {email}",
                    parse_mode="HTML"
                )
            except:
                pass
        
        account_check = check_account_exists_in_slotfruits(email, password, proxy)
        logger.info(f"📊 نتيجة التحقق لـ {email}: {account_check}")
        
        # ========== الحالة ١: الحساب موجود ==========
        if account_check.get("exists"):
            logger.info(f"✅ الحساب {email} موجود")
            
            mail_ok = False
            try:
                mail_success, mail_token = ensure_mail_account(email, password)
                if mail_success:
                    mail_ok = True
                    start_mail_monitor(email, password)
                    logger.info(f"📬 البريد شغال لـ {email}")
            except Exception as e:
                logger.error(f"خطأ في التحقق من البريد: {e}")
            
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
                    mail_ok=1 if mail_ok else 0,
                    account_type='existing'
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
                    mail_ok=1 if mail_ok else 0,
                    account_type='existing'
                )
                action = "إضافة"
            
            if account_id:
                bot_manager.start_account(account_id)
                
                if progress_msg and not silent:
                    try:
                        await progress_msg.edit_text(
                            f"✅ <b>تم {action} الحساب!</b>\n"
                            f"🆔 ID: {account_id}\n"
                            f"📧 {email}\n"
                            f"💰 الرصيد: {account_check.get('balance', 0):,.0f}\n"
                            f"💸 سحب إلى: {FAUCETPAY_EMAIL}\n"
                            f"📬 البريد: {'✅' if mail_ok else '❌'}",
                            parse_mode="HTML"
                        )
                    except:
                        pass
                return True
        
        # ========== الحالة ٢: محتاج تأكيد ==========
        if account_check.get("needs_confirmation"):
            logger.info(f"⚠️ الحساب {email} محتاج تأكيد")
            
            mail_ok, mail_token = ensure_mail_account(email, password)
            if not mail_ok:
                return False
            
            clear_old_slotfruits_messages(email, password)
            start_mail_monitor(email, password)
            do_register(email, password, proxy)
            
            code = wait_for_code(email, password, timeout=180)
            if not code:
                return False
            
            success, token, confirm_msg = do_confirm(email, code, proxy)
            if not success:
                return False
            
            user_info = get_user_info(token, proxy)
            if user_info:
                user_id_api = user_info.get("_id")
                balance = user_info.get("balance", 0)
                credits = user_info.get("credits", 0)
            else:
                user_id_api = None
                balance = 0
                credits = 0
            
            existing = get_account_by_email(email)
            
            if existing:
                update_account(
                    existing['id'],
                    token=token, user_id=user_id_api,
                    balance=balance, credits=credits,
                    last_login=datetime.now().isoformat(),
                    is_active=1, proxy=proxy, proxy_index=proxy_index,
                    mail_ok=1, account_type='confirmed'
                )
                account_id = existing['id']
            else:
                account_id = add_account(
                    email, password, token, user_id_api, balance, credits,
                    proxy, proxy_index, mail_ok=1, account_type='confirmed'
                )
            
            if account_id:
                bot_manager.start_account(account_id)
                if progress_msg and not silent:
                    try:
                        await progress_msg.edit_text(
                            f"✅ <b>تم التأكيد!</b>\n"
                            f"🆔 ID: {account_id}\n"
                            f"📧 {email}\n"
                            f"💸 سحب إلى: {FAUCETPAY_EMAIL}",
                            parse_mode="HTML"
                        )
                    except:
                        pass
                return True
            return False
        
        # ========== الحالة ٣: حساب جديد ==========
        if account_check.get("not_found"):
            logger.info(f"🆕 الحساب {email} جديد")
            
            mail_ok, mail_token = ensure_mail_account(email, password)
            if not mail_ok:
                return False
            
            clear_old_slotfruits_messages(email, password)
            start_mail_monitor(email, password)
            
            success, reg_msg = do_register(email, password, proxy)
            if not success:
                return False
            
            code = wait_for_code(email, password, timeout=180)
            if not code:
                return False
            
            success, token, confirm_msg = do_confirm(email, code, proxy)
            if not success:
                return False
            
            user_info = get_user_info(token, proxy)
            if user_info:
                user_id_api = user_info.get("_id")
                balance = user_info.get("balance", 0)
                credits = user_info.get("credits", 0)
            else:
                user_id_api = None
                balance = 0
                credits = 0
            
            account_id = add_account(
                email, password, token, user_id_api, balance, credits,
                proxy, proxy_index, mail_ok=1, account_type='new'
            )
            
            if account_id:
                bot_manager.start_account(account_id)
                if progress_msg and not silent:
                    try:
                        await progress_msg.edit_text(
                            f"✅ <b>تم إنشاء الحساب!</b>\n"
                            f"🆔 ID: {account_id}\n"
                            f"📧 {email}\n"
                            f"💰 الرصيد: {balance:,.0f}\n"
                            f"💸 سحب إلى: {FAUCETPAY_EMAIL}",
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
        logger.error(f"خطأ في add_single_account: {e}")
        if progress_msg and not silent:
            try:
                await progress_msg.edit_text(f"❌ خطأ: {str(e)[:80]}")
            except:
                pass
        return False


# ============================================================
# دوال التليجرام
# ============================================================
def get_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 تشغيل الكل", callback_data="start_all")],
        [InlineKeyboardButton("⏹️ إيقاف الكل", callback_data="stop_all")],
        [InlineKeyboardButton("📊 لوحة التحكم", callback_data="dashboard_0")],
        [InlineKeyboardButton("➕ إضافة حساب", callback_data="add_account")],
        [InlineKeyboardButton("➕➕ إضافة حسابات متعددة", callback_data="add_multiple_accounts")],
        [InlineKeyboardButton("🗑️ حذف حساب", callback_data="delete_account")],
        [InlineKeyboardButton("🌐 إدارة البروكسيات", callback_data="proxies_menu")],
        [InlineKeyboardButton("💰 سحب يدوي", callback_data="manual_withdraw")],
        [InlineKeyboardButton("📥 حالات السحب", callback_data="withdrawal_status")],
    ])


async def show_main_menu(update, context, chat_id):
    status = bot_manager.get_status()
    fp_display = FAUCETPAY_EMAIL if FAUCETPAY_EMAIL else "غير محدد"
    
    main_text = (
        f"🎰 <b>Slot Bot - لوحة التحكم</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📧 الحسابات: {status['total_accounts']}\n"
        f"🟢 النشطة: {status['running_accounts']}\n"
        f"💰 الرصيد الكلي: {status['total_balance']:,.0f}\n"
        f"💸 السحب إلى: <code>{fp_display}</code>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"اختر الإجراء المناسب:"
    )
    
    if update and update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                main_text,
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
        except:
            await context.bot.send_message(
                chat_id=chat_id,
                text=main_text,
                reply_markup=get_main_keyboard(),
                parse_mode="HTML"
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=main_text,
            reply_markup=get_main_keyboard(),
            parse_mode="HTML"
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_chat_id, bot_application
    
    bot_chat_id = update.message.chat_id
    bot_application = context.application
    bot_manager.chat_id = update.message.chat_id
    
    await show_main_menu(None, context, update.message.chat_id)


# ============================================================
# معالج الأزرار
# ============================================================
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
        started = bot_manager.start_all()
        await query.edit_message_text(f"🚀 تم تشغيل {started} حساب")
        await asyncio.sleep(1)
        await show_main_menu(update, context, query.message.chat_id)
    
    elif data == "stop_all":
        stopped = bot_manager.stop_all()
        await query.edit_message_text(f"⏹️ تم إيقاف {stopped} حساب")
        await asyncio.sleep(1)
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
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    
    elif data == "add_account":
        pending_emails[user_id] = "waiting_for_account"
        await query.edit_message_text(
            f"📝 <b>إضافة حساب جديد</b>\n\n"
            f"أرسل الإيميل وكلمة المرور:\n"
            f"<code>email password</code>\n\n"
            f"💸 سيتم السحب إلى: <code>{FAUCETPAY_EMAIL}</code>\n\n"
            f"🔙 لإلغاء العملية أرسل /cancel",
            parse_mode="HTML"
        )
    
    elif data == "add_multiple_accounts":
        pending_emails[user_id] = "waiting_for_multiple_accounts"
        await query.edit_message_text(
            f"📝 <b>إضافة حسابات متعددة</b>\n\n"
            f"أرسل قائمة (كل حساب في سطر):\n"
            f"<code>email1 password1</code>\n"
            f"<code>email2 password2</code>\n\n"
            f"⚡ كل حساب في Thread مستقل\n"
            f"💸 كلهم سحب إلى: <code>{FAUCETPAY_EMAIL}</code>\n\n"
            f"🔙 للإلغاء أرسل /cancel",
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
            await query.edit_message_text(f"✅ تم حذف الحساب: {account['email']}")
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
            f"🌐 <b>إدارة البروكسيات</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📊 المجموع: {len(proxies)}\n"
            f"🔀 الوضع: <b>{mode}</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    
    elif data == "view_proxies":
        proxies = load_proxies()
        if not proxies:
            await query.edit_message_text("📭 لا يوجد بروكسيات!")
            return
        
        await query.edit_message_text(f"🔄 جاري جلب IP لـ {len(proxies)} بروكسي...")
        
        text = "🌐 <b>قائمة البروكسيات</b>\n━━━━━━━━━━━━━━━━━\n"
        for i, p in enumerate(proxies, 1):
            session_icon = "🔀" if is_session_proxy(p) else "🌐"
            ip = get_cached_ip(p)
            status = "✅" if ip and ip != "Unknown" else "❌"
            p_display = p[:70] + "..." if len(p) > 70 else p
            text += f"{i}. {status} {session_icon} <code>{p_display}</code>\n   🌐 IP: <code>{ip}</code>\n\n"
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    
    elif data == "add_proxies":
        pending_emails[user_id] = "waiting_for_proxies"
        await query.edit_message_text(
            "📝 <b>إضافة بروكسيات</b>\n\n"
            "أرسل قائمة البروكسيات (كل بروكسي في سطر):\n"
            "<code>http://user:pass@host:port</code>\n\n"
            "🔙 للإلغاء أرسل /cancel",
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
                    await query.edit_message_text(text + "\n⏳ جاري الاختبار...", parse_mode="HTML")
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
            "🗑️ <b>اختر البروكسي للحذف:</b>",
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
                await query.edit_message_text(f"✅ تم حذف البروكسي")
            else:
                await query.edit_message_text("❌ لم يتم العثور عليه")
        else:
            await query.edit_message_text("❌ بروكسي غير صالح")
        
        await asyncio.sleep(1)
        await button_handler(update, context)
    
    elif data == "manual_withdraw":
        accounts = get_all_accounts()
        available = [a for a in accounts if a.get('balance', 0) >= MIN_WITHDRAW and a.get('mail_ok', 0)]
        
        if not available:
            have_balance = [a for a in accounts if a.get('balance', 0) >= MIN_WITHDRAW]
            if have_balance:
                await query.edit_message_text(
                    f"⚠️ لا يوجد حسابات جاهزة للسحب\n"
                    f"• {len(have_balance)} حساب عندها رصيد كافٍ\n"
                    f"• لكن البريد غير متاح",
                    parse_mode="HTML"
                )
            else:
                await query.edit_message_text(f"⚠️ لا يوجد حسابات قابلة للسحب (الحد: {MIN_WITHDRAW:,})")
            return
        
        keyboard = []
        for acc in available[:25]:
            keyboard.append([InlineKeyboardButton(
                f"💰 {acc['email'][:25]} ({acc['balance']:,.0f})",
                callback_data=f"wd_now_{acc['id']}"
            )])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
        
        await query.edit_message_text(
            f"💰 <b>اختر الحساب للسحب:</b>\n"
            f"💸 سيتم السحب إلى: <code>{FAUCETPAY_EMAIL}</code>\n"
            f"▶️ <b>الحساب سيفضل شغال بعد السحب</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    
    # ✅ السحب اليدوي - لا يوقف الحساب
    elif data.startswith("wd_now_"):
        account_id = int(data.split("_")[2])
        account = get_account_by_id(account_id)
        
        if not account:
            await query.edit_message_text("❌ الحساب غير موجود")
            return
        
        if account.get('balance', 0) < MIN_WITHDRAW:
            await query.edit_message_text(f"❌ الرصيد أقل من الحد الأدنى {MIN_WITHDRAW}")
            return
        
        if not account.get('mail_ok', 0):
            await query.edit_message_text("❌ البريد غير متاح لهذا الحساب")
            return
        
        # ✅ نحفظ حالة الـ worker الأصلي
        original_worker = bot_manager.workers.get(account_id)
        was_running = original_worker is not None and original_worker.running
        
        if was_running:
            original_worker.running = False
            time.sleep(1)
        
        await query.edit_message_text(
            f"🔄 <b>جاري السحب اليدوي...</b>\n"
            f"💸 إلى: {FAUCETPAY_EMAIL}\n"
            f"▶️ الحساب سيفضل شغال بعد السحب",
            parse_mode="HTML"
        )
        
        # نستخدم worker مؤقت
        proxies = load_proxies()
        proxy = account.get('proxy')
        if proxies and SESSION_BASED_PROXY and is_session_proxy(proxies[0]):
            proxy = build_session_proxy(account_id, proxies[0], SESSION_PREFIX)
        
        temp_worker = AccountWorker(
            email=account['email'],
            password=account['password'],
            proxy=proxy,
            index=account.get('proxy_index', 0),
            account_id=account_id
        )
        temp_worker.token = account.get('token')
        temp_worker.user_id = account.get('user_id')
        temp_worker.balance = account.get('balance', 0)
        temp_worker.credits = account.get('credits', 0)
        temp_worker.account = account
        temp_worker.mail_ok = True
        
        temp_worker.coin_id = get_coin_id_by_symbol(temp_worker.token, WITHDRAW_COIN, temp_worker.proxy)
        
        # ✅ سحب يدوي
        success = temp_worker.withdraw(is_manual=True)
        
        updated_account = get_account_by_id(account_id)
        new_balance = updated_account.get('balance', 0) if updated_account else 0
        
        if success:
            await query.edit_message_text(
                f"✅ <b>تم السحب بنجاح!</b>\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"💸 إلى: {FAUCETPAY_EMAIL}\n"
                f"💰 الرصيد الجديد: {new_balance:,.0f}\n"
                f"📊 عدد السحوبات: {updated_account.get('withdrawal_count', 0) if updated_account else 0}\n"
                f"▶️ الحساب مستمر في العمل",
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text(
                f"❌ <b>فشل السحب</b>\n"
                f"━━━━━━━━━━━━━━━━━\n"
                f"💸 إلى: {FAUCETPAY_EMAIL}\n"
                f"💰 الرصيد الحالي: {new_balance:,.0f}\n"
                f"▶️ الحساب مستمر في العمل",
                parse_mode="HTML"
            )
        
        # ✅ نرجع الـ worker الأصلي
        if was_running and original_worker and account_id in bot_manager.workers:
            original_worker.running = True
            original_worker.stopped = False
            original_worker.balance = new_balance
            logger.info(f"▶️ الحساب {account['email']} استأنف العمل")
        
        await asyncio.sleep(2)
        await show_main_menu(update, context, query.message.chat_id)
    
    elif data == "withdrawal_status":
        accounts = get_all_accounts()
        if not accounts:
            await query.edit_message_text("📭 لا يوجد حسابات!")
            return
        
        keyboard = []
        for acc in accounts[:25]:
            keyboard.append([InlineKeyboardButton(
                f"📥 {acc['email'][:25]} ({acc.get('withdrawal_count', 0)})",
                callback_data=f"wd_status_{acc['id']}"
            )])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
        
        await query.edit_message_text(
            "📥 <b>اختر الحساب لعرض السحوبات:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    
    # ✅ عرض حالات السحب من API
    elif data.startswith("wd_status_"):
        account_id = int(data.split("_")[2])
        account = get_account_by_id(account_id)
        
        if not account:
            await query.edit_message_text("❌ الحساب غير موجود")
            return
        
        await query.edit_message_text(
            f"🔄 <b>جاري جلب السحوبات من SlotFruits...</b>\n"
            f"⏳ ممكن ياخد 10-20 ثانية",
            parse_mode="HTML"
        )
        
        token = account.get('token')
        proxy = account.get('proxy')
        
        mail_icon = "✅" if account.get('mail_ok', 0) else "❌"
        has_wd = "✅ نعم" if account.get('has_withdrawn_today', 0) else "❌ لا"
        
        text = (
            f"📥 <b>سحوبات الحساب</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📧 {account['email']}\n"
            f"💰 الرصيد: {account.get('balance', 0):,.0f}\n"
            f"📊 عدد السحوبات: {account.get('withdrawal_count', 0)}\n"
            f"📬 البريد: {mail_icon}\n"
            f"💸 يرسل إلى: <code>{FAUCETPAY_EMAIL}</code>\n"
            f"🎯 سحب اليوم: {has_wd}\n"
            f"📅 آخر سحب: {account.get('last_withdraw_date', 'لا يوجد') or 'لا يوجد'}\n"
            f"━━━━━━━━━━━━━━━━━\n"
        )
        
        # نجرب نجيب من API
        api_results = []
        if token:
            api_results = find_withdrawals_endpoint(token, proxy)
        
        if api_results:
            best = api_results[0]
            text += f"\n✅ <b>المصدر:</b> {best['kind']}\n"
            text += f"🔗 <code>{best['url'][:70]}</code>\n"
            text += f"📊 <b>عدد السحوبات:</b> {best['count']}\n"
            text += f"━━━━━━━━━━━━━━━━━\n\n"
            text += format_withdrawals(best['items'], WITHDRAW_COIN.upper())
            
            if len(api_results) > 1:
                text += f"\n💡 في {len(api_results) - 1} مصدر تاني متاح"
        else:
            text += "\n⚠️ <b>لم يتم العثور على API</b>\n"
            text += "بنعرض السحوبات المحلية:\n\n"
            
            local = get_withdrawals(account_id, limit=10)
            if local:
                for i, wd in enumerate(local, 1):
                    status = wd.get('status', 'unknown')
                    icon = "✅" if status == 'completed' else ("❌" if status == 'failed' else "⏳")
                    stext = {'completed': 'مدفوع', 'failed': 'مرفوض', 'pending': 'معلق'}.get(status, status)
                    text += (
                        f"{icon} <b>سحب #{i}</b> — <b>{stext}</b>\n"
                        f"   💰 {wd.get('amount', 0):,.0f}\n"
                        f"   📅 {wd.get('created_at', '')[:19]}\n"
                        f"   ─────────────\n"
                    )
            else:
                text += "📭 لا توجد سحوبات مسجلة"
        
        keyboard = [
            [InlineKeyboardButton("🔄 تحديث", callback_data=f"wd_status_{account_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="withdrawal_status")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    
    elif data == "back_main":
        await show_main_menu(update, context, query.message.chat_id)


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
        f"━━━━━━━━━━━━━━━━━\n"
        f"📧 إجمالي: {total}\n"
        f"📄 صفحة {page+1}/{total_pages}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


# ============================================================
# معالج الرسائل النصية
# ============================================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if text == "/cancel":
        if user_id in pending_emails:
            del pending_emails[user_id]
        await update.message.reply_text("❌ تم إلغاء العملية!")
        return
    
    action = pending_emails.get(user_id)
    
    if action == "waiting_for_account":
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ صيغة غير صحيحة.\nأرسل: <code>email password</code>",
                parse_mode="HTML"
            )
            return
        
        email = parts[0]
        password = " ".join(parts[1:])
        
        if not email or not password or len(password) < 6:
            await update.message.reply_text("❌ إيميل أو كلمة مرور غير صالحة")
            return
        
        del pending_emails[user_id]
        
        progress = await update.message.reply_text(
            f"🔄 <b>جاري إضافة الحساب...</b>\n📧 {email}\n💸 سحب إلى: {FAUCETPAY_EMAIL}",
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
            await update.message.reply_text("❌ لم يتم العثور على حسابات صالحة.")
            del pending_emails[user_id]
            return
        
        del pending_emails[user_id]
        
        total = len(accounts_data)
        proxies = load_proxies()
        session_mode = proxies and SESSION_BASED_PROXY and is_session_proxy(proxies[0])
        
        progress = await update.message.reply_text(
            f"🚀 <b>بدء إضافة {total} حساب</b>\n"
            f"🌐 الوضع: {'🔀 Session' if session_mode else '🌐 عادي'}\n"
            f"💸 السحب إلى: <code>{FAUCETPAY_EMAIL}</code>",
            parse_mode="HTML"
        )
        
        results = {}
        results_lock = threading.Lock()
        account_counter = [0]
        counter_lock = threading.Lock()
        
        def process_account(idx, email, password):
            try:
                with counter_lock:
                    account_number = account_counter[0]
                    account_counter[0] += 1
                
                assigned_proxy = None
                assigned_proxy_index = 0
                
                if USE_PROXIES and proxies:
                    base_proxy = proxies[0]
                    if SESSION_BASED_PROXY and is_session_proxy(base_proxy):
                        temp_id = int(time.time() * 1000) % 1000000 + account_number
                        assigned_proxy = build_session_proxy(temp_id, base_proxy, SESSION_PREFIX)
                    else:
                        assigned_proxy_index = account_number % len(proxies)
                        assigned_proxy = proxies[assigned_proxy_index]
                
                success = asyncio.run(
                    add_single_account(
                        email, password, None, silent=True,
                        forced_proxy=assigned_proxy,
                        forced_proxy_index=assigned_proxy_index
                    )
                )
                
                with results_lock:
                    results[idx] = {
                        "email": email,
                        "success": success,
                        "proxy_index": assigned_proxy_index
                    }
            except Exception as e:
                logger.error(f"❌ خطأ في Thread {idx}: {e}")
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
                        f"⏳ منتهي: {done}/{total}\n"
                        f"✅ نجح: {success_count}\n"
                        f"❌ فشل: {fail_count}\n"
                        f"🔄 قيد التنفيذ: {len(alive)}",
                        parse_mode="HTML"
                    )
                except:
                    pass
                
                last_update = time.time()
            
            await asyncio.sleep(1)
        
        for t in threads:
            t.join(timeout=2)
        
        with results_lock:
            success_count = sum(1 for r in results.values() if r.get("success"))
            fail_count = total - success_count
            success_list = [r for r in results.values() if r.get('success')]
            fail_list = [r for r in results.values() if not r.get('success')]
        
        summary = (
            f"📊 <b>النتيجة النهائية</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"✅ نجح: {success_count}\n"
            f"❌ فشل: {fail_count}\n"
            f"📝 إجمالي: {total}\n"
            f"💸 السحب إلى: {FAUCETPAY_EMAIL}\n"
        )
        
        if success_list:
            summary += "\n<b>✅ الناجحة:</b>\n"
            for r in success_list[:10]:
                summary += f"• {r['email'][:30]}\n"
        
        if fail_list:
            summary += "\n<b>❌ الفاشلة:</b>\n"
            for r in fail_list[:10]:
                summary += f"• {r['email'][:30]}\n"
        
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
            await update.message.reply_text("⚠️ لم يتم إضافة أي بروكسي جديد")
        
        del pending_emails[user_id]
        await show_main_menu(None, context, update.message.chat_id)
    
    else:
        await update.message.reply_text("❌ أمر غير معروف. استخدم /start للبدء.")


# ============================================================
# أوامر إضافية
# ============================================================
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in pending_emails:
        del pending_emails[user_id]
    await update.message.reply_text("❌ تم إلغاء العملية!")


async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_manager.chat_id = update.message.chat_id
    text, page, total = bot_manager.dashboard_text(0)
    
    keyboard = []
    if total > 1:
        keyboard.append([InlineKeyboardButton("التالي ➡️", callback_data="dashboard_1")])
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
        parse_mode="HTML"
    )


# ============================================================
# الوظيفة الرئيسية
# ============================================================
def main():
    global bot_application, is_shutting_down, main_event_loop
    
    init_database()
    
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ الرجاء تعيين BOT_TOKEN في config.json")
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
    
    print("🎰 Starting Slot Bot - النسخة النهائية")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("✅ Bot is running! Press Ctrl+C to stop")
    print(f"💰 إيميل السحب: {FAUCETPAY_EMAIL}")
    print(f"🎯 العملة: {WITHDRAW_COIN.upper()}")
    print(f"🌐 وضع البروكسي: {'Session (Bright Data)' if session_mode else 'عادي'}")
    print(f"📊 عدد البروكسيات: {len(proxies)}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("✅ get_coin_id (ديناميكي): مفعل")
    print("✅ execute_initial_sequence: مفعل")
    print("✅ مراقبة البريد: مفعل")
    print("✅ مسح الرسائل القديمة: مفعل")
    print("✅ التحقق من الرصيد بعد السحب: مفعل")
    print("✅ Session Proxy: مفعل")
    print("✅ إيميل FaucetPay موحد: مفعل")
    print("✅ السحب اليدوي لا يوقف الحساب: مفعل")
    print("✅ عرض حالات السحب من API: مفعل")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        is_shutting_down = True
        bot_manager.stop_all()
        print("✅ All accounts stopped")
        print("👋 Goodbye!")


if __name__ == "__main__":
    main()
