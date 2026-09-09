#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Slot Fruits Bot - نظام الهدف اليومي مع إشعارات السحب
نسخة محسنة مع دعم إضافة حسابات متعددة - معالجة مستقلة لكل حساب
"""

import os
import sys
import json
import time
import random
import requests
import re
import sqlite3
import threading
import logging
import asyncio
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import warnings
from telegram.warnings import PTBUserWarning

# ============================================================
# تحميل الإعدادات من ملف config.json
# ============================================================

def load_config():
    """تحميل الإعدادات من ملف config.json"""
    config_file = "config.json"
    default_config = {
        "bot_token": "YOUR_BOT_TOKEN_HERE",
        "mail_tm_api": "https://api.mail.tm",
        "mail_tm_domain": "@uberip.com",
        "base_url": "https://slotfruits.com",
        "timeout": 30,
        "refresh_seconds": 5,
        "max_spin_cycles": 100,
        "min_withdraw_amount": 1000,
        "use_proxies": True,
        "proxy_rotation_interval": 300,
        "database_file": "slot_bot.db",
        "min_withdraw_interval": 300,
        "work_min_duration": 300,
        "work_max_duration": 600,
        "rest_min_duration": 180,
        "rest_max_duration": 420,
        "min_target": 55000,
        "max_target": 65000,
        "reset_hour": 0,
        "reset_minute": 0,
        "auto_fix_proxies": True
    }
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            print("✅ تم تحميل الإعدادات من config.json")
            return config
        except Exception as e:
            print(f"❌ خطأ في تحميل config.json: {e}")
            print("🔄 استخدام الإعدادات الافتراضية...")
            return default_config
    else:
        print("⚠️ ملف config.json غير موجود، يتم إنشاؤه...")
        try:
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            print("✅ تم إنشاء ملف config.json بنجاح")
            print("📝 الرجاء تعديل التوكن في config.json ثم إعادة التشغيل")
            print("🛑 إيقاف التشغيل...")
            sys.exit(1)
        except Exception as e:
            print(f"❌ خطأ في إنشاء config.json: {e}")
        return default_config

# تحميل الإعدادات
CONFIG = load_config()

# ============================================================
# الإعدادات من الملف
# ============================================================

BOT_TOKEN = CONFIG.get("bot_token")
if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or not BOT_TOKEN:
    print("❌ خطأ: لم يتم تعيين BOT_TOKEN في config.json")
    print("📝 الرجاء تعديل config.json وإضافة التوكن الصحيح")
    sys.exit(1)

MAIL_TM_API = CONFIG.get("mail_tm_api", "https://api.mail.tm")
MAIL_TM_DOMAIN = CONFIG.get("mail_tm_domain", "@uberip.com")
BASE_URL = CONFIG.get("base_url", "https://slotfruits.com")
TO = CONFIG.get("timeout", 30)
REFRESH_SECONDS = CONFIG.get("refresh_seconds", 5)
MAX_SPIN_CYCLES = CONFIG.get("max_spin_cycles", 100)
MIN_WITHDRAW_AMOUNT = CONFIG.get("min_withdraw_amount", 1000)
USE_PROXIES = CONFIG.get("use_proxies", True)
PROXY_ROTATION_INTERVAL = CONFIG.get("proxy_rotation_interval", 300)
DATABASE_FILE = CONFIG.get("database_file", "slot_bot.db")
MIN_WITHDRAW_INTERVAL = CONFIG.get("min_withdraw_interval", 300)
WORK_MIN_DURATION = CONFIG.get("work_min_duration", 300)
WORK_MAX_DURATION = CONFIG.get("work_max_duration", 600)
REST_MIN_DURATION = CONFIG.get("rest_min_duration", 180)
REST_MAX_DURATION = CONFIG.get("rest_max_duration", 420)
MIN_TARGET = CONFIG.get("min_target", 55000)
MAX_TARGET = CONFIG.get("max_target", 65000)
RESET_HOUR = CONFIG.get("reset_hour", 0)
RESET_MINUTE = CONFIG.get("reset_minute", 0)
AUTO_FIX_PROXIES = CONFIG.get("auto_fix_proxies", True)

# العملة المستخدمة في السحب
COIN_ID = "65d2e4f4a3b5c7d8e9f0a1b2"

print(f"""
🎰 Slot Fruits Bot - نظام الهدف اليومي مع إشعارات السحب
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🤖 توكن البوت: {'✅ موجود' if BOT_TOKEN and BOT_TOKEN != 'YOUR_BOT_TOKEN_HERE' else '❌ غير موجود'}
📧 Mail.tm API: {MAIL_TM_API}
🌐 دومين Mail.tm: {MAIL_TM_DOMAIN}
⏱️ وقت الاستجابة: {TO} ثانية
🔄 استخدام البروكسيات: {'نعم' if USE_PROXIES else 'لا'}
🎯 الحد الأدنى للهدف: {MIN_TARGET:,}
🎯 الحد الأقصى للهدف: {MAX_TARGET:,}
✅ نظام إشعارات السحب: مفعل
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
""")

# ============================================================
# إعدادات السجلات
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=PTBUserWarning)

# ============================================================
# متغيرات عامة
# ============================================================

API_URL = f"{BASE_URL}/api/v1"
GRAPHQL_URL = f"{BASE_URL}/graphql"

BOT_APPLICATION = None
BOT_CHAT_ID = None
last_withdraw_time = None
withdraw_lock = threading.Lock()
user_states = {}
waiting_for = {}
temp_messages = {}
batch_add_accounts = {}
account_workers = {}
worker_threads = {}
stop_events = {}
worker_locks = {}
is_shutting_down = False
dashboard_message_ids = []
current_dashboard_text = ""
dashboard_update_lock = threading.Lock()
pending_notifications = []
notification_lock = threading.Lock()
proxy_failures = {}
last_proxy_validation = {}

# ============================================================
# نظام البريد المؤقت Mail.tm
# ============================================================

mail_monitors = {}
seen_messages = {}
mail_callbacks = {}
verification_codes = {}
withdraw_notifications = {}

def clean_html(raw_html):
    if not raw_html:
        return ""
    if isinstance(raw_html, list):
        raw_html = "".join(raw_html)
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, "", raw_html).strip()

def get_mail_token(email, password):
    """تسجيل الدخول إلى Mail.tm والحصول على توكن"""
    url = f"{MAIL_TM_API}/token"
    try:
        res = requests.post(url, json={"address": email, "password": password}, timeout=30)
        if res.status_code == 200:
            token = res.json().get("token")
            logger.info(f"✅ تم الحصول على توكن Mail.tm لـ {email}")
            return token
        logger.warning(f"⚠️ فشل الحصول على توكن لـ {email}: {res.status_code}")
        return None
    except Exception as e:
        logger.error(f"❌ خطأ في get_mail_token لـ {email}: {e}")
        return None

def create_mail_account(email=None, password=None):
    """إنشاء حساب بريد مؤقت جديد"""
    url = f"{MAIL_TM_API}/accounts"
    
    if not email:
        import uuid
        local_part = str(uuid.uuid4())[:8]
        email = f"{local_part}{MAIL_TM_DOMAIN}"
    
    if not password:
        import string
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    
    try:
        res = requests.post(url, json={
            "address": email,
            "password": password
        }, timeout=30)
        
        if res.status_code == 201:
            logger.info(f"✅ تم إنشاء بريد مؤقت: {email}")
            return email, password, True
        logger.error(f"❌ فشل إنشاء البريد {email}: {res.status_code}")
        return email, password, False
    except Exception as e:
        logger.error(f"❌ خطأ في create_mail_account: {e}")
        return email, password, False

def get_mail_messages(token, limit=10):
    """الحصول على رسائل البريد المؤقت"""
    url = f"{MAIL_TM_API}/messages"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(url, headers=headers, params={"page": 1, "limit": limit}, timeout=30)
        if res.status_code == 200:
            return res.json().get("hydra:member", [])
        return []
    except Exception as e:
        logger.error(f"❌ خطأ في get_mail_messages: {e}")
        return []

def get_mail_message(token, message_id):
    """الحصول على تفاصيل رسالة معينة"""
    url = f"{MAIL_TM_API}/messages/{message_id}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code == 200:
            return res.json()
        return None
    except Exception as e:
        logger.error(f"❌ خطأ في get_mail_message: {e}")
        return None

def extract_verification_code_from_mail(email_data):
    """استخراج كود التحقق من محتوى البريد"""
    if not email_data:
        return None
    
    body_text = email_data.get("text") or ""
    body_html = email_data.get("html") or ""
    
    if body_html:
        body_text = clean_html(body_html)
    
    patterns = [
        r"verification\s*code\s*[:\-]?\s*#?\s*([0-9]{4,10})",
        r"verification\s+code.{0,120}?#?\s*([0-9]{4,10})",
        r"(?:رمز|كود)\s*(?:التحقق|التأكيد).{0,120}?#?\s*([0-9]{4,10})",
        r"Withdrawal\s+amount.*?Verification\s+code:\s*([0-9]{4,10})",
        r"Verification\s+code:\s*([0-9]{4,10})",
        r"code[:\s]+([0-9]{4,10})",
        r"([0-9]{4,10})\s*(?:is|this is|your)\s*(?:your\s+)?verification",
        r"رمز التحقق:\s*([0-9]{4,10})",
        r"كود التأكيد:\s*([0-9]{4,10})",
    ]
    
    for pattern in patterns:
        match = re.search(pattern, body_text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            code = match.group(1)
            if len(code) >= 4 and len(code) <= 10 and code.isdigit():
                logger.info(f"✅ تم استخراج الكود: {code}")
                return code
    
    numbers = re.findall(r'\b(\d{4,6})\b', body_text)
    if numbers:
        code = numbers[0]
        logger.info(f"✅ تم استخراج كود محتمل: {code}")
        return code
    
    return None

def extract_withdraw_confirmation(email_data):
    """استخراج معلومات تأكيد السحب من البريد"""
    if not email_data:
        return None
    
    body_text = email_data.get("text") or ""
    body_html = email_data.get("html") or ""
    
    if body_html:
        body_text = clean_html(body_html)
    
    withdraw_info = {}
    
    amount_match = re.search(r'(?:amount|المبلغ|Withdrawal amount)[:\s]+([0-9,]+\.?[0-9]*)', body_text, re.IGNORECASE)
    if amount_match:
        withdraw_info['amount'] = amount_match.group(1).replace(',', '')
    
    status_match = re.search(r'(?:status|الحالة)[:\s]+(completed|success|تم|ناجح|Confirmed)', body_text, re.IGNORECASE)
    if status_match:
        withdraw_info['status'] = status_match.group(1)
    
    tx_match = re.search(r'(?:transaction|معاملة|TX|tx)[:\s#]+([A-Za-z0-9]{10,})', body_text, re.IGNORECASE)
    if tx_match:
        withdraw_info['tx_hash'] = tx_match.group(1)
    
    address_match = re.search(r'(?:address|عنوان|to)[:\s]+([A-Za-z0-9@._-]{5,})', body_text, re.IGNORECASE)
    if address_match:
        withdraw_info['address'] = address_match.group(1)
    
    if withdraw_info:
        logger.info(f"✅ تم استخراج معلومات السحب: {withdraw_info}")
        return withdraw_info
    
    return None

def start_mail_monitor(email, password, callback=None):
    """بدء مراقبة البريد المؤقت مع إعادة محاولة التسجيل"""
    if email in mail_monitors and mail_monitors[email].get("running", False):
        logger.info(f"📧 البريد لـ {email} قيد المراقبة بالفعل")
        return mail_monitors[email].get("token")
    
    token = None
    for attempt in range(3):
        token = get_mail_token(email, password)
        if token:
            break
        logger.info(f"🔄 محاولة تسجيل الدخول {attempt+1}/3 لـ {email}")
        time.sleep(2)
    
    if not token:
        logger.error(f"❌ فشل تسجيل الدخول إلى Mail.tm لـ {email} بعد 3 محاولات")
        return None
    
    if email not in seen_messages:
        seen_messages[email] = set()
    
    mail_monitors[email] = {
        "token": token,
        "running": True,
        "thread": None,
        "email": email,
        "password": password
    }
    
    if callback:
        mail_callbacks[email] = callback
    
    def monitor_loop():
        logger.info(f"📧 بدء مراقبة البريد لـ {email}")
        retry_count = 0
        
        while mail_monitors.get(email, {}).get("running", False):
            try:
                token = mail_monitors[email]["token"]
                messages = get_mail_messages(token, limit=5)
                retry_count = 0
                
                for msg in messages:
                    msg_id = msg.get("id")
                    if msg_id not in seen_messages[email]:
                        seen_messages[email].add(msg_id)
                        
                        detail = get_mail_message(token, msg_id)
                        if detail:
                            code = extract_verification_code_from_mail(detail)
                            if code:
                                verification_codes[email] = {
                                    "code": code,
                                    "timestamp": time.time(),
                                    "message": detail
                                }
                                logger.info(f"✅ تم العثور على كود لـ {email}: {code}")
                                
                                if email in mail_callbacks:
                                    try:
                                        mail_callbacks[email](email, code, detail)
                                    except Exception as e:
                                        logger.error(f"❌ خطأ في callback لـ {email}: {e}")
                            
                            withdraw_info = extract_withdraw_confirmation(detail)
                            if withdraw_info:
                                withdraw_notifications[email] = {
                                    "info": withdraw_info,
                                    "timestamp": time.time(),
                                    "message": detail
                                }
                                logger.info(f"✅ تم العثور على تأكيد سحب لـ {email}: {withdraw_info}")
                                
                                asyncio.run_coroutine_threadsafe(
                                    send_withdraw_notification(email, withdraw_info),
                                    asyncio.get_event_loop()
                                )
                
            except Exception as e:
                logger.error(f"❌ خطأ في مراقبة البريد لـ {email}: {e}")
                retry_count += 1
                
                if retry_count >= 3:
                    logger.warning(f"🔄 محاولة إعادة تسجيل الدخول لـ {email}")
                    new_token = get_mail_token(email, password)
                    if new_token:
                        mail_monitors[email]["token"] = new_token
                        retry_count = 0
                        logger.info(f"✅ تم تجديد توكن Mail.tm لـ {email}")
                    else:
                        logger.warning(f"⚠️ فشل تجديد التوكن لـ {email}")
                        time.sleep(10)
            
            time.sleep(3)
        
        logger.info(f"⏹️ توقفت مراقبة البريد لـ {email}")
    
    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()
    mail_monitors[email]["thread"] = thread
    
    logger.info(f"✅ بدأت مراقبة البريد لـ {email}")
    return token

# ============================================================
# دوال إرسال الإشعارات
# ============================================================

async def send_withdraw_notification(email, withdraw_info):
    """إرسال إشعار عند وصول تأكيد السحب"""
    try:
        if not BOT_APPLICATION or not BOT_CHAT_ID:
            logger.warning("⚠️ البوت غير جاهز لإرسال الإشعارات")
            return
        
        account = get_account_by_email(email)
        account_id = account.get('id') if account else 'غير معروف'
        
        amount = withdraw_info.get('amount', 'غير معروف')
        status = withdraw_info.get('status', 'مكتمل')
        tx_hash = withdraw_info.get('tx_hash', 'غير متوفر')
        address = withdraw_info.get('address', 'غير معروف')
        
        notification_text = (
            f"💰 <b>تم تأكيد السحب!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📧 البريد: {email}\n"
            f"🆔 الحساب: {account_id}\n"
            f"💵 المبلغ: {amount} فوت\n"
            f"📊 الحالة: ✅ {status}\n"
            f"🔗 رقم المعاملة: <code>{tx_hash}</code>\n"
            f"📬 عنوان المحفظة: {address}\n"
            f"🕐 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ تم تحويل الأموال بنجاح إلى محفظتك!"
        )
        
        await BOT_APPLICATION.bot.send_message(
            chat_id=BOT_CHAT_ID,
            text=notification_text,
            parse_mode="HTML"
        )
        
        logger.info(f"✅ تم إرسال إشعار السحب لـ {email}")
        
        if account:
            update_account(
                account_id,
                last_withdrawal=datetime.now().isoformat(),
                has_withdrawn_today=1,
                last_withdraw_date=datetime.now().strftime("%Y-%m-%d")
            )
            
    except Exception as e:
        logger.error(f"❌ خطأ في إرسال إشعار السحب: {e}")

async def send_notification(message):
    """إرسال إشعار عام"""
    global pending_notifications
    if BOT_APPLICATION and BOT_CHAT_ID:
        try:
            with notification_lock:
                pending_notifications.append(message)
            
            while True:
                with notification_lock:
                    if not pending_notifications:
                        break
                    msg = pending_notifications.pop(0)
                try:
                    await BOT_APPLICATION.bot.send_message(
                        chat_id=BOT_CHAT_ID, 
                        text=msg, 
                        parse_mode="HTML"
                    )
                except:
                    pass
                await asyncio.sleep(0.5)
        except:
            pass

def send_notification_sync(message):
    """إرسال إشعار متزامن"""
    if BOT_APPLICATION and BOT_CHAT_ID:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(send_notification(message))
            loop.close()
        except:
            pass

def wait_for_code_mailtm(email, password, timeout=180, check_interval=3):
    """انتظار كود التحقق من Mail.tm مع محاولات متعددة"""
    
    if email not in mail_monitors or not mail_monitors[email].get("running", False):
        logger.info(f"📧 بدء مراقبة البريد لـ {email}")
        token = start_mail_monitor(email, password)
        if not token:
            logger.error(f"❌ فشل بدء مراقبة البريد لـ {email}")
            return None
    
    start_time = time.time()
    last_manual_check = start_time
    retry_register_attempts = 0
    
    while time.time() - start_time < timeout:
        if email in verification_codes:
            code_data = verification_codes[email]
            if code_data.get("code"):
                code = code_data["code"]
                del verification_codes[email]
                logger.info(f"✅ تم استلام الكود لـ {email}: {code}")
                return code
        
        if time.time() - last_manual_check > 15:
            token = mail_monitors[email]["token"]
            try:
                messages = get_mail_messages(token, limit=10)
                for msg in messages:
                    msg_id = msg.get("id")
                    if msg_id not in seen_messages.get(email, set()):
                        seen_messages.setdefault(email, set()).add(msg_id)
                        detail = get_mail_message(token, msg_id)
                        if detail:
                            code = extract_verification_code_from_mail(detail)
                            if code:
                                verification_codes[email] = {
                                    "code": code,
                                    "timestamp": time.time(),
                                    "message": detail
                                }
                                logger.info(f"✅ تم العثور على كود يدوياً لـ {email}: {code}")
                                return code
            except Exception as e:
                logger.debug(f"Manual mail check error: {e}")
            last_manual_check = time.time()
        
        if time.time() - start_time > 45 and retry_register_attempts < 3:
            logger.info(f"🔄 محاولة إعادة التسجيل في SlotFruits لـ {email} (المحاولة {retry_register_attempts+1})")
            success, msg = do_register_mailtm(email, password, None)
            if success:
                logger.info(f"✅ تم إعادة التسجيل بنجاح لـ {email}")
                retry_register_attempts += 1
            else:
                logger.warning(f"⚠️ فشل إعادة التسجيل لـ {email}: {msg}")
                retry_register_attempts += 1
        
        time.sleep(check_interval)
    
    logger.warning(f"⏰ انتهى وقت انتظار الكود لـ {email} بعد {timeout} ثانية")
    return None

def verify_mail_account_exists(email, password):
    """التحقق من وجود الحساب في Mail.tm"""
    url = f"{MAIL_TM_API}/token"
    try:
        res = requests.post(url, json={"address": email, "password": password}, timeout=10)
        if res.status_code == 200:
            return True
        return False
    except:
        return False

# ============================================================
# دوال API للعبة
# ============================================================

def safe_request(method, url, **kw):
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

def do_register_mailtm(email, password, proxy=None):
    """التسجيل في SlotFruits باستخدام البريد المؤقت"""
    try:
        if not verify_mail_account_exists(email, password):
            logger.warning(f"⚠️ الحساب {email} غير موجود في Mail.tm، يتم إنشاؤه...")
            email, password, success = create_mail_account(email, password)
            if not success:
                return False, "فشل إنشاء البريد المؤقت"
        
        time.sleep(1)
        
        url = f"{BASE_URL}/api/v1/users/registerFaucetPay"
        payload = {"email": email, "password": password}
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }
        
        kw = {"headers": headers, "data": json.dumps(payload), "timeout": TO}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}
        
        res = safe_request("POST", url, **kw)
        
        if not res:
            return False, "No response from server"
        
        try:
            data = res.json()
        except:
            return False, "Invalid response"
        
        if data.get("success") or data.get("needsConfirmation") == True:
            return True, "Registration successful"
        else:
            return False, data.get("message", "Registration failed")
    except Exception as e:
        return False, str(e)

def do_confirm_mailtm(email, code, proxy=None):
    """تأكيد التسجيل في SlotFruits باستخدام الكود"""
    try:
        url = f"{BASE_URL}/api/v1/users/confirmFaucetPay"
        payload = {"email": email, "code": code}
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }
        
        kw = {"headers": headers, "data": json.dumps(payload), "timeout": TO}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}
        
        res = safe_request("POST", url, **kw)
        
        if not res:
            return False, None, "No response"
        
        try:
            data = res.json()
        except:
            return False, None, "Invalid response"
        
        if data.get("token") or data.get("user") or data.get("success"):
            return True, data.get("token"), "Verification successful"
        else:
            return False, None, data.get("message", "Verification failed")
    except Exception as e:
        return False, None, str(e)

def do_login(email, password, proxy=None):
    """تسجيل الدخول إلى SlotFruits"""
    try:
        url = f"{BASE_URL}/api/v1/users/signupFaucetPayLogin"
        payload = {"email": email, "password": password}
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }
        
        kw = {"headers": headers, "data": json.dumps(payload)}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}
        
        res = safe_request("POST", url, **kw)
        
        if not res:
            return None, None, 0, 0, "No response"

        data = res.json()
        user = data.get("user")
        if not user:
            return None, None, 0, 0, "Login failed"

        bal = user.get("balance", 0)
        cr = user.get("credits", 0)
        token = data.get("token")
        userid = user.get("_id")

        return token, userid, bal, cr, "Success"
    except Exception as e:
        return None, None, 0, 0, str(e)

def get_user_info(token, proxy=None):
    """الحصول على معلومات المستخدم"""
    try:
        url = f"{BASE_URL}/api/v1/users/me"
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {token}"
        }
        
        kw = {"headers": headers}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}
        
        res = safe_request("GET", url, **kw)
        if res and res.status_code == 200:
            data = res.json()
            return data.get("user", {})
        return None
    except:
        return None

def spin_once(token, proxy=None):
    """الدوران مرة واحدة"""
    try:
        headers = {
            "User-Agent": "okhttp/4.12.0",
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip",
            "authorization": f"Bearer {token}",
        }
        
        kw = {"headers": headers}
        if proxy:
            proxy_clean = proxy.strip()
            if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}
        
        r = safe_request("GET", f"{BASE_URL}/api/v1/users/earnRoll", **kw)
        if not r or r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None
    except:
        return None

def farm_ads(userid, proxy=None):
    """تشغيل الإعلانات للحصول على كريدت"""
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
            if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://"):
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
                        if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://"):
                            proxy_clean = f"http://{proxy_clean}"
                        kw2["proxies"] = {"http": proxy_clean, "https": proxy_clean}
                    safe_request("GET", urlunparse(new), **kw2)
                    hit = True
        except Exception:
            pass
        time.sleep(0.3)
    return hit

def request_withdrawal_code(token, address, amount, coin_id, wallet_type="FP", proxy=None):
    """طلب كود السحب"""
    try:
        url = f"{BASE_URL}/api/v1/users/requestWithdrawCode"
        
        payload = {
            "input": {
                "address": address,
                "value": amount,
                "token_recaptcha": "token_recaptcha",
                "id": coin_id,
                "type_wallet": wallet_type
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
            if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}
        
        res = safe_request("POST", url, **kw)
        
        if not res:
            return False, None, None
        
        try:
            data = res.json()
            result = data.get("result", {})
            if result.get("status") == "success" or data.get("success"):
                return True, coin_id, result.get("info", "Code sent")
            else:
                return False, None, result.get("msg", "Unknown error")
        except Exception as e:
            return False, None, str(e)
    except Exception as e:
        return False, None, str(e)

def confirm_withdrawal(token, address, amount, code, coin_id, wallet_type="FP", proxy=None):
    """تأكيد السحب"""
    try:
        url = f"{BASE_URL}/api/v1/users/withdraw"
        
        payload = {
            "input": {
                "address": address,
                "value": amount,
                "token_recaptcha": "token_recaptcha",
                "id": coin_id,
                "type_wallet": wallet_type,
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
            if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://"):
                proxy_clean = f"http://{proxy_clean}"
            kw["proxies"] = {"http": proxy_clean, "https": proxy_clean}
        
        res = safe_request("POST", url, **kw)
        
        if not res:
            return False, None, "No response from server"
        
        try:
            data = res.json()
            result = data.get("result", {})
            
            if result.get("status") == "success" or data.get("success"):
                return True, data, None
            else:
                error_msg = result.get("msg") or data.get("message") or "Unknown error"
                return False, data, error_msg
        except Exception as e:
            return False, None, f"Parse error: {e}"
    except Exception as e:
        return False, None, f"Request error: {e}"

# ============================================================
# دوال قاعدة البيانات
# ============================================================

def init_database():
    """تهيئة قاعدة البيانات"""
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
            auto_withdraw_enabled INTEGER DEFAULT 0,
            proxy TEXT,
            last_proxy_check TEXT,
            limit_notified INTEGER DEFAULT 0,
            spin_count INTEGER DEFAULT 0,
            proxy_fail_count INTEGER DEFAULT 0,
            target_amount INTEGER DEFAULT 0,
            has_withdrawn_today INTEGER DEFAULT 0,
            last_withdraw_date TEXT,
            work_start_time TEXT,
            rest_start_time TEXT,
            is_resting INTEGER DEFAULT 0,
            daily_target_reached INTEGER DEFAULT 0
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
            response_data TEXT,
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
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)
    
    cursor.execute("""
        INSERT OR IGNORE INTO settings (key, value) VALUES 
        ('auto_withdraw_threshold', '999999999'),
        ('auto_withdraw_enabled', 'false'),
        ('max_spin_cycles', '100'),
        ('use_proxies', 'true'),
        ('proxy_rotation_interval', '300'),
        ('last_proxy_validation', ''),
        ('auto_fix_proxies', 'true'),
        ('work_min_duration', '300'),
        ('work_max_duration', '600'),
        ('rest_min_duration', '180'),
        ('rest_max_duration', '420'),
        ('min_target', '55000'),
        ('max_target', '65000')
    """)
    
    conn.commit()
    conn.close()

def get_setting(key, default=None):
    """الحصول على إعداد"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else default
    except:
        return default

def set_setting(key, value):
    """تعيين إعداد"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def add_account(email, password, token=None, user_id=None, balance=0, credits=0, proxy=None):
    """إضافة حساب جديد"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        target = random.randint(MIN_TARGET, MAX_TARGET)
        
        cursor.execute("""
            INSERT INTO accounts (email, password, token, user_id, balance, credits, created_at, proxy, target_amount, auto_withdraw_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (email, password, token, user_id, balance, credits, datetime.now().isoformat(), proxy, target, 0))
        conn.commit()
        account_id = cursor.lastrowid
        conn.close()
        return account_id
    except Exception as e:
        logger.error(f"Error adding account: {e}")
        return None

def get_account_by_id(account_id):
    """الحصول على حساب بالمعرف"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE id = ?", (account_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            columns = ['id', 'email', 'password', 'token', 'user_id', 'balance', 'credits', 'total_earned', 
                       'created_at', 'last_login', 'is_active', 'withdrawal_count', 'last_withdrawal', 
                       'auto_withdraw_enabled', 'proxy', 'last_proxy_check', 'limit_notified', 'spin_count',
                       'proxy_fail_count', 'target_amount', 'has_withdrawn_today', 'last_withdraw_date',
                       'work_start_time', 'rest_start_time', 'is_resting', 'daily_target_reached']
            return dict(zip(columns, row))
        return None
    except:
        return None

def get_account_by_email(email):
    """الحصول على حساب بالبريد"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM accounts WHERE email = ?", (email,))
        row = cursor.fetchone()
        conn.close()
        if row:
            columns = ['id', 'email', 'password', 'token', 'user_id', 'balance', 'credits', 'total_earned', 
                       'created_at', 'last_login', 'is_active', 'withdrawal_count', 'last_withdrawal', 
                       'auto_withdraw_enabled', 'proxy', 'last_proxy_check', 'limit_notified', 'spin_count',
                       'proxy_fail_count', 'target_amount', 'has_withdrawn_today', 'last_withdraw_date',
                       'work_start_time', 'rest_start_time', 'is_resting', 'daily_target_reached']
            return dict(zip(columns, row))
        return None
    except:
        return None

def get_all_accounts(active_only=True):
    """الحصول على جميع الحسابات"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        query = "SELECT * FROM accounts"
        if active_only:
            query += " WHERE is_active = 1"
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        columns = ['id', 'email', 'password', 'token', 'user_id', 'balance', 'credits', 'total_earned', 
                   'created_at', 'last_login', 'is_active', 'withdrawal_count', 'last_withdrawal', 
                   'auto_withdraw_enabled', 'proxy', 'last_proxy_check', 'limit_notified', 'spin_count',
                   'proxy_fail_count', 'target_amount', 'has_withdrawn_today', 'last_withdraw_date',
                   'work_start_time', 'rest_start_time', 'is_resting', 'daily_target_reached']
        return [dict(zip(columns, row)) for row in rows]
    except:
        return []

def update_account(account_id, **kwargs):
    """تحديث بيانات الحساب"""
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
        logger.error(f"Error updating account: {e}")
        return False

def delete_account(account_id):
    """حذف حساب"""
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
    """إضافة سحب جديد"""
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

def update_withdrawal(withdrawal_id, **kwargs):
    """تحديث بيانات السحب"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [withdrawal_id]
        cursor.execute(f"UPDATE withdrawals SET {set_clause} WHERE id = ?", values)
        conn.commit()
        conn.close()
        return True
    except:
        return False

def get_withdrawals(account_id=None, limit=10):
    """الحصول على سجلات السحوبات"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        if account_id:
            cursor.execute("SELECT * FROM withdrawals WHERE account_id = ? ORDER BY created_at DESC LIMIT ?", (account_id, limit))
        else:
            cursor.execute("SELECT * FROM withdrawals ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        columns = ['id', 'account_id', 'amount', 'address', 'wallet_type', 'status', 'tx_hash', 'response_data', 'created_at', 'completed_at']
        return [dict(zip(columns, row)) for row in rows]
    except:
        return []

def add_spin(account_id, spin_number, reward, balance, credits):
    """إضافة سجل دوران"""
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

def get_spins_count(account_id):
    """الحصول على عدد الدورات"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM spin_history WHERE account_id = ?", (account_id,))
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except:
        return 0

def reset_daily_withdrawals():
    """إعادة تعيين السحوبات اليومية"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE accounts 
            SET has_withdrawn_today = 0,
                daily_target_reached = 0,
                last_withdraw_date = NULL,
                is_resting = 0
        """)
        conn.commit()
        conn.close()
        logger.info("🔄 تم إعادة تعيين حالة السحب اليومي لجميع الحسابات")
        return True
    except Exception as e:
        logger.error(f"Error resetting daily withdrawals: {e}")
        return False

# ============================================================
# إدارة البروكسيات
# ============================================================

def load_proxies(proxy_file="proxy.txt"):
    """تحميل البروكسيات من الملف"""
    proxies = []
    if not os.path.exists(proxy_file):
        try:
            with open(proxy_file, "w", encoding="utf-8") as f:
                f.write("# قائمة البروكسيات\n")
                f.write("# http://ip:port أو ip:port\n")
        except:
            pass
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
        logger.error(f"Error loading proxies: {e}")
    
    return proxies

def save_proxies(proxies, proxy_file="proxy.txt"):
    """حفظ البروكسيات في الملف"""
    try:
        with open(proxy_file, "w", encoding="utf-8") as f:
            f.write("# قائمة البروكسيات - تم تحديثها تلقائياً\n")
            for proxy in proxies:
                proxy_clean = proxy.replace("http://", "").replace("https://", "").replace("socks://", "")
                f.write(f"{proxy_clean}\n")
        return True
    except Exception as e:
        logger.error(f"Error saving proxies: {e}")
        return False

def test_proxy(proxy, timeout=10):
    """اختبار بروكسي"""
    if not proxy:
        return None
    
    proxy = proxy.strip()
    if not proxy.startswith("http://") and not proxy.startswith("https://") and not proxy.startswith("socks"):
        proxy = f"http://{proxy}"
    
    test_urls = [
        "https://api.ipify.org?format=json",
        "https://httpbin.org/ip",
        "https://www.google.com"
    ]
    
    for url in test_urls:
        try:
            response = requests.get(
                url, 
                proxies={"http": proxy, "https": proxy}, 
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            if response.status_code == 200:
                try:
                    data = response.json()
                    ip = data.get("ip") or data.get("origin")
                    if ip:
                        return ip
                except:
                    text = response.text
                    ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', text)
                    if ip_match:
                        return ip_match.group(0)
                    return "Working"
        except:
            continue
    
    return None

def validate_proxies(proxies_list=None, max_workers=10):
    """التحقق من صحة البروكسيات"""
    if proxies_list is None:
        proxies_list = load_proxies()
    
    if not proxies_list:
        return [], []
    
    valid_proxies = []
    invalid_proxies = []
    
    def test_single_proxy(proxy):
        ip = test_proxy(proxy)
        return (proxy, ip)
    
    import concurrent.futures
    batch_size = min(max_workers, len(proxies_list))
    for i in range(0, len(proxies_list), batch_size):
        batch = proxies_list[i:i+batch_size]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=batch_size) as executor:
            futures = {executor.submit(test_single_proxy, proxy): proxy for proxy in batch}
            for future in concurrent.futures.as_completed(futures):
                proxy, ip = future.result()
                if ip:
                    valid_proxies.append(proxy)
                    logger.info(f"✅ Proxy {proxy} is working. IP: {ip}")
                else:
                    invalid_proxies.append(proxy)
                    logger.warning(f"❌ Proxy {proxy} is invalid")
    
    if invalid_proxies:
        save_proxies(valid_proxies)
        logger.info(f"Removed {len(invalid_proxies)} invalid proxies")
    
    return valid_proxies, invalid_proxies

def get_random_proxy(proxies_list=None, exclude_failed=True):
    """الحصول على بروكسي عشوائي"""
    if proxies_list is None:
        proxies_list = load_proxies()
    
    if not proxies_list:
        return None
    
    if exclude_failed:
        available = [p for p in proxies_list if p not in proxy_failures or proxy_failures.get(p, 0) < 3]
        if not available:
            available = proxies_list
    
    return random.choice(available) if available else None

def get_ip(proxy):
    """الحصول على IP البروكسي"""
    if not proxy:
        return "بدون بروكسي"
    
    cache_key = f"ip_{proxy}"
    if hasattr(get_ip, 'cache'):
        if cache_key in get_ip.cache:
            cached_time, cached_ip = get_ip.cache[cache_key]
            if (datetime.now() - cached_time).seconds < 300:
                return cached_ip
    
    try:
        proxy_clean = proxy.strip()
        if not proxy_clean.startswith("http://") and not proxy_clean.startswith("https://") and not proxy_clean.startswith("socks"):
            proxy_clean = f"http://{proxy_clean}"
        
        test_urls = [
            "https://api.ipify.org?format=json",
            "https://httpbin.org/ip"
        ]
        
        for url in test_urls:
            try:
                response = requests.get(
                    url, 
                    proxies={"http": proxy_clean, "https": proxy_clean}, 
                    timeout=10,
                    headers={"User-Agent": "Mozilla/5.0"}
                )
                if response.status_code == 200:
                    try:
                        data = response.json()
                        ip = data.get("ip") or data.get("origin")
                        if ip:
                            if not hasattr(get_ip, 'cache'):
                                get_ip.cache = {}
                            get_ip.cache[cache_key] = (datetime.now(), ip)
                            return ip
                    except:
                        text = response.text
                        ip_match = re.search(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', text)
                        if ip_match:
                            ip = ip_match.group(0)
                            if not hasattr(get_ip, 'cache'):
                                get_ip.cache = {}
                            get_ip.cache[cache_key] = (datetime.now(), ip)
                            return ip
            except:
                continue
    except:
        pass
    
    return "فشل البروكسي"

def mark_proxy_failed(proxy):
    """تسجيل فشل بروكسي"""
    if proxy:
        proxy_failures[proxy] = proxy_failures.get(proxy, 0) + 1
        if proxy_failures[proxy] >= 5:
            proxies = load_proxies()
            if proxy in proxies:
                proxies.remove(proxy)
                save_proxies(proxies)
                logger.info(f"🔄 Removed permanently failed proxy: {proxy}")
            del proxy_failures[proxy]

def reset_proxy_failures(proxy):
    """إعادة تعيين فشل بروكسي"""
    if proxy in proxy_failures:
        del proxy_failures[proxy]

def get_working_proxy(account_id=None, current_proxy=None):
    """الحصول على بروكسي شغال"""
    if not USE_PROXIES:
        return None
    
    if account_id:
        account = get_account_by_id(account_id)
        if account and account.get('proxy'):
            ip = test_proxy(account['proxy'])
            if ip:
                reset_proxy_failures(account['proxy'])
                return account['proxy']
            else:
                mark_proxy_failed(account['proxy'])
    
    proxy = get_random_proxy(exclude_failed=True)
    
    if not proxy:
        proxies = load_proxies()
        if proxies:
            proxy = random.choice(proxies)
    
    return proxy

def update_account_proxy(account_id, new_proxy=None):
    """تحديث بروكسي الحساب"""
    if not new_proxy:
        new_proxy = get_working_proxy(account_id)
        if not new_proxy:
            proxies = load_proxies()
            if proxies:
                new_proxy = random.choice(proxies)
                if not test_proxy(new_proxy):
                    for p in proxies:
                        if test_proxy(p):
                            new_proxy = p
                            break
                    else:
                        return False
    
    if not new_proxy:
        return False
    
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE accounts 
            SET proxy = ?,
                last_proxy_check = ?,
                proxy_fail_count = 0
            WHERE id = ?
        """, (new_proxy, datetime.now().isoformat(), account_id))
        conn.commit()
        conn.close()
        logger.info(f"✅ Updated proxy for account {account_id} to {new_proxy}")
        return True
    except Exception as e:
        logger.error(f"Error updating proxy for account {account_id}: {e}")
        return False

def update_all_accounts_proxies(force=False):
    """تحديث بروكسيات جميع الحسابات"""
    accounts = get_all_accounts(active_only=True)
    if not accounts:
        return 0
    
    proxies = load_proxies()
    if not proxies:
        logger.warning("No proxies available to update accounts")
        return 0
    
    valid_proxies = []
    for p in proxies:
        if test_proxy(p):
            valid_proxies.append(p)
    
    if not valid_proxies:
        logger.warning("No valid proxies found")
        return 0
    
    updated = 0
    for i, acc in enumerate(accounts):
        proxy_index = i % len(valid_proxies)
        new_proxy = valid_proxies[proxy_index]
        
        if force or acc.get('proxy') != new_proxy or not acc.get('proxy'):
            if update_account_proxy(acc['id'], new_proxy):
                updated += 1
                logger.info(f"✅ Updated account {acc['id']} to proxy {new_proxy}")
    
    logger.info(f"🔄 Updated {updated} accounts with new proxies")
    return updated

def check_and_fix_proxies():
    """فحص وإصلاح البروكسيات"""
    accounts = get_all_accounts(active_only=True)
    if not accounts:
        return 0
    
    fixed = 0
    for acc in accounts:
        proxy = acc.get('proxy')
        
        if not proxy:
            if update_account_proxy(acc['id']):
                fixed += 1
                logger.info(f"✅ Added proxy to account {acc['id']}")
            continue
        
        if not test_proxy(proxy):
            logger.warning(f"⚠️ Proxy {proxy} is dead for account {acc['id']}")
            mark_proxy_failed(proxy)
            
            if update_account_proxy(acc['id']):
                fixed += 1
                logger.info(f"✅ Fixed proxy for account {acc['id']}")
    
    if fixed > 0:
        send_notification_sync(f"🔧 تم إصلاح {fixed} حساب وإعادة تعيين بروكسياتهم")
    
    return fixed

# ============================================================
# Class AccountWorker
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
        self.current_ip = "بدون بروكسي"
        self.last_proxy_check = datetime.now()
        self.withdrawing = False
        self.limit_notified = False
        self.last_spin_time = datetime.now()
        self.fail_count = 0
        self.max_fails = 5
        self.should_restart = False
        self.proxy_retry_count = 0
        self.max_proxy_retries = 3
        self.force_proxy_use = True
        self.last_proxy_validation = datetime.now()
        self.proxy_validation_interval = 300
        
        self.is_resting = False
        self.work_start_time = None
        self.rest_start_time = None
        self.next_work_duration = random.randint(WORK_MIN_DURATION, WORK_MAX_DURATION)
        self.next_rest_duration = random.randint(REST_MIN_DURATION, REST_MAX_DURATION)
        
        self.account = get_account_by_id(account_id)
        if self.account:
            self.balance = self.account.get('balance', 0)
            self.credits = self.account.get('credits', 0)
            self.total_earned = self.account.get('total_earned', 0)
            self.token = self.account.get('token')
            self.user_id = self.account.get('user_id')
            self.spin_count = self.account.get('spin_count', 0)
            self.limit_notified = self.account.get('limit_notified', 0) == 1
            
            if not self.proxy:
                self.proxy = self.account.get('proxy')
            
            if not self.proxy or not test_proxy(self.proxy):
                if USE_PROXIES:
                    new_proxy = get_working_proxy(account_id)
                    if new_proxy:
                        self.proxy = new_proxy
                        update_account(self.account_id, proxy=self.proxy)
                        logger.info(f"✅ New proxy assigned to account {account_id}: {self.proxy}")
                    else:
                        send_notification_sync(f"⚠️ تحذير: لا يوجد بروكسي للحساب {account_id}!")
                        self.force_proxy_use = False
            
            self.current_ip = get_ip(self.proxy) if self.proxy else "بدون بروكسي"
            
            self.is_resting = self.account.get('is_resting', 0) == 1
            if self.is_resting:
                self.rest_start_time = datetime.fromisoformat(self.account.get('rest_start_time')) if self.account.get('rest_start_time') else datetime.now()
            else:
                self.work_start_time = datetime.fromisoformat(self.account.get('work_start_time')) if self.account.get('work_start_time') else datetime.now()
            
            target = self.account.get('target_amount', 0)
            has_withdrawn = self.account.get('has_withdrawn_today', 0)
            
            if has_withdrawn:
                logger.info(f"📊 Account {account_id} has already withdrawn today (Target: {target})")
                self.is_resting = True
                self.rest_start_time = datetime.now()
        
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json, text/plain, */*"})
    
    def ensure_proxy(self, force_new=False):
        """تأكيد وجود بروكسي شغال"""
        if not USE_PROXIES:
            return None
        
        if self.proxy and not force_new:
            if (datetime.now() - self.last_proxy_validation).seconds < self.proxy_validation_interval:
                return self.proxy
            
            self.last_proxy_validation = datetime.now()
            ip = test_proxy(self.proxy)
            if ip:
                self.current_ip = ip
                reset_proxy_failures(self.proxy)
                return self.proxy
            else:
                mark_proxy_failed(self.proxy)
                logger.warning(f"⚠️ Proxy {self.proxy} failed validation for account {self.account_id}")
                force_new = True
        
        new_proxy = get_working_proxy(self.account_id, self.proxy)
        if new_proxy:
            self.proxy = new_proxy
            self.current_ip = get_ip(self.proxy)
            update_account(self.account_id, proxy=self.proxy)
            logger.info(f"🔄 New proxy for account {self.account_id}: {self.proxy}")
            return self.proxy
        
        if not self.proxy:
            send_notification_sync(f"⚠️ تحذير: لا يوجد بروكسي للحساب {self.account_id}!")
            self.force_proxy_use = False
        else:
            self.force_proxy_use = True
        
        return self.proxy
    
    def safe_request_with_proxy(self, method, url, **kw):
        """طلب آمن مع بروكسي"""
        if self.force_proxy_use and USE_PROXIES:
            proxy = self.ensure_proxy()
            if proxy:
                kw["proxies"] = {"http": proxy, "https": proxy}
                kw['_proxy_used'] = proxy
            else:
                send_notification_sync(f"⚠️ تحذير: محاولة طلب بدون بروكسي للحساب {self.account_id}!")
                self.force_proxy_use = False
        
        kw.setdefault("timeout", TO)
        for attempt in range(3):
            try:
                return self.session.request(method, url, **kw)
            except Exception as e:
                if '_proxy_used' in kw and attempt >= 2:
                    mark_proxy_failed(kw['_proxy_used'])
                    new_proxy = self.ensure_proxy(force_new=True)
                    if new_proxy:
                        kw["proxies"] = {"http": new_proxy, "https": new_proxy}
                        kw['_proxy_used'] = new_proxy
                        continue
                time.sleep(0.5 * (attempt + 1))
        return None
    
    def check_proxy(self):
        """التحقق من البروكسي"""
        if not USE_PROXIES:
            return True
        
        if not self.ensure_proxy():
            return False
        
        return True
    
    def rotate_proxy(self):
        """تدوير البروكسي"""
        if not USE_PROXIES:
            return False
        
        new_proxy = get_working_proxy(self.account_id, self.proxy)
        if new_proxy:
            self.proxy = new_proxy
            self.current_ip = get_ip(self.proxy)
            update_account(self.account_id, proxy=self.proxy)
            logger.info(f"🔄 Rotated proxy for account {self.account_id}: {self.proxy}")
            return True
        
        return False
    
    def login(self):
        """تسجيل الدخول إلى SlotFruits"""
        if not self.account:
            return False
        
        if USE_PROXIES:
            self.ensure_proxy()
        
        token, user_id, balance, credits, msg = do_login(
            self.account['email'], 
            self.account['password'],
            self.proxy
        )
        
        if token:
            logger.info(f"✅ Login successful for account {self.account_id}")
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
            return True
        
        logger.info(f"🔄 Login failed for account {self.account_id}, trying registration...")
        
        success, msg = do_register_mailtm(
            self.account['email'],
            self.account['password'],
            self.proxy
        )
        
        if not success:
            logger.error(f"Registration failed for account {self.account_id}: {msg}")
            return False
        
        code = wait_for_code_mailtm(
            self.account['email'],
            self.account['password'],
            timeout=90
        )
        
        if not code:
            logger.error(f"Timeout waiting for verification code for account {self.account_id}")
            return False
        
        success, token, msg = do_confirm_mailtm(
            self.account['email'],
            code,
            self.proxy
        )
        
        if not success:
            logger.error(f"Confirmation failed for account {self.account_id}: {msg}")
            return False
        
        logger.info(f"✅ Registration successful for account {self.account_id}")
        
        user_info = get_user_info(token, self.proxy)
        if user_info:
            user_id = user_info.get("_id")
            balance = user_info.get("balance", 0)
            credits = user_info.get("credits", 0)
        else:
            user_id = None
            balance = 0
            credits = 0
        
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
        
        return True
    
    def spin(self):
        """الدوران"""
        try:
            if self.credits <= 0:
                farm_ads(self.user_id, self.proxy)
                time.sleep(0.5)
                
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
                    
                    today = datetime.now().strftime("%Y-%m-%d")
                    if self.account.get('last_withdraw_date') != today:
                        update_account(self.account_id, has_withdrawn_today=0, daily_target_reached=0)
                
                add_spin(self.account_id, self.spin_count, reward, self.balance, self.credits)
                update_account(self.account_id, spin_count=self.spin_count)
                
                self.fail_count = 0
                self.last_spin_time = datetime.now()
                
                return data
            
            self.fail_count += 1
            return None
        except Exception as e:
            logger.error(f"Spin error for account {self.account_id}: {e}")
            self.fail_count += 1
            return None
    
    def check_daily_target(self):
        """التحقق من الوصول للهدف اليومي"""
        if not self.account:
            return False
        
        target = self.account.get('target_amount', 0)
        has_withdrawn = self.account.get('has_withdrawn_today', 0)
        
        if has_withdrawn:
            return True
        
        if self.balance >= target:
            logger.info(f"🎯 Account {self.account_id} reached target: {self.balance} >= {target}")
            
            success, msg = self.withdraw_full_amount()
            
            if success:
                update_account(
                    self.account_id,
                    has_withdrawn_today=1,
                    last_withdraw_date=datetime.now().strftime("%Y-%m-%d"),
                    daily_target_reached=1
                )
                
                send_notification_sync(
                    f"🎯 <b>تم تحقيق الهدف اليومي!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🆔 الحساب: {self.account_id}\n"
                    f"📧 البريد: {self.account['email']}\n"
                    f"💰 تم السحب: {self.balance:,.0f}\n"
                    f"🎯 الهدف: {target:,.0f}\n"
                    f"🌐 IP: {self.current_ip}\n"
                    f"🕐 الوقت: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                
                self.is_resting = True
                self.rest_start_time = datetime.now()
                update_account(
                    self.account_id,
                    is_resting=1,
                    rest_start_time=self.rest_start_time.isoformat()
                )
                
                return True
        
        return False
    
    def withdraw_full_amount(self):
        """سحب المبلغ بالكامل"""
        if self.withdrawing:
            return False, "Already withdrawing"
        
        if self.balance < MIN_WITHDRAW_AMOUNT:
            return False, f"Balance {self.balance} below minimum {MIN_WITHDRAW_AMOUNT}"
        
        amount = int(self.balance * 0.9)
        if amount < MIN_WITHDRAW_AMOUNT:
            amount = int(self.balance)
        
        self.withdrawing = True
        
        try:
            address = self.account['email']
            password = self.account['password']
            
            if USE_PROXIES:
                self.ensure_proxy()
            
            success, coin_id, message = request_withdrawal_code(
                self.token, address, amount, COIN_ID, "FP", self.proxy
            )
            
            if not success:
                self.withdrawing = False
                if "proxy" in str(message).lower() or "timeout" in str(message).lower():
                    if self.rotate_proxy():
                        success, coin_id, message = request_withdrawal_code(
                            self.token, address, amount, COIN_ID, "FP", self.proxy
                        )
                        if not success:
                            return False, f"Failed to request code: {message}"
                return False, f"Failed to request code: {message}"
            
            code = wait_for_code_mailtm(address, password, timeout=120)
            
            if not code:
                self.withdrawing = False
                return False, "Timeout waiting for withdrawal code"
            
            success, result, error = confirm_withdrawal(
                self.token, address, amount, code, COIN_ID, "FP", self.proxy
            )
            
            if success:
                add_withdrawal(
                    self.account_id, amount, address, "FP", "completed"
                )
                
                update_account(
                    self.account_id,
                    balance=self.balance - amount,
                    withdrawal_count=self.account.get('withdrawal_count', 0) + 1,
                    last_withdrawal=datetime.now().isoformat()
                )
                
                asyncio.run_coroutine_threadsafe(
                    send_withdraw_notification(
                        address,
                        {
                            'amount': amount,
                            'status': 'completed',
                            'tx_hash': result.get('tx_hash', 'غير متوفر') if result else 'غير متوفر',
                            'address': address
                        }
                    ),
                    asyncio.get_event_loop()
                )
                
                self.balance -= amount
                self.withdrawing = False
                
                return True, f"Withdrawal of {amount} completed successfully"
            else:
                self.withdrawing = False
                return False, f"Withdrawal failed: {error}"
                
        except Exception as e:
            self.withdrawing = False
            logger.error(f"Withdrawal error for account {self.account_id}: {e}")
            return False, f"Error: {str(e)}"
    
    def should_rest(self):
        """التحقق من وقت الراحة"""
        if not self.work_start_time:
            return False
        
        elapsed = (datetime.now() - self.work_start_time).total_seconds()
        return elapsed >= self.next_work_duration
    
    def should_work(self):
        """التحقق من وقت العمل"""
        if not self.rest_start_time:
            return True
        
        elapsed = (datetime.now() - self.rest_start_time).total_seconds()
        return elapsed >= self.next_rest_duration
    
    def start_work_cycle(self):
        """بدء دورة العمل"""
        self.is_resting = False
        self.work_start_time = datetime.now()
        self.next_work_duration = random.randint(WORK_MIN_DURATION, WORK_MAX_DURATION)
        self.next_rest_duration = random.randint(REST_MIN_DURATION, REST_MAX_DURATION)
        
        update_account(
            self.account_id,
            is_resting=0,
            work_start_time=self.work_start_time.isoformat()
        )
        
        logger.info(f"▶️ Account {self.account_id} starting work cycle ({self.next_work_duration}s)")
    
    def start_rest_cycle(self):
        """بدء دورة الراحة"""
        self.is_resting = True
        self.rest_start_time = datetime.now()
        self.next_work_duration = random.randint(WORK_MIN_DURATION, WORK_MAX_DURATION)
        self.next_rest_duration = random.randint(REST_MIN_DURATION, REST_MAX_DURATION)
        
        update_account(
            self.account_id,
            is_resting=1,
            rest_start_time=self.rest_start_time.isoformat()
        )
        
        logger.info(f"💤 Account {self.account_id} starting rest cycle ({self.next_rest_duration}s)")
    
    def run(self):
        """الحلقة الرئيسية لتشغيل الحساب"""
        if not self.login():
            self.running = False
            return
        
        self.start_work_cycle()
        self.running = True
        
        while self.running and not self.stopped and not is_shutting_down:
            try:
                if self.check_daily_target():
                    self.start_rest_cycle()
                    send_notification_sync(
                        f"💤 <b>الحساب في راحة</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n"
                        f"🆔 الحساب: {self.account_id}\n"
                        f"📧 البريد: {self.account['email']}\n"
                        f"🎯 تم تحقيق الهدف اليومي\n"
                        f"⏰ سيستأنف العمل عند منتصف الليل"
                    )
                    time.sleep(3600)
                    continue
                
                if self.is_resting:
                    if self.should_work():
                        self.start_work_cycle()
                    else:
                        remaining = int(self.next_rest_duration - (datetime.now() - self.rest_start_time).total_seconds())
                        if remaining > 0:
                            logger.info(f"💤 Account {self.account_id} resting for {remaining}s")
                            time.sleep(min(remaining, 60))
                        continue
                
                if self.should_rest():
                    self.start_rest_cycle()
                    continue
                
                if USE_PROXIES and not self.check_proxy():
                    if not update_account_proxy(self.account_id):
                        time.sleep(5)
                        continue
                    else:
                        self.proxy = get_account_by_id(self.account_id).get('proxy')
                        self.current_ip = get_ip(self.proxy)
                
                for spin_num in range(1, 6):
                    if not self.running or self.stopped or is_shutting_down:
                        return
                    
                    try:
                        result = self.spin()
                        if result is None and self.fail_count >= self.max_fails:
                            if self.rotate_proxy():
                                if self.login():
                                    self.fail_count = 0
                            else:
                                if update_account_proxy(self.account_id):
                                    self.proxy = get_account_by_id(self.account_id).get('proxy')
                                    self.current_ip = get_ip(self.proxy)
                                    if self.login():
                                        self.fail_count = 0
                                else:
                                    time.sleep(5)
                                    break
                    except Exception as e:
                        logger.error(f"Spin loop error: {e}")
                        self.fail_count += 1
                    
                    time.sleep(random.uniform(1, 2))
                
                try:
                    update_account(
                        self.account_id,
                        balance=self.balance,
                        credits=self.credits,
                        total_earned=self.total_earned
                    )
                except:
                    pass
                
                time.sleep(random.uniform(3, 5))
                
            except Exception as e:
                logger.error(f"Error in account loop {self.account_id}: {e}")
                time.sleep(5)
                if self.fail_count > 10:
                    try:
                        if self.rotate_proxy():
                            self.login()
                            self.fail_count = 0
                        else:
                            if update_account_proxy(self.account_id):
                                self.proxy = get_account_by_id(self.account_id).get('proxy')
                                self.current_ip = get_ip(self.proxy)
                                self.login()
                                self.fail_count = 0
                    except:
                        pass
        
        self.running = False

# ============================================================
# BotManager
# ============================================================

class BotManager:
    def __init__(self):
        self.workers = {}
        self.threads = {}
        self.stop_events = {}
        self.worker_locks = {}
        self.running = False
        self.chat_id = None
        self.main_message_id = None
        self.dashboard_message_ids = []
        self.current_dashboard_text = ""
        self.dashboard_update_lock = threading.Lock()
        self.is_updating = False
        self.last_dashboard_update = datetime.now()
        self.update_interval = 30
        self.start_time = datetime.now()
        self.total_spins = 0
        self.total_withdrawals = 0
        self.total_earned = 0
        self.proxy_validation_thread = None
        self.auto_fix_enabled = True
        self.daily_reset_thread = None
        self.restart_thread = None
        self.proxy_thread = None
    
    def start_account(self, account_id, proxy=None):
        """بدء تشغيل حساب"""
        if account_id in self.workers:
            worker = self.workers[account_id]
            if worker.running and not worker.stopped:
                return False, "Account already running"
            else:
                self.stop_account(account_id)
        
        if not proxy:
            account = get_account_by_id(account_id)
            if account:
                proxy = account.get('proxy')
                if proxy and not test_proxy(proxy):
                    logger.warning(f"⚠️ Proxy {proxy} is dead for account {account_id}")
                    mark_proxy_failed(proxy)
                    proxy = get_working_proxy(account_id)
                    if proxy:
                        update_account(account_id, proxy=proxy)
        
        if account_id not in self.stop_events:
            self.stop_events[account_id] = threading.Event()
        
        if account_id not in self.worker_locks:
            self.worker_locks[account_id] = threading.Lock()
        
        with self.worker_locks[account_id]:
            worker = AccountWorker(account_id, proxy)
            self.workers[account_id] = worker
            
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()
            self.threads[account_id] = thread
            
            return True, "Account started successfully"
    
    def stop_account(self, account_id):
        """إيقاف تشغيل حساب"""
        if account_id not in self.workers:
            return False, "Account not running"
        
        if account_id in self.stop_events:
            self.stop_events[account_id].set()
        
        worker = self.workers[account_id]
        worker.stopped = True
        worker.running = False
        
        if account_id in self.threads:
            try:
                self.threads[account_id].join(timeout=5)
            except:
                pass
            del self.threads[account_id]
        
        del self.workers[account_id]
        if account_id in self.stop_events:
            del self.stop_events[account_id]
        if account_id in self.worker_locks:
            del self.worker_locks[account_id]
        
        return True, "Account stopped"
    
    def start_all_accounts(self):
        """تشغيل جميع الحسابات"""
        if self.auto_fix_enabled:
            update_all_accounts_proxies()
        
        accounts = get_all_accounts(active_only=True)
        if not accounts:
            return 0, "No accounts found"
        
        started = 0
        for acc in accounts:
            if acc['id'] in self.workers:
                continue
            
            proxy = acc.get('proxy')
            if USE_PROXIES and (not proxy or not test_proxy(proxy)):
                proxy = get_working_proxy(acc['id'])
                if proxy:
                    update_account(acc['id'], proxy=proxy)
            
            success, _ = self.start_account(acc['id'], proxy)
            if success:
                started += 1
                time.sleep(0.5)
        
        self.running = True
        return started, f"Started {started} accounts"
    
    def stop_all_accounts(self):
        """إيقاف جميع الحسابات"""
        account_ids = list(self.workers.keys())
        stopped = 0
        
        for acc_id in account_ids:
            success, _ = self.stop_account(acc_id)
            if success:
                stopped += 1
        
        self.running = False
        return stopped, f"Stopped {stopped} accounts"
    
    def start_inactive_accounts(self):
        """تشغيل الحسابات غير النشطة"""
        accounts = get_all_accounts(active_only=True)
        started = 0
        
        for acc in accounts:
            if acc['id'] in self.workers:
                continue
            
            proxy = acc.get('proxy')
            if USE_PROXIES and (not proxy or not test_proxy(proxy)):
                proxy = get_working_proxy(acc['id'])
                if proxy:
                    update_account(acc['id'], proxy=proxy)
            
            success, _ = self.start_account(acc['id'], proxy)
            if success:
                started += 1
                time.sleep(0.5)
        
        return started
    
    def restart_failed_accounts(self):
        """إعادة تشغيل الحسابات المتوقفة"""
        if self.auto_fix_enabled:
            update_all_accounts_proxies()
        
        accounts = get_all_accounts(active_only=True)
        restarted = 0
        
        for acc in accounts:
            acc_id = acc['id']
            if acc_id in self.workers:
                worker = self.workers[acc_id]
                if not worker.running or worker.stopped:
                    self.stop_account(acc_id)
                    
                    proxy = acc.get('proxy')
                    if USE_PROXIES and (not proxy or not test_proxy(proxy)):
                        proxy = get_working_proxy(acc_id)
                        if proxy:
                            update_account(acc_id, proxy=proxy)
                    
                    success, _ = self.start_account(acc_id, proxy)
                    if success:
                        restarted += 1
            else:
                proxy = acc.get('proxy')
                if USE_PROXIES and (not proxy or not test_proxy(proxy)):
                    proxy = get_working_proxy(acc_id)
                    if proxy:
                        update_account(acc_id, proxy=proxy)
                
                success, _ = self.start_account(acc_id, proxy)
                if success:
                    restarted += 1
        
        return restarted
    
    def get_status(self):
        """الحصول على حالة البوت"""
        accounts = get_all_accounts()
        total = len(accounts)
        running = len(self.workers)
        
        total_balance = 0
        total_earned = 0
        total_withdrawals = 0
        total_spins = 0
        
        details = []
        for acc in accounts:
            total_balance += acc.get('balance', 0)
            total_earned += acc.get('total_earned', 0)
            total_withdrawals += acc.get('withdrawal_count', 0)
            total_spins += acc.get('spin_count', 0)
            
            is_running = acc['id'] in self.workers
            is_resting = acc.get('is_resting', 0) == 1
            has_withdrawn = acc.get('has_withdrawn_today', 0)
            target = acc.get('target_amount', 0)
            
            status_icon = "🟢" if is_running else "🔴"
            if is_resting:
                status_icon = "💤"
            if has_withdrawn:
                status_icon = "✅"
            
            proxy = acc.get('proxy')
            proxy_status = "بدون بروكسي"
            if proxy:
                ip = test_proxy(proxy)
                proxy_status = ip if ip else "بروكسي تالف"
            
            details.append(
                f"{status_icon} ID:{acc['id']} {acc['email'][:25]} | "
                f"💰{acc['balance']:,.0f} | 🎯{target:,.0f} | 🌐{proxy_status}"
            )
        
        self.total_spins = total_spins
        self.total_withdrawals = total_withdrawals
        self.total_earned = total_earned
        
        proxies = load_proxies()
        valid_proxies = [p for p in proxies if test_proxy(p)]
        
        return {
            'total_accounts': total,
            'running_accounts': running,
            'inactive_accounts': total - running,
            'total_balance': total_balance,
            'total_earned': total_earned,
            'total_withdrawals': total_withdrawals,
            'total_spins': total_spins,
            'proxies_count': len(proxies),
            'valid_proxies': len(valid_proxies),
            'failed_proxies': len(proxy_failures),
            'uptime': str(datetime.now() - self.start_time).split('.')[0],
            'details': details
        }
    
    def dashboard_text(self):
        """نص لوحة التحكم"""
        status = self.get_status()
        
        text = (
            f"📊 <b>لوحة التحكم - Slot Fruits Bot</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ وقت التشغيل: {status['uptime']}\n"
            f"📧 الحسابات: {status['total_accounts']}\n"
            f"🟢 النشطة: {status['running_accounts']}\n"
            f"💤 في راحة: {sum(1 for d in status['details'] if '💤' in d)}\n"
            f"✅ مكتملة الهدف: {sum(1 for d in status['details'] if '✅' in d)}\n"
            f"🔴 غير النشطة: {status['inactive_accounts']}\n"
            f"💰 الرصيد الكلي: {status['total_balance']:,.0f}\n"
            f"💵 إجمالي الأرباح: {status['total_earned']:,.0f}\n"
            f"🔄 إجمالي الدورات: {status['total_spins']}\n"
            f"📤 إجمالي السحوبات: {status['total_withdrawals']}\n"
            f"🌐 البروكسيات: {status['proxies_count']} (صالح: {status['valid_proxies']}, فاشل: {status['failed_proxies']})\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>تفاصيل الحسابات:</b>\n"
        )
        
        if status['details']:
            text += "\n".join(status['details'])
        else:
            text += "⚠️ لا توجد حسابات"
        
        text += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n🔄 {datetime.now().strftime('%H:%M:%S')}"
        
        return text

bot_manager = BotManager()

# ============================================================
# دوال إضافة الحسابات - النسخة النهائية
# ============================================================

async def create_single_account_standalone(email, password, progress_msg=None, update=None, context=None, proxy=None):
    """
    إنشاء حساب واحد بشكل مستقل مع استخدام بروكسي مختلف
    """
    try:
        # === الحصول على بروكسي جديد لكل حساب ===
        if USE_PROXIES and not proxy:
            proxy = get_working_proxy()
            if not proxy:
                proxies = load_proxies()
                if proxies:
                    proxy = random.choice(proxies)
                    if not test_proxy(proxy):
                        for p in proxies:
                            if test_proxy(p):
                                proxy = p
                                break
        
        if proxy:
            proxy_display = proxy[:30] + "..." if len(proxy) > 30 else proxy
            msg = f"🌐 استخدام بروكسي: {proxy_display}"
            if progress_msg:
                try:
                    await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
                except:
                    pass
        
        # === التنظيف: إزالة أي بيانات سابقة ===
        if email in verification_codes:
            del verification_codes[email]
        if email in seen_messages:
            del seen_messages[email]
        if email in mail_monitors:
            try:
                mail_monitors[email]["running"] = False
                del mail_monitors[email]
            except:
                pass
        
        # === الخطوة 1: التحقق من وجود الحساب ===
        existing = get_account_by_email(email)
        if existing:
            msg = f"⚠️ الحساب {email} موجود مسبقاً (ID: {existing['id']})"
            if progress_msg:
                try:
                    await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
                except:
                    pass
            return False, "Account already exists"
        
        # === الخطوة 2: إنشاء البريد المؤقت ===
        if not verify_mail_account_exists(email, password):
            msg = f"📧 إنشاء بريد مؤقت: {email}"
            if progress_msg:
                try:
                    await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
                except:
                    pass
            
            email, password, success = create_mail_account(email, password)
            if not success:
                msg = f"❌ فشل إنشاء البريد المؤقت"
                if progress_msg:
                    try:
                        await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
                    except:
                        pass
                return False, "Failed to create mail"
        
        # === الخطوة 3: بدء مراقبة البريد ===
        msg = f"📧 بدء مراقبة البريد: {email}"
        if progress_msg:
            try:
                await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
            except:
                pass
        
        token = start_mail_monitor(email, password)
        if not token:
            msg = f"❌ فشل مراقبة البريد"
            if progress_msg:
                try:
                    await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
                except:
                    pass
            return False, "Failed to monitor mail"
        
        # === الخطوة 4: التسجيل في SlotFruits (مع 3 محاولات) ===
        msg = f"🔄 التسجيل في SlotFruits (محاولة 1/3)..."
        if progress_msg:
            try:
                await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
            except:
                pass
        
        success = False
        reg_msg = ""
        for attempt in range(3):
            success, reg_msg = do_register_mailtm(email, password, proxy)
            if success:
                break
            msg = f"🔄 إعادة المحاولة {attempt+2}/3..."
            if progress_msg:
                try:
                    await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
                except:
                    pass
            await asyncio.sleep(5)
        
        if not success:
            msg = f"❌ فشل التسجيل بعد 3 محاولات: {reg_msg}"
            if progress_msg:
                try:
                    await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
                except:
                    pass
            return False, f"Registration failed: {reg_msg}"
        
        # === الخطوة 5: انتظار كود التحقق (180 ثانية) ===
        msg = f"📧 انتظار كود التحقق (180 ثانية)..."
        if progress_msg:
            try:
                await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
            except:
                pass
        
        code = None
        for attempt in range(3):
            code = wait_for_code_mailtm(email, password, timeout=60)
            if code:
                break
            msg = f"🔄 محاولة الحصول على الكود {attempt+2}/3..."
            if progress_msg:
                try:
                    await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
                except:
                    pass
            if attempt < 2:
                success, _ = do_register_mailtm(email, password, proxy)
                await asyncio.sleep(3)
        
        if not code:
            msg = f"❌ انتهى الوقت، لم يتم استلام الكود"
            if progress_msg:
                try:
                    await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
                except:
                    pass
            return False, "Timeout waiting for code"
        
        # === الخطوة 6: تأكيد الحساب ===
        msg = f"✅ تم استلام الكود: {code}"
        if progress_msg:
            try:
                await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
            except:
                pass
        
        success, token, confirm_msg = do_confirm_mailtm(email, code, proxy)
        if not success:
            msg = f"❌ فشل تأكيد الحساب: {confirm_msg}"
            if progress_msg:
                try:
                    await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
                except:
                    pass
            return False, f"Confirmation failed: {confirm_msg}"
        
        # === الخطوة 7: الحصول على معلومات المستخدم ===
        msg = f"📊 جلب معلومات الحساب..."
        if progress_msg:
            try:
                await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
            except:
                pass
        
        user_info = get_user_info(token, proxy)
        if user_info:
            user_id_api = user_info.get("_id")
            balance = user_info.get("balance", 0)
            credits = user_info.get("credits", 0)
        else:
            user_id_api = None
            balance = 0
            credits = 0
        
        # === الخطوة 8: حفظ في قاعدة البيانات ===
        account_id = add_account(email, password, token, user_id_api, balance, credits, proxy)
        
        if account_id:
            account = get_account_by_id(account_id)
            target = account.get('target_amount', 0)
            
            proxy_display = proxy[:30] + "..." if proxy and len(proxy) > 30 else (proxy or "بدون")
            
            msg = (
                f"✅ <b>تم إنشاء الحساب بنجاح!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 ID: {account_id}\n"
                f"📧 البريد: {email}\n"
                f"💰 الرصيد: {balance:,.0f}\n"
                f"🎯 الهدف: {target:,.0f}\n"
                f"🌐 بروكسي: {proxy_display}\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            if progress_msg:
                try:
                    await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}", parse_mode="HTML")
                except:
                    pass
            return True, "Success"
        else:
            msg = f"❌ فشل حفظ الحساب في قاعدة البيانات"
            if progress_msg:
                try:
                    await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
                except:
                    pass
            return False, "Failed to save account"
            
    except Exception as e:
        error_msg = str(e)[:50]
        msg = f"❌ خطأ غير متوقع: {error_msg}"
        if progress_msg:
            try:
                await progress_msg.edit_text(f"{progress_msg.text}\n\n{msg}")
            except:
                pass
        logger.error(f"Error creating account {email}: {e}")
        return False, error_msg

# ============================================================
# دوال واجهة التليجرام
# ============================================================

def split_telegram_text(text, max_len=3800):
    """تقسيم النص الطويل لإرساله في عدة رسائل"""
    if len(text) <= max_len:
        return [text]
    
    parts = []
    current = []
    current_len = 0
    
    for line in text.splitlines(True):
        if len(line) > max_len:
            if current:
                parts.append("".join(current).rstrip())
                current = []
                current_len = 0
            for i in range(0, len(line), max_len):
                parts.append(line[i:i + max_len].rstrip())
            continue
        
        if current_len + len(line) > max_len and current:
            parts.append("".join(current).rstrip())
            current = []
            current_len = 0
        
        current.append(line)
        current_len += len(line)
    
    if current:
        parts.append("".join(current).rstrip())
    
    return [p for p in parts if p]

def get_main_keyboard():
    """لوحة المفاتيح الرئيسية"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 تشغيل الكل", callback_data="start_all")],
        [InlineKeyboardButton("⏹️ إيقاف الكل", callback_data="stop_all")],
        [InlineKeyboardButton("🔄 تشغيل غير النشطة", callback_data="start_inactive")],
        [InlineKeyboardButton("🔁 إعادة تشغيل المتوقفة", callback_data="restart_failed")],
        [InlineKeyboardButton("📊 لوحة التحكم", callback_data="dashboard")],
        [InlineKeyboardButton("📧 إدارة الحسابات", callback_data="accounts_menu")],
        [InlineKeyboardButton("🌐 إدارة البروكسيات", callback_data="proxies_menu")],
        [InlineKeyboardButton("🔧 إصلاح البروكسيات", callback_data="fix_all_proxies")],
        [InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings_menu")],
        [InlineKeyboardButton("📈 الإحصائيات", callback_data="stats")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر /start"""
    global BOT_CHAT_ID, BOT_APPLICATION
    
    BOT_CHAT_ID = update.message.chat_id
    BOT_APPLICATION = context.application
    bot_manager.chat_id = update.message.chat_id
    
    status = bot_manager.get_status()
    
    main_text = (
        f"🎰 <b>Slot Fruits Bot - نظام الهدف اليومي</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ وقت التشغيل: {status['uptime']}\n"
        f"📧 الحسابات: {status['total_accounts']}\n"
        f"🟢 النشطة: {status['running_accounts']}\n"
        f"🔴 غير النشطة: {status['inactive_accounts']}\n"
        f"💰 الرصيد الكلي: {status['total_balance']:,.0f}\n"
        f"🌐 البروكسيات: {status['proxies_count']} (صالح: {status['valid_proxies']})\n"
        f"🎯 الهدف: {MIN_TARGET:,} - {MAX_TARGET:,}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"اختر الإجراء المناسب:"
    )
    
    reply_markup = get_main_keyboard()
    
    msg = await update.message.reply_text(
        main_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
    bot_manager.main_message_id = msg.message_id

async def show_main_menu(update, context, chat_id):
    """عرض القائمة الرئيسية"""
    status = bot_manager.get_status()
    
    main_text = (
        f"🎰 <b>Slot Fruits Bot - نظام الهدف اليومي</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ وقت التشغيل: {status['uptime']}\n"
        f"📧 الحسابات: {status['total_accounts']}\n"
        f"🟢 النشطة: {status['running_accounts']}\n"
        f"🔴 غير النشطة: {status['inactive_accounts']}\n"
        f"💰 الرصيد الكلي: {status['total_balance']:,.0f}\n"
        f"🌐 البروكسيات: {status['proxies_count']} (صالح: {status['valid_proxies']})\n"
        f"🎯 الهدف: {MIN_TARGET:,} - {MAX_TARGET:,}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"اختر الإجراء المناسب:"
    )
    
    reply_markup = get_main_keyboard()
    
    if update and update.callback_query:
        await update.callback_query.edit_message_text(
            main_text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=main_text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )

async def update_dashboard_async():
    """تحديث لوحة التحكم"""
    if not bot_manager.chat_id or not BOT_APPLICATION:
        return
    
    with bot_manager.dashboard_update_lock:
        if bot_manager.is_updating:
            return
        bot_manager.is_updating = True
    
    try:
        new_text = bot_manager.dashboard_text()
        
        if new_text == bot_manager.current_dashboard_text and bot_manager.dashboard_message_ids:
            bot_manager.is_updating = False
            return
        
        bot_manager.current_dashboard_text = new_text
        parts = split_telegram_text(new_text)
        
        keyboard = [
            [InlineKeyboardButton("🔄 تحديث", callback_data="refresh_dashboard")],
            [InlineKeyboardButton("🔁 إعادة تشغيل المتوقفة", callback_data="restart_failed")],
            [InlineKeyboardButton("🔧 إصلاح البروكسيات", callback_data="fix_all_proxies")],
            [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="back_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        while len(bot_manager.dashboard_message_ids) < len(parts):
            try:
                msg = await BOT_APPLICATION.bot.send_message(
                    chat_id=bot_manager.chat_id,
                    text=parts[len(bot_manager.dashboard_message_ids)],
                    parse_mode="HTML"
                )
                bot_manager.dashboard_message_ids.append(msg.message_id)
            except:
                break
        
        while len(bot_manager.dashboard_message_ids) > len(parts):
            old_id = bot_manager.dashboard_message_ids.pop()
            try:
                await BOT_APPLICATION.bot.delete_message(
                    chat_id=bot_manager.chat_id,
                    message_id=old_id
                )
            except:
                pass
        
        for i, part in enumerate(parts):
            if i >= len(bot_manager.dashboard_message_ids):
                break
            try:
                await BOT_APPLICATION.bot.edit_message_text(
                    chat_id=bot_manager.chat_id,
                    message_id=bot_manager.dashboard_message_ids[i],
                    text=part,
                    reply_markup=reply_markup if i == len(parts) - 1 else None,
                    parse_mode="HTML"
                )
            except:
                pass
                
    except Exception as e:
        logger.error(f"Error updating dashboard: {e}")
    finally:
        bot_manager.is_updating = False
        bot_manager.last_dashboard_update = datetime.now()

# ============================================================
# معالج الرسائل المحسن
# ============================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الرسائل النصية - النسخة المحسنة"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if text == "/cancel":
        if user_id in waiting_for:
            del waiting_for[user_id]
        await update.message.reply_text("❌ تم إلغاء العملية!")
        return
    
    action = waiting_for.get(user_id)
    
    if action == "add_account":
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ صيغة غير صحيحة. الرجاء إرسال الإيميل وكلمة المرور مفصولين بمسافة.\n"
                "مثال: <code>user@uberip.com MyPass123</code>",
                parse_mode="HTML"
            )
            return
        
        email = parts[0]
        password = " ".join(parts[1:])
        
        if not email or not password or len(password) < 6:
            await update.message.reply_text("❌ إيميل أو كلمة مرور غير صالحة")
            return
        
        progress_msg = await update.message.reply_text(
            f"🔄 جاري إنشاء الحساب...\n📧 {email}"
        )
        
        success, _ = await create_single_account_standalone(
            email, password, 
            progress_msg=progress_msg,
            update=update, 
            context=context
        )
        
        if success:
            await update.message.reply_text("✅ تم إنشاء الحساب بنجاح!")
        else:
            await update.message.reply_text("❌ فشل إنشاء الحساب")
        
        del waiting_for[user_id]
        return
    
    elif action == "add_multiple_accounts":
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
            return
        
        # إرسال رسالة بداية
        progress_msg = await update.message.reply_text(
            f"🚀 <b>بدء إنشاء {len(accounts_data)} حساب</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏳ سيتم إنشاء كل حساب بشكل مستقل\n"
            f"⏱️ قد يستغرق كل حساب 2-3 دقائق\n"
            f"🌐 سيتم استخدام بروكسي مختلف لكل حساب\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔄 جاري التحضير...",
            parse_mode="HTML"
        )
        
        success_count = 0
        fail_count = 0
        results = []
        errors = []
        start_time = datetime.now()
        current = 0
        
        for email, password in accounts_data:
            current += 1
            elapsed = (datetime.now() - start_time).total_seconds()
            avg_time = elapsed / current if current > 1 else 0
            remaining = avg_time * (len(accounts_data) - current) if avg_time > 0 else 0
            
            progress_text = (
                f"🚀 <b>جاري إنشاء الحساب {current}/{len(accounts_data)}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"📧 {email}\n"
                f"⏱️ الوقت المنقضي: {int(elapsed)} ثانية\n"
                f"⏳ الوقت المتبقي: ~{int(remaining)} ثانية\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            
            try:
                await progress_msg.edit_text(progress_text, parse_mode="HTML")
                
                # محاولة إنشاء الحساب مع إعادة المحاولة
                success = False
                for retry in range(3):
                    if retry > 0:
                        await progress_msg.edit_text(
                            f"{progress_text}\n\n🔄 إعادة محاولة {retry+1}/3 لـ {email}\n⏳ انتظار 30 ثانية...",
                            parse_mode="HTML"
                        )
                        await asyncio.sleep(30)
                    
                    success, _ = await create_single_account_standalone(
                        email, password,
                        progress_msg=progress_msg,
                        update=update,
                        context=context
                    )
                    if success:
                        break
                
                if success:
                    success_count += 1
                    results.append(f"✅ {email[:30]}...")
                else:
                    fail_count += 1
                    results.append(f"❌ {email[:30]}...")
                    errors.append(email)
                
                # إضافة تأخير كبير بين الحسابات
                if current < len(accounts_data):
                    wait_time = random.randint(30, 60)
                    await progress_msg.edit_text(
                        f"{progress_text}\n\n⏳ انتظار {wait_time} ثانية قبل الحساب التالي...",
                        parse_mode="HTML"
                    )
                    await asyncio.sleep(wait_time)
                    
            except Exception as e:
                fail_count += 1
                results.append(f"❌ {email[:30]}... (خطأ)")
                errors.append(email)
                logger.error(f"Error creating account {email}: {e}")
        
        # عرض النتائج النهائية
        summary = (
            f"📊 <b>نتيجة إضافة الحسابات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ تمت الإضافة: {success_count}\n"
            f"❌ فشل: {fail_count}\n"
            f"📝 إجمالي: {len(accounts_data)}\n"
            f"⏱️ الوقت المستغرق: {int((datetime.now() - start_time).total_seconds())} ثانية\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
        
        if results:
            summary += "\n".join(results[:15])
            if len(results) > 15:
                summary += f"\n... و {len(results)-15} حسابات أخرى"
        
        if errors:
            summary += f"\n━━━━━━━━━━━━━━━━━━━━\n"
            summary += f"⚠️ الحسابات الفاشلة:\n"
            summary += "\n".join([f"• {e[:30]}..." for e in errors[:5]])
            if len(errors) > 5:
                summary += f"\n... و {len(errors)-5} أخرى"
        
        summary += f"\n━━━━━━━━━━━━━━━━━━━━\n"
        summary += f"💡 نصيحة: الحسابات الفاشلة قد تحتاج إلى بروكسيات جديدة"
        
        await progress_msg.edit_text(summary, parse_mode="HTML")
        del waiting_for[user_id]
        
        await show_main_menu(update, context, update.message.chat_id)
        return
    
    elif action == "add_proxies":
        proxies = [p.strip() for p in text.split('\n') if p.strip()]
        current_proxies = load_proxies()
        added = 0
        
        for p in proxies:
            if not p.startswith("http://") and not p.startswith("https://") and not p.startswith("socks"):
                p = f"http://{p}"
            if p not in current_proxies:
                current_proxies.append(p)
                added += 1
        
        if added > 0:
            save_proxies(current_proxies)
            await update.message.reply_text(f"✅ تم إضافة {added} بروكسي جديد")
        else:
            await update.message.reply_text("⚠️ لم يتم إضافة أي بروكسي جديد")
        
        del waiting_for[user_id]
        return
    
    elif action == "set_global_limit":
        try:
            threshold = int(text)
            if threshold < 1000:
                await update.message.reply_text("❌ الحد الأدنى هو 1000")
                return
            set_setting('auto_withdraw_threshold', threshold)
            await update.message.reply_text(f"✅ تم تعيين حد السحب العام إلى <code>{threshold}</code>", parse_mode="HTML")
        except ValueError:
            await update.message.reply_text("❌ الرجاء إدخال رقم صحيح")
        del waiting_for[user_id]
        return
    
    elif action == "set_target_value":
        try:
            target = int(text)
            if target < MIN_TARGET or target > MAX_TARGET:
                await update.message.reply_text(f"❌ القيمة يجب أن تكون بين {MIN_TARGET:,} و {MAX_TARGET:,}")
                return
            
            account_id = context.user_data.get('target_account')
            if not account_id:
                await update.message.reply_text("❌ لم يتم تحديد الحساب")
                return
            
            update_account(account_id, target_amount=target)
            await update.message.reply_text(f"✅ تم تعيين الهدف للحساب {account_id} إلى <code>{target:,}</code>", parse_mode="HTML")
            
            if account_id in bot_manager.workers:
                bot_manager.stop_account(account_id)
                time.sleep(1)
                bot_manager.start_account(account_id)
            
        except ValueError:
            await update.message.reply_text("❌ الرجاء إدخال رقم صحيح")
        
        del waiting_for[user_id]
        return
    
    else:
        await update.message.reply_text("❌ أمر غير معروف. استخدم /start للبدء.")

# ============================================================
# بقيية دوال معالج الأزرار
# ============================================================

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج الأزرار"""
    global BOT_CHAT_ID, BOT_APPLICATION
    
    query = update.callback_query
    await query.answer()
    
    BOT_CHAT_ID = query.message.chat_id
    BOT_APPLICATION = context.application
    bot_manager.chat_id = query.message.chat_id
    
    data = query.data
    
    if data == "start_all":
        started, msg = bot_manager.start_all_accounts()
        await query.edit_message_text(f"🚀 {msg}")
        
        if started > 0 and not hasattr(bot_manager, 'restart_thread'):
            bot_manager.restart_thread = start_auto_restart()
            bot_manager.proxy_thread = start_proxy_validation()
            bot_manager.daily_reset_thread = start_daily_reset()
        
        await show_main_menu(update, context, query.message.chat_id)
        return
    
    elif data == "stop_all":
        stopped, msg = bot_manager.stop_all_accounts()
        bot_manager.running = False
        await query.edit_message_text(f"⏹️ {msg}")
        await show_main_menu(update, context, query.message.chat_id)
        return
    
    elif data == "start_inactive":
        started = bot_manager.start_inactive_accounts()
        await query.edit_message_text(f"🔄 تم تشغيل {started} حساب غير نشط")
        
        if bot_manager.running and not hasattr(bot_manager, 'restart_thread'):
            bot_manager.restart_thread = start_auto_restart()
            bot_manager.proxy_thread = start_proxy_validation()
            bot_manager.daily_reset_thread = start_daily_reset()
        
        if bot_manager.dashboard_message_ids:
            await update_dashboard_async()
        else:
            await show_main_menu(update, context, query.message.chat_id)
        return
    
    elif data == "restart_failed":
        restarted = bot_manager.restart_failed_accounts()
        await query.edit_message_text(f"🔄 تم إعادة تشغيل {restarted} حساب متوقف")
        
        if bot_manager.dashboard_message_ids:
            await update_dashboard_async()
        else:
            await show_main_menu(update, context, query.message.chat_id)
        return
    
    elif data == "fix_all_proxies":
        await query.edit_message_text("🔧 جاري فحص وإصلاح جميع البروكسيات...")
        
        fixed = check_and_fix_proxies()
        updated = update_all_accounts_proxies(force=True)
        restarted = bot_manager.restart_failed_accounts()
        
        await query.edit_message_text(
            f"✅ تم إصلاح {fixed} حساب\n"
            f"🔄 تم تحديث {updated} حساب ببروكسيات جديدة\n"
            f"🚀 تم إعادة تشغيل {restarted} حساب"
        )
        
        if bot_manager.dashboard_message_ids:
            await update_dashboard_async()
        else:
            await show_main_menu(update, context, query.message.chat_id)
        return
    
    elif data == "dashboard":
        for msg_id in bot_manager.dashboard_message_ids:
            try:
                await context.bot.delete_message(
                    chat_id=query.message.chat_id,
                    message_id=msg_id
                )
            except:
                pass
        bot_manager.dashboard_message_ids = []
        bot_manager.current_dashboard_text = ""
        
        await update_dashboard_async()
        return
    
    elif data == "refresh_dashboard":
        await update_dashboard_async()
        return
    
    elif data == "stats":
        status = bot_manager.get_status()
        
        stats_text = (
            f"📊 <b>الإحصائيات العامة</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ وقت التشغيل: {status['uptime']}\n"
            f"📧 إجمالي الحسابات: {status['total_accounts']}\n"
            f"🟢 الحسابات النشطة: {status['running_accounts']}\n"
            f"💰 إجمالي الرصيد: {status['total_balance']:,.0f}\n"
            f"💵 إجمالي الأرباح: {status['total_earned']:,.0f}\n"
            f"🔄 إجمالي الدورات: {status['total_spins']}\n"
            f"📤 إجمالي السحوبات: {status['total_withdrawals']}\n"
            f"🌐 البروكسيات: {status['proxies_count']} (صالح: {status['valid_proxies']})\n"
            f"🎯 الهدف اليومي: {MIN_TARGET:,} - {MAX_TARGET:,}\n"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="back_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode="HTML")
        return
    
    elif data == "accounts_menu":
        keyboard = [
            [InlineKeyboardButton("📋 عرض الحسابات", callback_data="view_accounts")],
            [InlineKeyboardButton("➕ إضافة حساب", callback_data="add_account")],
            [InlineKeyboardButton("➕ إضافة حسابات متعددة", callback_data="add_multiple_accounts")],
            [InlineKeyboardButton("🗑️ حذف حساب", callback_data="delete_account")],
            [InlineKeyboardButton("🎯 تعيين هدف للحساب", callback_data="set_target")],
            [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="back_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "📧 <b>إدارة الحسابات</b>\n\nاختر الإجراء المناسب:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return
    
    elif data == "view_accounts":
        accounts = get_all_accounts()
        if not accounts:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="accounts_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("📭 لا يوجد حسابات!", reply_markup=reply_markup)
            return
        
        text = "📋 <b>قائمة الحسابات</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        for acc in accounts:
            status = "🟢" if acc['id'] in bot_manager.workers else "🔴"
            if acc.get('is_resting', 0) == 1:
                status = "💤"
            if acc.get('has_withdrawn_today', 0) == 1:
                status = "✅"
            
            acc_ip = get_ip(acc.get('proxy'))
            proxy_status = "✅" if test_proxy(acc.get('proxy')) else "❌"
            
            target = acc.get('target_amount', 0)
            balance = acc.get('balance', 0)
            progress = (balance / target * 100) if target > 0 else 0
            
            text += f"{status} ID:{acc['id']} - {acc['email'][:30]}\n"
            text += f"   💰 {balance:,.0f} | 🎯 {target:,.0f} ({progress:.0f}%)\n"
            text += f"   🎯 {acc.get('credits', 0)} | 🌐 {acc_ip} {proxy_status}\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 تحديث", callback_data="view_accounts")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="accounts_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        parts = split_telegram_text(text, max_len=3800)
        for i, part in enumerate(parts):
            if i == 0:
                await query.edit_message_text(part, reply_markup=reply_markup if i == len(parts)-1 else None, parse_mode="HTML")
            else:
                await context.bot.send_message(chat_id=query.message.chat_id, text=part, parse_mode="HTML")
        return
    
    elif data == "add_account":
        waiting_for[query.from_user.id] = "add_account"
        await query.edit_message_text(
            "📝 <b>إضافة حساب جديد</b>\n\n"
            "أرسل الإيميل وكلمة المرور بالصيغة:\n"
            "<code>email password</code>\n\n"
            "مثال: <code>user@uberip.com MyPass123</code>\n\n"
            "🔙 لإلغاء العملية أرسل /cancel",
            parse_mode="HTML"
        )
        return
    
    elif data == "add_multiple_accounts":
        waiting_for[query.from_user.id] = "add_multiple_accounts"
        await query.edit_message_text(
            "📝 <b>إضافة حسابات متعددة</b>\n\n"
            "أرسل قائمة الحسابات (كل حساب في سطر منفصل):\n"
            "<code>email1 password1</code>\n"
            "<code>email2 password2</code>\n"
            "<code>email3 password3</code>\n\n"
            "⚠️ سيتم إنشاء كل حساب بالتسلسل مع انتظار كود التحقق\n"
            "⏱️ قد يستغرق كل حساب 2-3 دقائق\n"
            "🌐 سيتم استخدام بروكسي مختلف لكل حساب\n\n"
            "🔙 لإلغاء العملية أرسل /cancel",
            parse_mode="HTML"
        )
        return
    
    elif data == "delete_account":
        accounts = get_all_accounts()
        if not accounts:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="accounts_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("📭 لا يوجد حسابات!", reply_markup=reply_markup)
            return
        
        keyboard = []
        for acc in accounts:
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑️ {acc['email'][:25]} (ID:{acc['id']})",
                    callback_data=f"del_acc_{acc['id']}"
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="accounts_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🗑️ <b>اختر الحساب للحذف:</b>",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return
    
    elif data == "set_target":
        accounts = get_all_accounts()
        if not accounts:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="accounts_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("📭 لا يوجد حسابات!", reply_markup=reply_markup)
            return
        
        keyboard = []
        for acc in accounts:
            target = acc.get('target_amount', 0)
            keyboard.append([
                InlineKeyboardButton(
                    f"🎯 {acc['email'][:25]} ({target:,.0f})",
                    callback_data=f"set_target_{acc['id']}"
                )
            ])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="accounts_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🎯 <b>اختر الحساب لتعيين الهدف:</b>",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return
    
    elif data.startswith("set_target_"):
        account_id = int(data.split("_")[2])
        context.user_data['target_account'] = account_id
        waiting_for[query.from_user.id] = "set_target_value"
        
        await query.edit_message_text(
            f"🎯 <b>تعيين الهدف للحساب {account_id}</b>\n\n"
            f"أدخل القيمة الجديدة (بين {MIN_TARGET:,} و {MAX_TARGET:,}):\n"
            f"مثال: <code>60000</code>\n\n"
            f"🔙 لإلغاء العملية أرسل /cancel",
            parse_mode="HTML"
        )
        return
    
    elif data.startswith("del_acc_"):
        account_id = int(data.split("_")[2])
        account = get_account_by_id(account_id)
        
        if not account:
            await query.edit_message_text("❌ الحساب غير موجود")
            return
        
        if account_id in bot_manager.workers:
            bot_manager.stop_account(account_id)
        
        delete_account(account_id)
        
        keyboard = [
            [InlineKeyboardButton("🔙 رجوع", callback_data="accounts_menu")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"✅ تم حذف الحساب: {account['email']} (ID:{account_id})",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return
    
    elif data == "proxies_menu":
        proxies = load_proxies()
        valid_count = sum(1 for p in proxies if test_proxy(p))
        
        keyboard = [
            [InlineKeyboardButton("📋 عرض البروكسيات", callback_data="view_proxies")],
            [InlineKeyboardButton("➕ إضافة بروكسيات", callback_data="add_proxies")],
            [InlineKeyboardButton("🧪 اختبار جميع البروكسيات", callback_data="test_all_proxies")],
            [InlineKeyboardButton("🔧 إصلاح بروكسيات الحسابات", callback_data="fix_all_proxies")],
            [InlineKeyboardButton("🔄 تحديث البروكسيات", callback_data="refresh_proxies")],
            [InlineKeyboardButton("🗑️ حذف بروكسي", callback_data="delete_proxy")],
            [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="back_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"🌐 <b>إدارة البروكسيات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 المجموع: {len(proxies)}\n"
            f"✅ الصالحة: {valid_count}\n"
            f"❌ التالفة: {len(proxies) - valid_count}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"اختر الإجراء المناسب:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return
    
    elif data == "view_proxies":
        proxies = load_proxies()
        if not proxies:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("📭 لا يوجد بروكسيات!", reply_markup=reply_markup)
            return
        
        text = "🌐 <b>قائمة البروكسيات</b>\n━━━━━━━━━━━━━━━━━━━━\n"
        for i, p in enumerate(proxies, 1):
            ip = test_proxy(p)
            status = "✅" if ip else "❌"
            text += f"{i}. {status} {p}"
            if ip:
                text += f" → {ip}"
            text += "\n"
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        parts = split_telegram_text(text, max_len=3800)
        for i, part in enumerate(parts):
            if i == 0:
                await query.edit_message_text(part, reply_markup=reply_markup if i == len(parts)-1 else None, parse_mode="HTML")
            else:
                await context.bot.send_message(chat_id=query.message.chat_id, text=part, parse_mode="HTML")
        return
    
    elif data == "add_proxies":
        waiting_for[query.from_user.id] = "add_proxies"
        await query.edit_message_text(
            "📝 <b>إضافة بروكسيات جديدة</b>\n\n"
            "أرسل قائمة البروكسيات (كل بروكسي في سطر منفصل):\n"
            "<code>192.168.1.1:8080</code>\n"
            "<code>proxy.example.com:3128</code>\n\n"
            "🔙 لإلغاء العملية أرسل /cancel",
            parse_mode="HTML"
        )
        return
    
    elif data == "refresh_proxies":
        await query.edit_message_text("🔄 جاري تحديث البروكسيات...")
        
        proxies = load_proxies()
        if proxies:
            valid_proxies, invalid_proxies = validate_proxies(proxies)
            save_proxies(valid_proxies)
            
            await query.edit_message_text(
                f"🔄 تم تحديث البروكسيات\n"
                f"✅ صالح: {len(valid_proxies)}\n"
                f"❌ تالف: {len(invalid_proxies)}"
            )
        else:
            await query.edit_message_text("📭 لا يوجد بروكسيات للتحديث!")
        
        await show_main_menu(update, context, query.message.chat_id)
        return
    
    elif data == "test_all_proxies":
        await query.edit_message_text("🧪 جاري اختبار جميع البروكسيات...")
        
        proxies = load_proxies()
        if not proxies:
            await query.edit_message_text("📭 لا يوجد بروكسيات للاختبار!")
            return
        
        valid_proxies = []
        invalid_proxies = []
        
        for i, proxy in enumerate(proxies):
            await query.edit_message_text(f"🧪 جاري اختبار {i+1}/{len(proxies)}...")
            ip = test_proxy(proxy)
            if ip:
                valid_proxies.append(proxy)
            else:
                invalid_proxies.append(proxy)
            time.sleep(0.5)
        
        if invalid_proxies:
            save_proxies(valid_proxies)
        
        result_text = (
            f"🧪 <b>نتيجة اختبار البروكسيات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ صالح: {len(valid_proxies)}\n"
            f"❌ تالف: {len(invalid_proxies)}\n"
            f"📊 المجموع: {len(proxies)}\n"
        )
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(result_text, reply_markup=reply_markup, parse_mode="HTML")
        return
    
    elif data == "delete_proxy":
        proxies = load_proxies()
        if not proxies:
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("📭 لا يوجد بروكسيات!", reply_markup=reply_markup)
            return
        
        keyboard = []
        for i, p in enumerate(proxies[:20]):
            ip = test_proxy(p)
            status = "✅" if ip else "❌"
            display = f"{status} {p[:30]}..." if len(p) > 30 else f"{status} {p}"
            keyboard.append([
                InlineKeyboardButton(f"🗑️ {display}", callback_data=f"del_proxy_{i}")
            ])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        context.user_data['delete_proxies'] = {str(i): p for i, p in enumerate(proxies[:20])}
        
        await query.edit_message_text(
            "🗑️ <b>اختر البروكسي للحذف:</b>",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return
    
    elif data.startswith("del_proxy_"):
        idx = data.replace("del_proxy_", "")
        delete_map = context.user_data.get('delete_proxies', {})
        proxy = delete_map.get(idx)
        
        if not proxy:
            await query.edit_message_text("❌ بروكسي غير صالح")
            return
        
        proxies = load_proxies()
        if proxy in proxies:
            proxies.remove(proxy)
            save_proxies(proxies)
            await query.edit_message_text(f"✅ تم حذف البروكسي: {proxy}")
        else:
            await query.edit_message_text("❌ لم يتم العثور على البروكسي")
        
        keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="proxies_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🗑️ تم الحذف بنجاح",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return
    
    elif data == "settings_menu":
        auto_withdraw = get_setting('auto_withdraw_enabled', 'false')
        threshold = get_setting('auto_withdraw_threshold', 999999999)
        use_proxies = get_setting('use_proxies', 'true')
        auto_fix = get_setting('auto_fix_proxies', 'true')
        
        keyboard = [
            [InlineKeyboardButton(
                f"{'❌ تعطيل' if auto_withdraw == 'true' else '✅ تفعيل'} السحب التلقائي",
                callback_data="toggle_auto_withdraw"
            )],
            [InlineKeyboardButton(
                f"📝 تعيين حد السحب (الحالي: {threshold})",
                callback_data="set_global_limit"
            )],
            [InlineKeyboardButton(
                f"{'❌ تعطيل' if use_proxies == 'true' else '✅ تفعيل'} البروكسيات",
                callback_data="toggle_proxies"
            )],
            [InlineKeyboardButton(
                f"{'❌ تعطيل' if auto_fix == 'true' else '✅ تفعيل'} الإصلاح التلقائي",
                callback_data="toggle_auto_fix"
            )],
            [InlineKeyboardButton("🔙 رجوع للقائمة الرئيسية", callback_data="back_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⚙️ <b>الإعدادات</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔄 السحب التلقائي: {'مفعل' if auto_withdraw == 'true' else 'معطل'}\n"
            f"💰 حد السحب: {threshold}\n"
            f"🌐 البروكسيات: {'مفعلة' if use_proxies == 'true' else 'معطلة'}\n"
            f"🔧 الإصلاح التلقائي: {'مفعل' if auto_fix == 'true' else 'معطل'}\n"
            f"🎯 نظام الهدف اليومي: مفعل\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"اختر الإعداد لتعديله:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return
    
    elif data == "toggle_auto_withdraw":
        current = get_setting('auto_withdraw_enabled', 'false')
        new_value = 'true' if current == 'false' else 'false'
        set_setting('auto_withdraw_enabled', new_value)
        await query.edit_message_text(f"🔄 تم {'تفعيل' if new_value == 'true' else 'تعطيل'} السحب التلقائي")
        await button_handler(update, context)
        return
    
    elif data == "toggle_proxies":
        current = get_setting('use_proxies', 'true')
        new_value = 'false' if current == 'true' else 'true'
        set_setting('use_proxies', new_value)
        await query.edit_message_text(f"🔄 تم {'تفعيل' if new_value == 'true' else 'تعطيل'} البروكسيات")
        await button_handler(update, context)
        return
    
    elif data == "toggle_auto_fix":
        current = get_setting('auto_fix_proxies', 'true')
        new_value = 'false' if current == 'true' else 'true'
        set_setting('auto_fix_proxies', new_value)
        bot_manager.auto_fix_enabled = (new_value == 'true')
        await query.edit_message_text(f"🔄 تم {'تفعيل' if new_value == 'true' else 'تعطيل'} الإصلاح التلقائي للبروكسيات")
        await button_handler(update, context)
        return
    
    elif data == "set_global_limit":
        waiting_for[query.from_user.id] = "set_global_limit"
        await query.edit_message_text(
            "📝 <b>تعيين حد السحب العام</b>\n\n"
            "أدخل الحد الجديد (بالعملات):\n"
            "مثال: <code>15000</code>\n\n"
            "🔙 لإلغاء العملية أرسل /cancel",
            parse_mode="HTML"
        )
        return
    
    elif data == "back_main":
        for msg_id in bot_manager.dashboard_message_ids:
            try:
                await context.bot.delete_message(
                    chat_id=query.message.chat_id,
                    message_id=msg_id
                )
            except:
                pass
        bot_manager.dashboard_message_ids = []
        bot_manager.current_dashboard_text = ""
        
        await show_main_menu(update, context, query.message.chat_id)
        return

# ============================================================
# دوال الأوامر الإضافية
# ============================================================

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إلغاء العملية الحالية"""
    user_id = update.effective_user.id
    if user_id in waiting_for:
        del waiting_for[user_id]
    await update.message.reply_text("❌ تم إلغاء العملية!")

async def dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض لوحة التحكم"""
    bot_manager.chat_id = update.message.chat_id
    await update_dashboard_async()

async def start_inactive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """تشغيل الحسابات غير النشطة"""
    started = bot_manager.start_inactive_accounts()
    await update.message.reply_text(f"🔄 تم تشغيل {started} حساب غير نشط")

async def fix_proxies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """إصلاح البروكسيات"""
    await update.message.reply_text("🔧 جاري فحص وإصلاح جميع البروكسيات...")
    
    fixed = check_and_fix_proxies()
    updated = update_all_accounts_proxies(force=True)
    restarted = bot_manager.restart_failed_accounts()
    
    await update.message.reply_text(
        f"✅ تم إصلاح {fixed} حساب\n"
        f"🔄 تم تحديث {updated} حساب ببروكسيات جديدة\n"
        f"🚀 تم إعادة تشغيل {restarted} حساب"
    )

# ============================================================
# وظائف المراقبة التلقائية
# ============================================================

def auto_restart_monitor():
    """مراقبة وإعادة تشغيل الحسابات المتوقفة"""
    while not is_shutting_down:
        try:
            time.sleep(60)
            
            if bot_manager.running:
                if bot_manager.auto_fix_enabled:
                    update_all_accounts_proxies()
                
                restarted = bot_manager.restart_failed_accounts()
                if restarted > 0:
                    send_notification_sync(f"🔄 تم إعادة تشغيل {restarted} حساب متوقف")
                    
                    if bot_manager.chat_id and BOT_APPLICATION:
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            loop.run_until_complete(update_dashboard_async())
                            loop.close()
                        except:
                            pass
                        
        except Exception as e:
            logger.error(f"Auto restart monitor error: {e}")

def start_auto_restart():
    """بدء مراقبة إعادة التشغيل التلقائي"""
    monitor_thread = threading.Thread(target=auto_restart_monitor, daemon=True)
    monitor_thread.start()
    return monitor_thread

def auto_proxy_monitor():
    """مراقبة البروكسيات التلقائية"""
    while not is_shutting_down:
        try:
            time.sleep(300)
            
            proxies = load_proxies()
            if proxies:
                valid_proxies, invalid_proxies = validate_proxies(proxies)
                if invalid_proxies:
                    logger.info(f"🧹 Removed {len(invalid_proxies)} invalid proxies")
            
            fixed = check_and_fix_proxies()
            if fixed > 0:
                logger.info(f"🔧 Fixed {fixed} accounts with bad proxies")
                
                if bot_manager.chat_id and BOT_APPLICATION:
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(update_dashboard_async())
                        loop.close()
                    except:
                        pass
            
        except Exception as e:
            logger.error(f"Auto proxy monitor error: {e}")

def start_auto_proxy_monitor():
    """بدء مراقبة البروكسيات التلقائية"""
    proxy_thread = threading.Thread(target=auto_proxy_monitor, daemon=True)
    proxy_thread.start()
    return proxy_thread

def proxy_validation_monitor():
    """مراقبة صحة البروكسيات"""
    while not is_shutting_down:
        try:
            time.sleep(300)
            
            proxies = load_proxies()
            if not proxies:
                continue
            
            valid_proxies, invalid_proxies = validate_proxies(proxies)
            
            if invalid_proxies:
                send_notification_sync(f"🧹 تم إزالة {len(invalid_proxies)} بروكسي تالف")
                
                accounts = get_all_accounts()
                for acc in accounts:
                    if acc.get('proxy') in invalid_proxies:
                        new_proxy = get_working_proxy(acc['id'])
                        if new_proxy:
                            update_account(acc['id'], proxy=new_proxy)
                            send_notification_sync(f"🔄 تم تحديث بروكسي الحساب {acc['id']}")
                        else:
                            send_notification_sync(f"⚠️ لا يوجد بروكسي بديل للحساب {acc['id']}")
                        
        except Exception as e:
            logger.error(f"Proxy validation monitor error: {e}")

def start_proxy_validation():
    """بدء مراقبة صحة البروكسيات"""
    proxy_thread = threading.Thread(target=proxy_validation_monitor, daemon=True)
    proxy_thread.start()
    return proxy_thread

def daily_reset_task():
    """مهمة إعادة التعيين اليومية"""
    while not is_shutting_down:
        try:
            now = datetime.now()
            midnight = datetime(now.year, now.month, now.day, 0, 0, 0) + timedelta(days=1)
            seconds_until_midnight = (midnight - now).total_seconds()
            
            time.sleep(seconds_until_midnight)
            
            logger.info("🔄 Midnight reset - Resetting daily targets")
            reset_daily_withdrawals()
            
            restarted = bot_manager.restart_failed_accounts()
            send_notification_sync(
                f"🌙 <b>إعادة تعيين يومي</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🔄 تم إعادة تعيين أهداف جميع الحسابات\n"
                f"🚀 تم إعادة تشغيل {restarted} حساب"
            )
            
        except Exception as e:
            logger.error(f"Daily reset error: {e}")
            time.sleep(60)

def start_daily_reset():
    """بدء مهمة إعادة التعيين اليومية"""
    reset_thread = threading.Thread(target=daily_reset_task, daemon=True)
    reset_thread.start()
    return reset_thread

# ============================================================
# الوظيفة الرئيسية
# ============================================================

def main():
    """الوظيفة الرئيسية"""
    global BOT_APPLICATION, is_shutting_down
    
    init_database()
    
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ الرجاء تعيين BOT_TOKEN في config.json")
        return
    
    application = Application.builder().token(BOT_TOKEN).build()
    BOT_APPLICATION = application
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("dashboard", dashboard_command))
    application.add_handler(CommandHandler("start_inactive", start_inactive_command))
    application.add_handler(CommandHandler("fix_proxies", fix_proxies_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # بدء عمليات المراقبة
    restart_thread = start_auto_restart()
    proxy_thread = start_proxy_validation()
    auto_proxy_thread = start_auto_proxy_monitor()
    daily_reset_thread = start_daily_reset()
    
    print("🎰 Starting Slot Fruits Bot - نظام الهدف اليومي مع إشعارات السحب")
    print("✅ Bot is running! Press Ctrl+C to stop")
    print("🔄 Auto-restart monitor is active")
    print("🌐 Proxy validation monitor is active")
    print("🔧 Auto-proxy fix monitor is active")
    print("🌙 Daily reset monitor is active")
    print("📧 Mail.tm email monitor is active")
    print("🎯 Daily target system: ENABLED")
    print("✅ Auto withdraw system: ENABLED")
    print("📧 Withdrawal notifications: ENABLED")
    print("📝 Multi-account with different proxies: ENABLED")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        is_shutting_down = True
        bot_manager.stop_all_accounts()
        print("✅ All accounts stopped")
        print("👋 Goodbye!")

if __name__ == "__main__":
    import concurrent.futures
    main()