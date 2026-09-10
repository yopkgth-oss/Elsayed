#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Slot Bot - النسخة النهائية المحسنة
دمج بين بساطة Espin وقوة Slots مع حل جميع المشاكل
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
        "use_proxies": True,
        "database_file": "accounts.db"
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
USE_PROXIES = CONFIG.get("use_proxies", True)
DATABASE_FILE = CONFIG.get("database_file", "accounts.db")

API_URL = f"{BASE_URL}/api/v1"
GRAPHQL_URL = f"{BASE_URL}/graphql"

# ============================================================
# متغيرات عامة
# ============================================================
bot_application = None
bot_chat_id = None
account_workers = {}
worker_threads = {}
stop_events = {}
is_shutting_down = False
pending_emails = {}  # {user_id: email}

# 🔒 أقفال لحماية المتغيرات المشتركة
mail_lock = threading.Lock()
worker_lock = threading.Lock()
proxy_lock = threading.Lock()

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
            last_withdraw_date TEXT
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
                       'has_withdrawn_today', 'last_withdraw_date']
            return dict(zip(columns, row))
        return None
    except:
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
                       'has_withdrawn_today', 'last_withdraw_date']
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
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        columns = ['id', 'email', 'password', 'token', 'user_id', 'balance', 'credits', 
                   'total_earned', 'created_at', 'last_login', 'is_active', 'withdrawal_count',
                   'last_withdrawal', 'proxy', 'spin_count', 'target_amount', 
                   'has_withdrawn_today', 'last_withdraw_date']
        return [dict(zip(columns, row)) for row in rows]
    except:
        return []

def add_account(email, password, token=None, user_id=None, balance=0, credits=0, proxy=None):
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        target = random.randint(55000, 65000)
        cursor.execute("""
            INSERT INTO accounts (email, password, token, user_id, balance, credits, created_at, proxy, target_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (email, password, token, user_id, balance, credits, datetime.now().isoformat(), proxy, target))
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
# خدمات البريد المؤقت (محسنة من Slots)
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
        
        # محاولة الحصول على توكن
        token = get_mail_token(email, password)
        if not token:
            # محاولة إنشاء حساب بريد جديد
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
                retry_count = 0  # reset on success
                
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
                
                # إعادة محاولة الحصول على توكن جديد
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
    """انتظار الكود مع إعادة محاولة التسجيل إذا لزم الأمر"""
    if email not in mail_monitors or not mail_monitors[email].get("running", False):
        token = start_mail_monitor(email, password)
        if not token:
            return None
    
    start_time = time.time()
    retry_attempts = 0
    
    while time.time() - start_time < timeout:
        # التحقق من وجود الكود
        with mail_lock:
            if email in verification_codes:
                code = verification_codes[email]["code"]
                del verification_codes[email]
                return code
        
        # إعادة محاولة التسجيل إذا مر وقت طويل
        if time.time() - start_time > 60 and retry_attempts < 3:
            logger.info(f"🔄 إعادة محاولة التسجيل لـ {email} (المحاولة {retry_attempts+1})")
            success, _ = do_register(email, password)
            if success:
                retry_attempts += 1
                logger.info(f"✅ تم إعادة التسجيل بنجاح لـ {email}")
            else:
                logger.warning(f"⚠️ فشل إعادة التسجيل لـ {email}")
        
        time.sleep(3)
    
    logger.warning(f"⏰ انتهى وقت انتظار الكود لـ {email} بعد {timeout} ثانية")
    return None

# ============================================================
# نظام البروكسيات (محسن)
# ============================================================
proxy_failures = {}

def load_proxies():
    proxies = []
    if os.path.exists("proxy.txt"):
        with open("proxy.txt", "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if not line.startswith("http://") and not line.startswith("https://"):
                        line = f"http://{line}"
                    proxies.append(line)
    return proxies

def save_proxies(proxies):
    with open("proxy.txt", "w", encoding="utf-8") as f:
        f.write("# قائمة البروكسيات\n")
        for p in proxies:
            f.write(f"{p}\n")

def get_proxy():
    """الحصول على بروكسي صالح مع تجاهل الفاشل"""
    with proxy_lock:
        proxies = load_proxies()
        if not proxies:
            return None
        
        # استبعاد البروكسيات الفاشلة
        available = [p for p in proxies if p not in proxy_failures or proxy_failures[p] < 3]
        if not available:
            # إذا كلهم فشلوا، نعيد تعيين العداد
            proxy_failures.clear()
            available = proxies
        
        return random.choice(available) if available else None

def test_proxy(proxy):
    """اختبار بروكسي مع محاولتين"""
    if not proxy:
        return None
    try:
        proxy_clean = proxy.strip()
        if not proxy_clean.startswith("http://"):
            proxy_clean = f"http://{proxy_clean}"
        
        # محاولتين
        for _ in range(2):
            try:
                response = requests.get(
                    "https://api.ipify.org?format=json",
                    proxies={"http": proxy_clean, "https": proxy_clean},
                    timeout=10
                )
                if response.status_code == 200:
                    ip = response.json().get("ip")
                    if ip:
                        return ip
            except:
                time.sleep(1)
    except:
        pass
    return None

def mark_proxy_failed(proxy):
    """تسجيل فشل بروكسي وحذفه إذا فشل 3 مرات"""
    with proxy_lock:
        if proxy:
            proxy_failures[proxy] = proxy_failures.get(proxy, 0) + 1
            if proxy_failures[proxy] >= 3:
                proxies = load_proxies()
                if proxy in proxies:
                    proxies.remove(proxy)
                    save_proxies(proxies)
                    logger.info(f"🗑️ تم حذف بروكسي فاشل: {proxy}")
                del proxy_failures[proxy]

# ============================================================
# دوال API للعبة
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
    """التسجيل في اللعبة (إنشاء حساب جديد)"""
    try:
        # التحقق من وجود البريد في Mail.tm
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
            return False, "لا يوجد استجابة من السيرفر"
        
        data = res.json()
        if data.get("success") or data.get("needsConfirmation") == True:
            return True, "تم التسجيل بنجاح، انتظر الكود"
        else:
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
    """تأكيد الحساب بالكود"""
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
        else:
            return False, None, data.get("message", "فشل التأكيد")
            
    except Exception as e:
        return False, None, str(e)

def register_or_login(email, password, proxy=None):
    """محاولة تسجيل الدخول أولاً، ثم التسجيل إذا فشل"""
    # 1. محاولة تسجيل الدخول
    token, user_id, balance, credits, msg = do_login(email, password, proxy)
    if token:
        return True, token, user_id, balance, credits, "تم تسجيل الدخول"
    
    # 2. محاولة التسجيل
    success, msg = do_register(email, password, proxy)
    if not success:
        return False, None, None, 0, 0, msg
    
    # 3. انتظار الكود
    code = wait_for_code(email, password, timeout=180)
    if not code:
        return False, None, None, 0, 0, "انتهى وقت انتظار الكود"
    
    # 4. تأكيد الحساب
    success, token, msg = do_confirm(email, code, proxy)
    if not success:
        return False, None, None, 0, 0, msg
    
    # 5. جلب معلومات المستخدم
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
    """تشغيل إعلانات للحصول على كريدت - محسنة"""
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
# AccountWorker (محسن بالكامل)
# ============================================================
class AccountWorker:
    def __init__(self, account_id, proxy=None):
        self.account_id = account_id
        self.proxy = proxy
        self.running = False
        self.stopped = False
        self.token = None
        self.user_id = None
        self.balance = 0
        self.credits = 0
        self.total_earned = 0
        self.spin_count = 0
        self.fail_count = 0
        self.max_fails = 5
        self.last_spin_time = datetime.now()
        self.login_attempts = 0
        self.max_login_attempts = 3
        
        self.account = get_account_by_id(account_id)
        if self.account:
            self.balance = self.account.get('balance', 0)
            self.credits = self.account.get('credits', 0)
            self.total_earned = self.account.get('total_earned', 0)
            self.token = self.account.get('token')
            self.user_id = self.account.get('user_id')
            self.spin_count = self.account.get('spin_count', 0)
            self.proxy = self.account.get('proxy')
            
            if USE_PROXIES and (not self.proxy or not test_proxy(self.proxy)):
                new_proxy = get_proxy()
                if new_proxy:
                    self.proxy = new_proxy
                    update_account(self.account_id, proxy=self.proxy)
        
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json, text/plain, */*"})
        if self.proxy:
            self.session.proxies = {"http": self.proxy, "https": self.proxy}
    
    def login(self):
        """تسجيل الدخول أو إنشاء حساب جديد"""
        if not self.account:
            return False
        
        self.login_attempts = 0
        
        while self.login_attempts < self.max_login_attempts:
            try:
                if USE_PROXIES and self.proxy:
                    self.session.proxies = {"http": self.proxy, "https": self.proxy}
                
                # محاولة تسجيل الدخول أو التسجيل
                success, token, user_id, balance, credits, msg = register_or_login(
                    self.account['email'],
                    self.account['password'],
                    self.proxy
                )
                
                if success:
                    self.token = token
                    self.user_id = user_id
                    self.balance = balance
                    self.credits = credits
                    
                    update_account(
                        self.account_id,
                        token=token,
                        user_id=user_id,
                        balance=balance,
                        credits=credits,
                        last_login=datetime.now().isoformat()
                    )
                    logger.info(f"✅ نجح تسجيل الدخول للحساب {self.account_id}: {msg}")
                    return True
                
                logger.warning(f"⚠️ فشل تسجيل الدخول {self.account_id}: {msg}")
                
                # تغيير البروكسي إذا فشل
                if USE_PROXIES:
                    mark_proxy_failed(self.proxy)
                    new_proxy = get_proxy()
                    if new_proxy:
                        self.proxy = new_proxy
                        update_account(self.account_id, proxy=self.proxy)
                        self.session.proxies = {"http": self.proxy, "https": self.proxy}
                        logger.info(f"🔄 تغيير البروكسي للحساب {self.account_id} إلى {self.proxy}")
                
                self.login_attempts += 1
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"❌ خطأ في تسجيل الدخول {self.account_id}: {e}")
                self.login_attempts += 1
                time.sleep(5)
        
        logger.error(f"❌ فشل تسجيل الدخول للحساب {self.account_id} بعد {self.max_login_attempts} محاولات")
        return False
    
    def spin(self):
        """الدوران مع إدارة الإعلانات"""
        try:
            # التحقق من الرصيد
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
                
                add_spin(self.account_id, self.spin_count, reward, self.balance, self.credits)
                update_account(self.account_id, spin_count=self.spin_count)
                
                self.fail_count = 0
                self.last_spin_time = datetime.now()
                return data
            
            self.fail_count += 1
            return None
            
        except Exception as e:
            logger.error(f"خطأ في الدوران {self.account_id}: {e}")
            self.fail_count += 1
            return None
    
    def check_target(self):
        """التحقق من الوصول للهدف اليومي"""
        if not self.account:
            return False
        
        target = self.account.get('target_amount', 55000)
        has_withdrawn = self.account.get('has_withdrawn_today', 0)
        
        if has_withdrawn:
            return True
        
        if self.balance >= target:
            return self.withdraw()
        
        return False
    
    def withdraw(self):
        """السحب التلقائي مع إعادة محاولة قوية"""
        if self.balance < MIN_WITHDRAW:
            return False
        
        amount = int(self.balance * 0.9)
        if amount < MIN_WITHDRAW:
            amount = int(self.balance)
        
        try:
            address = self.account['email']
            password = self.account['password']
            
            # محاولة طلب الكود مع إعادة المحاولة
            for attempt in range(3):
                if USE_PROXIES and self.proxy:
                    self.session.proxies = {"http": self.proxy, "https": self.proxy}
                
                success, coin_id, message = request_withdrawal_code(
                    self.token, address, amount, proxy=self.proxy
                )
                
                if success:
                    break
                
                logger.warning(f"⚠️ فشل طلب كود السحب {self.account_id}، المحاولة {attempt+1}")
                if USE_PROXIES:
                    mark_proxy_failed(self.proxy)
                    new_proxy = get_proxy()
                    if new_proxy:
                        self.proxy = new_proxy
                        update_account(self.account_id, proxy=self.proxy)
                        self.session.proxies = {"http": self.proxy, "https": self.proxy}
                
                time.sleep(5)
            else:
                logger.error(f"❌ فشل طلب كود السحب {self.account_id} بعد 3 محاولات")
                return False
            
            # انتظار الكود
            code = wait_for_code(address, password, timeout=180)
            if not code:
                logger.error(f"❌ انتهى وقت انتظار كود السحب {self.account_id}")
                return False
            
            # تأكيد السحب
            success, result, error = confirm_withdrawal(
                self.token, address, amount, code, coin_id, self.proxy
            )
            
            if success:
                add_withdrawal(self.account_id, amount, address, "FP", "completed")
                
                update_account(
                    self.account_id,
                    balance=self.balance - amount,
                    withdrawal_count=self.account.get('withdrawal_count', 0) + 1,
                    last_withdrawal=datetime.now().isoformat(),
                    has_withdrawn_today=1,
                    last_withdraw_date=datetime.now().strftime("%Y-%m-%d")
                )
                
                self.balance -= amount
                
                # إرسال إشعار
                asyncio.run_coroutine_threadsafe(
                    send_notification(
                        f"💰 <b>تم السحب التلقائي!</b>\n"
                        f"━━━━━━━━━━━━━━━━━\n"
                        f"📧 {self.account['email']}\n"
                        f"💰 المبلغ: {amount:,.0f}\n"
                        f"✅ تم التحويل إلى محفظتك"
                    ),
                    asyncio.get_event_loop()
                )
                
                logger.info(f"✅ تم السحب بنجاح للحساب {self.account_id}: {amount}")
                return True
            
            logger.error(f"❌ فشل السحب {self.account_id}: {error}")
            return False
            
        except Exception as e:
            logger.error(f"❌ خطأ في السحب {self.account_id}: {e}")
            return False
    
    def run(self):
        """الحلقة الرئيسية لتشغيل الحساب"""
        # محاولة تسجيل الدخول
        if not self.login():
            self.running = False
            return
        
        self.running = True
        
        while self.running and not self.stopped and not is_shutting_down:
            try:
                # التحقق من الهدف اليومي
                try:
                    if self.check_target():
                        self.stopped = True
                        logger.info(f"⏸️ توقف الحساب {self.account_id} بعد السحب")
                        break
                except Exception as e:
                    logger.error(f"خطأ في التحقق من الهدف {self.account_id}: {e}")
                    time.sleep(5)
                    continue
                
                # جولة دوران (5 مرات)
                try:
                    for _ in range(5):
                        if not self.running or self.stopped or is_shutting_down:
                            return
                        
                        result = self.spin()
                        if result is None and self.fail_count >= self.max_fails:
                            # تغيير البروكسي وإعادة تسجيل الدخول
                            if USE_PROXIES:
                                mark_proxy_failed(self.proxy)
                                new_proxy = get_proxy()
                                if new_proxy:
                                    self.proxy = new_proxy
                                    update_account(self.account_id, proxy=self.proxy)
                                    self.session.proxies = {"http": self.proxy, "https": self.proxy}
                                    if self.login():
                                        self.fail_count = 0
                                        logger.info(f"✅ تم تغيير البروكسي وإعادة تسجيل الدخول {self.account_id}")
                            break
                        
                        # توقيت عشوائي بين الدورات
                        time.sleep(random.uniform(1.0, 4.0))
                        
                except Exception as e:
                    logger.error(f"خطأ في جولة الدوران {self.account_id}: {e}")
                    time.sleep(10)
                    continue
                
                # تحديث الرصيد
                try:
                    update_account(
                        self.account_id,
                        balance=self.balance,
                        credits=self.credits,
                        total_earned=self.total_earned
                    )
                except Exception as e:
                    logger.error(f"خطأ في تحديث الرصيد {self.account_id}: {e}")
                
                # توقيت عشوائي بين الجولات
                time.sleep(random.uniform(3.0, 8.0))
                
            except Exception as e:
                logger.error(f"❌ خطأ رئيسي في حلقة الحساب {self.account_id}: {e}")
                time.sleep(10)
        
        self.running = False
        logger.info(f"⏹️ توقف الحساب {self.account_id}")

# ============================================================
# BotManager
# ============================================================
class BotManager:
    def __init__(self):
        self.workers = {}
        self.threads = {}
        self.running = False
        self.chat_id = None
        self.dashboard_message_id = None
    
    def start_account(self, account_id):
        """تشغيل حساب"""
        with worker_lock:
            if account_id in self.workers:
                return False
            
            account = get_account_by_id(account_id)
            if not account:
                return False
            
            proxy = account.get('proxy')
            if USE_PROXIES and (not proxy or not test_proxy(proxy)):
                new_proxy = get_proxy()
                if new_proxy:
                    proxy = new_proxy
                    update_account(account_id, proxy=proxy)
            
            worker = AccountWorker(account_id, proxy)
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
                time.sleep(0.5)
        
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
    
    def restart_account(self, account_id):
        """إعادة تشغيل حساب"""
        self.stop_account(account_id)
        time.sleep(2)
        return self.start_account(account_id)
    
    def get_status(self):
        """الحصول على حالة البوت"""
        accounts = get_all_accounts()
        total = len(accounts)
        running = len(self.workers)
        
        total_balance = 0
        details = []
        
        for acc in accounts:
            total_balance += acc.get('balance', 0)
            is_running = acc['id'] in self.workers
            status_icon = "🟢" if is_running else "🔴"
            has_withdrawn = acc.get('has_withdrawn_today', 0)
            if has_withdrawn:
                status_icon = "✅"
            
            details.append(
                f"{status_icon} ID:{acc['id']} {acc['email'][:25]} | "
                f"💰{acc['balance']:,.0f} | 🎯{acc.get('target_amount', 0):,}"
            )
        
        return {
            'total_accounts': total,
            'running_accounts': running,
            'total_balance': total_balance,
            'details': details
        }
    
    def dashboard_text(self):
        """نص لوحة التحكم"""
        status = self.get_status()
        
        text = (
            f"📊 <b>لوحة التحكم</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"📧 الحسابات: {status['total_accounts']}\n"
            f"🟢 النشطة: {status['running_accounts']}\n"
            f"💰 الرصيد الكلي: {status['total_balance']:,.0f}\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"<b>تفاصيل الحسابات:</b>\n"
        )
        
        if status['details']:
            text += "\n".join(status['details'])
        else:
            text += "⚠️ لا توجد حسابات"
        
        text += f"\n━━━━━━━━━━━━━━━━━\n🔄 {datetime.now().strftime('%H:%M:%S')}"
        
        return text

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
        [InlineKeyboardButton("📊 لوحة التحكم", callback_data="dashboard")],
        [InlineKeyboardButton("📧 إضافة حساب", callback_data="add_account")],
        [InlineKeyboardButton("🗑️ حذف حساب", callback_data="delete_account")],
        [InlineKeyboardButton("🌐 إدارة البروكسيات", callback_data="proxies_menu")],
        [InlineKeyboardButton("💰 سحب يدوي", callback_data="manual_withdraw")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_chat_id, bot_application
    
    bot_chat_id = update.message.chat_id
    bot_application = context.application
    
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
    
    await update.message.reply_text(
        main_text,
        reply_markup=get_main_keyboard(),
        parse_mode="HTML"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_chat_id, bot_application
    
    query = update.callback_query
    await query.answer()
    
    bot_chat_id = query.message.chat_id
    bot_application = context.application
    
    data = query.data
    
    if data == "start_all":
        if bot_manager.running:
            await query.edit_message_text("✅ البوت يعمل بالفعل!")
            return
        
        started = bot_manager.start_all()
        await query.edit_message_text(f"🚀 تم تشغيل {started} حساب")
        await show_main_menu(update, context, query.message.chat_id)
    
    elif data == "stop_all":
        if not bot_manager.running:
            await query.edit_message_text("❌ البوت لا يعمل!")
            return
        
        stopped = bot_manager.stop_all()
        await query.edit_message_text(f"⏹️ تم إيقاف {stopped} حساب")
        await show_main_menu(update, context, query.message.chat_id)
    
    elif data == "dashboard":
        text = bot_manager.dashboard_text()
        keyboard = [
            [InlineKeyboardButton("🔄 تحديث", callback_data="dashboard")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    
    elif data == "add_account":
        pending_emails[query.from_user.id] = "waiting_for_account"
        await query.edit_message_text(
            "📝 <b>إضافة حساب جديد</b>\n\n"
            "أرسل الإيميل وكلمة المرور بالصيغة:\n"
            "<code>email password</code>\n\n"
            "مثال: <code>user@uberip.com MyPass123</code>\n\n"
            "🔙 لإلغاء العملية أرسل /cancel",
            parse_mode="HTML"
        )
    
    elif data == "delete_account":
        accounts = get_all_accounts()
        if not accounts:
            await query.edit_message_text("📭 لا يوجد حسابات!")
            return
        
        keyboard = []
        for acc in accounts:
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑️ {acc['email'][:25]} (ID:{acc['id']})",
                    callback_data=f"del_acc_{acc['id']}"
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
        
        await query.edit_message_text(
            "🗑️ <b>اختر الحساب للحذف:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    
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
        
        await show_main_menu(update, context, query.message.chat_id)
    
    elif data == "proxies_menu":
        keyboard = [
            [InlineKeyboardButton("📋 عرض البروكسيات", callback_data="view_proxies")],
            [InlineKeyboardButton("➕ إضافة بروكسيات", callback_data="add_proxies")],
            [InlineKeyboardButton("🧪 اختبار البروكسيات", callback_data="test_proxies")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_main")],
        ]
        await query.edit_message_text(
            "🌐 <b>إدارة البروكسيات</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    
    elif data == "view_proxies":
        proxies = load_proxies()
        if not proxies:
            await query.edit_message_text("📭 لا يوجد بروكسيات!")
            return
        
        text = "🌐 <b>قائمة البروكسيات</b>\n━━━━━━━━━━━━━━━━━\n"
        for i, p in enumerate(proxies, 1):
            ip = test_proxy(p)
            status = "✅" if ip else "❌"
            text += f"{i}. {status} {p}\n"
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    
    elif data == "add_proxies":
        pending_emails[query.from_user.id] = "waiting_for_proxies"
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
        
        await query.edit_message_text("🔄 جاري اختبار البروكسيات...")
        
        valid = []
        invalid = []
        for p in proxies:
            ip = test_proxy(p)
            if ip:
                valid.append(p)
            else:
                invalid.append(p)
        
        if invalid:
            save_proxies(valid)
        
        text = (
            f"🧪 <b>نتيجة الاختبار</b>\n"
            f"━━━━━━━━━━━━━━━━━\n"
            f"✅ صالح: {len(valid)}\n"
            f"❌ تالف: {len(invalid)}\n"
        )
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    
    elif data == "manual_withdraw":
        accounts = get_all_accounts()
        if not accounts:
            await query.edit_message_text("📭 لا يوجد حسابات!")
            return
        
        keyboard = []
        for acc in accounts:
            if acc.get('has_withdrawn_today', 0) == 0 and acc.get('balance', 0) >= MIN_WITHDRAW:
                keyboard.append([
                    InlineKeyboardButton(
                        f"💰 {acc['email'][:25]} (💰{acc['balance']:,.0f})",
                        callback_data=f"withdraw_{acc['id']}"
                    )
                ])
        
        if not keyboard:
            await query.edit_message_text("⚠️ لا يوجد حسابات قابلة للسحب (رصيد كافٍ أو تم السحب اليوم)")
            return
        
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_main")])
        
        await query.edit_message_text(
            "💰 <b>اختر الحساب للسحب:</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    
    elif data.startswith("withdraw_"):
        account_id = int(data.split("_")[1])
        account = get_account_by_id(account_id)
        
        if not account:
            await query.edit_message_text("❌ الحساب غير موجود")
            return
        
        # التحقق من الرصيد
        balance = account.get('balance', 0)
        if balance < MIN_WITHDRAW:
            await query.edit_message_text(f"❌ الرصيد {balance} أقل من الحد الأدنى {MIN_WITHDRAW}")
            await show_main_menu(update, context, query.message.chat_id)
            return
        
        # إيقاف الحساب مؤقتاً
        was_running = account_id in bot_manager.workers
        if was_running:
            bot_manager.stop_account(account_id)
        
        await query.edit_message_text("🔄 جاري السحب...")
        
        # إنشاء Worker مؤقت للسحب
        worker = AccountWorker(account_id, account.get('proxy'))
        worker.token = account.get('token')
        worker.user_id = account.get('user_id')
        worker.balance = balance
        worker.credits = account.get('credits', 0)
        worker.account = account
        
        # محاولة السحب
        success = worker.withdraw()
        
        if success:
            await query.edit_message_text("✅ تم السحب بنجاح!")
        else:
            await query.edit_message_text("❌ فشل السحب")
        
        # إعادة تشغيل الحساب
        if was_running:
            bot_manager.start_account(account_id)
        
        await show_main_menu(update, context, query.message.chat_id)
    
    elif data == "back_main":
        await show_main_menu(update, context, query.message.chat_id)

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
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            main_text,
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
        
        progress = await update.message.reply_text(f"🔄 جاري إنشاء الحساب...\n📧 {email}")
        
        try:
            # الحصول على بروكسي
            proxy = get_proxy() if USE_PROXIES else None
            
            # محاولة تسجيل الدخول أو التسجيل
            success, token, user_id_api, balance, credits, msg = register_or_login(
                email, password, proxy
            )
            
            if not success:
                await progress.edit_text(f"❌ {msg}")
                del pending_emails[user_id]
                return
            
            # التحقق من وجود الحساب
            existing = get_account_by_email(email)
            
            if existing:
                # تحديث الحساب الموجود
                update_account(
                    existing['id'],
                    token=token,
                    user_id=user_id_api,
                    balance=balance,
                    credits=credits,
                    last_login=datetime.now().isoformat(),
                    is_active=1
                )
                account_id = existing['id']
            else:
                # إضافة حساب جديد
                account_id = add_account(email, password, token, user_id_api, balance, credits, proxy)
            
            if account_id:
                # تشغيل الحساب
                bot_manager.start_account(account_id)
                
                await progress.edit_text(
                    f"✅ <b>تم {'تسجيل الدخول' if existing else 'إنشاء'} الحساب!</b>\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"🆔 ID: {account_id}\n"
                    f"📧 {email}\n"
                    f"💰 الرصيد: {balance:,.0f}\n"
                    f"🌐 بروكسي: {proxy if proxy else 'بدون'}\n"
                    f"📝 {msg}",
                    parse_mode="HTML"
                )
            else:
                await progress.edit_text("❌ فشل حفظ الحساب في قاعدة البيانات")
            
        except Exception as e:
            logger.error(f"خطأ في إضافة حساب: {e}")
            await progress.edit_text(f"❌ خطأ غير متوقع: {str(e)[:50]}")
        
        del pending_emails[user_id]
        await show_main_menu(update, context, update.message.chat_id)
    
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
        await show_main_menu(update, context, update.message.chat_id)
    
    else:
        await update.message.reply_text("❌ أمر غير معروف. استخدم /start للبدء.")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in pending_emails:
        del pending_emails[user_id]
    await update.message.reply_text("❌ تم إلغاء العملية!")

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
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🎰 Starting Slot Bot - النسخة النهائية المحسنة")
    print("✅ Bot is running! Press Ctrl+C to stop")
    print("📧 نظام مراقبة البريد التلقائي: مفعل")
    print("💰 نظام السحب التلقائي: مفعل (عند الوصول للهدف)")
    print("💰 نظام السحب اليدوي: مفعل")
    print("🌐 نظام البروكسيات: مفعل" if USE_PROXIES else "🌐 نظام البروكسيات: معطل")
    print("🔄 إعادة المحاولة: مفعلة (3 مرات)")
    print("📧 وقت انتظار الكود: 180 ثانية")
    
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
