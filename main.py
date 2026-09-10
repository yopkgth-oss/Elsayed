#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Slot Bot - النسخة النهائية
دمج Slots + Espin مع جميع الميزات
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
        "timeout": 30,
        "min_withdraw": 1000,
        "min_target": 55000,
        "max_target": 65000,
        "use_proxies": True,
        "database_file": "accounts.db",
        "items_per_page": 25
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
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
TIMEOUT = CONFIG.get("timeout", 30)
MIN_WITHDRAW = CONFIG.get("min_withdraw", 1000)
MIN_TARGET = CONFIG.get("min_target", 55000)
MAX_TARGET = CONFIG.get("max_target", 65000)
USE_PROXIES = CONFIG.get("use_proxies", True)
DATABASE_FILE = CONFIG.get("database_file", "accounts.db")
ITEMS_PER_PAGE = CONFIG.get("items_per_page", 25)

API_URL = f"{BASE_URL}/api/v1"
GRAPHQL_URL = f"{BASE_URL}/graphql"

# ============================================================
# متغيرات عامة
# ============================================================
bot_application = None
bot_chat_id = None
is_shutting_down = False
pending_emails = {}  # {user_id: action}

# 🔒 أقفال
mail_lock = threading.Lock()
worker_lock = threading.Lock()
proxy_lock = threading.Lock()
ip_cache_lock = threading.Lock()

# كاش للـ IP
ip_cache = {}

# فشل البروكسيات
proxy_failures = {}

# ============================================================
# قاعدة البيانات (SQLite)
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
            proxy_index INTEGER DEFAULT 0
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

def get_account_by_id(account_id):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            columns = ['id', 'email', 'password', 'token', 'user_id', 'balance', 'credits', 
                       'total_earned', 'created_at', 'last_login', 'is_active', 'withdrawal_count',
                       'last_withdrawal', 'proxy', 'spin_count', 'target_amount', 
                       'has_withdrawn_today', 'last_withdraw_date', 'proxy_index']
            return dict(zip(columns, row))
        return None
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
        if row:
            columns = ['id', 'email', 'password', 'token', 'user_id', 'balance', 'credits', 
                       'total_earned', 'created_at', 'last_login', 'is_active', 'withdrawal_count',
                       'last_withdrawal', 'proxy', 'spin_count', 'target_amount', 
                       'has_withdrawn_today', 'last_withdraw_date', 'proxy_index']
            return dict(zip(columns, row))
        return None
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
        columns = ['id', 'email', 'password', 'token', 'user_id', 'balance', 'credits', 
                   'total_earned', 'created_at', 'last_login', 'is_active', 'withdrawal_count',
                   'last_withdrawal', 'proxy', 'spin_count', 'target_amount', 
                   'has_withdrawn_today', 'last_withdraw_date', 'proxy_index']
        return [dict(zip(columns, row)) for row in rows]
    except:
        return []

def add_account(email, password, token=None, user_id=None, balance=0, credits=0, proxy=None, proxy_index=0):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        target = random.randint(MIN_TARGET, MAX_TARGET)
        cursor.execute("""
            INSERT INTO accounts (email, password, token, user_id, balance, credits, created_at, proxy, target_amount, proxy_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (email, password, token, user_id, balance, credits, datetime.now().isoformat(), proxy, target, proxy_index))
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

def add_withdrawal(account_id, amount, address, wallet_type="FP", status="pending"):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO withdrawals (account_id, amount, address, wallet_type, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (account_id, amount, address, wallet_type, status, datetime.now().isoformat()))
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
# نظام البروكسيات (نسخة Espin + تغيير عند الفشل)
# ============================================================
def load_proxies(proxy_file="proxy.txt"):
    """تحميل البروكسيات - زي Espin"""
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
    """حفظ البروكسيات"""
    try:
        with open(proxy_file, "w", encoding="utf-8") as f:
            f.write("# قائمة البروكسيات - تم تحديثها تلقائياً\n")
            for p in proxies:
                f.write(f"{p}\n")
        return True
    except Exception as e:
        logger.error(f"خطأ في حفظ البروكسيات: {e}")
        return False

def get_ip(proxy, timeout=10):
    """الحصول على IP البروكسي - زي Espin"""
    if not proxy:
        return "بدون بروكسي"
    
    # التحقق من الكاش
    with ip_cache_lock:
        if proxy in ip_cache:
            cached_time, cached_ip = ip_cache[proxy]
            if (time.time() - cached_time) < 300:  # 5 دقائق
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
            # حفظ في الكاش
            with ip_cache_lock:
                ip_cache[proxy] = (time.time(), ip)
            return ip
    except:
        pass
    return "Unknown"

def get_cached_ip(proxy, force_refresh=False):
    """الحصول على IP من الكاش أو من البروكسي"""
    if not proxy:
        return "بدون بروكسي"
    
    with ip_cache_lock:
        if not force_refresh and proxy in ip_cache:
            cached_time, cached_ip = ip_cache[proxy]
            if (time.time() - cached_time) < 300:
                return cached_ip
    
    ip = get_ip(proxy, timeout=10)
    
    with ip_cache_lock:
        ip_cache[proxy] = (time.time(), ip)
    
    return ip

def test_proxy_detailed(proxy):
    """اختبار بروكسي مع IP والسرعة - نسخة Espin"""
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
            return {
                "status": "working",
                "ip": ip,
                "speed": round(response_time, 2),
                "proxy": proxy
            }
    except Exception as e:
        pass
    
    return {"status": "failed"}

def test_proxy(proxy):
    """اختبار بسيط للبروكسي (يرجع IP أو None)"""
    result = test_proxy_detailed(proxy)
    if result["status"] == "working":
        return result["ip"]
    return None

def mark_proxy_failed(proxy):
    """تسجيل فشل بروكسي"""
    with proxy_lock:
        if proxy:
            proxy_failures[proxy] = proxy_failures.get(proxy, 0) + 1
            if proxy_failures[proxy] >= 5:
                logger.warning(f"⚠️ البروكسي {proxy} فشل 5 مرات، سيتم حذفه")
                proxies = load_proxies()
                if proxy in proxies:
                    proxies.remove(proxy)
                    save_proxies(proxies)
                del proxy_failures[proxy]

def get_working_proxy(current_proxy=None):
    """الحصول على بروكسي شغال (يستبعد الفاشل)"""
    with proxy_lock:
        proxies = load_proxies()
        if not proxies:
            return None
        
        # استبعاد البروكسيات الفاشلة
        available = [p for p in proxies if p not in proxy_failures or proxy_failures[p] < 3]
        
        if not available:
            # إعادة تعيين
            proxy_failures.clear()
            available = proxies
        
        # لو البروكسي الحالي موجود في المتاح، نرجع نتأكد منه أولاً
        if current_proxy and current_proxy in available:
            if test_proxy(current_proxy):
                return current_proxy
            else:
                mark_proxy_failed(current_proxy)
                available.remove(current_proxy)
                if not available:
                    proxy_failures.clear()
                    available = proxies
        
        return random.choice(available) if available else None

def get_proxy_for_account(index):
    """الحصول على بروكسي حسب الترتيب - زي Espin"""
    proxies = load_proxies()
    if not proxies:
        return None, 0
    proxy_index = index % len(proxies)
    return proxies[proxy_index], proxy_index

# ============================================================
# خدمات البريد المؤقت (Mail.tm)
# ============================================================
mail_monitors = {}
seen_messages = {}
verification_codes = {}

def clean_html(raw_html):
    if not raw_html:
        return ""
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, "", raw_html).strip()

def get_mail_token(email, password):
    url = f"{MAIL_TM_API}/token"
    try:
        res = requests.post(url, json={"address": email, "password": password}, timeout=30)
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
        res = requests.post(url, json={"address": email, "password": password}, timeout=30)
        if res.status_code == 201:
            return email, password, True
        return email, password, False
    except:
        return email, password, False

def get_mail_messages(token, limit=10):
    url = f"{MAIL_TM_API}/messages"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(url, headers=headers, params={"page": 1, "limit": limit}, timeout=30)
        if res.status_code == 200:
            return res.json().get("hydra:member", [])
        return []
    except:
        return []

def get_mail_message(token, message_id):
    url = f"{MAIL_TM_API}/messages/{message_id}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code == 200:
            return res.json()
        return None
    except:
        return None

def extract_code_from_mail(email_data):
    if not email_data:
        return None
    
    body_text = email_data.get("text") or ""
    body_html = email_data.get("html") or ""
    
    if body_html:
        body_text = clean_html(body_html)
    
    patterns = [
        r"verification\s*code\s*[:\-]?\s*#?\s*([0-9]{4,10})",
        r"رمز التحقق:\s*([0-9]{4,10})",
        r"كود التأكيد:\s*([0-9]{4,10})",
        r"code[:\s]+([0-9]{4,10})",
        r"([0-9]{4,10})\s*(?:is|this is|your)\s*(?:your\s+)?verification",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, body_text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            code = match.group(1)
            if len(code) >= 4 and len(code) <= 10 and code.isdigit():
                return code
    
    numbers = re.findall(r'\b(\d{4,6})\b', body_text)
    if numbers:
        return numbers[0]
    
    return None

def start_mail_monitor(email, password):
    """بدء مراقبة البريد مع إعادة محاولة قوية"""
    with mail_lock:
        if email in mail_monitors and mail_monitors[email].get("running", False):
            return mail_monitors[email].get("token")
        
        token = get_mail_token(email, password)
        if not token:
            email, password, success = create_mail_account(email, password)
            if success:
                token = get_mail_token(email, password)
                if not token:
                    return None
            else:
                return None
        
        if email not in seen_messages:
            seen_messages[email] = set()
        
        mail_monitors[email] = {
            "token": token,
            "running": True,
            "email": email,
            "password": password,
            "retry_count": 0
        }
    
    def monitor_loop():
        retry_count = 0
        while mail_monitors.get(email, {}).get("running", False):
            try:
                with mail_lock:
                    token = mail_monitors[email]["token"]
                
                messages = get_mail_messages(token, limit=5)
                retry_count = 0
                
                for msg in messages:
                    msg_id = msg.get("id")
                    if msg_id not in seen_messages[email]:
                        seen_messages[email].add(msg_id)
                        detail = get_mail_message(token, msg_id)
                        if detail:
                            code = extract_code_from_mail(detail)
                            if code:
                                with mail_lock:
                                    verification_codes[email] = {
                                        "code": code,
                                        "timestamp": time.time()
                                    }
                                logger.info(f"✅ تم استلام كود لـ {email}: {code}")
                
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"خطأ في مراقبة البريد {email}: {e}")
                retry_count += 1
                
                if retry_count >= 3:
                    with mail_lock:
                        new_token = get_mail_token(email, mail_monitors[email]["password"])
                        if new_token:
                            mail_monitors[email]["token"] = new_token
                            retry_count = 0
                            logger.info(f"✅ تم تجديد توكن البريد لـ {email}")
                        else:
                            time.sleep(10)
                else:
                    time.sleep(5)
    
    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()
    mail_monitors[email]["thread"] = thread
    
    return token

def wait_for_code(email, password, timeout=180):
    """انتظار الكود مع إعادة محاولة التسجيل"""
    if email not in mail_monitors or not mail_monitors[email].get("running", False):
        token = start_mail_monitor(email, password)
        if not token:
            return None
    
    start_time = time.time()
    retry_attempts = 0
    
    while time.time() - start_time < timeout:
        with mail_lock:
            if email in verification_codes:
                code = verification_codes[email]["code"]
                del verification_codes[email]
                return code
        
        # إعادة محاولة التسجيل كل 60 ثانية
        if time.time() - start_time > 60 and retry_attempts < 3:
            if int(time.time() - start_time) % 60 < 3:
                logger.info(f"🔄 إعادة محاولة التسجيل لـ {email}")
                do_register(email, password)
                retry_attempts += 1
        
        time.sleep(3)
    
    logger.warning(f"⏰ انتهى وقت انتظار الكود لـ {email}")
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
    """التسجيل في اللعبة"""
    try:
        if not get_mail_token(email, password):
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
    """تسجيل الدخول"""
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

def do_confirm(email, code, proxy=None):
    """تأكيد الحساب"""
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

def register_or_login(email, password, proxy=None):
    """تسجيل الدخول أولاً، ثم التسجيل إذا فشل"""
    # محاولة تسجيل الدخول
    token, user_id, balance, credits, msg = do_login(email, password, proxy)
    if token:
        return True, token, user_id, balance, credits, "تم تسجيل الدخول"
    
    # محاولة التسجيل
    success, msg = do_register(email, password, proxy)
    if not success:
        return False, None, None, 0, 0, msg
    
    # انتظار الكود
    code = wait_for_code(email, password, timeout=180)
    if not code:
        return False, None, None, 0, 0, "انتهى وقت انتظار الكود"
    
    # تأكيد الحساب
    success, token, msg = do_confirm(email, code, proxy)
    if not success:
        return False, None, None, 0, 0, msg
    
    # جلب معلومات المستخدم
    user_info = get_user_info(token, proxy)
    if user_info:
        user_id = user_info.get("_id")
        balance = user_info.get("balance", 0)
        credits = user_info.get("credits", 0)
    else:
        user_id = None
        balance = 0
        credits = 0
    
    return True, token, user_id, balance, credits, "تم إنشاء حساب جديد"

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
    """تشغيل إعلانات"""
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

def request_withdrawal_code(token, address, amount, coin_id="65d2e4f4a3b5c7d8e9f0a1b2", proxy=None):
    """طلب كود السحب"""
    try:
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
        result = data.get("result", {})
        if result.get("status") == "success" or data.get("success"):
            return True, coin_id, "تم إرسال الكود"
        return False, None, result.get("msg", "فشل طلب الكود")
    except Exception as e:
        return False, None, str(e)

def confirm_withdrawal(token, address, amount, code, coin_id="65d2e4f4a3b5c7d8e9f0a1b2", proxy=None):
    """تأكيد السحب"""
    try:
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
            return False, None, "لا يوجد استجابة"
        
        data = res.json()
        result = data.get("result", {})
        if result.get("status") == "success" or data.get("success"):
            return True, data, "تم السحب بنجاح"
        return False, data, result.get("msg", "فشل السحب")
    except Exception as e:
        return False, None, str(e)

# ============================================================
# [تكملة الكود في الرسالة التالية]
# ============================================================
# ============================================================
# AccountWorker (نسخة Espin + وظائف Slots)
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
        self.current_ip = "جاري الجلب..."
        
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json, text/plain, */*"})
        
        # تحميل بيانات الحساب
        self.account = get_account_by_id(account_id) if account_id else None
        if self.account:
            self.balance = self.account.get('balance', 0)
            self.credits = self.account.get('credits', 0)
            self.total_earned = self.account.get('total_earned', 0)
            self.token = self.account.get('token')
            self.user_id = self.account.get('user_id')
            self.spin_count = self.account.get('spin_count', 0)
            if not self.proxy:
                self.proxy = self.account.get('proxy')
                self.raw_proxy = self.proxy
        
        self.setup_proxy()
    
    def setup_proxy(self):
        """تعيين البروكسي - نسخة Espin"""
        if not self.raw_proxy and USE_PROXIES:
            proxies = load_proxies()
            if not proxies:
                # انتظار
                for _ in range(12):
                    time.sleep(5)
                    proxies = load_proxies()
                    if proxies:
                        break
            
            if proxies:
                self.raw_proxy = proxies[self.index % len(proxies)]
        
        self.proxy = self.raw_proxy
        
        if self.proxy:
            self.session.proxies = {
                "http": self.proxy,
                "https": self.proxy
            }
    
    def change_proxy(self):
        """تغيير البروكسي (عند الفشل)"""
        if not USE_PROXIES:
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
            logger.info(f"🔄 تغيير بروكسي الحساب {self.email}: {new_proxy}")
            return True
        return False
    
    def init_network(self):
        """تهيئة الشبكة - نسخة Espin"""
        self.setup_proxy()
        
        if not self.proxy:
            self.current_ip = "بدون بروكسي"
            return
        
        self.current_ip = get_ip(self.proxy, timeout=15)
        
        retry = 0
        while self.current_ip == "Unknown" and retry < 3 and self.running:
            logger.warning(f"⚠️ البروكسي للحساب {self.email} لا يستجيب، إعادة محاولة...")
            time.sleep(5)
            if self.change_proxy():
                self.current_ip = get_ip(self.proxy, timeout=15)
            retry += 1
    
    def login(self):
        """تسجيل الدخول أو إنشاء حساب"""
        if not self.email or not self.password:
            return False
        
        for attempt in range(3):
            try:
                if USE_PROXIES and self.proxy:
                    self.session.proxies = {"http": self.proxy, "https": self.proxy}
                
                success, token, user_id, balance, credits, msg = register_or_login(
                    self.email, self.password, self.proxy
                )
                
                if success:
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
                    
                    logger.info(f"✅ تسجيل الدخول نجح: {self.email} ({msg})")
                    return True
                
                logger.warning(f"⚠️ محاولة {attempt+1}/3 فشلت للحساب {self.email}: {msg}")
                
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
        """الدوران"""
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
                self.credits = user.get("credits", self.credits)
                
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
        """التحقق من الهدف - نسخة Espin (يتجدد كل يوم)"""
        if not self.account_id:
            return False
        
        # تحديث بيانات الحساب من DB
        self.account = get_account_by_id(self.account_id)
        if not self.account:
            return False
        
        today = datetime.now().strftime("%Y-%m-%d")
        last_date = self.account.get('last_withdraw_date', '') or ''
        
        # ✅ إذا كان تاريخ جديد، نعيد تعيين الحساب
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
        
        # إذا تم السحب النهارده، متوقف
        if self.account.get('has_withdrawn_today', 0):
            return True
        
        # إذا الرصيد وصل للهدف، نسحب
        target = self.account.get('target_amount', MIN_TARGET)
        if self.balance >= target:
            return self.withdraw()
        
        return False
    
    def withdraw(self):
        """السحب التلقائي - نسخة Espin"""
        if self.balance < MIN_WITHDRAW:
            return False
        
        amount = int(self.balance * 0.9)
        if amount < MIN_WITHDRAW:
            amount = int(self.balance)
        
        try:
            address = self.email
            password = self.password
            
            # طلب كود السحب
            success = False
            coin_id = None
            
            for attempt in range(3):
                if USE_PROXIES and self.proxy:
                    self.session.proxies = {"http": self.proxy, "https": self.proxy}
                
                success, coin_id, message = request_withdrawal_code(
                    self.token, address, amount, proxy=self.proxy
                )
                
                if success:
                    break
                
                logger.warning(f"⚠️ محاولة {attempt+1}/3 لطلب كود السحب للحساب {self.email}")
                
                if USE_PROXIES:
                    mark_proxy_failed(self.proxy)
                    self.change_proxy()
                
                time.sleep(5)
            
            if not success:
                logger.error(f"❌ فشل طلب كود السحب للحساب {self.email}")
                return False
            
            # انتظار الكود من البريد
            code = wait_for_code(address, password, timeout=180)
            if not code:
                logger.error(f"❌ انتهى وقت انتظار كود السحب {self.email}")
                return False
            
            # تأكيد السحب
            success, result, error = confirm_withdrawal(
                self.token, address, amount, code, coin_id, self.proxy
            )
            
            if success:
                # تسجيل السحب
                if self.account_id:
                    add_withdrawal(self.account_id, amount, address, "FP", "completed")
                    
                    today = datetime.now().strftime("%Y-%m-%d")
                    update_account(
                        self.account_id,
                        balance=self.balance - amount,
                        withdrawal_count=(self.account.get('withdrawal_count', 0) + 1),
                        last_withdrawal=datetime.now().isoformat(),
                        has_withdrawn_today=1,
                        last_withdraw_date=today
                    )
                
                self.balance -= amount
                
                # إرسال إشعار
                try:
                    asyncio.run_coroutine_threadsafe(
                        send_notification(
                            f"💰 <b>تم السحب التلقائي!</b>\n"
                            f"━━━━━━━━━━━━━━━━━\n"
                            f"📧 {self.email}\n"
                            f"💰 المبلغ: {amount:,.0f}\n"
                            f"🌐 IP: {self.current_ip}\n"
                            f"✅ تم التحويل إلى محفظتك"
                        ),
                        asyncio.get_event_loop()
                    )
                except:
                    pass
                
                logger.info(f"✅ تم السحب بنجاح: {self.email} - {amount:,.0f}")
                return True
            
            logger.error(f"❌ فشل السحب {self.email}: {error}")
            return False
            
        except Exception as e:
            logger.error(f"❌ خطأ في السحب {self.email}: {e}")
            return False
    
    def run(self):
        """الحلقة الرئيسية - نسخة Espin"""
        self.init_network()
        
        if not self.login():
            self.running = False
            return
        
        self.running = True
        
        while self.running and not is_shutting_down:
            try:
                # التحقق من الهدف (يتجدد كل يوم)
                if self.check_target():
                    self.stopped = True
                    logger.info(f"⏸️ الحساب {self.email} متوقف بعد السحب")
                    
                    # ✅ ننتظر بكرة (نسأل كل دقيقة)
                    while self.stopped and self.running and not is_shutting_down:
                        time.sleep(60)
                        
                        # ✅ التحقق من التاريخ الجديد
                        today = datetime.now().strftime("%Y-%m-%d")
                        self.account = get_account_by_id(self.account_id)
                        if self.account:
                            last_date = self.account.get('last_withdraw_date', '') or ''
                            if last_date and last_date != today:
                                self.stopped = False
                                logger.info(f"🔄 الحساب {self.email} استأنف العمل بيوم جديد")
                                break
                    continue
                
                # جولة دوران (5 مرات)
                for _ in range(5):
                    if not self.running or self.stopped or is_shutting_down:
                        return
                    
                    result = self.spin()
                    
                    if result is None and self.fail_count >= self.max_fails:
                        logger.warning(f"⚠️ فشل متكرر للحساب {self.email}، تغيير البروكسي...")
                        if USE_PROXIES:
                            if self.change_proxy():
                                if self.login():
                                    self.fail_count = 0
                        break
                    
                    time.sleep(random.uniform(1.0, 4.0))
                
                # تحديث الرصيد في DB
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
                logger.error(f"❌ خطأ في حلقة الحساب {self.email}: {e}")
                time.sleep(10)
        
        self.running = False
        logger.info(f"⏹️ توقف الحساب {self.email}")


# ============================================================
# BotManager (نسخة Espin)
# ============================================================
class BotManager:
    def __init__(self):
        self.workers = {}  # {account_id: AccountWorker}
        self.threads = {}  # {account_id: thread}
        self.running = False
        self.chat_id = None
        self.current_view = "main"
        self.dashboard_page = 0
        self.accounts_page = 0
        self.delete_page = 0
        self.withdraw_status_page = 0
    
    def start_account(self, account_id):
        """تشغيل حساب واحد"""
        with worker_lock:
            if account_id in self.workers:
                worker = self.workers[account_id]
                if worker.running:
                    return False
            
            account = get_account_by_id(account_id)
            if not account:
                return False
            
            # ✅ توزيع البروكسيات حسب الترتيب (زي Espin)
            proxies = load_proxies()
            proxy = None
            proxy_index = 0
            
            if USE_PROXIES and proxies:
                proxy_index = account_id % len(proxies)
                proxy = proxies[proxy_index]
            
            # إنشاء Worker جديد
            worker = AccountWorker(
                email=account['email'],
                password=account['password'],
                proxy=proxy,
                index=proxy_index,
                account_id=account_id
            )
            
            # تحديث البروكسي في DB
            if proxy:
                update_account(account_id, proxy=proxy, proxy_index=proxy_index)
            
            self.workers[account_id] = worker
            
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()
            self.threads[account_id] = thread
            
            return True
    
    def stop_account(self, account_id):
        """إيقاف حساب"""
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
        """تشغيل جميع الحسابات"""
        accounts = get_all_accounts(active_only=True)
        started = 0
        
        for acc in accounts:
            if self.start_account(acc['id']):
                started += 1
                time.sleep(0.3)
        
        self.running = True
        return started
    
    def stop_all(self):
        """إيقاف جميع الحسابات"""
        account_ids = list(self.workers.keys())
        stopped = 0
        
        for acc_id in account_ids:
            if self.stop_account(acc_id):
                stopped += 1
        
        self.running = False
        return stopped
    
    def get_status(self):
        """حالة البوت"""
        accounts = get_all_accounts()
        total = len(accounts)
        running = len(self.workers)
        
        total_balance = 0
        details = []
        
        for acc in accounts:
            total_balance += acc.get('balance', 0)
            
            worker = self.workers.get(acc['id'])
            
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
            
            # آخر جزء من IP
            if current_ip and current_ip != "Unknown" and current_ip != "بدون بروكسي":
                ip_short = current_ip.split('.')[-1]
            else:
                ip_short = "---"
            
            details.append({
                'id': acc['id'],
                'email': acc['email'],
                'status_icon': status_icon,
                'balance': balance,
                'credits': credits,
                'target': target,
                'ip': current_ip,
                'ip_short': ip_short
            })
        
        return {
            'total_accounts': total,
            'running_accounts': running,
            'total_balance': total_balance,
            'details': details
        }
    
    def dashboard_text(self, page=0):
        """نص لوحة التحكم مع IP"""
        status = self.get_status()
        
        total_accounts = status['total_accounts']
        total_pages = max(1, ((total_accounts - 1) // ITEMS_PER_PAGE) + 1)
        
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
        
        start = page * ITEMS_PER_PAGE
        end = min(start + ITEMS_PER_PAGE, total_accounts)
        
        text = (
            f"📊 <b>لوحة التحكم</b> (صفحة {page+1}/{total_pages})\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📧 إجمالي الحسابات: {status['total_accounts']}\n"
            f"🟢 النشطة: {status['running_accounts']}\n"
            f"💰 الرصيد الكلي: {status['total_balance']:,.0f}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"<b>تفاصيل الحسابات:</b>\n"
        )
        
        if status['details']:
            for detail in status['details'][start:end]:
                text += (
                    f"{detail['status_icon']} <b>{detail['id']}</b> | "
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
    
    def get_dashboard_workers_status(self):
        """تفاصيل الحسابات النشطة (للاطلاع)"""
        result = []
        for acc_id, worker in self.workers.items():
            result.append({
                'id': acc_id,
                'email': worker.email,
                'ip': worker.current_ip,
                'balance': worker.balance,
                'credits': worker.credits,
                'running': worker.running,
                'stopped': worker.stopped
            })
        return result


bot_manager = BotManager()
# ============================================================
# دوال التليجرام
# ============================================================
async def send_notification(message):
    if bot_application and bot_chat_id:
        try:
            await bot_application.bot.send_message(
                chat_id=bot_chat_id,
                text=message,
                parse_mode="HTML"
            )
        except:
            pass


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
    
    main_text = (
        f"🎰 <b>Slot Bot - لوحة التحكم</b>\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📧 الحسابات: {status['total_accounts']}\n"
        f"🟢 النشطة: {status['running_accounts']}\n"
        f"💰 الرصيد الكلي: {status['total_balance']:,.0f}\n"
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
    
    # ============ تشغيل / إيقاف ============
    if data == "start_all":
        started = bot_manager.start_all()
        await query.edit_message_text(f"🚀 تم تشغيل {started} حساب")
        await show_main_menu(update, context, query.message.chat_id)
    
    elif data == "stop_all":
        stopped = bot_manager.stop_all()
        await query.edit_message_text(f"⏹️ تم إيقاف {stopped} حساب")
        await show_main_menu(update, context, query.message.chat_id)
    
    # ============ لوحة التحكم ============
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
    
    # ============ إضافة حساب ============
    elif data == "add_account":
        pending_emails[user_id] = "waiting_for_account"
        await query.edit_message_text(
            "📝 <b>إضافة حساب جديد</b>\n\n"
            "أرسل الإيميل وكلمة المرور بالصيغة:\n"
            "<code>email password</code>\n\n"
            "مثال: <code>user@uberip.com MyPass123</code>\n\n"
            "🔙 لإلغاء العملية أرسل /cancel",
            parse_mode="HTML"
        )
    
    elif data == "add_multiple_accounts":
        pending_emails[user_id] = "waiting_for_multiple_accounts"
        await query.edit_message_text(
            "📝 <b>إضافة حسابات متعددة</b>\n\n"
            "أرسل قائمة الحسابات (كل حساب في سطر):\n"
            "<code>email1 password1</code>\n"
            "<code>email2 password2</code>\n"
            "<code>email3 password3</code>\n\n"
            "⚠️ سيتم إضافة كل حساب بشكل مستقل\n"
            "⏱️ قد يستغرق كل حساب 2-3 دقائق\n"
            "🌐 سيتم استخدام بروكسي مختلف لكل حساب\n\n"
            "🔙 لإلغاء العملية أرسل /cancel",
            parse_mode="HTML"
        )
    
    # ============ حذف حساب ============
    elif data == "delete_account":
        accounts = get_all_accounts()
        if not accounts:
            await query.edit_message_text("📭 لا يوجد حسابات!")
            return
        
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
    
    # ============ إدارة البروكسيات ============
    elif data == "proxies_menu":
        proxies = load_proxies()
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
            f"📊 المجموع: {len(proxies)}",
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
            ip = get_cached_ip(p)
            status = "✅" if ip and ip != "Unknown" else "❌"
            text += f"{i}. {status} <code>{p}</code>\n   🌐 IP: <code>{ip}</code>\n\n"
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    
    elif data == "add_proxies":
        pending_emails[user_id] = "waiting_for_proxies"
        await query.edit_message_text(
            "📝 <b>إضافة بروكسيات</b>\n\n"
            "أرسل قائمة البروكسيات (كل بروكسي في سطر):\n"
            "<code>192.168.1.1:8080</code>\n"
            "<code>proxy.example.com:3128</code>\n\n"
            "🔙 لإلغاء العملية أرسل /cancel",
            parse_mode="HTML"
        )
    
    elif data == "test_proxies":
        proxies = load_proxies()
        if not proxies:
            await query.edit_message_text("📭 لا يوجد بروكسيات!")
            return
        
        await query.edit_message_text(f"🔄 جاري اختبار {len(proxies)} بروكسي...")
        
        text = "🧪 <b>نتيجة اختبار البروكسيات</b>\n━━━━━━━━━━━━━━━━━\n"
        valid = 0
        invalid = 0
        valid_proxies = []
        
        for i, p in enumerate(proxies, 1):
            result = test_proxy_detailed(p)
            
            if result["status"] == "working":
                text += f"✅ <code>{p}</code>\n"
                text += f"   🌐 IP: <code>{result['ip']}</code>\n"
                text += f"   ⚡ السرعة: {result['speed']}s\n\n"
                valid += 1
                valid_proxies.append(p)
            else:
                text += f"❌ <code>{p}</code>\n"
                text += f"   ⚠️ لا يعمل\n\n"
                invalid += 1
            
            if i % 5 == 0 and i < len(proxies):
                try:
                    await query.edit_message_text(text + "\n⏳ جاري الاختبار...", parse_mode="HTML")
                except:
                    pass
        
        # حفظ البروكسيات الصالحة فقط
        if invalid > 0:
            save_proxies(valid_proxies)
        
        text += f"━━━━━━━━━━━━━━━━━\n"
        text += f"📊 الإحصائيات:\n"
        text += f"   ✅ صالح: {valid}\n"
        text += f"   ❌ تالف: {invalid}\n"
        if invalid > 0:
            text += f"   🗑️ تم حذف التالف\n"
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    
    elif data == "delete_proxy":
        proxies = load_proxies()
        if not proxies:
            await query.edit_message_text("📭 لا يوجد بروكسيات!")
            return
        
        keyboard = []
        for i, p in enumerate(proxies[:20]):
            display = p[:30] + "..." if len(p) > 30 else p
            keyboard.append([
                InlineKeyboardButton(f"🗑️ {display}", callback_data=f"del_proxy_{i}")
            ])
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
                await query.edit_message_text(f"✅ تم حذف البروكسي:\n<code>{proxy}</code>", parse_mode="HTML")
            else:
                await query.edit_message_text("❌ لم يتم العثور على البروكسي")
        else:
            await query.edit_message_text("❌ بروكسي غير صالح")
        
        await asyncio.sleep(1)
        await button_handler(update, context)
    
    # ============ سحب يدوي ============
    elif data == "manual_withdraw":
        accounts = get_all_accounts()
        available = [a for a in accounts if a.get('balance', 0) >= MIN_WITHDRAW]
        
        if not available:
            await query.edit_message_text(
                f"⚠️ لا يوجد حسابات قابلة للسحب\n"
                f"(الحد الأدنى: {MIN_WITHDRAW:,})"
            )
            return
        
        keyboard = []
        for acc in available[:25]:
            keyboard.append([
                InlineKeyboardButton(
                    f"💰 {acc['email'][:25]} ({acc['balance']:,.0f})",
                    callback_data=f"wd_now_{acc['id']}"
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
        
        await query.edit_message_text(
            "💰 <b>اختر الحساب للسحب:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    
    elif data.startswith("wd_now_"):
        account_id = int(data.split("_")[2])
        account = get_account_by_id(account_id)
        
        if not account:
            await query.edit_message_text("❌ الحساب غير موجود")
            return
        
        if account.get('balance', 0) < MIN_WITHDRAW:
            await query.edit_message_text(f"❌ الرصيد أقل من الحد الأدنى {MIN_WITHDRAW}")
            return
        
        # إيقاف الحساب مؤقتاً إذا شغال
        was_running = account_id in bot_manager.workers
        if was_running:
            bot_manager.stop_account(account_id)
        
        await query.edit_message_text("🔄 جاري السحب...")
        
        # إنشاء Worker مؤقت للسحب
        worker = AccountWorker(
            email=account['email'],
            password=account['password'],
            proxy=account.get('proxy'),
            index=account.get('proxy_index', 0),
            account_id=account_id
        )
        worker.token = account.get('token')
        worker.user_id = account.get('user_id')
        worker.balance = account.get('balance', 0)
        worker.credits = account.get('credits', 0)
        worker.account = account
        
        success = worker.withdraw()
        
        if success:
            await query.edit_message_text("✅ تم السحب بنجاح!")
        else:
            await query.edit_message_text("❌ فشل السحب، حاول مرة أخرى")
        
        # إعادة تشغيل الحساب
        if was_running:
            bot_manager.start_account(account_id)
        
        await asyncio.sleep(2)
        await show_main_menu(update, context, query.message.chat_id)
    
    # ============ حالات السحب ============
    elif data == "withdrawal_status":
        accounts = get_all_accounts()
        if not accounts:
            await query.edit_message_text("📭 لا يوجد حسابات!")
            return
        
        keyboard = []
        for acc in accounts[:25]:
            keyboard.append([
                InlineKeyboardButton(
                    f"📥 {acc['email'][:25]} ({acc.get('withdrawal_count', 0)})",
                    callback_data=f"wd_status_{acc['id']}"
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
        
        await query.edit_message_text(
            "📥 <b>اختر الحساب لعرض حالات السحب:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    
    elif data.startswith("wd_status_"):
        account_id = int(data.split("_")[2])
        account = get_account_by_id(account_id)
        
        if not account:
            await query.edit_message_text("❌ الحساب غير موجود")
            return
        
        withdrawals = get_withdrawals(account_id, limit=10)
        
        text = (
            f"📥 <b>حالات السحب - {account['email']}</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"💰 الرصيد الحالي: {account.get('balance', 0):,.0f}\n"
            f"📊 عدد السحوبات: {account.get('withdrawal_count', 0)}\n"
            f"📅 آخر سحب: {account.get('last_withdraw_date', 'لا يوجد') or 'لا يوجد'}\n"
            f"━━━━━━━━━━━━━━━━━\n"
        )
        
        if withdrawals:
            for i, wd in enumerate(withdrawals, 1):
                text += (
                    f"<b>سحب #{i}</b>\n"
                    f"   💰 المبلغ: {wd.get('amount', 0):,.0f}\n"
                    f"   📊 الحالة: {wd.get('status', 'غير معروف')}\n"
                    f"   📅 التاريخ: {wd.get('created_at', '')[:19]}\n"
                    f"   ─────────────\n"
                )
        else:
            text += "📭 لا توجد سحوبات مسجلة\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 تحديث", callback_data=f"wd_status_{account_id}")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="withdrawal_status")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    
    # ============ رجوع ============
    elif data == "back_main":
        await show_main_menu(update, context, query.message.chat_id)


async def show_delete_accounts(update, context):
    """عرض الحسابات للحذف مع ترقيم"""
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
        keyboard.append([
            InlineKeyboardButton(f"🗑️ {display}", callback_data=f"del_acc_{acc['id']}")
        ])
    
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
        f"📧 إجمالي: {total} حساب\n"
        f"📄 صفحة {page+1}/{total_pages}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"اختر الحساب للحذف:",
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
    
    # ============ إضافة حساب واحد ============
    if action == "waiting_for_account":
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ صيغة غير صحيحة.\n"
                "أرسل: <code>email password</code>",
                parse_mode="HTML"
            )
            return
        
        email = parts[0]
        password = " ".join(parts[1:])
        
        if not email or not password or len(password) < 6:
            await update.message.reply_text("❌ إيميل أو كلمة مرور غير صالحة")
            return
        
        del pending_emails[user_id]
        
        progress = await update.message.reply_text(f"🔄 جاري إنشاء الحساب...\n📧 {email}")
        
        result = await add_single_account(email, password, progress)
        
        if result:
            await show_main_menu(None, context, update.message.chat_id)
    
    # ============ إضافة حسابات متعددة ============
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
            await update.message.reply_text(
                "❌ لم يتم العثور على حسابات صالحة.\n"
                "تأكد من الصيغة: <code>email password</code> لكل سطر",
                parse_mode="HTML"
            )
            del pending_emails[user_id]
            return
        
        del pending_emails[user_id]
        
        progress = await update.message.reply_text(
            f"🚀 <b>بدء إضافة {len(accounts_data)} حساب</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"⏳ جاري التحضير...",
            parse_mode="HTML"
        )
        
        success_count = 0
        fail_count = 0
        results = []
        
        for i, (email, password) in enumerate(accounts_data, 1):
            try:
                await progress.edit_text(
                    f"🚀 <b>إضافة الحساب {i}/{len(accounts_data)}</b>\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"📧 {email}\n"
                    f"✅ نجح: {success_count}\n"
                    f"❌ فشل: {fail_count}\n"
                    f"⏳ انتظر...",
                    parse_mode="HTML"
                )
                
                success = await add_single_account(email, password, None, silent=True)
                
                if success:
                    success_count += 1
                    results.append(f"✅ {email[:30]}")
                else:
                    fail_count += 1
                    results.append(f"❌ {email[:30]}")
                
                # تأخير بين الحسابات
                if i < len(accounts_data):
                    wait = random.randint(5, 10)
                    await asyncio.sleep(wait)
                
            except Exception as e:
                logger.error(f"خطأ في إضافة حساب {email}: {e}")
                fail_count += 1
                results.append(f"❌ {email[:30]} (خطأ)")
        
        # عرض النتائج
        summary = (
            f"📊 <b>نتيجة إضافة الحسابات</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"✅ نجح: {success_count}\n"
            f"❌ فشل: {fail_count}\n"
            f"📝 إجمالي: {len(accounts_data)}\n"
            f"━━━━━━━━━━━━━━━━━\n"
        )
        
        for r in results[:15]:
            summary += r + "\n"
        
        if len(results) > 15:
            summary += f"... و {len(results) - 15} أخرى\n"
        
        await progress.edit_text(summary, parse_mode="HTML")
        await show_main_menu(None, context, update.message.chat_id)
    
    # ============ إضافة بروكسيات ============
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


async def add_single_account(email, password, progress_msg=None, silent=False):
    """إضافة حساب واحد (بدون رسائل إن silent=True)"""
    try:
        if progress_msg:
            try:
                await progress_msg.edit_text(f"🔄 التسجيل/الدخول لـ {email}...")
            except:
                pass
        
        # جلب بروكسي
        proxies = load_proxies()
        proxy = None
        proxy_index = 0
        
        if USE_PROXIES and proxies:
            account_count = len(get_all_accounts())
            proxy_index = account_count % len(proxies)
            proxy = proxies[proxy_index]
        
        # تسجيل الدخول أو التسجيل
        success, token, user_id_api, balance, credits, msg = register_or_login(
            email, password, proxy
        )
        
        if not success:
            if progress_msg and not silent:
                try:
                    await progress_msg.edit_text(f"❌ {msg}")
                except:
                    pass
            return False
        
        # التحقق من وجود الحساب
        existing = get_account_by_email(email)
        
        if existing:
            update_account(
                existing['id'],
                token=token,
                user_id=user_id_api,
                balance=balance,
                credits=credits,
                last_login=datetime.now().isoformat(),
                is_active=1,
                proxy=proxy,
                proxy_index=proxy_index
            )
            account_id = existing['id']
            action = "تسجيل الدخول"
        else:
            account_id = add_account(
                email, password, token, user_id_api, balance, credits, proxy, proxy_index
            )
            action = "إنشاء حساب"
        
        if account_id:
            # تشغيل الحساب
            bot_manager.start_account(account_id)
            
            if progress_msg and not silent:
                try:
                    await progress_msg.edit_text(
                        f"✅ <b>تم {action} بنجاح!</b>\n"
                        f"━━━━━━━━━━━━━━━━━\n"
                        f"🆔 ID: {account_id}\n"
                        f"📧 {email}\n"
                        f"💰 الرصيد: {balance:,.0f}\n"
                        f"🎯 الهدف: {random.randint(MIN_TARGET, MAX_TARGET):,}\n"
                        f"🌐 بروكسي: <code>{proxy if proxy else 'بدون'}</code>",
                        parse_mode="HTML"
                    )
                except:
                    pass
            return True
        else:
            if progress_msg and not silent:
                try:
                    await progress_msg.edit_text("❌ فشل حفظ الحساب")
                except:
                    pass
            return False
    
    except Exception as e:
        logger.error(f"خطأ في add_single_account: {e}")
        if progress_msg and not silent:
            try:
                await progress_msg.edit_text(f"❌ خطأ: {str(e)[:50]}")
            except:
                pass
        return False


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
    global bot_application, is_shutting_down
    
    init_database()
    
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ الرجاء تعيين BOT_TOKEN في config.json")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    bot_application = application
    
    # إضافة المعالجات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("dashboard", dashboard_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🎰 Starting Slot Bot - النسخة النهائية")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("✅ Bot is running! Press Ctrl+C to stop")
    print("📧 نظام مراقبة البريد: مفعل")
    print("💰 السحب التلقائي: مفعل (كل يوم هدف جديد)")
    print("💰 السحب اليدوي: مفعل")
    print("🌐 البروكسيات: ثابتة + تتغير عند الفشل")
    print("📊 عرض IP في لوحة التحكم: مفعل")
    print("📥 عرض حالات السحب: مفعل")
    print("➕ إضافة حسابات متعددة: مفعل")
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
