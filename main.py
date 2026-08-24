import os
import telebot
import requests
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta
import threading
import time
import random

# --- CONFIGURATION ---
BOT_TOKEN = "8980753842:AAG05SklWh3TshUWiJio1_MTWo2Net-ijiE"
ADMIN_ID = 7997110885

FAMPAY_API_KEY = "FAM_LIVE_sk_hRGdY9XAmPu7wzRg9HXjwa8pHdPhKNGB"
FAMPAY_BASE_URL = "https://py.freepanel.in/api/v1"

XYZ_API_URL = "https://adminpanels.shop/api/reseller_v1.php"
XYZ_API_KEY = "8dc220a22ee3ea0ba80340978c2f1248"
XYZ_MASTER_KEY = "a7f3e8b2c9d1f4a6b8c2d5e9f1a3b6c8"

SUPABASE_DB_URL = os.environ.get("DATABASE_URL")

# --- GLOBAL STATES ---
STORE_UNDER_MAINTENANCE = False
bot = telebot.TeleBot(BOT_TOKEN)

last_purchase_time = {}
admin_actions = {}
admin_coupon_flow = {}
user_orders = {}
waiting_for_custom_topup = {}
waiting_for_support_ticket = {}
waiting_for_coupon_code = {}

def get_db_connection():
    return psycopg2.connect(SUPABASE_DB_URL, sslmode='require', connect_timeout=3)

def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
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
        cursor.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_spins INTEGER DEFAULT 0;')
        cursor.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS total_referrals INTEGER DEFAULT 0;')
        cursor.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS last_spin_time TEXT;')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                duration TEXT,
                license_key TEXT,
                price REAL,
                date TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                type TEXT,
                amount REAL,
                details TEXT,
                date TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS support_tickets (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                category TEXT,
                message TEXT,
                status TEXT DEFAULT 'Open',
                date TEXT
            )
        ''')

        cursor.execute('''
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

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS coupon_redemptions (
                user_id BIGINT,
                code TEXT,
                used_count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, code)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS spam_tracker (
                user_id BIGINT PRIMARY KEY,
                abandon_count INTEGER DEFAULT 0,
                timeout_until TEXT
            )
        ''')

        conn.commit()
        cursor.close()
        conn.close()
        print("Database initialized safely with live DB queries (No RAM Cache).")
    except Exception as e:
        print(f"DB Init Error: {e}")

init_db()

def log_bot_transaction(user_id, tx_type, amount, details):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            'INSERT INTO bot_transactions (user_id, type, amount, details, date) VALUES (%s, %s, %s, %s, %s)',
            (user_id, tx_type, amount, details, current_time)
        )
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error logging bot transaction: {e}")

def get_user(user_id):
    """Directly queries Supabase every time to guarantee 100% accurate live balances."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
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
        print(f"Error fetching user: {e}")
    return None

def save_user(user_data):
    """Writes directly to Supabase immediately without relying on cache."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO users (user_id, name, phone, joined, balance, total_spent, orders_count, role, banned, verified, total_referrals, last_spin_time, bonus_spins)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                name = EXCLUDED.name,
                phone = EXCLUDED.phone,
                balance = EXCLUDED.balance,
                total_spent = EXCLUDED.total_spent,
                orders_count = EXCLUDED.orders_count,
                role = EXCLUDED.role,
                banned = EXCLUDED.banned,
                verified = EXCLUDED.verified,
                total_referrals = EXCLUDED.total_referrals,
                last_spin_time = EXCLUDED.last_spin_time,
                bonus_spins = EXCLUDED.bonus_spins
        ''', (
            user_data["user_id"], user_data["name"], user_data.get("phone"), user_data["joined"],
            user_data["balance"], user_data["total_spent"], user_data["orders_count"],
            user_data["role"], int(user_data["banned"]), int(user_data["verified"]), user_data.get("total_referrals", 0),
            user_data.get("last_spin_time"), user_data.get("bonus_spins", 0)
        ))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error saving user: {e}")

def check_timeout(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT timeout_until FROM spam_tracker WHERE user_id = %s', (user_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row and row[0]:
            timeout_time = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            if datetime.now() < timeout_time:
                return int((timeout_time - datetime.now()).total_seconds() / 60)
    except Exception:
        pass
    return 0

def add_abandon(user_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT abandon_count FROM spam_tracker WHERE user_id = %s', (user_id,))
        row = cursor.fetchone()
        count = (row[0] + 1) if row else 1
        if count >= 7:
            minutes = 15 * (2 ** (count - 7))
            timeout_until = (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
        else:
            timeout_until = None
        cursor.execute('''
            INSERT INTO spam_tracker (user_id, abandon_count, timeout_until) VALUES (%s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET abandon_count = EXCLUDED.abandon_count, timeout_until = EXCLUDED.timeout_until
        ''', (user_id, count, timeout_until))
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        pass

def get_price(retail_price, panel_price, is_reseller):
    if is_reseller:
        return panel_price + 1
    return retail_price

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if user and user["banned"]:
        bot.send_message(message.chat.id, "❌ **Access Denied:** Your account has been suspended.", parse_mode="Markdown")
        return

    if check_timeout(user_id) > 0:
        bot.send_message(message.chat.id, "⏳ You are temporarily timed out.", parse_mode="Markdown")
        return

    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].split("_")[1])
            ref_user = get_user(referrer_id)
            if referrer_id != user_id and ref_user and not user:
                ref_user["total_referrals"] += 1
                save_user(ref_user)
        except Exception:
            pass

    if not user or not user.get("verified", False):
        if not user:
            save_user({
                "user_id": user_id, "name": message.from_user.first_name, "phone": None,
                "joined": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "balance": 0.0,
                "total_spent": 0.0, "orders_count": 0, "role": "Customer", "banned": False,
                "verified": False, "total_referrals": 0, "last_spin_time": None, "bonus_spins": 0
            })
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
            
        if user:
            user["verified"] = True
            user["phone"] = message.contact.phone_number
            save_user(user)
        else:
            save_user({
                "user_id": user_id, "name": message.from_user.first_name, "phone": message.contact.phone_number,
                "joined": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "balance": 0.0,
                "total_spent": 0.0, "orders_count": 0, "role": "Customer", "banned": False,
                "verified": True, "total_referrals": 0, "last_spin_time": None, "bonus_spins": 0
            })
        bot.send_message(message.chat.id, "✅ Verification Successful!", reply_markup=telebot.types.ReplyKeyboardRemove(), parse_mode="Markdown")
        show_main_menu(message.chat.id, user_id)

def show_main_menu(chat_id, user_id):
    user = get_user(user_id)
    if user and user["banned"]:
        return
        
    is_admin = (user_id == ADMIN_ID)
    user_role = user.get("role", "Customer") if user else "Customer"
    is_res = (user_role == "Reseller" or is_admin)
    
    guest_price = get_price(15, 10, is_res)
    
    welcome_text = (
        "🟢 **STORE ONLINE | CHOOSE YOUR GAME** 🟢\n\n"
        "✨ **Available Perks**\n"
        "💎 Premium Verified Keys\n"
        "⚡ Lightning Instant Delivery\n"
        "🔒 Maximum Security & Protection\n"
        "🎟️ Support Ticket & Lucky Spin System Active\n\n"
        "🛒 **Select an option below:**"
    )
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🛒 All Products", callback_data="all_products"))
    markup.add(telebot.types.InlineKeyboardButton(f"🔥 Guest ID 9 Level Accounts - ₹{guest_price}", callback_data="buy_guest_account"))
    markup.add(telebot.types.InlineKeyboardButton("💳 Add Balance", callback_data="add_balance"),
               telebot.types.InlineKeyboardButton("📦 My Orders", callback_data="orders"))
    markup.add(telebot.types.InlineKeyboardButton("🎁 Referral", callback_data="referral"),
               telebot.types.InlineKeyboardButton("🎡 Lucky Spin", callback_data="lucky_spin"))
    markup.add(telebot.types.InlineKeyboardButton("🎟️ Support Ticket", callback_data="support_ticket"),
               telebot.types.InlineKeyboardButton("🏷️ Redeem Coupon", callback_data="redeem_coupon"))
    markup.add(telebot.types.InlineKeyboardButton("👤 Profile", callback_data="profile"))
    
    if is_admin or user_role == "Reseller":
        welcome_text += f"\n\n⚙️ [{user_role} Dashboard Unlocked]"
    if is_admin:
        markup.add(telebot.types.InlineKeyboardButton("👑 Master Admin Panel", callback_data="admin_panel"))
        
    bot.send_message(chat_id, welcome_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    
    if user and user["banned"]:
        bot.answer_callback_query(call.id, text="❌ Access Denied: Account Suspended.", show_alert=True)
        bot.send_message(call.message.chat.id, "❌ **Your account is banned. No actions are permitted.**", parse_mode="Markdown")
        return

    is_admin = (user_id == ADMIN_ID)
    user_role = user.get("role", "Customer") if user else "Customer"
    is_res = (user_role == "Reseller" or is_admin)
    
    global STORE_UNDER_MAINTENANCE
    maintenance_bypass_actions = [
        "admin_panel", "adm_users_list_1", "adm_all_transactions", "adm_check_user", 
        "adm_addbal_menu", "adm_cutbal_menu", "adm_broadcast", "adm_toggle_reseller", 
        "adm_ban_menu", "adm_toggle_maintenance", "adm_view_tickets", "adm_create_coupon",
        "profile", "orders", "referral", "support_ticket", "main_menu"
    ]
    
    if STORE_UNDER_MAINTENANCE and not is_admin and call.data not in maintenance_bypass_actions:
        bot.answer_callback_query(call.id, text="Store is under maintenance!", show_alert=True)
        bot.send_message(
            call.message.chat.id, 
            "🛠️ **STORE UNDER MAINTENANCE** 🛠️\n\nOur store is currently undergoing updates. Please check back shortly!", 
            parse_mode="Markdown"
        )
        return

    if call.data in ["all_products", "add_balance", "profile", "orders", "referral", "support_ticket", "main_menu", "admin_panel", "lucky_spin", "redeem_coupon"]:
        waiting_for_custom_topup.pop(user_id, None)
        waiting_for_support_ticket.pop(user_id, None)
        waiting_for_coupon_code.pop(user_id, None)
        admin_actions.pop(user_id, None)
        admin_coupon_flow.pop(user_id, None)

    if call.data == "all_products":
        bot.answer_callback_query(call.id)
        catalog_text = "🛍️ **— STORE CATALOG —** 🛍️\n\nSelect a product category below:"
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🛒 Bala Mod Config FF", callback_data="buy_config"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Bala Mod V2 FF", callback_data="buy_v2"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 BR Mod PC Version", callback_data="buy_br_pc"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 BR Mod Root Android", callback_data="buy_br_root"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 DripClient Nonroot", callback_data="buy_drip"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Haxx-Cker Pro Root", callback_data="buy_haxx"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Migul iPhone iOS", callback_data="buy_migul"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Pato Team Android", callback_data="buy_pato"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Prime Hook Nonroot", callback_data="buy_prime"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Silent Cheat Nonroot", callback_data="buy_silent_nonroot"))
        markup.add(telebot.types.InlineKeyboardButton("🛒 Silent Cheat Root", callback_data="buy_silent_root"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text(catalog_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_guest_account":
        bot.answer_callback_query(call.id, text="Processing order...")
        execute_purchase(call, user_id, product_id="guest_account", duration_text="1 Account", price_inr=get_price(15, 10, is_res), product_name="Guest ID 9 Level Account")

    # --- CATEGORY MENUS ---
    elif call.data == "buy_config":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"1 Hours — ₹{get_price(20, 10, is_res)}", callback_data="cfg_1h"))
        markup.add(telebot.types.InlineKeyboardButton(f"3 Hours — ₹{get_price(50, 30, is_res)}", callback_data="cfg_3h"))
        markup.add(telebot.types.InlineKeyboardButton(f"6 Hours — ₹{get_price(90, 60, is_res)}", callback_data="cfg_6h"))
        markup.add(telebot.types.InlineKeyboardButton(f"12 Hours — ₹{get_price(160, 120, is_res)}", callback_data="cfg_12h"))
        markup.add(telebot.types.InlineKeyboardButton(f"24 Hours — ₹{get_price(320, 240, is_res)}", callback_data="cfg_24h"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        bot.edit_message_text("🛍️ **BALA MOD CONFIG FF NONROOT**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_v2":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"1 Hours — ₹{get_price(20, 10, is_res)}", callback_data="v2_1h"))
        markup.add(telebot.types.InlineKeyboardButton(f"3 Hours — ₹{get_price(50, 30, is_res)}", callback_data="v2_3h"))
        markup.add(telebot.types.InlineKeyboardButton(f"6 Hours — ₹{get_price(90, 60, is_res)}", callback_data="v2_6h"))
        markup.add(telebot.types.InlineKeyboardButton(f"12 Hours — ₹{get_price(160, 120, is_res)}", callback_data="v2_12h"))
        markup.add(telebot.types.InlineKeyboardButton(f"1 Day — ₹{get_price(320, 240, is_res)}", callback_data="v2_1d"))
        markup.add(telebot.types.InlineKeyboardButton(f"2 Days — ₹{get_price(640, 480, is_res)}", callback_data="v2_2d"))
        markup.add(telebot.types.InlineKeyboardButton(f"3 Days — ₹{get_price(960, 720, is_res)}", callback_data="v2_3d"))
        markup.add(telebot.types.InlineKeyboardButton(f"5 Days — ₹{get_price(1600, 1200, is_res)}", callback_data="v2_5d"))
        markup.add(telebot.types.InlineKeyboardButton(f"7 Days — ₹{get_price(2240, 1680, is_res)}", callback_data="v2_7d"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        bot.edit_message_text("🛍️ **BALA MOD XYZ ~ V2 FF NONROOT**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_br_pc":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"1 Day Pc Aim Silent — ₹{get_price(80, 50, is_res)}", callback_data="br_1d_silent"))
        markup.add(telebot.types.InlineKeyboardButton(f"1 Day Pc Modmenu x86 — ₹{get_price(80, 50, is_res)}", callback_data="br_1d_mod"))
        markup.add(telebot.types.InlineKeyboardButton(f"10 Day Pc Modmenu x86 — ₹{get_price(300, 250, is_res)}", callback_data="br_10d_mod"))
        markup.add(telebot.types.InlineKeyboardButton(f"10 Days Pc Aim Silent — ₹{get_price(300, 250, is_res)}", callback_data="br_10d_silent"))
        markup.add(telebot.types.InlineKeyboardButton(f"10 Days Pc Bypass + Silent — ₹{get_price(379, 279, is_res)}", callback_data="br_10d_bypass"))
        markup.add(telebot.types.InlineKeyboardButton(f"30 Day Pc Modmenu x86 — ₹{get_price(599, 499, is_res)}", callback_data="br_30d_mod"))
        markup.add(telebot.types.InlineKeyboardButton(f"30 Days Pc Aim Silent — ₹{get_price(599, 499, is_res)}", callback_data="br_30d_silent"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        bot.edit_message_text("🛍️ **BR MOD FF PC VERSION**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_br_root":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"1 Day — ₹{get_price(80, 50, is_res)}", callback_data="br_root_1d"))
        markup.add(telebot.types.InlineKeyboardButton(f"7 Days — ₹{get_price(230, 150, is_res)}", callback_data="br_root_7d"))
        markup.add(telebot.types.InlineKeyboardButton(f"15 Days — ₹{get_price(380, 300, is_res)}", callback_data="br_root_15d"))
        markup.add(telebot.types.InlineKeyboardButton(f"30 Days — ₹{get_price(535, 400, is_res)}", callback_data="br_root_30d"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        bot.edit_message_text("🛍️ **BR MOD FF ROOT ANDROID**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_drip":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"1 Day Nonroot — ₹{get_price(75, 30, is_res)}", callback_data="drip_1d"))
        markup.add(telebot.types.InlineKeyboardButton(f"3 Days Nonroot — ₹{get_price(165, 70, is_res)}", callback_data="drip_3d"))
        markup.add(telebot.types.InlineKeyboardButton(f"7 Days Nonroot — ₹{get_price(245, 125, is_res)}", callback_data="drip_7d"))
        markup.add(telebot.types.InlineKeyboardButton(f"15 Days Nonroot — ₹{get_price(350, 200, is_res)}", callback_data="drip_15d"))
        markup.add(telebot.types.InlineKeyboardButton(f"30 Days Nonroot — ₹{get_price(550, 300, is_res)}", callback_data="drip_30d"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        bot.edit_message_text("🛍️ **DRIPCLIENT FF NONROOT APKMOD**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_haxx":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"10 Days — ₹{get_price(500, 360, is_res)}", callback_data="haxx_10d"))
        markup.add(telebot.types.InlineKeyboardButton(f"20 Days — ₹{get_price(850, 700, is_res)}", callback_data="haxx_20d"))
        markup.add(telebot.types.InlineKeyboardButton(f"30 Days — ₹{get_price(1250, 1050, is_res)}", callback_data="haxx_30d"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        bot.edit_message_text("🛍️ **HAXX-CKER PRO FF ROOT**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_migul":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"1 Day Basic — ₹{get_price(150, 120, is_res)}", callback_data="mig_1d_b"))
        markup.add(telebot.types.InlineKeyboardButton(f"7 Days Basic — ₹{get_price(500, 400, is_res)}", callback_data="mig_7d_b"))
        markup.add(telebot.types.InlineKeyboardButton(f"30 Days Basic — ₹{get_price(1000, 700, is_res)}", callback_data="mig_30d_b"))
        markup.add(telebot.types.InlineKeyboardButton(f"1 Day PRO — ₹{get_price(250, 200, is_res)}", callback_data="mig_1d_p"))
        markup.add(telebot.types.InlineKeyboardButton(f"7 Days PRO — ₹{get_price(800, 600, is_res)}", callback_data="mig_7d_p"))
        markup.add(telebot.types.InlineKeyboardButton(f"30 Days PRO — ₹{get_price(1300, 1000, is_res)}", callback_data="mig_30d_p"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        bot.edit_message_text("🛍️ **MIGUL IPHONE IOS FF**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_pato":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"3 Days Mix — ₹{get_price(160, 133, is_res)}", callback_data="pato_3d"))
        markup.add(telebot.types.InlineKeyboardButton(f"7 Days Mix — ₹{get_price(260, 199, is_res)}", callback_data="pato_7d"))
        markup.add(telebot.types.InlineKeyboardButton(f"15 Days Mix — ₹{get_price(490, 388, is_res)}", callback_data="pato_15d"))
        markup.add(telebot.types.InlineKeyboardButton(f"30 Days Mix — ₹{get_price(720, 469, is_res)}", callback_data="pato_30d"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        bot.edit_message_text("🛍️ **PATO TEAM FF ALL ANDROID**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_prime":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"1 Day Nonroot — ₹{get_price(80, 50, is_res)}", callback_data="prime_1d"))
        markup.add(telebot.types.InlineKeyboardButton(f"3 Days Nonroot — ₹{get_price(160, 120, is_res)}", callback_data="prime_3d"))
        markup.add(telebot.types.InlineKeyboardButton(f"7 Days Nonroot — ₹{get_price(300, 250, is_res)}", callback_data="prime_7d"))
        markup.add(telebot.types.InlineKeyboardButton(f"10 Days Nonroot — ₹{get_price(379, 300, is_res)}", callback_data="prime_10d"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        bot.edit_message_text("🛍️ **PRIME HOOK FF NONROOT ANDROID**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_silent_nonroot":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"1 Day — ₹{get_price(75, 25, is_res)}", callback_data="sil_nr_1d"))
        markup.add(telebot.types.InlineKeyboardButton(f"3 Days — ₹{get_price(160, 64, is_res)}", callback_data="sil_nr_3d"))
        markup.add(telebot.types.InlineKeyboardButton(f"7 Days — ₹{get_price(230, 129, is_res)}", callback_data="sil_nr_7d"))
        markup.add(telebot.types.InlineKeyboardButton(f"14 Days — ₹{get_price(350, 259, is_res)}", callback_data="sil_nr_14d"))
        markup.add(telebot.types.InlineKeyboardButton(f"28 Days — ₹{get_price(800, 519, is_res)}", callback_data="sil_nr_28d"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        bot.edit_message_text("🛍️ **SILENT CHEAT FF NONROOT APKMOD**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_silent_root":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"1 Day Safe — ₹{get_price(75, 25, is_res)}", callback_data="sil_r_1d_safe"))
        markup.add(telebot.types.InlineKeyboardButton(f"1 Day Brutal — ₹{get_price(75, 25, is_res)}", callback_data="sil_r_1d_brut"))
        markup.add(telebot.types.InlineKeyboardButton(f"3 Days Safe — ₹{get_price(160, 64, is_res)}", callback_data="sil_r_3d_safe"))
        markup.add(telebot.types.InlineKeyboardButton(f"3 Days Brutal — ₹{get_price(160, 64, is_res)}", callback_data="sil_r_3d_brut"))
        markup.add(telebot.types.InlineKeyboardButton(f"7 Days Safe — ₹{get_price(230, 129, is_res)}", callback_data="sil_r_7d_safe"))
        markup.add(telebot.types.InlineKeyboardButton(f"7 Days Brutal — ₹{get_price(230, 129, is_res)}", callback_data="sil_r_7d_brut"))
        markup.add(telebot.types.InlineKeyboardButton(f"14 Days Safe — ₹{get_price(350, 259, is_res)}", callback_data="sil_r_14d_safe"))
        markup.add(telebot.types.InlineKeyboardButton(f"14 Days Brutal — ₹{get_price(350, 259, is_res)}", callback_data="sil_r_14d_brut"))
        markup.add(telebot.types.InlineKeyboardButton(f"28 Days Safe — ₹{get_price(800, 519, is_res)}", callback_data="sil_r_28d_safe"))
        markup.add(telebot.types.InlineKeyboardButton(f"28 Days Brutal — ₹{get_price(800, 519, is_res)}", callback_data="sil_r_28d_brut"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        bot.edit_message_text("🛍️ **SILENT CHEAT FF ROOT ANDROID**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # --- PURCHASE EXECUTIONS ---
    elif call.data.startswith("cfg_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        cfg_map = {
            "cfg_1h": ("1 Hours", get_price(20, 10, is_res)),
            "cfg_3h": ("3 Hours", get_price(50, 30, is_res)),
            "cfg_6h": ("6 Hours", get_price(90, 60, is_res)),
            "cfg_12h": ("12 Hours", get_price(160, 120, is_res)),
            "cfg_24h": ("24 Hours", get_price(320, 240, is_res))
        }
        d_text, price = cfg_map[call.data]
        execute_purchase(call, user_id, "142", d_text, price, "Bala Mod Config")

    elif call.data.startswith("v2_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        v2_map = {
            "v2_1h": ("1 Hours", get_price(20, 10, is_res)),
            "v2_3h": ("3 Hours", get_price(50, 30, is_res)),
            "v2_6h": ("6 Hours", get_price(90, 60, is_res)),
            "v2_12h": ("12 Hours", get_price(160, 120, is_res)),
            "v2_1d": ("1 DayS", get_price(320, 240, is_res)),
            "v2_2d": ("2 DayS", get_price(640, 480, is_res)),
            "v2_3d": ("3 DayS", get_price(960, 720, is_res)),
            "v2_5d": ("5 DayS", get_price(1600, 1200, is_res)),
            "v2_7d": ("7 DayS", get_price(2240, 1680, is_res))
        }
        d_text, price = v2_map[call.data]
        execute_purchase(call, user_id, "136", d_text, price, "Bala Mod V2")

    elif call.data.startswith("br_") and not call.data.startswith("br_root_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        br_map = {
            "br_1d_silent": ("1 Day Pc Aim Silent", get_price(80, 50, is_res)),
            "br_1d_mod": ("1 Day Pc Modmenu x86", get_price(80, 50, is_res)),
            "br_10d_mod": ("10 Day Pc Modmenu x86", get_price(300, 250, is_res)),
            "br_10d_silent": ("10 Days Pc Aim Silent", get_price(300, 250, is_res)),
            "br_10d_bypass": ("10 Days Pc Bypass + Silent", get_price(379, 279, is_res)),
            "br_30d_mod": ("30 Day Pc Modmenu x86", get_price(599, 499, is_res)),
            "br_30d_silent": ("30 Days Pc Aim Silent", get_price(599, 499, is_res))
        }
        d_text, price = br_map[call.data]
        execute_purchase(call, user_id, "49", d_text, price, "BR Mod PC")

    elif call.data.startswith("br_root_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        root_map = {
            "br_root_1d": ("1 DaYs", get_price(80, 50, is_res)),
            "br_root_7d": ("7 DaYs", get_price(230, 150, is_res)),
            "br_root_15d": ("15 DaYs", get_price(380, 300, is_res)),
            "br_root_30d": ("30 DaYs", get_price(535, 400, is_res))
        }
        d_text, price = root_map[call.data]
        execute_purchase(call, user_id, "67", d_text, price, "BR Mod Root Android")

    elif call.data.startswith("drip_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        drip_map = {
            "drip_1d": ("1 DaYS NONROOT", get_price(75, 30, is_res)),
            "drip_3d": ("3 DaYS NONROOT", get_price(165, 70, is_res)),
            "drip_7d": ("7 DaYS NONROOT", get_price(245, 125, is_res)),
            "drip_15d": ("15 DaYS NONROOT", get_price(350, 200, is_res)),
            "drip_30d": ("30 DaYS NONROOT", get_price(550, 300, is_res))
        }
        d_text, price = drip_map[call.data]
        execute_purchase(call, user_id, "62", d_text, price, "DripClient Nonroot")

    elif call.data.startswith("haxx_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        haxx_map = {
            "haxx_10d": ("10 DaYs [HAXXCKERPRO API]", get_price(500, 360, is_res)),
            "haxx_20d": ("20 DaYs [HAXXCKERPRO API]", get_price(850, 700, is_res)),
            "haxx_30d": ("30 DaYs [HAXXCKERPRO API]", get_price(1250, 1050, is_res))
        }
        d_text, price = haxx_map[call.data]
        execute_purchase(call, user_id, "64", d_text, price, "Haxx-Cker Pro Root")

    elif call.data.startswith("mig_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        mig_map = {
            "mig_1d_b": ("1 DaYs Basic", get_price(150, 120, is_res)),
            "mig_7d_b": ("7 DaYs Basic", get_price(500, 400, is_res)),
            "mig_30d_b": ("30 DaYs Basic", get_price(1000, 700, is_res)),
            "mig_1d_p": ("1 DaYs PRO", get_price(250, 200, is_res)),
            "mig_7d_p": ("7 DaYs PRO", get_price(800, 600, is_res)),
            "mig_30d_p": ("30 DaYs PRO", get_price(1300, 1000, is_res))
        }
        d_text, price = mig_map[call.data]
        execute_purchase(call, user_id, "69", d_text, price, "Migul iPhone iOS")

    elif call.data.startswith("pato_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        pato_map = {
            "pato_3d": ("3 DaYs All Colours Mix", get_price(160, 133, is_res)),
            "pato_7d": ("7 DaYs All Colours Mix", get_price(260, 199, is_res)),
            "pato_15d": ("15 DaYs All Colours Mix", get_price(490, 388, is_res)),
            "pato_30d": ("30 DaYs All Colours Mix", get_price(720, 469, is_res))
        }
        d_text, price = pato_map[call.data]
        execute_purchase(call, user_id, "54", d_text, price, "Pato Team Android")

    elif call.data.startswith("prime_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        prime_map = {
            "prime_1d": ("1 Days Nonroot", get_price(80, 50, is_res)),
            "prime_3d": ("3 Days Nonroot", get_price(160, 120, is_res)),
            "prime_7d": ("7 Days NonRoot", get_price(300, 250, is_res)),
            "prime_10d": ("10 Days Nonroot", get_price(379, 300, is_res))
        }
        d_text, price = prime_map[call.data]
        execute_purchase(call, user_id, "48", d_text, price, "Prime Hook Nonroot")

    elif call.data.startswith("sil_nr_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        sil_nr_map = {
            "sil_nr_1d": ("1 DaYs", get_price(75, 25, is_res)),
            "sil_nr_3d": ("3 DaYs", get_price(160, 64, is_res)),
            "sil_nr_7d": ("7 DaYs", get_price(230, 129, is_res)),
            "sil_nr_14d": ("14 DaYs", get_price(350, 259, is_res)),
            "sil_nr_28d": ("28 DaYs", get_price(800, 519, is_res))
        }
        d_text, price = sil_nr_map[call.data]
        execute_purchase(call, user_id, "127", d_text, price, "Silent Cheat Nonroot")

    elif call.data.startswith("sil_r_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        sil_r_map = {
            "sil_r_1d_safe": ("1 DaYs SAFE", get_price(75, 25, is_res)),
            "sil_r_1d_brut": ("1 DaYs BRUTAL", get_price(75, 25, is_res)),
            "sil_r_3d_safe": ("3 Days SAFE", get_price(160, 64, is_res)),
            "sil_r_3d_brut": ("3 DaYs BRUTAL", get_price(160, 64, is_res)),
            "sil_r_7d_safe": ("7 DaYs SAFE", get_price(230, 129, is_res)),
            "sil_r_7d_brut": ("7 DaYs BRUTAL", get_price(230, 129, is_res)),
            "sil_r_14d_safe": ("14 DaYs SAFE", get_price(350, 259, is_res)),
            "sil_r_14d_brut": ("14 DaYs BRUTAL", get_price(350, 259, is_res)),
            "sil_r_28d_safe": ("28 DaYs SAFE", get_price(800, 519, is_res)),
            "sil_r_28d_brut": ("28 DaYs BRUTAL", get_price(800, 519, is_res))
        }
        d_text, price = sil_r_map[call.data]
        execute_purchase(call, user_id, "128", d_text, price, "Silent Cheat Root")

    # --- WALLET & UTILITIES ---
    elif call.data == "add_balance":
        bot.answer_callback_query(call.id)
        waiting_for_custom_topup[user_id] = True
        markup = telebot.types.InlineKeyboardMarkup().add(
            telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")
        )
        addbal_text = (
            "💰 **— ADD BALANCE —** 💰\n\n"
            f"💳 **Current Balance:** ₹{user['balance']:.2f}\n\n"
            "💳 **Payment Method:** UPI / QR\n"
            "⏱️ *Generated payment codes expire in 5 minutes.*\n\n"
            "👇 **Please reply with the amount in Rupees you want to add (e.g. `100`):**"
        )
        bot.edit_message_text(addbal_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "redeem_coupon":
        bot.answer_callback_query(call.id)
        waiting_for_coupon_code[user_id] = True
        markup = telebot.types.InlineKeyboardMarkup().add(
            telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")
        )
        bot.edit_message_text(
            "🏷️ **— REDEEM COUPON / CODE —** 🏷️\n\n👇 **Please reply with your coupon or discount code below:**",
            call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup
        )

    elif call.data == "lucky_spin":
        bot.answer_callback_query(call.id)
        fresh_user = get_user(user_id)
        last_spin = fresh_user.get("last_spin_time")
        bonus_spins = fresh_user.get("bonus_spins", 0)
        
        can_spin = True
        remaining_hours = 0
        if bonus_spins > 0:
            can_spin = True
        elif last_spin:
            try:
                last_time = datetime.strptime(last_spin, "%Y-%m-%d %H:%M:%S")
                elapsed_hours = (datetime.now() - last_time).total_seconds() / 3600.0
                if elapsed_hours < 24.0:
                    can_spin = False
                    remaining_hours = int(24.0 - elapsed_hours) + 1
            except Exception:
                pass

        markup = telebot.types.InlineKeyboardMarkup()
        if can_spin:
            markup.add(telebot.types.InlineKeyboardButton("🎯 SPIN NOW", callback_data="do_lucky_spin"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))

        if can_spin:
            spin_text = (
                "🎡 **LUCKY SPIN SYSTEM** 🎡\n\n"
                f"✨ Bonus Spins Available: **{bonus_spins}**\n"
                "✨ Spin the wheel to win free balance (₹1 to ₹5) or rewards!\n"
                "⏳ You are eligible to spin now."
            )
        else:
            spin_text = (
                "🎡 **LUCKY SPIN SYSTEM** 🎡\n\n"
                f"⏳ **Cooldown Active:** You can spin again in approx **{remaining_hours} hours** (24h rolling cycle)."
            )
        bot.edit_message_text(spin_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "do_lucky_spin":
        fresh_user = get_user(user_id)
        bonus_spins = fresh_user.get("bonus_spins", 0)
        last_spin = fresh_user.get("last_spin_time")
        
        can_spin = False
        if bonus_spins > 0:
            can_spin = True
            fresh_user["bonus_spins"] -= 1
        elif last_spin:
            try:
                last_time = datetime.strptime(last_spin, "%Y-%m-%d %H:%M:%S")
                if (datetime.now() - last_time).total_seconds() / 3600.0 >= 24.0:
                    can_spin = True
            except Exception:
                pass
        else:
            can_spin = True

        if not can_spin:
            bot.answer_callback_query(call.id, text="Cooldown active!", show_alert=True)
            return

        outcome_weights = [0, 0, 0, 0, 1, 1, 1, 1, 5]
        reward = random.choice(outcome_weights)
        
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fresh_user["last_spin_time"] = current_time_str
        
        if reward > 0:
            fresh_user["balance"] += float(reward)
            log_bot_transaction(user_id, "LUCKY_SPIN", float(reward), f"Won ₹{reward} from Lucky Spin")
            result_msg = f"🎉 **CONGRATULATIONS!** You won `₹{reward}` free wallet balance!"
        else:
            result_msg = "😢 **No Reward!** Better luck next time."

        save_user(fresh_user)
        bot.answer_callback_query(call.id, text=f"Spin Result: {reward if reward > 0 else 'No Win'}", show_alert=True)
        
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text(f"🎡 **LUCKY SPIN RESULT**\n\n{result_msg}\n\n💰 Balance: ₹{fresh_user['balance']:.2f}", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "support_ticket":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("💳 Payment Issue", callback_data="tkt_cat_Payment"))
        markup.add(telebot.types.InlineKeyboardButton("🔑 Key Not Delivered / Invalid", callback_data="tkt_cat_Key"))
        markup.add(telebot.types.InlineKeyboardButton("🎮 Game / Mod Issue", callback_data="tkt_cat_Game"))
        markup.add(telebot.types.InlineKeyboardButton("⚙️ Reseller Panel Issue", callback_data="tkt_cat_Reseller"))
        markup.add(telebot.types.InlineKeyboardButton("🎁 Referral / Commission Issue", callback_data="tkt_cat_Referral"))
        markup.add(telebot.types.InlineKeyboardButton("💬 Other Inquiry", callback_data="tkt_cat_Other"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text(
            "🎟️ **— SUPPORT TICKET SYSTEM —** 🎟️\n\nPlease select your problem category below:",
            call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup
        )

    elif call.data.startswith("tkt_cat_"):
        bot.answer_callback_query(call.id)
        category = call.data.split("_")[2]
        waiting_for_support_ticket[user_id] = category
        markup = telebot.types.InlineKeyboardMarkup().add(
            telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")
        )
        bot.edit_message_text(
            f"🎟️ **Selected Category:** `{category}`\n\n👇 **Please type and send your detailed message/proof below:**",
            call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup
        )

    elif call.data == "cancel_topup":
        bot.answer_callback_query(call.id, text="Order cancelled.")
        add_abandon(user_id)
        user_orders.pop(user_id, None)
        bot.edit_message_text("❌ **Order Cancelled.**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

    elif call.data == "profile":
        bot.answer_callback_query(call.id)
        fresh_user = get_user(user_id)
        role_display = "👑 Master Admin" if is_admin else f"👤 {user_role}"
        profile_text = (
            f"👤 **— YOUR PROFILE —** 👤\n\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"🔥 **Name:** {fresh_user['name']}\n"
            f"👑 **Account:** {role_display}\n\n"
            f"💰 **— Balance —** 💰\n"
            f"💳 **Current:** ₹{fresh_user['balance']:.2f}\n\n"
            f"📊 **— Statistics —** 📊\n"
            f"📦 **Orders:** {fresh_user['orders_count']}\n"
            f"💸 **Spent:** ₹{fresh_user['total_spent']:.2f}\n"
            f"👥 **Referrals:** {fresh_user.get('total_referrals', 0)}\n\n"
            f"📅 **Joined:** {fresh_user['joined']}"
        )
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text(profile_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "orders":
        bot.answer_callback_query(call.id)
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT duration, license_key, price, date FROM orders WHERE user_id = %s', (user_id,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
        except Exception:
            rows = []
        
        if not rows:
            history_text = "📦 You have no past orders."
        else:
            history_text = "🛍️ **— MY ORDERS —** 🛍️\n\n"
            for r in rows:
                history_text += f"🛒 **Product Key**\n⏳ {r[0]}\n🔑 `{r[1]}`\n💰 ₹{r[2]} | 📅 {r[3]}\n-------------------\n"
                
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text(history_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "referral":
        bot.answer_callback_query(call.id)
        bot_username = bot.get_me().username
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        ref_text = (
            f"🎁 **REFERRAL PROGRAM**\n\n"
            f"✅ **Status:** ACTIVE\n"
            f"💰 **Earn commission on purchases!**\n\n"
            f"🔗 **Your Referral Link:**\n`{ref_link}`"
        )
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text(ref_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "main_menu":
        bot.answer_callback_query(call.id)
        show_main_menu(call.message.chat.id, user_id)

    elif call.data == "admin_panel" and is_admin:
        bot.answer_callback_query(call.id)
        m_status = "🔴 OFF (Active)" if not STORE_UNDER_MAINTENANCE else "🟢 ON (Under Maintenance)"
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"🛠️ Toggle Maintenance: {m_status}", callback_data="adm_toggle_maintenance"))
        markup.add(telebot.types.InlineKeyboardButton("🎟️ View Support Tickets", callback_data="adm_view_tickets"))
        markup.add(telebot.types.InlineKeyboardButton("🏷️ Create Coupon Code", callback_data="adm_create_coupon"))
        markup.add(telebot.types.InlineKeyboardButton("📋 Users Started List", callback_data="adm_users_list_1"))
        markup.add(telebot.types.InlineKeyboardButton("📊 All Bot Transactions", callback_data="adm_all_transactions"))
        markup.add(telebot.types.InlineKeyboardButton("🔍 Check User Balance & Info", callback_data="adm_check_user"))
        markup.add(telebot.types.InlineKeyboardButton("💰 Add Balance to User", callback_data="adm_addbal_menu"))
        markup.add(telebot.types.InlineKeyboardButton("✂️ Cut Balance from User", callback_data="adm_cutbal_menu"))
        markup.add(telebot.types.InlineKeyboardButton("📢 Broadcast Announcement", callback_data="adm_broadcast"))
        markup.add(telebot.types.InlineKeyboardButton("🤝 Toggle Reseller Role", callback_data="adm_toggle_reseller"))
        markup.add(telebot.types.InlineKeyboardButton("🔨 Ban / Unban User", callback_data="adm_ban_menu"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text("👑 **MASTER ADMIN PANEL**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "adm_toggle_maintenance" and is_admin:
        STORE_UNDER_MAINTENANCE = not STORE_UNDER_MAINTENANCE
        bot.answer_callback_query(call.id, text=f"Maintenance mode is now {'ON' if STORE_UNDER_MAINTENANCE else 'OFF'}")
        
        m_status = "🔴 OFF (Active)" if not STORE_UNDER_MAINTENANCE else "🟢 ON (Under Maintenance)"
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"🛠️ Toggle Maintenance: {m_status}", callback_data="adm_toggle_maintenance"))
        markup.add(telebot.types.InlineKeyboardButton("🎟️ View Support Tickets", callback_data="adm_view_tickets"))
        markup.add(telebot.types.InlineKeyboardButton("🏷️ Create Coupon Code", callback_data="adm_create_coupon"))
        markup.add(telebot.types.InlineKeyboardButton("📋 Users Started List", callback_data="adm_users_list_1"))
        markup.add(telebot.types.InlineKeyboardButton("📊 All Bot Transactions", callback_data="adm_all_transactions"))
        markup.add(telebot.types.InlineKeyboardButton("🔍 Check User Balance & Info", callback_data="adm_check_user"))
        markup.add(telebot.types.InlineKeyboardButton("💰 Add Balance to User", callback_data="adm_addbal_menu"))
        markup.add(telebot.types.InlineKeyboardButton("✂️ Cut Balance from User", callback_data="adm_cutbal_menu"))
        markup.add(telebot.types.InlineKeyboardButton("📢 Broadcast Announcement", callback_data="adm_broadcast"))
        markup.add(telebot.types.InlineKeyboardButton("🤝 Toggle Reseller Role", callback_data="adm_toggle_reseller"))
        markup.add(telebot.types.InlineKeyboardButton("🔨 Ban / Unban User", callback_data="adm_ban_menu"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text("👑 **MASTER ADMIN PANEL**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "adm_view_tickets" and is_admin:
        bot.answer_callback_query(call.id)
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT id, user_id, category, message, status, date FROM support_tickets ORDER BY id DESC LIMIT 15')
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
        except Exception:
            rows = []

        if not rows:
            t_text = "🎟️ **SUPPORT TICKETS**\n\nNo active tickets found."
        else:
            t_text = "🎟️ **RECENT SUPPORT TICKETS (Last 15)**\n\n"
            for r in rows:
                t_text += f"🆔 Ticket #{r[0]} | User: `{r[1]}`\n📌 Cat: **{r[2]}** | Status: {r[4]} | 📅 {r[5]}\n💬 {r[3]}\n-------------------\n"
                
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel"))
        bot.edit_message_text(t_text[:4000], call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "adm_create_coupon" and is_admin:
        bot.answer_callback_query(call.id)
        admin_coupon_flow[user_id] = {"step": "code"}
        bot.send_message(
            call.message.chat.id,
            "🏷️ **STEP 1: CREATE COUPON**\n\nPlease reply with the **Coupon Code** name (e.g., `WELCOME50`):",
            parse_mode="Markdown"
        )

    elif call.data.startswith("adm_coupon_type_") and is_admin:
        bot.answer_callback_query(call.id)
        r_type = call.data.split("_")[3]
        if user_id in admin_coupon_flow:
            admin_coupon_flow[user_id]["type"] = r_type
            admin_coupon_flow[user_id]["step"] = "value"
            
            val_prompt = {
                "balance": "💳 Please reply with the **Amount in Rupees** (e.g., `100`):",
                "discount": "🏷️ Please reply with the **Discount Percentage** (e.g., `25` for 25% off):",
                "spin": "🎡 Please reply with the **Number of Bonus Spins** (e.g., `5`):"
            }
            bot.send_message(call.message.chat.id, val_prompt[r_type], parse_mode="Markdown")

    elif call.data.startswith("adm_users_list_") and is_admin:
        bot.answer_callback_query(call.id)
        try:
            page = int(call.data.split("_")[3])
        except Exception:
            page = 1
            
        per_page = 10
        offset = (page - 1) * per_page
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM users')
            total_users = cursor.fetchone()[0]
            
            cursor.execute('SELECT user_id, name, phone, role, joined FROM users ORDER BY joined DESC LIMIT %s OFFSET %s', (per_page, offset))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
        except Exception:
            rows = []
            total_users = 0

        max_pages = max(1, (total_users + per_page - 1) // per_page)
        
        text = f"📋 **— BOT USERS (Page {page}/{max_pages}) —** 📋\n\n"
        if not rows:
            text += "No users found."
        for r in rows:
            text += f"🆔 `{r[0]}` | {r[1]} | 📱 {r[2]} | Role: {r[3]} | 📅 {r[4]}\n\n"
            
        markup = telebot.types.InlineKeyboardMarkup()
        nav_buttons = []
        if page > 1:
            nav_buttons.append(telebot.types.InlineKeyboardButton("⬅️ Prev", callback_data=f"adm_users_list_{page-1}"))
        if page < max_pages:
            nav_buttons.append(telebot.types.InlineKeyboardButton("Next ➡️", callback_data=f"adm_users_list_{page+1}"))
        if nav_buttons:
            markup.row(*nav_buttons)
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel"))
        
        bot.edit_message_text(text[:4000], call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "adm_all_transactions" and is_admin:
        bot.answer_callback_query(call.id)
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, type, amount, details, date FROM bot_transactions ORDER BY id DESC LIMIT 30')
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
        except Exception:
            rows = []

        if not rows:
            tx_text = "📊 **GLOBAL BOT TRANSACTIONS**\n\nNo transactions recorded yet."
        else:
            tx_text = "📊 **GLOBAL BOT TRANSACTIONS (Last 30)**\n\n"
            for r in rows:
                tx_text += f"👤 User: `{r[0]}`\n📌 Type: **{r[1]}** | Amount: `₹{r[2]:.2f}`\n📝 Info: {r[3]}\n📅 {r[4]}\n-------------------\n"
                
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel"))
        bot.edit_message_text(tx_text[:4000], call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "adm_broadcast" and is_admin:
        bot.answer_callback_query(call.id)
        admin_actions[user_id] = "broadcast"
        bot.send_message(call.message.chat.id, "📢 **Send the announcement message you want to broadcast to all users:**", parse_mode="Markdown")

    elif call.data in ["adm_toggle_reseller", "adm_ban_menu", "adm_addbal_menu", "adm_cutbal_menu", "adm_check_user"] and is_admin:
        bot.answer_callback_query(call.id)
        actions = {
            "adm_toggle_reseller": "reseller", 
            "adm_ban_menu": "ban", 
            "adm_addbal_menu": "addbal",
            "adm_cutbal_menu": "cutbal",
            "adm_check_user": "checkuser"
        }
        admin_actions[user_id] = actions[call.data]
        if call.data == "adm_check_user":
            bot.send_message(call.message.chat.id, "💬 Send the target User ID to view balance and profile:")
        elif call.data == "adm_addbal_menu":
            bot.send_message(call.message.chat.id, "💬 Send target User ID and Amount to add. Example: `6444009163 100`")
        elif call.data == "adm_cutbal_menu":
            bot.send_message(call.message.chat.id, "💬 Send target User ID and Amount to cut. Example: `6444009163 50`")
        else:
            bot.send_message(call.message.chat.id, "💬 Send the target User ID:")

def execute_purchase(call, user_id, product_id, duration_text, price_inr, product_name):
    # Fetch live user data directly from DB
    user = get_user(user_id)
    if user and user["banned"]:
        return

    current_time_epoch = time.time()
    if user_id in last_purchase_time:
        if (current_time_epoch - last_purchase_time[user_id]) < 30:
            bot.send_message(
                call.message.chat.id,
                "⚠️ **SECURITY ALERT (ANTI-HACK SYSTEM)** ⚠️\n\n"
                "Rapid consecutive purchases are temporarily locked (30s cooldown).\n\n"
                "🎟️ Please submit a **Support Ticket** if you need assistance.",
                parse_mode="Markdown"
            )
            return

    fresh_user = get_user(user_id)
    if not fresh_user or fresh_user["balance"] < price_inr:
        current_bal = fresh_user["balance"] if fresh_user else 0.0
        bot.send_message(
            call.message.chat.id,
            f"❌ **Insufficient Balance!**\nRequired: ₹{price_inr} | Balance: ₹{current_bal:.2f}\n\nPlease add balance to your wallet.",
            parse_mode="Markdown",
            reply_markup=telebot.types.InlineKeyboardMarkup().add(
                telebot.types.InlineKeyboardButton("💳 Add Balance Now", callback_data="add_balance"),
                telebot.types.InlineKeyboardButton("🔙 Back to Shop", callback_data="all_products")
            )
        )
        return

    last_purchase_time[user_id] = current_time_epoch

    fresh_user["balance"] -= price_inr
    fresh_user["orders_count"] += 1
    fresh_user["total_spent"] += price_inr
    save_user(fresh_user)

    proc_msg = bot.send_message(call.message.chat.id, f"⏳ Contacting Reseller Server for {product_name}...")
    
    payload = {
        'api_key': XYZ_API_KEY,
        'action': 'buy',
        'product_id': product_id,
        'duration': duration_text
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'x-master-key': XYZ_MASTER_KEY
    }
    
    try:
        api_res = requests.post(XYZ_API_URL, data=payload, headers=headers, timeout=15)
        raw_response = api_res.text.strip()
        
        license_key = None
        try:
            res_json = api_res.json()
            license_key = res_json.get("key") or res_json.get("license") or res_json.get("message") or res_json.get("data")
        except Exception:
            if raw_response and "error" not in raw_response.lower() and "html" not in raw_response.lower():
                license_key = raw_response

        try:
            bot.delete_message(call.message.chat.id, proc_msg.message_id)
        except Exception:
            pass

        if license_key and "error" not in str(license_key).lower():
            log_bot_transaction(user_id, "PURCHASE", price_inr, f"Bought {product_name} ({duration_text})")

            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO orders (user_id, duration, license_key, price, date) VALUES (%s, %s, %s, %s, %s)',
                    (user_id, duration_text, str(license_key), price_inr, current_time)
                )
                conn.commit()
                cursor.close()
                conn.close()
            except Exception:
                pass
            
            bot.send_message(
                call.message.chat.id,
                f"🎉 **{product_name} Key Generated!**\n\n🔑 Key:\n`{license_key}`\n\n⏱️ Duration: {duration_text}\n💰 Cost: ₹{price_inr}\n💳 Remaining Balance: ₹{fresh_user['balance']:.2f}",
                parse_mode="Markdown"
            )
        else:
            fresh_user["balance"] += price_inr
            fresh_user["orders_count"] -= 1
            fresh_user["total_spent"] -= price_inr
            save_user(fresh_user)
            bot.send_message(call.message.chat.id, f"❌ **API Error / Purchase Failed (Balance Refunded)**\nServer response: `{raw_response[:300]}`", parse_mode="Markdown")
    except Exception as e:
        try:
            bot.delete_message(call.message.chat.id, proc_msg.message_id)
        except Exception:
            pass
        fresh_user["balance"] += price_inr
        fresh_user["orders_count"] -= 1
        fresh_user["total_spent"] -= price_inr
        save_user(fresh_user)
        bot.send_message(call.message.chat.id, f"⚠️ Connection Exception, balance refunded: {str(e)}")

def create_topup_order(message_obj, user_id, amount_inr):
    amount_paise = amount_inr * 100
    headers = {"Authorization": f"Bearer {FAMPAY_API_KEY}", "Content-Type": "application/json"}
    payload = {"amount": amount_paise, "redirect_url": "https://t.me/"}
    chat_id = message_obj.chat.id if hasattr(message_obj, 'chat') else message_obj
    
    try:
        response = requests.post(f"{FAMPAY_BASE_URL}/orders", json=payload, headers=headers)
        res_data = response.json()
        
        if "payment_link" in res_data:
            order_id = res_data["id"]
            pay_link = res_data["payment_link"]
            qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={requests.utils.quote(pay_link)}"
            expires_at = datetime.now() + timedelta(minutes=5)
            
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("❌ Cancel Order", callback_data="cancel_topup"))
            
            caption_text = (
                f"💳 **Top-Up Order:** ₹{amount_inr}\n"
                f"🆔 ID: `{order_id}`\n\n"
                f"⏱️ **Expires in:** 5 Minutes\n\n"
                f"🔗 **Payment Link:**\n`{pay_link}`\n\n"
                f"📲 **Scan the QR code or pay via UPI.**\n*(Balance will be added automatically upon payment confirmation!)*"
            )
            sent_msg = bot.send_photo(chat_id, qr_image_url, caption=caption_text, parse_mode="Markdown", reply_markup=markup)
            
            user_orders[user_id] = {
                "order_id": order_id, 
                "amount": amount_inr, 
                "expires_at": expires_at,
                "msg_id": sent_msg.message_id
            }

            def poll_payment_status(u_id, target_order_id, target_amount, msg_id):
                headers_verify = {"Authorization": f"Bearer {FAMPAY_API_KEY}"}
                for _ in range(150):
                    time.sleep(2)
                    if u_id not in user_orders or user_orders[u_id]["order_id"] != target_order_id:
                        break
                    
                    try:
                        verify = requests.get(f"{FAMPAY_BASE_URL}/verify/{target_order_id}", headers=headers_verify).json()
                        if verify.get("status") == "success":
                            active_order = user_orders.pop(u_id, None)
                            if not active_order:
                                break
                            
                            usr = get_user(u_id)
                            if usr:
                                usr["balance"] += target_amount
                                save_user(usr)
                                log_bot_transaction(u_id, "TOPUP", target_amount, f"FamPay Automatic UPI Topup ID: {target_order_id}")
                                
                                try:
                                    bot.delete_message(chat_id, msg_id)
                                except Exception:
                                    pass
                                
                                success_text = (
                                    "🎉 **PAYMENT SUCCESSFUL!** 🎉\n\n"
                                    f"💳 **Added to Wallet:** `₹{target_amount:.2f}`\n"
                                    f"💰 **New Total Balance:** `₹{usr['balance']:.2f}`\n\n"
                                    "✨ Thank you for topping up!"
                                )
                                bot.send_message(chat_id, success_text, parse_mode="Markdown")
                            break
                    except Exception:
                        pass
                
                if u_id in user_orders and user_orders[u_id]["order_id"] == target_order_id:
                    user_orders.pop(u_id, None)
                    try:
                        bot.delete_message(chat_id, msg_id)
                    except Exception:
                        pass
                    bot.send_message(chat_id, f"❌ **Your payment QR code for ₹{amount_inr} has expired.**", parse_mode="Markdown")

            threading.Thread(target=poll_payment_status, args=(user_id, order_id, amount_inr, sent_msg.message_id), daemon=True).start()
        else:
            bot.send_message(chat_id, f"❌ FamAPI Error Response: {res_data}")
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Gateway Error: {str(e)}")

@bot.message_handler(func=lambda message: message.from_user.id in waiting_for_custom_topup)
def handle_custom_topup(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if user and user["banned"]:
        return
        
    if user_id in waiting_for_custom_topup:
        waiting_for_custom_topup.pop(user_id, None)
        try:
            amount_inr = int(message.text.strip())
            if amount_inr < 10:
                bot.send_message(message.chat.id, "❌ Minimum top-up amount is ₹10.")
                return
            create_topup_order(message, user_id, amount_inr)
        except ValueError:
            bot.send_message(message.chat.id, "❌ Invalid amount. Please enter a number.")

@bot.message_handler(func=lambda message: message.from_user.id in waiting_for_support_ticket)
def handle_support_ticket_submission(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if user and user["banned"]:
        return

    if user_id in waiting_for_support_ticket:
        category = waiting_for_support_ticket.pop(user_id)
        ticket_msg = message.text.strip()
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO support_tickets (user_id, category, message, status, date) VALUES (%s, %s, %s, %s, %s)',
                (user_id, category, ticket_msg, 'Open', current_time)
            )
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error saving support ticket: {e}")
            
        bot.send_message(
            message.chat.id,
            "✅ **Ticket Submitted Successfully!**\n\nOur team has received your support request and will review it shortly.",
            parse_mode="Markdown"
        )
        
        try:
            bot.send_message(
                ADMIN_ID,
                f"🚨 **NEW SUPPORT TICKET**\n\n👤 User ID: `{user_id}`\n📌 Category: **{category}**\n💬 Message: {ticket_msg}\n📅 {current_time}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

@bot.message_handler(func=lambda message: message.from_user.id in waiting_for_coupon_code)
def handle_user_coupon_redemption(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if user and user["banned"]:
        return

    if user_id in waiting_for_coupon_code:
        waiting_for_coupon_code.pop(user_id, None)
        code = message.text.strip().upper()
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute('SELECT * FROM coupons WHERE code = %s', (code,))
            coupon = cursor.fetchone()
            
            if not coupon:
                bot.send_message(message.chat.id, "❌ **Invalid Coupon Code.**", parse_mode="Markdown")
                cursor.close()
                conn.close()
                return

            if coupon["expires_at"]:
                exp_date = datetime.strptime(coupon["expires_at"], "%Y-%m-%d %H:%M:%S")
                if datetime.now() > exp_date:
                    bot.send_message(message.chat.id, "❌ **This coupon has expired.**", parse_mode="Markdown")
                    cursor.close()
                    conn.close()
                    return

            if coupon["uses_count"] >= coupon["max_uses"]:
                bot.send_message(message.chat.id, "❌ **This coupon has reached its maximum global usage limit.**", parse_mode="Markdown")
                cursor.close()
                conn.close()
                return

            cursor.execute('SELECT used_count FROM coupon_redemptions WHERE user_id = %s AND code = %s', (user_id, code))
            redemption = cursor.fetchone()
            used_so_far = redemption["used_count"] if redemption else 0
            
            if used_so_far >= coupon["per_user_limit"]:
                bot.send_message(message.chat.id, "❌ **You have already used this coupon maximum allowed times.**", parse_mode="Markdown")
                cursor.close()
                conn.close()
                return

            reward_type = coupon["reward_type"]
            value = float(coupon["value"])
            
            if reward_type == "balance":
                user["balance"] += value
                save_user(user)
                log_bot_transaction(user_id, "COUPON_REDEEM", value, f"Redeemed coupon {code}")
                msg_response = f"🎉 **Coupon Redeemed Successfully!**\n\n💳 Added `₹{value:.2f}` to your wallet balance."
            elif reward_type == "spin":
                user["bonus_spins"] = user.get("bonus_spins", 0) + int(value)
                save_user(user)
                log_bot_transaction(user_id, "COUPON_SPIN", 0, f"Redeemed coupon {code} for {int(value)} spins")
                msg_response = f"🎉 **Coupon Redeemed Successfully!**\n\n🎡 Added `{int(value)}` bonus spins to your account."
            else:
                msg_response = f"🎉 **Coupon Validated!**\n\n🏷️ Coupon **{code}** grants `{value}% off` on your next order."

            cursor.execute('UPDATE coupons SET uses_count = uses_count + 1 WHERE code = %s', (code,))
            cursor.execute('''
                INSERT INTO coupon_redemptions (user_id, code, used_count) VALUES (%s, %s, 1)
                ON CONFLICT (user_id, code) DO UPDATE SET used_count = coupon_redemptions.used_count + 1
            ''', (user_id, code))
            conn.commit()
            cursor.close()
            conn.close()

            bot.send_message(message.chat.id, msg_response, parse_mode="Markdown")
        except Exception as e:
            bot.send_message(message.chat.id, f"⚠️ Error redeeming coupon: {e}")

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
        markup.add(telebot.types.InlineKeyboardButton("🏷️ Discount (%)", callback_data="adm_coupon_type_discount"))
        markup.add(telebot.types.InlineKeyboardButton("🎡 Lucky Spin", callback_data="adm_coupon_type_spin"))
        
        bot.send_message(message.chat.id, f"🏷️ **STEP 2: SELECT TYPE**\n\nCode: `{flow['code']}`\nChoose reward type below:", parse_mode="Markdown", reply_markup=markup)

    elif flow["step"] == "value":
        try:
            flow["value"] = float(text)
            flow["step"] = "max_users"
            bot.send_message(message.chat.id, "👥 **STEP 4: MAX USERS LIMIT**\n\nPlease reply with the **maximum total users** who can claim this coupon (e.g., `1` for single user):", parse_mode="Markdown")
        except ValueError:
            bot.send_message(message.chat.id, "❌ Invalid number. Please send a valid numeric value.")

    elif flow["step"] == "max_users":
        try:
            flow["max_users"] = int(text)
            flow["step"] = "hours"
            bot.send_message(message.chat.id, "⏳ **STEP 5: VALIDITY HOURS**\n\nPlease reply with the **active duration in hours** before it expires (e.g., `24`):", parse_mode="Markdown")
        except ValueError:
            bot.send_message(message.chat.id, "❌ Invalid integer. Please enter valid hours.")

    elif flow["step"] == "hours":
        try:
            hours = int(text)
            admin_coupon_flow.pop(admin_id, None)
            
            code = flow["code"]
            r_type = flow["type"]
            if r_type == "discount":
                r_type = "percent"
            val = flow["value"]
            max_uses = flow["max_users"]
            expires_at = (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO coupons (code, reward_type, value, max_uses, uses_count, per_user_limit, expires_at)
                VALUES (%s, %s, %s, %s, 0, 1, %s)
                ON CONFLICT (code) DO UPDATE SET reward_type = EXCLUDED.reward_type, value = EXCLUDED.value, max_uses = EXCLUDED.max_uses, expires_at = EXCLUDED.expires_at
            ''', (code, r_type, val, max_uses, expires_at))
            conn.commit()
            cursor.close()
            conn.close()

            bot.send_message(
                message.chat.id,
                f"✅ **COUPON CREATED SUCCESSFULLY!**\n\n"
                f"🏷️ Code: `{code}`\n"
                f"📌 Type: `{r_type}` (Value: {val})\n"
                f"👥 Max Total Users: {max_uses} (1 time per user)\n"
                f"⏳ Active Lifespan: {hours} Hours\n"
                f"📅 Expires At: {expires_at}",
                parse_mode="Markdown"
            )
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Error saving coupon: {e}")

@bot.message_handler(func=lambda message: message.from_user.id in admin_actions and message.from_user.id == ADMIN_ID)
def admin_input(message):
    admin_id = message.from_user.id
    action = admin_actions.pop(admin_id)
    text = message.text.strip()
    
    if action == "broadcast":
        status_msg = bot.send_message(message.chat.id, "⏳ Sending broadcast to all users...")
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT user_id FROM users')
            all_users = cursor.fetchall()
            cursor.close()
            conn.close()
        except Exception:
            all_users = []
        
        success_count, fail_count = 0, 0
        for u in all_users:
            try:
                bot.send_message(u[0], f"📢 **ANNOUNCEMENT**\n\n{text}", parse_mode="Markdown")
                success_count += 1
            except Exception:
                fail_count += 1
                
        bot.edit_message_text(f"✅ **Broadcast Completed!**\n\n📤 Sent: {success_count}\n❌ Failed: {fail_count}", message.chat.id, status_msg.message_id, parse_mode="Markdown")

    elif action == "reseller":
        try:
            target_id = int(text)
            target = get_user(target_id)
            if target:
                target["role"] = "Customer" if target["role"] == "Reseller" else "Reseller"
                save_user(target)
                bot.send_message(message.chat.id, f"✅ User `{target_id}` role is now **{target['role']}**", parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, "❌ User not found.")
        except Exception:
            bot.send_message(message.chat.id, "❌ Invalid ID.")
    elif action == "ban":
        try:
            target_id = int(text)
            target = get_user(target_id)
            if target:
                target["banned"] = not target["banned"]
                save_user(target)
                status = "Banned" if target["banned"] else "Unbanned"
                bot.send_message(message.chat.id, f"✅ User `{target_id}` status: **{status}** (All button interactions blocked)", parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, "❌ User not found.")
        except Exception:
            bot.send_message(message.chat.id, "❌ Invalid ID.")
    elif action == "checkuser":
        try:
            target_id = int(text)
            target = get_user(target_id)
            if target:
                info_text = (
                    f"👤 **USER INFO**\n\n"
                    f"🆔 ID: `{target['user_id']}`\n"
                    f"🔥 Name: {target['name']}\n"
                    f"📞 Phone: {target.get('phone', 'N/A')}\n"
                    f"👑 Role: {target['role']} | Banned: {target['banned']}\n"
                    f"💳 **Balance: ₹{target['balance']:.2f}**\n"
                    f"💸 Total Spent: ₹{target['total_spent']:.2f}\n"
                    f"📦 Orders: {target['orders_count']}\n"
                    f"📅 Joined: {target['joined']}"
                )
                bot.send_message(message.chat.id, info_text, parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, "❌ User not found in database.")
        except Exception:
            bot.send_message(message.chat.id, "❌ Invalid ID format.")
    elif action == "addbal":
        try:
            parts = text.split()
            target_id, amount = int(parts[0]), float(parts[1])
            target = get_user(target_id)
            if target:
                target["balance"] += amount
                save_user(target)
                log_bot_transaction(target_id, "ADMIN_ADD", amount, f"Admin added balance manually")
                bot.send_message(message.chat.id, f"✅ Added ₹{amount} to `{target_id}`. New Balance: ₹{target['balance']:.2f}", parse_mode="Markdown")
                try:
                    bot.send_message(target_id, f"💳 **ADMIN ADDED BALANCE**\n\nAdded: `₹{amount:.2f}`\nNew Balance: `₹{target['balance']:.2f}`", parse_mode="Markdown")
                except Exception:
                    pass
            else:
                bot.send_message(message.chat.id, "❌ User not found.")
        except Exception:
            bot.send_message(message.chat.id, "❌ Format error! Use: `USER_ID AMOUNT`", parse_mode="Markdown")
    elif action == "cutbal":
        try:
            parts = text.split()
            target_id, amount = int(parts[0]), float(parts[1])
            target = get_user(target_id)
            if target:
                target["balance"] = max(0.0, target["balance"] - amount)
                save_user(target)
                log_bot_transaction(target_id, "ADMIN_CUT", amount, f"Admin deducted balance manually")
                bot.send_message(message.chat.id, f"✅ Cut ₹{amount} from `{target_id}`. New Balance: ₹{target['balance']:.2f}", parse_mode="Markdown")
                try:
                    bot.send_message(target_id, f"💳 **ADMIN DEDUCTED BALANCE**\n\nDeducted: `₹{amount:.2f}`\nNew Balance: `₹{target['balance']:.2f}`", parse_mode="Markdown")
                except Exception:
                    pass
            else:
                bot.send_message(message.chat.id, "❌ User not found.")
        except Exception:
            bot.send_message(message.chat.id, "❌ Format error! Use: `USER_ID AMOUNT`", parse_mode="Markdown")

print("Ultimate Store Bot running live with Direct Supabase DB Queries (Zero Cache Risk)!")
bot.infinity_polling()
