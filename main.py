import os
import telebot
import requests
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from datetime import datetime, timedelta
import threading
import time
import random
import string
import urllib.parse

# --- CONFIGURATION ---
BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8980753842:AAG05SklWh3TshUWiJio1_MTWo2Net-ijiE"
ADMIN_ID = int(os.environ.get("ADMIN_ID") or 7997110885)

FAMPAY_API_KEY = os.environ.get("FAMPAY_API_KEY") or "FAM_LIVE_sk_hRGdY9XAmPu7wzRg9HXjwa8pHdPhKNGB"
FAMPAY_BASE_URL = "https://py.freepanel.in/api/v1"

# BANTIBHAIYA RESELLER CONFIG
BANTI_API_URL = "https://bantibhaiya.com/api/reseller_v1.php"
BANTI_API_KEY = os.environ.get("BANTI_API_KEY") or "8dc220a22ee3ea0ba80340978c2f1248"
BANTI_MASTER_KEY = os.environ.get("BANTI_MASTER_KEY") or "a7f3e8b2c9d1f4a6b8c2d5e9f1a3b6c8"

# AAPKA PROVIDER SMM CONFIG
AAPKA_API_URL = "https://aapkaprovider.com/api/v2"
AAPKA_API_KEY = os.environ.get("AAPKA_API_KEY") or "64e5f851a708586e575c1e76719bd653"

# POLLINATIONS AI CONFIG
POLLINATIONS_API_KEY = os.environ.get("POLLINATIONS_API_KEY") or "sk_T1yQaq7ay5S6l1QdjepQtMh0ak8F1SJi"
IMAGE_FEE = 2.0  # Cost per image in INR
VIDEO_FEE = 2.0  # Cost per video in INR

# AI & DB CONFIG
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
SUPABASE_DB_URL = os.environ.get("DATABASE_URL")

AI_INSTRUCTION = (
    "You are CandidStore AI, customer assistant for CandidStore.\n"
    "We provide Game Mod Keys (Free Fire, CODM, MLBB, 8 Ball Pool, Carrom Pool, Snake Soccer), "
    "iOS Gbox Certificates, SMM Social Media Boosting (IG Views @ ₹1/1k, TG Members @ ₹35/1k, Likes, Followers), "
    "AI Image & Video Generation @ ₹2 each, and 100% Free Disposable Temp Mail.\n"
    "Explain Root vs Non-Root vs iOS cleanly and assist with orders."
)

STORE_UNDER_MAINTENANCE = False
bot = telebot.TeleBot(BOT_TOKEN)

# DB Connection Pool
db_pool = pool.ThreadedConnectionPool(2, 30, SUPABASE_DB_URL, sslmode='require', connect_timeout=5)

def get_db_connection():
    return db_pool.getconn()

def release_db_connection(conn, close=False):
    try:
        if close:
            db_pool.putconn(conn, close=True)
        else:
            db_pool.putconn(conn)
    except Exception:
        pass

last_purchase_time = {}
admin_actions = {}
admin_coupon_flow = {}
user_orders = {}
waiting_for_custom_topup = {}
waiting_for_support_ticket = {}
waiting_for_coupon_code = {}
waiting_for_ai_prompt = {}
waiting_for_image_prompt = {}
waiting_for_video_prompt = {}
user_temp_mails = {}
waiting_for_smm_link = {}

# --- COMPLETE MODS CATALOG ---
CATALOG = {
    # 1. Free Fire Non-Root
    "ff_nr_abcd": {
        "name": "ABCD PANEL FF NONROOT", "pid": "151",
        "items": [("12 Hours", 49.0), ("1 DaYs", 99.0), ("3 DaYs", 199.0), ("7 DaYs", 350.0)]
    },
    "ff_nr_bala": {
        "name": "XYZ CHEATS BALA FF NONROOT", "pid": "155",
        "items": [("1 Hours", 15.0), ("2 Hours", 23.0), ("4 Hours", 30.0), ("6 Hours", 40.0), ("12 Hours", 55.0), ("24 Hours", 100.0)]
    },
    "ff_nr_silent_apk": {
        "name": "XYZ CHEATS APK SILENT FF NONROOT", "pid": "153",
        "items": [("1 Hours", 15.0), ("3 Hours", 35.0), ("6 Hours", 60.0), ("12 Hours", 130.0), ("24 Hours", 180.0)]
    },
    "ff_nr_cfg_proxy": {
        "name": "XYZ CHEATS CONFIG PROXY FF NONROOT", "pid": "142",
        "items": [("1 Hours", 15.0), ("3 Hours", 35.0), ("6 Hours", 60.0), ("12 Hours", 130.0), ("24 Hours", 180.0)]
    },
    "ff_nr_sc_proxy": {
        "name": "SILENT CHEAT FF NONROOT PROXY", "pid": "148",
        "items": [
            ("1 Hours Apk Silent", 15.0), ("3 Hours Apk Silent", 30.0), ("6 Hours Apk Silent", 50.0), ("12 Hours Apk Silent", 90.0), ("1 DaYs Apk Silent", 170.0),
            ("1 Hours Config Proxy", 15.0), ("3 Hours Config Proxy", 30.0), ("6 Hours Config Proxy", 50.0), ("12 Hours Config Proxy", 90.0), ("1 DaYs Config Proxy", 170.0)
        ]
    },
    "ff_nr_sc_apkmod": {
        "name": "SILENT CHEAT FF NONROOT APKMOD", "pid": "127",
        "items": [("1 DaYs", 90.0), ("3 DaYs", 180.0), ("7 DaYs", 350.0), ("14 DaYs", 600.0), ("28 DaYs", 900.0)]
    },
    "ff_nr_prime": {
        "name": "PRIME HOOK FF NONROOT ANDROID", "pid": "48",
        "items": [("1 Days Nonroot", 70.0), ("3 Days Nonroot", 120.0), ("7 Days NonRoot", 290.0), ("10 Days Nonroot", 320.0)]
    },
    "ff_nr_drip_wire": {
        "name": "DRIPCLIENT WIRE FF NONROOT ANDROID+IPHONE", "pid": "150",
        "items": [("6 Hours", 35.0), ("12 Hours", 55.0), ("1 DaYs", 90.0), ("7 DaYs", 350.0)]
    },
    "ff_nr_drip_proxy": {
        "name": "DRIPCLIENT PROXY FF NONROOT ANDROID", "pid": "91",
        "items": [("1 DaYs", 60.0), ("3 DaYs", 140.0), ("7 DaYs", 250.0), ("30 DaYs", 600.0)]
    },
    "ff_nr_hg_proxy": {
        "name": "HG CHEATS ANDROID PROXY FF NONROOT", "pid": "123",
        "items": [("1 DaYs", 70.0), ("7 DaYs", 270.0), ("10 DaYs", 300.0), ("30 DaYs", 500.0)]
    },
    "ff_nr_hg_prime": {
        "name": "HG CHEATS PRIME PROXY FF NONROOT", "pid": "141",
        "items": [("1 DaYs", 70.0), ("7 DaYs", 250.0), ("10 DaYs", 300.0)]
    },
    "ff_nr_xrag": {
        "name": "XRAG FF ROOT+NONROOT+IOS IPHONE+PC", "pid": "149",
        "items": [("1 Hours", 15.0), ("3 Hours", 30.0), ("6 Hours", 40.0), ("12 Hours", 55.0), ("24 Hours", 70.0), ("3 DaYs", 150.0), ("7 DaYs", 200.0)]
    },
    "ff_nr_aimhack": {
        "name": "AIM HACK FF ROOT+NONROOT+IOS IPHONE+PC", "pid": "133",
        "items": [("1 Hours", 15.0), ("3 Hours", 30.0), ("6 Hours", 40.0), ("12 Hours", 55.0), ("1 DaYs", 70.0), ("3 DaYs", 150.0), ("7 DaYs", 200.0)]
    },
    "ff_nr_pato": {
        "name": "PATO TEAM FF ALL ANDROID", "pid": "54",
        "items": [("3 DaYs All Colours Mix", 150.0), ("7 DaYs All Colours Mix", 300.0), ("15 DaYs All Colours Mix", 500.0), ("30 DaYs All Colours Mix", 700.0)]
    },
    # 2. Free Fire Root
    "ff_r_silent": {
        "name": "SILENT CHEAT FF ROOT ANDROID", "pid": "128",
        "items": [
            ("1 DaYs SAFE", 90.0), ("3 DaYs SAFE", 180.0), ("7 DaYs SAFE", 350.0), ("14 DaYs SAFE", 600.0), ("28 DaYs SAFE", 900.0),
            ("1 DaYs BRUTAL", 90.0), ("3 DaYs BRUTAL", 180.0), ("7 DaYs BRUTAL", 350.0), ("14 DaYs BRUTAL", 600.0), ("28 DaYs BRUTAL", 900.0)
        ]
    },
    "ff_r_haxx": {
        "name": "HAXX-CKER PRO FF ANDROID", "pid": "64",
        "items": [("3 DaYs", 180.0), ("5 DaYs", 280.0), ("10 DaYs", 550.0), ("20 DaYs", 1050.0), ("30 DaYs", 1450.0), ("60 DaYs", 2800.0)]
    },
    "ff_r_rapid": {
        "name": "RAPID CORE FF ROOT ANDROID", "pid": "152",
        "items": [("1 DaYs", 80.0), ("7 DaYs", 300.0), ("14 DaYs", 500.0), ("30 DaYs", 699.0)]
    },
    "ff_r_drip": {
        "name": "DRIPCLIENT FF ROOT ANDROID", "pid": "63",
        "items": [("1 DaYS ROOT", 60.0), ("7 DaYS ROOT", 250.0), ("30 DaYS ROOT", 600.0)]
    },
    "ff_r_hg": {
        "name": "HG CHEATS FF APKMOD NONROOT+ROOT", "pid": "65",
        "items": [("1 DaYs Root + Nonroot", 70.0), ("7 DaYs Root+Nonroot", 270.0), ("10 DaYs Root+Nonroot", 300.0), ("30 DaYs Root+Nonroot", 500.0)]
    },
    # 3. Free Fire iOS
    "ff_ios_migul": {
        "name": "MIGUL IPHONE IOS FF", "pid": "69",
        "items": [
            ("1 DaYs Basic", 250.0), ("7 DaYs Basic", 600.0), ("30 DaYs Basic", 1200.0),
            ("1 DaYs PRO", 250.0), ("7 DaYs PRO", 600.0), ("30 DaYs PRO", 1200.0)
        ]
    },
    "ff_ios_delta": {
        "name": "DELTA PROXY IOS IPHONE", "pid": "140",
        "items": [("1 DaYs", 150.0), ("7 DaYs", 350.0), ("30 DaYs", 700.0)]
    },
    # 4. Free Fire PC
    "ff_pc_brmod": {
        "name": "BR MOD FF PC VERSION", "pid": "49",
        "items": [
            ("1 Day Pc Aim Silent", 79.0), ("10 Days Pc Aim Silent", 479.0), ("30 Days Pc Aim Silent", 799.0),
            ("10 Days Pc Bypass + Silent", 519.0),
            ("1 Day Pc Modmenu x86", 79.0), ("10 Day Pc Modmenu x86", 479.0), ("30 Day Pc Modmenu x86", 799.0)
        ]
    },
    # 5. CODM
    "codm_ios_cloud": {
        "name": "IOS CLOUD CODM", "pid": "87",
        "items": [("30 DaYs", 2000.0)]
    },
    # 6. MLBB
    "mlbb_ios_fluorite": {
        "name": "FLUORITE IOS MLBB", "pid": "84",
        "items": [("1 DaYs", 400.0), ("7 DaYs", 1000.0), ("30 DaYs", 2000.0)]
    },
    # 7. 8 Ball Pool
    "8bp_snake_nr": {
        "name": "SNAKE 8 BALL POOL NONROOT ANDROID", "pid": "79",
        "items": [("3 DaYs", 230.0), ("10 DaYs", 570.0), ("30 DaYs", 1200.0)]
    },
    "8bp_kos_virtual": {
        "name": "KOS 8 BALL POOL VIRTUAL", "pid": "76",
        "items": [("1 DaYs", 150.0), ("7 DaYs", 450.0), ("15 DaYs", 800.0), ("30 DaYs", 1500.0)]
    },
    "8bp_kos_root": {
        "name": "KOS 8 BALL POOL MOD+ROOT", "pid": "138",
        "items": [("1 DaYs", 150.0), ("7 DaYs", 450.0), ("15 DaYs", 900.0), ("30 DaYs", 1500.0)]
    },
    "8bp_ios_fluorite": {
        "name": "IOS FLUORITE 8 BALL POOL", "pid": "86",
        "items": [("1 DaYs", 400.0), ("30 DaYs", 2000.0)]
    },
    # 8. Carrom Pool
    "carrom_snake_nr": {
        "name": "SNAKE CARROM POOL NONROOT ANDROID", "pid": "77",
        "items": [("3 DaYs", 200.0), ("10 DaYs", 430.0), ("30 DaYs", 970.0)]
    },
    "carrom_kos_nr": {
        "name": "KOS CARROM POOL NONROOT ANDROID", "pid": "75",
        "items": [("1 DaYs", 150.0), ("7 DaYs", 450.0), ("15 DaYs", 900.0), ("30 DaYs", 1500.0)]
    },
    # 9. Snake Soccer Stars
    "soccer_snake_nr": {
        "name": "SNAKE SOCCER STARS NONROOT ANDROID", "pid": "78",
        "items": [("3 DaYs", 160.0), ("10 DaYs", 350.0), ("30 DaYs", 650.0)]
    },
    # 10. iOS Certificates
    "ios_certs": {
        "name": "IOS IPHONE ALL GBOX CERTIFICATE", "pid": "85",
        "items": [("1 Year Ios Esign Gbox Certificate", 320.0), ("1 Year Ios Signer Gbox Certificate", 800.0)]
    }
}

MAINTENANCE_PRODUCTS = [
    "BALA MOD XYZ ~ V4 FF NONROOT (PID 136)",
    "DRIPCLIENT FF NONROOT APKMOD (PID 62)",
    "FLUORITE IOS FF (PID 58)",
    "DRIPCLIENT 8BP NONROOT ANDROID (PID 59)",
    "DRIPCLIENT FF PC AIMKILL (PID 44)",
    "NINE X FF NONROOT (PID 144)",
    "KOS FF ROOT ANDROID (PID 74)",
    "BR MOD FF ROOT ANDROID (PID 67)",
    "XYZ CHEATS FF ROOT ANDROID (PID 66)",
    "REAPER X PRO FF ROOT ANDROID (PID 81)"
]

def init_db():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT,
                phone TEXT,
                joined TEXT,
                balance REAL DEFAULT 0.0,
                total_spent REAL DEFAULT 0.0,
                orders_count INTEGER DEFAULT 0,
                role TEXT DEFAULT 'Customer',
                banned INTEGER DEFAULT 0,
                verified INTEGER DEFAULT 0,
                total_referrals INTEGER DEFAULT 0,
                last_spin_time TEXT,
                bonus_spins INTEGER DEFAULT 0
            )
        ''')
        cur.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_spins INTEGER DEFAULT 0;')
        cur.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS total_referrals INTEGER DEFAULT 0;')
        cur.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS last_spin_time TEXT;')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                duration TEXT,
                license_key TEXT,
                price REAL,
                date TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS bot_transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                type TEXT,
                amount REAL,
                details TEXT,
                date TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS support_tickets (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                category TEXT,
                message TEXT,
                status TEXT DEFAULT 'Open',
                date TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS coupons (
                code TEXT PRIMARY KEY,
                reward_type TEXT,
                value REAL,
                max_uses INTEGER,
                uses_count INTEGER DEFAULT 0,
                per_user_limit INTEGER DEFAULT 1,
                expires_at TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS coupon_redemptions (
                user_id BIGINT,
                code TEXT,
                used_count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, code)
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS spam_tracker (
                user_id BIGINT PRIMARY KEY,
                abandon_count INTEGER DEFAULT 0,
                timeout_until TEXT
            )
        ''')
        conn.commit()
        cur.close()
        print("Database schema successfully verified.")
    except Exception as e:
        print(f"DB Init Error: {e}")
    finally:
        release_db_connection(conn)

init_db()

def log_bot_transaction(user_id, tx_type, amount, details):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur.execute(
            'INSERT INTO bot_transactions (user_id, type, amount, details, date) VALUES (%s, %s, %s, %s, %s)',
            (user_id, tx_type, float(amount), str(details), current_time)
        )
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"Transaction Log Error: {e}")
    finally:
        release_db_connection(conn)

def get_user(user_id):
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
        row = cur.fetchone()
        cur.close()
        if row:
            return {
                "user_id": row["user_id"],
                "name": row["name"],
                "phone": row["phone"],
                "joined": row["joined"],
                "balance": float(row["balance"] or 0.0),
                "total_spent": float(row["total_spent"] or 0.0),
                "orders_count": int(row["orders_count"] or 0),
                "role": row["role"] or "Customer",
                "banned": bool(row["banned"]),
                "verified": bool(row["verified"]),
                "total_referrals": int(row["total_referrals"] or 0),
                "last_spin_time": row["last_spin_time"],
                "bonus_spins": int(row["bonus_spins"] or 0)
            }
    except Exception as e:
        print(f"Fetch User Error: {e}")
    finally:
        release_db_connection(conn)
    return None

def save_user_profile(user_id, name, phone, verified=True):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO users (user_id, name, phone, joined, verified)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                name = EXCLUDED.name,
                phone = COALESCE(EXCLUDED.phone, users.phone),
                verified = EXCLUDED.verified
        ''', (user_id, name, phone, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), int(verified)))
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"Save User Error: {e}")
    finally:
        release_db_connection(conn)

def atomic_update_balance(user_id, amount_change, spend_add=0, order_add=0):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('''
            UPDATE users SET 
                balance = balance + %s,
                total_spent = total_spent + %s,
                orders_count = orders_count + %s
            WHERE user_id = %s
        ''', (amount_change, spend_add, order_add, user_id))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"Update Balance Error: {e}")
        return False
    finally:
        release_db_connection(conn)

# --- MAIL.TM FREE DISPOSABLE INBOX ENGINE ---
def mailtm_get_domain():
    try:
        r = requests.get("https://api.mail.tm/domains", timeout=10)
        domains = r.json().get("hydra:member", [])
        if domains:
            return domains[0]["domain"]
    except Exception:
        pass
    return None

def mailtm_create_account():
    domain = mailtm_get_domain()
    if not domain:
        return None, None
    rand_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
    address = f"{rand_id}@{domain}"
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    try:
        requests.post("https://api.mail.tm/accounts", json={"address": address, "password": password}, timeout=10)
        tok_res = requests.post("https://api.mail.tm/token", json={"address": address, "password": password}, timeout=10)
        return address, tok_res.json().get("token")
    except Exception:
        return None, None

def mailtm_fetch_messages(token):
    try:
        r = requests.get("https://api.mail.tm/messages", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        return r.json().get("hydra:member", [])
    except Exception:
        return []

def mailtm_fetch_message_detail(token, msg_id):
    try:
        r = requests.get(f"https://api.mail.tm/messages/{msg_id}", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        return r.json()
    except Exception:
        return None

# --- SMM API CALL ---
def smm_place_order(service_id, link, quantity):
    try:
        payload = {
            "key": AAPKA_API_KEY,
            "action": "add",
            "service": str(service_id),
            "link": link.strip(),
            "quantity": int(quantity)
        }
        res = requests.post(AAPKA_API_URL, data=payload, timeout=15)
        return res.json()
    except Exception as e:
        return {"error": str(e)}

# --- START COMMAND ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if user and user["banned"]:
        bot.send_message(message.chat.id, "❌ **Access Denied:** Your account has been suspended.", parse_mode="Markdown")
        return

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].split("_")[1])
            if referrer_id != user_id and not user:
                conn = get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute('UPDATE users SET total_referrals = total_referrals + 1 WHERE user_id = %s', (referrer_id,))
                    conn.commit()
                    cur.close()
                finally:
                    release_db_connection(conn)
        except Exception:
            pass

    if not user or not user.get("verified", False):
        if not user:
            save_user_profile(user_id, message.from_user.first_name, None, verified=False)
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(telebot.types.KeyboardButton("🛡️ Share Contact for Verification", request_contact=True))
        bot.send_message(message.chat.id, "🔐 **IDENTITY CHECK NEEDED**\n\nPlease verify your contact before continuing:", parse_mode="Markdown", reply_markup=markup)
        return

    show_main_menu(message.chat.id, user_id)

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    user_id = message.from_user.id
    if message.contact:
        user = get_user(user_id)
        if user and user["banned"]:
            bot.send_message(message.chat.id, "❌ Your account is suspended.", parse_mode="Markdown")
            return
        save_user_profile(user_id, message.from_user.first_name, message.contact.phone_number, verified=True)
        bot.send_message(message.chat.id, "✅ Verification Successful!", reply_markup=telebot.types.ReplyKeyboardRemove(), parse_mode="Markdown")
        show_main_menu(message.chat.id, user_id)

def show_main_menu(chat_id, user_id):
    user = get_user(user_id)
    if user and user["banned"]:
        return

    is_admin = (user_id == ADMIN_ID)
    user_role = user.get("role", "Customer") if user else "Customer"

    welcome_text = (
        "🟢 **STORE & UTILITIES HUB ONLINE** 🟢\n\n"
        "✨ **Available Services & Perks**\n"
        "💎 Instant Delivery of Verified Game Keys\n"
        "🚀 Social Media Booster (IG Views @ ₹1/1k, TG Members @ ₹35/1k)\n"
        "🎨 AI Image Generator (Flux 4K @ ₹2)\n"
        "🎬 AI Video Generator (Veo HD @ ₹2)\n"
        "📬 100% Free Disposable Temp Mail Service\n"
        "🤖 Dual-Core Smart AI Assistant (24/7 Support)\n"
        "🎟️ Support Tickets & Lucky Spin System\n\n"
        "🛒 **Select an option below:**"
    )
    if is_admin or user_role == "Reseller":
        welcome_text += f"\n\n⚙️ [{user_role} Dashboard Unlocked]"

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("🎮 FF MOD KEYS", callback_data="mods_game_select"),
        telebot.types.InlineKeyboardButton("🚀 Boost Socials", callback_data="smm_main_menu")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("🎨 AI Image Gen (₹2)", callback_data="open_image_gen"),
        telebot.types.InlineKeyboardButton("🎬 AI Video Gen (₹2)", callback_data="open_video_gen")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("📬 Temp Mail (Free)", callback_data="temp_mail_menu"),
        telebot.types.InlineKeyboardButton("🤖 Ask Store AI", callback_data="open_ai_assistant")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("💳 Add Balance", callback_data="add_balance"),
        telebot.types.InlineKeyboardButton("📦 My Orders", callback_data="orders")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("🎁 Referral", callback_data="referral"),
        telebot.types.InlineKeyboardButton("🎡 Lucky Spin", callback_data="lucky_spin")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("🎟️ Support Ticket", callback_data="support_ticket"),
        telebot.types.InlineKeyboardButton("🏷️ Redeem Coupon", callback_data="redeem_coupon")
    )
    markup.add(telebot.types.InlineKeyboardButton("👤 Full Profile Dashboard", callback_data="profile"))
    if is_admin:
        markup.add(telebot.types.InlineKeyboardButton("👑 Master Admin Panel", callback_data="admin_panel"))

    bot.send_message(chat_id, welcome_text, reply_markup=markup, parse_mode="Markdown")

# --- CALLBACK DISPATCHER ---
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    if user and user["banned"]:
        bot.answer_callback_query(call.id, text="❌ Access Denied: Account Suspended.", show_alert=True)
        return

    is_admin = (user_id == ADMIN_ID)
    global STORE_UNDER_MAINTENANCE

    admin_bypass = [
        "admin_panel", "adm_users_list_1", "adm_all_transactions", "adm_check_user",
        "adm_addbal_menu", "adm_cutbal_menu", "adm_broadcast", "adm_toggle_reseller",
        "adm_ban_menu", "adm_toggle_maintenance", "adm_view_tickets", "adm_create_coupon",
        "profile", "orders", "referral", "support_ticket", "main_menu", "open_ai_assistant",
        "temp_mail_menu", "open_image_gen", "open_video_gen"
    ]
    if STORE_UNDER_MAINTENANCE and not is_admin and call.data not in admin_bypass:
        bot.answer_callback_query(call.id, text="Store under maintenance!", show_alert=True)
        bot.send_message(call.message.chat.id, "🛠️ **STORE UNDER MAINTENANCE**\n\nPlease check back shortly.", parse_mode="Markdown")
        return

    if call.data in [
        "mods_game_select", "add_balance", "profile", "orders", "referral", "support_ticket",
        "main_menu", "admin_panel", "lucky_spin", "redeem_coupon", "open_ai_assistant",
        "temp_mail_menu", "smm_main_menu", "open_image_gen", "open_video_gen"
    ]:
        waiting_for_custom_topup.pop(user_id, None)
        waiting_for_support_ticket.pop(user_id, None)
        waiting_for_coupon_code.pop(user_id, None)
        waiting_for_ai_prompt.pop(user_id, None)
        waiting_for_image_prompt.pop(user_id, None)
        waiting_for_video_prompt.pop(user_id, None)
        waiting_for_smm_link.pop(user_id, None)
        admin_actions.pop(user_id, None)
        admin_coupon_flow.pop(user_id, None)

    # 1. NAVIGATION & GAME SELECTION
    if call.data == "main_menu":
        bot.answer_callback_query(call.id)
        show_main_menu(call.message.chat.id, user_id)

    elif call.data == "mods_game_select":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🔥 Free Fire (FF)", callback_data="game_ff"))
        markup.add(telebot.types.InlineKeyboardButton("🎯 Call of Duty Mobile (CODM)", callback_data="game_codm"))
        markup.add(telebot.types.InlineKeyboardButton("⚔️ Mobile Legends (MLBB)", callback_data="game_mlbb"))
        markup.add(telebot.types.InlineKeyboardButton("🎱 8 Ball Pool", callback_data="game_8bp"))
        markup.add(telebot.types.InlineKeyboardButton("⚪ Carrom Pool", callback_data="game_carrom"))
        markup.add(telebot.types.InlineKeyboardButton("⚽ Snake Soccer Stars", callback_data="game_soccer"))
        markup.add(telebot.types.InlineKeyboardButton("🍏 iOS Gbox Certificates", callback_data="prod_ios_certs"))
        markup.add(telebot.types.InlineKeyboardButton("🛠️ Maintenance Products", callback_data="show_maint_list"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu"))
        bot.edit_message_text("🎮 **— SELECT A GAME —**\n\nChoose your game to view available mods:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "game_ff":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("⚡ Non-Root", callback_data="ff_plat_nr"))
        markup.add(telebot.types.InlineKeyboardButton("🛡️ Root", callback_data="ff_plat_root"))
        markup.add(telebot.types.InlineKeyboardButton("🍏 iOS (iPhone)", callback_data="ff_plat_ios"))
        markup.add(telebot.types.InlineKeyboardButton("💻 PC Version", callback_data="prod_ff_pc_brmod"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Games", callback_data="mods_game_select"))
        bot.edit_message_text("🔥 **FREE FIRE — SELECT PLATFORM**\n\nChoose your device setup:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "ff_plat_nr":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🛒 ABCD Panel Nonroot", callback_data="prod_ff_nr_abcd"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Bala Mod Nonroot", callback_data="prod_ff_nr_bala"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 XYZ Apk Silent Nonroot", callback_data="prod_ff_nr_silent_apk"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 XYZ Config Proxy Nonroot", callback_data="prod_ff_nr_cfg_proxy"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Silent Cheat Proxy Nonroot", callback_data="prod_ff_nr_sc_proxy"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Silent Cheat Apkmod Nonroot", callback_data="prod_ff_nr_sc_apkmod"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Prime Hook Nonroot", callback_data="prod_ff_nr_prime"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 DripClient Wire Nonroot", callback_data="prod_ff_nr_drip_wire"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 DripClient Proxy Nonroot", callback_data="prod_ff_nr_drip_proxy"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 HG Cheats Proxy Nonroot", callback_data="prod_ff_nr_hg_proxy"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 HG Cheats Prime Proxy Nonroot", callback_data="prod_ff_nr_hg_prime"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 XRAG Nonroot/Root", callback_data="prod_ff_nr_xrag"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Aim Hack Nonroot/Root", callback_data="prod_ff_nr_aimhack"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Pato Team Android", callback_data="prod_ff_nr_pato"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to FF Platforms", callback_data="game_ff"))
        bot.edit_message_text("⚡ **FREE FIRE (NON-ROOT) MODS**\n\nSelect a mod to view duration packs:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "ff_plat_root":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🛒 Silent Cheat Root Android", callback_data="prod_ff_r_silent"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Haxx-Cker Pro Root", callback_data="prod_ff_r_haxx"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Rapid Core Root", callback_data="prod_ff_r_rapid"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 DripClient Root", callback_data="prod_ff_r_drip"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 HG Cheats Apkmod Root", callback_data="prod_ff_r_hg"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to FF Platforms", callback_data="game_ff"))
        bot.edit_message_text("🛡️ **FREE FIRE (ROOT) MODS**\n\nSelect a mod to view duration packs:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "ff_plat_ios":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🛒 Migul iPhone iOS FF", callback_data="prod_ff_ios_migul"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Delta Proxy iOS iPhone", callback_data="prod_ff_ios_delta"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to FF Platforms", callback_data="game_ff"))
        bot.edit_message_text("🍏 **FREE FIRE (IOS IPHONE) MODS**\n\nSelect a mod to view duration packs:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "game_codm":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🛒 iOS Cloud CODM (30 Days)", callback_data="prod_codm_ios_cloud"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Games", callback_data="mods_game_select"))
        bot.edit_message_text("🎯 **CALL OF DUTY MOBILE (CODM)**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "game_mlbb":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🛒 Fluorite iOS MLBB", callback_data="prod_mlbb_ios_fluorite"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Games", callback_data="mods_game_select"))
        bot.edit_message_text("⚔️ **MOBILE LEGENDS (MLBB)**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "game_8bp":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🛒 Snake 8 Ball Pool Nonroot", callback_data="prod_8bp_snake_nr"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 KOS 8 Ball Pool Virtual", callback_data="prod_8bp_kos_virtual"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 KOS 8 Ball Pool Mod+Root", callback_data="prod_8bp_kos_root"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 iOS Fluorite 8 Ball Pool", callback_data="prod_8bp_ios_fluorite"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Games", callback_data="mods_game_select"))
        bot.edit_message_text("🎱 **8 BALL POOL MODS**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "game_carrom":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🛒 Snake Carrom Pool Nonroot", callback_data="prod_carrom_snake_nr"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 KOS Carrom Pool Nonroot", callback_data="prod_carrom_kos_nr"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Games", callback_data="mods_game_select"))
        bot.edit_message_text("⚪ **CARROM POOL MODS**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "game_soccer":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🛒 Snake Soccer Stars Nonroot", callback_data="prod_soccer_snake_nr"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Games", callback_data="mods_game_select"))
        bot.edit_message_text("⚽ **SNAKE SOCCER STARS MODS**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # 2. DURATION PACK PICKER
    elif call.data.startswith("prod_"):
        bot.answer_callback_query(call.id)
        prod_key = call.data.replace("prod_", "")
        data = CATALOG.get(prod_key)
        if not data:
            bot.send_message(call.message.chat.id, "Product not found.")
            return

        markup = telebot.types.InlineKeyboardMarkup()
        for idx, (dur, price) in enumerate(data["items"]):
            markup.add(telebot.types.InlineKeyboardButton(f"{dur} — ₹{int(price)}", callback_data=f"buykey_{prod_key}_{idx}"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Game Catalog", callback_data="mods_game_select"))

        bot.edit_message_text(
            f"🛒 **{data['name']}**\n📌 Select a duration pack below:",
            call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup
        )

    # 3. DIRECT PURCHASE HANDLER
    elif call.data.startswith("buykey_"):
        parts = call.data.split("_")
        prod_key = "_".join(parts[1:-1])
        idx = int(parts[-1])

        product = CATALOG.get(prod_key)
        if not product:
            bot.answer_callback_query(call.id, text="Product expired.", show_alert=True)
            return

        duration_text, price_inr = product["items"][idx]
        pid = product["pid"]
        product_name = product["name"]

        bot.answer_callback_query(call.id, text="Processing order...")
        execute_purchase(call, user_id, pid, duration_text, price_inr, product_name)

    # 4. MAINTENANCE MODS POPUP
    elif call.data == "show_maint_list":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        for p in MAINTENANCE_PRODUCTS:
            markup.add(telebot.types.InlineKeyboardButton(f"🛠️ {p[:28]}...", callback_data="maint_click_alert"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Games", callback_data="mods_game_select"))
        bot.edit_message_text("🛠️ **PRODUCTS CURRENTLY UNDER MAINTENANCE**\n\nTap any product to view status:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "maint_click_alert":
        bot.answer_callback_query(
            call.id,
            text="⚠️ UNDER MAINTENANCE!\nThis product is being updated by developers. No keys can be purchased right now.",
            show_alert=True
        )

    # 5. 100% FREE DISPOSABLE TEMP MAIL
    elif call.data == "temp_mail_menu":
        bot.answer_callback_query(call.id)
        current = user_temp_mails.get(user_id)
        markup = telebot.types.InlineKeyboardMarkup()
        if current:
            addr = current["address"]
            text_body = (
                "📬 **— 100% FREE TEMP MAIL HUB —** 📬\n\n"
                f"📧 **Active Address:**\n`{addr}`\n*(Tap to copy address)*\n\n"
                "Use this email to receive registration OTP codes and verification links instantly."
            )
            markup.add(telebot.types.InlineKeyboardButton("🔄 Check Inbox", callback_data="tmail_inbox"))
            markup.add(telebot.types.InlineKeyboardButton("⚡ Generate New Mail", callback_data="tmail_gen_new"))
        else:
            text_body = (
                "📬 **— 100% FREE TEMP MAIL HUB —** 📬\n\n"
                "⚡ Generate unlimited disposable mailboxes for games & websites.\n"
                "No payment or pass required. Tap below to generate:"
            )
            markup.add(telebot.types.InlineKeyboardButton("⚡ Generate Free Email", callback_data="tmail_gen_new"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu"))
        bot.edit_message_text(text_body, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "tmail_gen_new":
        bot.answer_callback_query(call.id, text="Creating inbox...")
        addr, token = mailtm_create_account()
        if addr and token:
            user_temp_mails[user_id] = {"address": addr, "token": token}
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("🔄 Check Inbox", callback_data="tmail_inbox"))
            markup.add(telebot.types.InlineKeyboardButton("⚡ Generate Another", callback_data="tmail_gen_new"))
            markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
            bot.edit_message_text(
                f"🎉 **Free Temporary Mail Ready!**\n\n📧 **Address:**\n`{addr}`\n\n"
                "*(Tap to copy)*\n\nOnce you request an OTP on a website/app, tap **🔄 Check Inbox** below.",
                call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup
            )
        else:
            bot.send_message(call.message.chat.id, "⚠️ Failed to connect to mail server. Try again in 5 seconds.")

    elif call.data == "tmail_inbox":
        bot.answer_callback_query(call.id, text="Checking inbox...")
        current = user_temp_mails.get(user_id)
        if not current:
            bot.answer_callback_query(call.id, text="Generate an email first.", show_alert=True)
            return

        msgs = mailtm_fetch_messages(current["token"])
        markup = telebot.types.InlineKeyboardMarkup()
        if not msgs:
            inbox_text = f"📬 **INBOX: `{current['address']}`**\n\n📭 **Inbox is currently empty.**\nWait a few seconds for emails to deliver, then tap refresh."
        else:
            inbox_text = f"📬 **INBOX: `{current['address']}`**\n\nIncoming messages:\n\n"
            for m in msgs[:6]:
                sender = m.get("from", {}).get("address", "Unknown")
                subject = m.get("subject", "(No Subject)")
                intro = m.get("intro", "")
                m_id = m.get("id")
                inbox_text += f"📩 **From:** `{sender}`\n📌 **Subject:** {subject}\n💬 {intro[:80]}...\n-------------------\n"
                markup.add(telebot.types.InlineKeyboardButton(f"📖 Read: {subject[:25]}", callback_data=f"tmail_read_{m_id}"))

        markup.add(telebot.types.InlineKeyboardButton("🔄 Refresh Inbox", callback_data="tmail_inbox"))
        markup.add(telebot.types.InlineKeyboardButton("⚡ New Email", callback_data="tmail_gen_new"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Temp Mail", callback_data="temp_mail_menu"))
        bot.edit_message_text(inbox_text[:4000], call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data.startswith("tmail_read_"):
        bot.answer_callback_query(call.id)
        current = user_temp_mails.get(user_id)
        if not current:
            return
        m_id = call.data.replace("tmail_read_", "")
        detail = mailtm_fetch_message_detail(current["token"], m_id)
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Inbox", callback_data="tmail_inbox"))
        if detail:
            sender = detail.get("from", {}).get("address", "Unknown")
            subject = detail.get("subject", "(No Subject)")
            text_body = detail.get("text", "(No Body)")
            bot.edit_message_text(f"📩 **MESSAGE DETAILS**\n\n👤 From: `{sender}`\n📌 Subject: {subject}\n\n📝 Body:\n{text_body[:3500]}", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)
        else:
            bot.send_message(call.message.chat.id, "❌ Unable to load email content.", reply_markup=markup)

    # 6. SMM BOOSTING SERVICES
    elif call.data == "smm_main_menu":
        bot.answer_callback_query(call.id)
        smm_text = (
            "🚀 **— SOCIAL MEDIA BOOSTING HUB —** 🚀\n\n"
            "Boost your reach with instant automated delivery:\n\n"
            "🔥 **Instagram Reel Views** — Only ₹1 / 1,000\n"
            "👥 **Telegram Members** — Only ₹35 / 1,000 (Non-Drop 30D Refill)\n"
            "❤️ **Instagram Likes** — Indian Real Accounts\n"
            "🇮🇳 **Instagram Followers** — 100% Indian Profiles\n\n"
            "👇 **Choose a service category below:**"
        )
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🔥 IG Reel Views (₹1/1k)", callback_data="smm_cat_views"))
        markup.add(telebot.types.InlineKeyboardButton("👥 TG Channel Members (₹35/1k)", callback_data="smm_cat_tg"))
        markup.add(telebot.types.InlineKeyboardButton("❤️ IG Indian Likes", callback_data="smm_cat_likes"))
        markup.add(telebot.types.InlineKeyboardButton("🇮🇳 IG Indian Followers", callback_data="smm_cat_followers"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu"))
        bot.edit_message_text(smm_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "smm_cat_views":
        bot.answer_callback_query(call.id)
        v_text = "🔥 **INSTAGRAM REELS VIEWS** (Service ID: 14686)\n⚡ Ultra-Fast 500k/Day Speed | Instant Start\n\nSelect a pack below:"
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("⚡ 1,000 Views — ₹1", callback_data="smm_buy_14686_1000_1.0_IG_Reel_Views"))
        markup.add(telebot.types.InlineKeyboardButton("⚡ 5,000 Views — ₹5", callback_data="smm_buy_14686_5000_5.0_IG_Reel_Views"))
        markup.add(telebot.types.InlineKeyboardButton("⚡ 10,000 Views — ₹10", callback_data="smm_buy_14686_10000_10.0_IG_Reel_Views"))
        markup.add(telebot.types.InlineKeyboardButton("⚡ 50,000 Views — ₹45", callback_data="smm_buy_14686_50000_45.0_IG_Reel_Views"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to SMM Menu", callback_data="smm_main_menu"))
        bot.edit_message_text(v_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "smm_cat_tg":
        bot.answer_callback_query(call.id)
        tg_text = "👥 **TELEGRAM CHANNEL MEMBERS** (Service ID: 14811)\n🛡️ Non-Drop | 30 Days Refill Guarantee | 10k/hr Speed\n\nSelect a pack below:"
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("👥 500 Members — ₹18", callback_data="smm_buy_14811_500_18.0_TG_Members"))
        markup.add(telebot.types.InlineKeyboardButton("👥 1,000 Members — ₹35", callback_data="smm_buy_14811_1000_35.0_TG_Members"))
        markup.add(telebot.types.InlineKeyboardButton("👥 2,000 Members — ₹70", callback_data="smm_buy_14811_2000_70.0_TG_Members"))
        markup.add(telebot.types.InlineKeyboardButton("👥 5,000 Members — ₹170", callback_data="smm_buy_14811_5000_170.0_TG_Members"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to SMM Menu", callback_data="smm_main_menu"))
        bot.edit_message_text(tg_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "smm_cat_likes":
        bot.answer_callback_query(call.id)
        lk_text = "❤️ **INSTAGRAM INDIAN LIKES** (Service ID: 14166)\n🇮🇳 100% Indian Profiles | Instant Start | Low Drop\n\nSelect a pack below:"
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("❤️ 100 Likes — ₹3", callback_data="smm_buy_14166_100_3.0_IG_Likes"))
        markup.add(telebot.types.InlineKeyboardButton("❤️ 500 Likes — ₹12", callback_data="smm_buy_14166_500_12.0_IG_Likes"))
        markup.add(telebot.types.InlineKeyboardButton("❤️ 1,000 Likes — ₹20", callback_data="smm_buy_14166_1000_20.0_IG_Likes"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to SMM Menu", callback_data="smm_main_menu"))
        bot.edit_message_text(lk_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "smm_cat_followers":
        bot.answer_callback_query(call.id)
        fol_text = "🇮🇳 **INSTAGRAM INDIAN FOLLOWERS** (Service ID: 9895)\n🇮🇳 Real Indian Accounts with Posts | 30 Days Refill\n\nSelect a pack below:"
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🇮🇳 100 Followers — ₹15", callback_data="smm_buy_9895_100_15.0_IG_Followers"))
        markup.add(telebot.types.InlineKeyboardButton("🇮🇳 500 Followers — ₹65", callback_data="smm_buy_9895_500_65.0_IG_Followers"))
        markup.add(telebot.types.InlineKeyboardButton("🇮🇳 1,000 Followers — ₹120", callback_data="smm_buy_9895_1000_120.0_IG_Followers"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to SMM Menu", callback_data="smm_main_menu"))
        bot.edit_message_text(fol_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data.startswith("smm_buy_"):
        bot.answer_callback_query(call.id)
        parts = call.data.split("_")
        srv_id = parts[2]
        qty = int(parts[3])
        cost = float(parts[4])
        srv_name = " ".join(parts[5:])

        fresh_user = get_user(user_id)
        if not fresh_user or fresh_user["balance"] < cost:
            cur_b = fresh_user["balance"] if fresh_user else 0.0
            bot.send_message(
                call.message.chat.id,
                f"❌ **Insufficient Balance!**\nRequired: ₹{cost:.2f} | Balance: ₹{cur_b:.2f}\n\nPlease add balance to continue.",
                parse_mode="Markdown",
                reply_markup=telebot.types.InlineKeyboardMarkup().add(
                    telebot.types.InlineKeyboardButton("💳 Add Balance Now", callback_data="add_balance"),
                    telebot.types.InlineKeyboardButton("🔙 Back to SMM Menu", callback_data="smm_main_menu")
                )
            )
            return

        waiting_for_smm_link[user_id] = {
            "service_id": srv_id,
            "quantity": qty,
            "cost": cost,
            "name": srv_name
        }

        markup = telebot.types.InlineKeyboardMarkup().add(
            telebot.types.InlineKeyboardButton("🔙 Cancel & Back", callback_data="smm_main_menu")
        )
        instruction = "your Instagram post/reel link" if "Views" in srv_name or "Likes" in srv_name else "your Instagram profile link"
        if "TG" in srv_name:
            instruction = "your Public Telegram channel/group link (`https://t.me/...`)"

        prompt_text = (
            f"🛒 **Confirm Order: {srv_name}**\n\n"
            f"📦 **Quantity:** {qty:,}\n"
            f"💰 **Total Cost:** ₹{cost:.2f}\n\n"
            f"👇 **Reply with {instruction}:**\n"
            "*(Make sure your account/channel is PUBLIC)*"
        )
        bot.edit_message_text(prompt_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # 7. AI IMAGE & VIDEO GENERATOR MENUS (BUG FIX INCLUDED)
    elif call.data == "open_image_gen":
        bot.answer_callback_query(call.id)
        waiting_for_image_prompt[user_id] = True
        markup = telebot.types.InlineKeyboardMarkup().add(
            telebot.types.InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")
        )
        text_prompt = (
            f"🎨 **AI IMAGE GENERATOR (FLUX 4K)**\n\n"
            f"⚡ Rate: **₹{IMAGE_FEE:.2f} per generation**\n\n"
            "Generate esports mascots, gaming thumbnails, wallpapers, or anime characters.\n\n"
            "👇 **Type and reply with your prompt below:**\n"
            "*(Example: `Cyberpunk futuristic samurai warrior with glowing neon katana, 4k ultra detailed wallpaper`)*"
        )
        # Fix: Delete photo message if triggered from "Create Another" button
        if call.message.content_type == 'photo':
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            bot.send_message(call.message.chat.id, text_prompt, parse_mode="Markdown", reply_markup=markup)
        else:
            bot.edit_message_text(text_prompt, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "open_video_gen":
        bot.answer_callback_query(call.id)
        waiting_for_video_prompt[user_id] = True
        markup = telebot.types.InlineKeyboardMarkup().add(
            telebot.types.InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")
        )
        text_prompt = (
            f"🎬 **AI VIDEO GENERATOR (VEO HD)**\n\n"
            f"⚡ Rate: **₹{VIDEO_FEE:.2f} per generation**\n\n"
            "Generate cinematic 4-second AI videos, gaming clips, and 3D animations.\n\n"
            "👇 **Type and reply with your prompt below:**\n"
            "*(Example: `Cinematic drone shot of an ancient neon pagoda at sunset, 4k 60fps`)*"
        )
        if call.message.content_type in ['video', 'photo']:
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            bot.send_message(call.message.chat.id, text_prompt, parse_mode="Markdown", reply_markup=markup)
        else:
            bot.edit_message_text(text_prompt, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # 8. WALLET TOPUP
    elif call.data == "add_balance":
        bot.answer_callback_query(call.id)
        waiting_for_custom_topup[user_id] = True
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        fresh_user = get_user(user_id)
        bot.edit_message_text(
            f"💰 **— ADD BALANCE —** 💰\n\n💳 Current Balance: ₹{fresh_user['balance']:.2f}\n\n"
            "👇 **Reply with the amount in Rupees to add (e.g. `100`):**",
            call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup
        )

    elif call.data == "cancel_topup":
        bot.answer_callback_query(call.id, text="Top-up canceled.")
        user_orders.pop(user_id, None)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        bot.send_message(call.message.chat.id, "❌ Top-up canceled.", reply_markup=telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")))

    # 9. USER UTILITIES & EXPANDED BIG PROFILE DASHBOARD
    elif call.data == "profile":
        bot.answer_callback_query(call.id)
        fresh = get_user(user_id)
        role = "👑 Master Admin" if is_admin else f"👤 {fresh['role']}"
        status_badge = "🚫 Banned" if fresh["banned"] else "🟢 Verified & Active"

        profile_text = (
            "╔═══════════════════════════╗\n"
            "      👤 **USER ACCOUNT DASHBOARD**\n"
            "╚═══════════════════════════╝\n\n"
            f"🏷️ **User Tag:** {fresh['name']}\n"
            f"🆔 **Telegram ID:** `{user_id}`\n"
            f"🎖️ **Account Tier:** `{role}`\n"
            f"🛡️ **Account Status:** {status_badge}\n"
            f"📅 **Member Since:** `{fresh['joined']}`\n\n"
            "┌─── 💳 **WALLET & SPENDING** ────────┐\n"
            f"│ 💰 **Current Balance:** ₹{fresh['balance']:.2f}\n"
            f"│ 💸 **Lifetime Spent:**  ₹{fresh['total_spent']:.2f}\n"
            f"│ 📦 **Orders Completed:** {fresh['orders_count']}\n"
            "└────────────────────────────────┘\n\n"
            "┌─── 🎁 **REWARDS & BONUSES** ────────┐\n"
            f"│ 👥 **Total Referrals:** {fresh.get('total_referrals', 0)}\n"
            f"│ 🎡 **Bonus Spins Bank:** {fresh.get('bonus_spins', 0)}\n"
            f"│ ⏱️ **Last Daily Spin:**  `{fresh.get('last_spin_time') or 'Available Now'}`\n"
            "└────────────────────────────────┘"
        )
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(
            telebot.types.InlineKeyboardButton("💳 Add Balance", callback_data="add_balance"),
            telebot.types.InlineKeyboardButton("📦 My Orders", callback_data="orders")
        )
        markup.add(
            telebot.types.InlineKeyboardButton("🎡 Lucky Spin", callback_data="lucky_spin"),
            telebot.types.InlineKeyboardButton("🎁 Refer Friends", callback_data="referral")
        )
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu"))

        if call.message.content_type in ['photo', 'video']:
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
            bot.send_message(call.message.chat.id, profile_text, parse_mode="Markdown", reply_markup=markup)
        else:
            bot.edit_message_text(profile_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "orders":
        bot.answer_callback_query(call.id)
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute('SELECT duration, license_key, price, date FROM orders WHERE user_id = %s ORDER BY id DESC LIMIT 10', (user_id,))
            rows = cur.fetchall()
            cur.close()
        except Exception:
            rows = []
        finally:
            release_db_connection(conn)

        if not rows:
            text_hist = "📦 You have no past orders."
        else:
            text_hist = "🛍️ **— MY ORDERS (Last 10) —** 🛍️\n\n"
            for r in rows:
                text_hist += f"🛒 {r[0]}\n🔑 `{r[1]}`\n💰 ₹{r[2]} | 📅 {r[3]}\n-------------------\n"
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text(text_hist, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "referral":
        bot.answer_callback_query(call.id)
        bot_username = bot.get_me().username
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text(
            f"🎁 **REFERRAL PROGRAM**\n\nShare your link to invite friends:\n`https://t.me/{bot_username}?start=ref_{user_id}`",
            call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup
        )

    elif call.data == "lucky_spin":
        bot.answer_callback_query(call.id)
        fresh = get_user(user_id)
        bonus_spins = fresh.get("bonus_spins", 0)
        last_spin = fresh.get("last_spin_time")
        can_spin = (bonus_spins > 0)
        if not can_spin and last_spin:
            try:
                last_dt = datetime.strptime(last_spin, "%Y-%m-%d %H:%M:%S")
                can_spin = ((datetime.now() - last_dt).total_seconds() / 3600.0 >= 24.0)
            except Exception:
                can_spin = True
        elif not last_spin:
            can_spin = True

        markup = telebot.types.InlineKeyboardMarkup()
        if can_spin:
            markup.add(telebot.types.InlineKeyboardButton("🎯 SPIN NOW", callback_data="do_lucky_spin"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text("🎡 **LUCKY SPIN SYSTEM**\n\nSpin daily to win free wallet rewards!", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "do_lucky_spin":
        reward = random.choice([0, 0, 0, 1, 1, 2, 5])
        atomic_update_balance(user_id, float(reward))
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute('UPDATE users SET last_spin_time = %s WHERE user_id = %s', (now_str, user_id))
            conn.commit()
            cur.close()
        except Exception:
            pass
        finally:
            release_db_connection(conn)

        bot.answer_callback_query(call.id, text=f"Reward: ₹{reward}", show_alert=True)
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        res_msg = f"🎉 Won ₹{reward} balance!" if reward > 0 else "😢 No reward this time!"
        bot.edit_message_text(f"🎡 **SPIN RESULT**\n\n{res_msg}", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "support_ticket":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("💳 Payment Issue", callback_data="tkt_Payment"))
        markup.add(telebot.types.InlineKeyboardButton("🔑 Mod Key Issue", callback_data="tkt_Key"))
        markup.add(telebot.types.InlineKeyboardButton("🚀 SMM Boosting Issue", callback_data="tkt_SMM"))
        markup.add(telebot.types.InlineKeyboardButton("💬 Other Issue", callback_data="tkt_Other"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text("🎟️ **SUPPORT TICKET**\n\nSelect your category:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data.startswith("tkt_"):
        bot.answer_callback_query(call.id)
        cat = call.data.replace("tkt_", "")
        waiting_for_support_ticket[user_id] = cat
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Cancel", callback_data="main_menu"))
        bot.edit_message_text(f"🎟️ Category: `{cat}`\n\n👇 Reply with your issue/proof message:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "redeem_coupon":
        bot.answer_callback_query(call.id)
        waiting_for_coupon_code[user_id] = True
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Cancel", callback_data="main_menu"))
        bot.edit_message_text("🏷️ **REDEEM COUPON**\n\n👇 Reply with your code below:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "open_ai_assistant":
        bot.answer_callback_query(call.id)
        waiting_for_ai_prompt[user_id] = True
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text("🤖 **STORE AI ASSISTANT**\n\n👇 Reply with any question regarding mod keys, root vs non-root, or boosting services:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # 10. MASTER ADMIN PANEL
    elif call.data == "admin_panel" and is_admin:
        bot.answer_callback_query(call.id)
        m_status = "🔴 OFF (Active)" if not STORE_UNDER_MAINTENANCE else "🟢 ON (Maintenance)"
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"🛠️ Toggle Maintenance: {m_status}", callback_data="adm_toggle_maintenance"))
        markup.add(telebot.types.InlineKeyboardButton("🎟️ View Support Tickets", callback_data="adm_view_tickets"))
        markup.add(telebot.types.InlineKeyboardButton("🏷️ Create Coupon Code", callback_data="adm_create_coupon"))
        markup.add(telebot.types.InlineKeyboardButton("📋 Users List", callback_data="adm_users_list_1"))
        markup.add(telebot.types.InlineKeyboardButton("📊 All Bot Transactions", callback_data="adm_all_transactions"))
        markup.add(telebot.types.InlineKeyboardButton("🔍 Check User Info", callback_data="adm_check_user"))
        markup.add(telebot.types.InlineKeyboardButton("💰 Add Balance", callback_data="adm_addbal_menu"))
        markup.add(telebot.types.InlineKeyboardButton("✂️ Cut Balance", callback_data="adm_cutbal_menu"))
        markup.add(telebot.types.InlineKeyboardButton("🔨 Ban / Unban User", callback_data="adm_ban_menu"))
        markup.add(telebot.types.InlineKeyboardButton("🤝 Toggle Reseller Role", callback_data="adm_toggle_reseller"))
        markup.add(telebot.types.InlineKeyboardButton("📢 Broadcast Message", callback_data="adm_broadcast"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text("👑 **MASTER ADMIN PANEL**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "adm_toggle_maintenance" and is_admin:
        STORE_UNDER_MAINTENANCE = not STORE_UNDER_MAINTENANCE
        bot.answer_callback_query(call.id, text=f"Maintenance is now {'ON' if STORE_UNDER_MAINTENANCE else 'OFF'}")
        handle_callback(type('obj', (object,), {'from_user': call.from_user, 'message': call.message, 'data': 'admin_panel', 'id': call.id}))

    elif call.data == "adm_create_coupon" and is_admin:
        bot.answer_callback_query(call.id)
        admin_coupon_flow[user_id] = {"step": "code"}
        bot.send_message(call.message.chat.id, "🏷️ **CREATE COUPON**\n\nReply with the code name (e.g. `PROMO50`):", parse_mode="Markdown")

    elif call.data.startswith("adm_coupon_type_") and is_admin:
        bot.answer_callback_query(call.id)
        r_type = call.data.split("_")[3]
        if user_id in admin_coupon_flow:
            admin_coupon_flow[user_id]["type"] = r_type
            admin_coupon_flow[user_id]["step"] = "value"
            val_prompt = "💳 Enter the **Rupee amount** (e.g. `50`):" if r_type == "balance" else "🎡 Enter the **Bonus Spins count** (e.g. `3`):"
            bot.send_message(call.message.chat.id, val_prompt, parse_mode="Markdown")

    elif call.data == "adm_view_tickets" and is_admin:
        bot.answer_callback_query(call.id)
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute('SELECT id, user_id, category, message, date FROM support_tickets ORDER BY id DESC LIMIT 10')
            rows = cur.fetchall()
            cur.close()
        except Exception:
            rows = []
        finally:
            release_db_connection(conn)
        t_text = "🎟️ **RECENT TICKETS**\n\n" + ("\n".join([f"#{r[0]} | User: `{r[1]}` [{r[2]}]\n💬 {r[3]}" for r in rows]) if rows else "No open tickets.")
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel"))
        bot.edit_message_text(t_text[:4000], call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data.startswith("adm_users_list_") and is_admin:
        bot.answer_callback_query(call.id)
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute('SELECT user_id, name, balance FROM users ORDER BY joined DESC LIMIT 15')
            rows = cur.fetchall()
            cur.close()
        except Exception:
            rows = []
        finally:
            release_db_connection(conn)
        u_text = "📋 **USERS REGISTERED (Last 15)**\n\n" + "\n".join([f"`{r[0]}` | {r[1]} | ₹{r[2]:.2f}" for r in rows])
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel"))
        bot.edit_message_text(u_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "adm_all_transactions" and is_admin:
        bot.answer_callback_query(call.id)
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute('SELECT user_id, type, amount, details, date FROM bot_transactions ORDER BY id DESC LIMIT 15')
            rows = cur.fetchall()
            cur.close()
        except Exception:
            rows = []
        finally:
            release_db_connection(conn)
        t_text = "📊 **LAST 15 TRANSACTIONS**\n\n" + "\n".join([f"`{r[0]}` | {r[1]} ₹{r[2]} | {r[3]}" for r in rows])
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel"))
        bot.edit_message_text(t_text[:4000], call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "adm_broadcast" and is_admin:
        bot.answer_callback_query(call.id)
        admin_actions[user_id] = "broadcast"
        bot.send_message(call.message.chat.id, "📢 Send your announcement text:")

    elif call.data in ["adm_addbal_menu", "adm_cutbal_menu", "adm_check_user", "adm_ban_menu", "adm_toggle_reseller"] and is_admin:
        bot.answer_callback_query(call.id)
        act = {
            "adm_addbal_menu": "addbal",
            "adm_cutbal_menu": "cutbal",
            "adm_check_user": "checkuser",
            "adm_ban_menu": "ban",
            "adm_toggle_reseller": "reseller"
        }[call.data]
        admin_actions[user_id] = act
        prompt = "Send: `USER_ID AMOUNT`" if act in ["addbal", "cutbal"] else "Send: `USER_ID`"
        bot.send_message(call.message.chat.id, f"💬 {prompt}", parse_mode="Markdown")

# --- RESELLER PURCHASE API DISPATCH ---
def execute_purchase(call, user_id, product_id, duration_text, price_inr, product_name):
    fresh_user = get_user(user_id)
    if not fresh_user or fresh_user["balance"] < price_inr:
        cur_b = fresh_user["balance"] if fresh_user else 0.0
        bot.send_message(
            call.message.chat.id,
            f"❌ **Insufficient Balance!**\nRequired: ₹{price_inr:.2f} | Balance: ₹{cur_b:.2f}",
            parse_mode="Markdown",
            reply_markup=telebot.types.InlineKeyboardMarkup().add(
                telebot.types.InlineKeyboardButton("💳 Add Balance Now", callback_data="add_balance"),
                telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="mods_game_select")
            )
        )
        return

    atomic_update_balance(user_id, -price_inr, spend_add=price_inr, order_add=1)
    proc_msg = bot.send_message(call.message.chat.id, f"⏳ Contacting panel for {product_name}...")

    payload = {
        'api_key': BANTI_API_KEY,
        'action': 'buy',
        'product_id': str(product_id),
        'duration': duration_text
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'x-master-key': BANTI_MASTER_KEY
    }

    try:
        api_res = requests.post(BANTI_API_URL, data=payload, headers=headers, timeout=20)
        raw_resp = api_res.text.strip()
        license_key = None

        try:
            res_json = api_res.json()
            license_key = res_json.get("key") or res_json.get("license") or res_json.get("data")
        except Exception:
            if raw_resp and "error" not in raw_resp.lower() and "html" not in raw_resp.lower():
                license_key = raw_resp

        try:
            bot.delete_message(call.message.chat.id, proc_msg.message_id)
        except Exception:
            pass

        if license_key and "error" not in str(license_key).lower():
            log_bot_transaction(user_id, "PURCHASE", price_inr, f"Bought {product_name} ({duration_text})")
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn = get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute('INSERT INTO orders (user_id, duration, license_key, price, date) VALUES (%s, %s, %s, %s, %s)', (user_id, duration_text, str(license_key), price_inr, now_str))
                conn.commit()
                cur.close()
            finally:
                release_db_connection(conn)

            u_upd = get_user(user_id)
            markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
            bot.send_message(
                call.message.chat.id,
                f"🎉 **KEY GENERATED SUCCESSFULLY!**\n\n📌 **Product:** {product_name}\n⏱️ **Duration:** {duration_text}\n🔑 **Key:**\n`{license_key}`\n\n💰 Cost: ₹{price_inr}\n💳 Remaining Balance: ₹{u_upd['balance']:.2f}",
                parse_mode="Markdown", reply_markup=markup
            )
        else:
            atomic_update_balance(user_id, price_inr, spend_add=-price_inr, order_add=-1)
            log_bot_transaction(user_id, "REFUND", price_inr, f"API Purchase Failed - Refunded for {product_name}")
            markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
            bot.send_message(call.message.chat.id, f"❌ **Purchase Failed (Balance Refunded)**\nServer response: `{raw_resp[:300]}`", parse_mode="Markdown", reply_markup=markup)

    except Exception as e:
        try:
            bot.delete_message(call.message.chat.id, proc_msg.message_id)
        except Exception:
            pass
        atomic_update_balance(user_id, price_inr, spend_add=-price_inr, order_add=-1)
        log_bot_transaction(user_id, "REFUND", price_inr, f"Exception - Refunded for {product_name}")
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, f"⚠️ Connection error, balance refunded: {str(e)}", reply_markup=markup)

# --- SMM LINK RECEIVER ---
@bot.message_handler(func=lambda m: m.from_user.id in waiting_for_smm_link)
def handle_smm_submission(message):
    user_id = message.from_user.id
    details = waiting_for_smm_link.pop(user_id, None)
    if not details:
        return

    link = message.text.strip()
    if link.startswith("/"):
        bot.send_message(message.chat.id, "❌ SMM Boost canceled.")
        return

    cost = details["cost"]
    srv_id = details["service_id"]
    qty = details["quantity"]
    name = details["name"]

    fresh = get_user(user_id)
    if not fresh or fresh["balance"] < cost:
        bot.send_message(message.chat.id, "❌ Insufficient balance.")
        return

    atomic_update_balance(user_id, -cost, spend_add=cost, order_add=1)
    load = bot.send_message(message.chat.id, f"⏳ Submitting order for {qty:,} {name}...")

    res = smm_place_order(srv_id, link, qty)
    try:
        bot.delete_message(message.chat.id, load.message_id)
    except Exception:
        pass

    markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to SMM", callback_data="smm_main_menu"))
    if "order" in res:
        smm_id = res["order"]
        log_bot_transaction(user_id, "SMM_ORDER", cost, f"SMM Order #{smm_id} ({qty:,} {name})")
        bot.send_message(
            message.chat.id,
            f"🎉 **BOOST ORDER PLACED!**\n\n🆔 **Order ID:** `{smm_id}`\n📌 **Service:** {name}\n📦 **Quantity:** {qty:,}\n🔗 **Link:** `{link}`\n💰 **Cost:** ₹{cost:.2f}",
            parse_mode="Markdown", reply_markup=markup
        )
    else:
        atomic_update_balance(user_id, cost, spend_add=-cost, order_add=-1)
        err = res.get("error", str(res))
        bot.send_message(message.chat.id, f"❌ Order failed, balance refunded. Reason: `{err}`", reply_markup=markup)

# --- FAMPAY UPI TOPUP ---
def create_topup_order(message_obj, user_id, amount_inr):
    headers = {"Authorization": f"Bearer {FAMPAY_API_KEY}", "Content-Type": "application/json"}
    payload = {"amount": amount_inr * 100, "redirect_url": "https://t.me/"}
    chat_id = message_obj.chat.id

    try:
        res_data = requests.post(f"{FAMPAY_BASE_URL}/orders", json=payload, headers=headers).json()
        if "payment_link" in res_data:
            order_id = res_data["id"]
            pay_link = res_data["payment_link"]
            qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={requests.utils.quote(pay_link)}"

            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("❌ Cancel Order", callback_data="cancel_topup"))
            sent = bot.send_photo(
                chat_id, qr_url,
                caption=f"💳 **Order:** ₹{amount_inr}\n🆔 ID: `{order_id}`\n\n🔗 [Pay via UPI]({pay_link})\n⏱️ Valid for 5 minutes.",
                parse_mode="Markdown", reply_markup=markup
            )
            user_orders[user_id] = {"order_id": order_id}

            def poll(uid, oid, amt, mid):
                for _ in range(150):
                    time.sleep(2)
                    if uid not in user_orders or user_orders[uid]["order_id"] != oid:
                        break
                    try:
                        v = requests.get(f"{FAMPAY_BASE_URL}/verify/{oid}", headers={"Authorization": f"Bearer {FAMPAY_API_KEY}"}).json()
                        if v.get("status") == "success":
                            user_orders.pop(uid, None)
                            atomic_update_balance(uid, amt)
                            log_bot_transaction(uid, "TOPUP", amt, f"UPI Topup ID: {oid}")
                            try:
                                bot.delete_message(chat_id, mid)
                            except Exception:
                                pass
                            up = get_user(uid)
                            bot.send_message(chat_id, f"🎉 **Payment of ₹{amt} credited!** Current Balance: ₹{up['balance']:.2f}")
                            break
                    except Exception:
                        pass
            threading.Thread(target=poll, args=(user_id, order_id, amount_inr, sent.message_id), daemon=True).start()
    except Exception as e:
        bot.send_message(chat_id, f"Gateway Error: {str(e)}")

# --- USER INPUT HANDLERS ---
@bot.message_handler(func=lambda m: m.from_user.id in waiting_for_custom_topup)
def handle_topup_input(message):
    uid = message.from_user.id
    waiting_for_custom_topup.pop(uid, None)
    try:
        amt = int(message.text.strip())
        if amt < 10:
            bot.send_message(message.chat.id, "Minimum ₹10 required.")
            return
        create_topup_order(message, uid, amt)
    except Exception:
        bot.send_message(message.chat.id, "Enter a valid number.")

@bot.message_handler(func=lambda m: m.from_user.id in waiting_for_support_ticket)
def handle_ticket_input(message):
    uid = message.from_user.id
    cat = waiting_for_support_ticket.pop(uid, "General")
    msg = message.text.strip()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('INSERT INTO support_tickets (user_id, category, message, status, date) VALUES (%s, %s, %s, %s, %s)', (uid, cat, msg, 'Open', now_str))
        conn.commit()
        cur.close()
    finally:
        release_db_connection(conn)

    bot.send_message(message.chat.id, "✅ Ticket submitted. We will inspect it shortly.")
    try:
        bot.send_message(ADMIN_ID, f"🚨 Ticket from `{uid}` [{cat}]:\n{msg}")
    except Exception:
        pass

@bot.message_handler(func=lambda m: m.from_user.id in waiting_for_coupon_code)
def handle_coupon_input(message):
    uid = message.from_user.id
    waiting_for_coupon_code.pop(uid, None)
    code = message.text.strip().upper()
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('SELECT * FROM coupons WHERE code = %s', (code,))
        c = cur.fetchone()
        if not c or (c["expires_at"] and datetime.now() > datetime.strptime(c["expires_at"], "%Y-%m-%d %H:%M:%S")) or c["uses_count"] >= c["max_uses"]:
            bot.send_message(message.chat.id, "❌ Invalid or expired code.")
            cur.close()
            return

        cur.execute('SELECT used_count FROM coupon_redemptions WHERE user_id = %s AND code = %s', (uid, code))
        red = cur.fetchone()
        if red and red["used_count"] >= c["per_user_limit"]:
            bot.send_message(message.chat.id, "❌ You have already redeemed this code.")
            cur.close()
            return

        val = float(c["value"])
        if c["reward_type"] == "balance":
            atomic_update_balance(uid, val)
            bot.send_message(message.chat.id, f"🎉 Code redeemed! ₹{val:.2f} credited.")
        elif c["reward_type"] == "spin":
            cur.execute('UPDATE users SET bonus_spins = bonus_spins + %s WHERE user_id = %s', (int(val), uid))
            bot.send_message(message.chat.id, f"🎉 Code redeemed! {int(val)} bonus spins added.")

        cur.execute('UPDATE coupons SET uses_count = uses_count + 1 WHERE code = %s', (code,))
        cur.execute('INSERT INTO coupon_redemptions (user_id, code, used_count) VALUES (%s, %s, 1) ON CONFLICT (user_id, code) DO UPDATE SET used_count = coupon_redemptions.used_count + 1', (uid, code))
        conn.commit()
        cur.close()
    except Exception as e:
        bot.send_message(message.chat.id, f"Coupon error: {e}")
    finally:
        release_db_connection(conn)

@bot.message_handler(func=lambda m: m.from_user.id in waiting_for_ai_prompt)
def handle_ai_input(message):
    uid = message.from_user.id
    waiting_for_ai_prompt.pop(uid, None)
    query = message.text.strip()
    bot.send_chat_action(message.chat.id, 'typing')
    ans = None

    if GEMINI_API_KEY:
        try:
            r = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent",
                headers={"Content-Type": "application/json", "X-goog-api-key": GEMINI_API_KEY.strip()},
                json={"contents": [{"parts": [{"text": f"{AI_INSTRUCTION}\n\nCustomer: {query}\nAnswer:"}]}]},
                timeout=10
            )
            cands = r.json().get("candidates", [])
            if cands:
                ans = cands[0]["content"]["parts"][0]["text"]
        except Exception:
            pass

    if not ans and OPENROUTER_API_KEY:
        try:
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY.strip()}", "Content-Type": "application/json"},
                json={"model": "meta-llama/llama-3.1-8b-instruct:free", "messages": [{"role": "system", "content": AI_INSTRUCTION}, {"role": "user", "content": query}]},
                timeout=10
            )
            ans = r.json()["choices"][0]["message"]["content"]
        except Exception:
            pass

    bot.send_message(message.chat.id, ans or "Store AI is momentarily busy. Please try again.")

# --- AI IMAGE GENERATION HANDLER ---
@bot.message_handler(func=lambda m: m.from_user.id in waiting_for_image_prompt)
def handle_ai_image_prompt(message):
    uid = message.from_user.id
    waiting_for_image_prompt.pop(uid, None)
    prompt = message.text.strip()

    if prompt.startswith("/"):
        bot.send_message(message.chat.id, "❌ Image generation canceled.")
        return

    fresh_user = get_user(uid)
    if not fresh_user or fresh_user["balance"] < IMAGE_FEE:
        cur_b = fresh_user["balance"] if fresh_user else 0.0
        bot.send_message(
            message.chat.id,
            f"❌ **Insufficient Balance!**\n"
            f"Image generation costs: ₹{IMAGE_FEE:.2f}\n"
            f"Your current balance: ₹{cur_b:.2f}\n\n"
            "Please top up your wallet to generate custom AI images.",
            parse_mode="Markdown",
            reply_markup=telebot.types.InlineKeyboardMarkup().add(
                telebot.types.InlineKeyboardButton("💳 Add Balance", callback_data="add_balance"),
                telebot.types.InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")
            )
        )
        return

    atomic_update_balance(uid, -IMAGE_FEE, spend_add=IMAGE_FEE, order_add=1)
    status_msg = bot.send_message(message.chat.id, f"🎨 Generating your artwork (₹{IMAGE_FEE:.2f} deducted)...")
    bot.send_chat_action(message.chat.id, 'upload_photo')

    try:
        encoded_prompt = urllib.parse.quote(prompt)
        api_key_clean = (POLLINATIONS_API_KEY or "").strip()

        if api_key_clean and not api_key_clean.endswith("_REPLACE_WITH_FULL_KEY"):
            image_url = f"https://gen.pollinations.ai/image/{encoded_prompt}?model=flux&width=1024&height=1024&nologo=true&key={api_key_clean}"
            resp = requests.get(image_url, timeout=45)
        else:
            image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"
            resp = requests.get(image_url, timeout=45)

        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except Exception:
            pass

        if resp.status_code == 200:
            log_bot_transaction(uid, "AI_IMAGE", IMAGE_FEE, f"Generated: {prompt[:40]}")
            u_upd = get_user(uid)
            markup = telebot.types.InlineKeyboardMarkup().add(
                telebot.types.InlineKeyboardButton("🎨 Create Another (₹2)", callback_data="open_image_gen"),
                telebot.types.InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")
            )
            bot.send_photo(
                message.chat.id,
                resp.content,
                caption=(
                    f"✨ **Prompt:** `{prompt[:150]}`\n"
                    f"💰 Charged: ₹{IMAGE_FEE:.2f} | 💳 Balance: ₹{u_upd['balance']:.2f}"
                ),
                parse_mode="Markdown",
                reply_markup=markup
            )
        else:
            atomic_update_balance(uid, IMAGE_FEE, spend_add=-IMAGE_FEE, order_add=-1)
            log_bot_transaction(uid, "REFUND", IMAGE_FEE, f"Failed image status {resp.status_code}")
            bot.send_message(
                message.chat.id,
                f"⚠️ Server returned error ({resp.status_code}). Your balance has been fully refunded.",
                reply_markup=telebot.types.InlineKeyboardMarkup().add(
                    telebot.types.InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")
                )
            )

    except Exception as e:
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except Exception:
            pass
        atomic_update_balance(uid, IMAGE_FEE, spend_add=-IMAGE_FEE, order_add=-1)
        log_bot_transaction(uid, "REFUND", IMAGE_FEE, "Image timeout refund")
        bot.send_message(message.chat.id, f"⚠️ Connection timed out. Balance refunded. Error: {e}")

# --- AI VIDEO GENERATION HANDLER ---
@bot.message_handler(func=lambda m: m.from_user.id in waiting_for_video_prompt)
def handle_ai_video_prompt(message):
    uid = message.from_user.id
    waiting_for_video_prompt.pop(uid, None)
    prompt = message.text.strip()

    if prompt.startswith("/"):
        bot.send_message(message.chat.id, "❌ Video generation canceled.")
        return

    fresh_user = get_user(uid)
    if not fresh_user or fresh_user["balance"] < VIDEO_FEE:
        cur_b = fresh_user["balance"] if fresh_user else 0.0
        bot.send_message(
            message.chat.id,
            f"❌ **Insufficient Balance!**\n"
            f"Video generation costs: ₹{VIDEO_FEE:.2f}\n"
            f"Your current balance: ₹{cur_b:.2f}\n\n"
            "Please top up your wallet to generate AI video clips.",
            parse_mode="Markdown",
            reply_markup=telebot.types.InlineKeyboardMarkup().add(
                telebot.types.InlineKeyboardButton("💳 Add Balance", callback_data="add_balance"),
                telebot.types.InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")
            )
        )
        return

    atomic_update_balance(uid, -VIDEO_FEE, spend_add=VIDEO_FEE, order_add=1)
    status_msg = bot.send_message(message.chat.id, f"🎬 Rendering AI video clip (₹{VIDEO_FEE:.2f} deducted)... This takes ~30-60s.")
    bot.send_chat_action(message.chat.id, 'upload_video')

    try:
        encoded_prompt = urllib.parse.quote(prompt)
        api_key_clean = (POLLINATIONS_API_KEY or "").strip()

        video_url = f"https://gen.pollinations.ai/video/{encoded_prompt}?model=veo&duration=4"
        if api_key_clean and not api_key_clean.endswith("_REPLACE_WITH_FULL_KEY"):
            video_url += f"&key={api_key_clean}"

        resp = requests.get(video_url, timeout=90)

        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except Exception:
            pass

        if resp.status_code == 200:
            log_bot_transaction(uid, "AI_VIDEO", VIDEO_FEE, f"Generated: {prompt[:40]}")
            u_upd = get_user(uid)
            markup = telebot.types.InlineKeyboardMarkup().add(
                telebot.types.InlineKeyboardButton("🎬 Create Another (₹2)", callback_data="open_video_gen"),
                telebot.types.InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")
            )
            bot.send_video(
                message.chat.id,
                resp.content,
                caption=(
                    f"🎬 **Prompt:** `{prompt[:150]}`\n"
                    f"💰 Charged: ₹{VIDEO_FEE:.2f} | 💳 Balance: ₹{u_upd['balance']:.2f}"
                ),
                parse_mode="Markdown",
                reply_markup=markup
            )
        else:
            atomic_update_balance(uid, VIDEO_FEE, spend_add=-VIDEO_FEE, order_add=-1)
            log_bot_transaction(uid, "REFUND", VIDEO_FEE, f"Failed video status {resp.status_code}")
            bot.send_message(
                message.chat.id,
                f"⚠️ Video render error ({resp.status_code}). Your balance has been fully refunded.",
                reply_markup=telebot.types.InlineKeyboardMarkup().add(
                    telebot.types.InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")
                )
            )

    except Exception as e:
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except Exception:
            pass
        atomic_update_balance(uid, VIDEO_FEE, spend_add=-VIDEO_FEE, order_add=-1)
        log_bot_transaction(uid, "REFUND", VIDEO_FEE, "Video timeout refund")
        bot.send_message(message.chat.id, f"⚠️ Video render timed out. Balance refunded. Error: {e}")

# --- ADMIN COUPON CREATOR ENGINE ---
@bot.message_handler(func=lambda message: message.from_user.id in admin_coupon_flow and message.from_user.id == ADMIN_ID)
def admin_coupon_builder(message):
    admin_id = message.from_user.id
    flow = admin_coupon_flow[admin_id]
    text = message.text.strip()

    if flow["step"] == "code":
        flow["code"] = text.upper()
        flow["step"] = "type_select"
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("💳 Balance", callback_data="adm_coupon_type_balance"))
        markup.add(telebot.types.InlineKeyboardButton("🎡 Lucky Spin", callback_data="adm_coupon_type_spin"))
        bot.send_message(message.chat.id, f"🏷️ **Code: `{flow['code']}`**\nSelect coupon reward type:", parse_mode="Markdown", reply_markup=markup)

    elif flow["step"] == "value":
        try:
            flow["value"] = float(text)
            flow["step"] = "max_users"
            bot.send_message(message.chat.id, "👥 Enter max allowed global uses (e.g. `5`):")
        except ValueError:
            bot.send_message(message.chat.id, "❌ Send a valid numeric value.")

    elif flow["step"] == "max_users":
        try:
            flow["max_users"] = int(text)
            flow["step"] = "hours"
            bot.send_message(message.chat.id, "⏳ Enter expiry validity in hours (e.g. `24`):")
        except ValueError:
            bot.send_message(message.chat.id, "❌ Send a valid integer.")

    elif flow["step"] == "hours":
        try:
            hours = int(text)
            admin_coupon_flow.pop(admin_id, None)
            code = flow["code"]
            r_type = flow["type"]
            val = flow["value"]
            max_uses = flow["max_users"]
            expires_at = (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

            conn = get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute('''
                    INSERT INTO coupons (code, reward_type, value, max_uses, uses_count, per_user_limit, expires_at)
                    VALUES (%s, %s, %s, %s, 0, 1, %s)
                    ON CONFLICT (code) DO UPDATE SET reward_type = EXCLUDED.reward_type, value = EXCLUDED.value, max_uses = EXCLUDED.max_uses, expires_at = EXCLUDED.expires_at
                ''', (code, r_type, val, max_uses, expires_at))
                conn.commit()
                cur.close()
            finally:
                release_db_connection(conn)

            bot.send_message(message.chat.id, f"✅ **Coupon `{code}` Created!**\nReward: {r_type} ({val})\nUses: {max_uses}\nExpires: {expires_at}", parse_mode="Markdown")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Error: {e}")

# --- FULL ADMIN ACTIONS ---
@bot.message_handler(func=lambda m: m.from_user.id in admin_actions and m.from_user.id == ADMIN_ID)
def handle_admin_action(message):
    admin_id = message.from_user.id
    action = admin_actions.pop(admin_id)
    text = message.text.strip()

    if action == "broadcast":
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute('SELECT user_id FROM users')
            users = cur.fetchall()
            cur.close()
        except Exception:
            users = []
        finally:
            release_db_connection(conn)
        sent, fail = 0, 0
        for u in users:
            try:
                bot.send_message(u[0], f"📢 **ANNOUNCEMENT**\n\n{text}", parse_mode="Markdown")
                sent += 1
            except Exception:
                fail += 1
        bot.send_message(message.chat.id, f"Broadcast complete. Sent: {sent} | Failed: {fail}")

    elif action in ["addbal", "cutbal"]:
        try:
            target_id, amt = int(text.split()[0]), float(text.split()[1])
            change = amt if action == "addbal" else -amt
            atomic_update_balance(target_id, change)
            log_bot_transaction(target_id, "ADMIN_MOD", change, "Admin manual balance adjustment")
            bot.send_message(message.chat.id, f"Balance adjusted by {change} for `{target_id}`.")
        except Exception:
            bot.send_message(message.chat.id, "Format error: `USER_ID AMOUNT`")

    elif action == "checkuser":
        try:
            target_id = int(text)
            u = get_user(target_id)
            if u:
                role = "👑 Master Admin" if target_id == ADMIN_ID else f"👤 {u['role']}"
                ban_txt = "🚫 BANNED" if u['banned'] else "🟢 ACTIVE"
                bot.send_message(
                    message.chat.id, 
                    f"🆔 `{u['user_id']}` | {u['name']}\nStatus: {ban_txt} | Role: {role}\n💳 Balance: ₹{u['balance']:.2f}\n📦 Orders: {u['orders_count']}\n💸 Spent: ₹{u['total_spent']:.2f}\n👥 Referrals: {u.get('total_referrals', 0)}\n📅 Joined: {u['joined']}",
                    parse_mode="Markdown"
                )
            else:
                bot.send_message(message.chat.id, "User not found.")
        except Exception:
            bot.send_message(message.chat.id, "Invalid ID format.")

    elif action == "ban":
        try:
            target_id = int(text)
            target = get_user(target_id)
            if target:
                new_ban = 0 if target["banned"] else 1
                conn = get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute('UPDATE users SET banned = %s WHERE user_id = %s', (new_ban, target_id))
                    conn.commit()
                    cur.close()
                finally:
                    release_db_connection(conn)
                status = "Banned" if new_ban == 1 else "Unbanned"
                bot.send_message(message.chat.id, f"✅ User `{target_id}` is now **{status}**.", parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, "❌ User not found.")
        except Exception:
            bot.send_message(message.chat.id, "❌ Invalid user ID.")

    elif action == "reseller":
        try:
            target_id = int(text)
            target = get_user(target_id)
            if target:
                new_role = "Customer" if target["role"] == "Reseller" else "Reseller"
                conn = get_db_connection()
                try:
                    cur = conn.cursor()
                    cur.execute('UPDATE users SET role = %s WHERE user_id = %s', (new_role, target_id))
                    conn.commit()
                    cur.close()
                finally:
                    release_db_connection(conn)
                bot.send_message(message.chat.id, f"✅ User `{target_id}` role set to **{new_role}**.", parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, "❌ User not found.")
        except Exception:
            bot.send_message(message.chat.id, "❌ Invalid user ID.")

print("Bot is up and running.")
bot.infinity_polling()
