import os
import telebot
import requests
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta

# --- CONFIGURATION ---
BOT_TOKEN = "8980753842:AAG05SklWh3TshUWiJio1_MTWo2Net-ijiE"
ADMIN_ID = 7997110885

# 1. FamAPI / FreePanel Configuration
FAMPAY_API_KEY = "FAM_LIVE_sk_hRGdY9XAmPu7wzRg9HXjwa8pHdPhKNGB"
FAMPAY_BASE_URL = "https://py.freepanel.in/api/v1"

# 2. Reseller Panel API Configuration
XYZ_API_URL = "https://adminpanels.shop/api/reseller_v1.php"
XYZ_API_KEY = "8dc220a22ee3ea0ba80340978c2f1248"
XYZ_MASTER_KEY = "a7f3e8b2c9d1f4a6b8c2d5e9f1a3b6c8"

# 3. Supabase Cloud Database Connection (Session Pooler)
SUPABASE_DB_URL = os.environ.get("DATABASE_URL")

bot = telebot.TeleBot(BOT_TOKEN)

# --- CLOUD DATABASE SETUP (Fast Connection) ---
def get_db_connection():
    return psycopg2.connect(SUPABASE_DB_URL, sslmode='require', connect_timeout=5)

def init_db():
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
            total_referrals INTEGER DEFAULT 0
        )
    ''')
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
        CREATE TABLE IF NOT EXISTS spam_tracker (
            user_id BIGINT PRIMARY KEY,
            abandon_count INTEGER DEFAULT 0,
            timeout_until TEXT
        )
    ''')
    conn.commit()
    cursor.close()
    conn.close()

init_db()

def get_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    try:
        cursor.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
        row = cursor.fetchone()
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
                "total_referrals": int(row["total_referrals"] or 0)
            }
    except Exception as e:
        print(f"Error fetching user: {e}")
    finally:
        cursor.close()
        conn.close()
    return None

def save_user(user_data):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO users (user_id, name, phone, joined, balance, total_spent, orders_count, role, banned, verified, total_referrals)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                name = EXCLUDED.name,
                phone = EXCLUDED.phone,
                balance = EXCLUDED.balance,
                total_spent = EXCLUDED.total_spent,
                orders_count = EXCLUDED.orders_count,
                role = EXCLUDED.role,
                banned = EXCLUDED.banned,
                verified = EXCLUDED.verified,
                total_referrals = EXCLUDED.total_referrals
        ''', (
            user_data["user_id"], user_data["name"], user_data.get("phone"), user_data["joined"],
            user_data["balance"], user_data["total_spent"], user_data["orders_count"],
            user_data["role"], int(user_data["banned"]), int(user_data["verified"]), user_data.get("total_referrals", 0)
        ))
        conn.commit()
    except Exception as e:
        print(f"Error saving user: {e}")
    finally:
        cursor.close()
        conn.close()

def check_timeout(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT timeout_until FROM spam_tracker WHERE user_id = %s', (user_id,))
        row = cursor.fetchone()
        if row and row[0]:
            timeout_time = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            if datetime.now() < timeout_time:
                return int((timeout_time - datetime.now()).total_seconds() / 60)
    except Exception:
        pass
    finally:
        cursor.close()
        conn.close()
    return 0

def add_abandon(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
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
    except Exception:
        pass
    finally:
        cursor.close()
        conn.close()

user_orders = {}
waiting_for_custom_topup = {}
admin_actions = {}

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    
    if check_timeout(user_id) > 0:
        bot.send_message(message.chat.id, "⏳ You are temporarily timed out for canceling payment orders too many times.", parse_mode="Markdown")
        return

    user = get_user(user_id)
    if user and user["banned"]:
        bot.send_message(message.chat.id, "❌ Your account has been suspended.")
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
                "verified": False, "total_referrals": 0
            })
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(telebot.types.KeyboardButton("🛡️ Share Contact for Identity Check", request_contact=True))
        bot.send_message(
            message.chat.id,
            "🔐 **IDENTITY CHECK NEEDED**\n\nBefore exploring our store, please verify your contact:",
            parse_mode="Markdown", reply_markup=markup
        )
        return

    show_main_menu(message.chat.id, user_id)

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    user_id = message.from_user.id
    if message.contact:
        user = get_user(user_id)
        if user:
            user["verified"] = True
            user["phone"] = message.contact.phone_number
            save_user(user)
        else:
            save_user({
                "user_id": user_id, "name": message.from_user.first_name, "phone": message.contact.phone_number,
                "joined": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "balance": 0.0,
                "total_spent": 0.0, "orders_count": 0, "role": "Customer", "banned": False,
                "verified": True, "total_referrals": 0
            })
        bot.send_message(message.chat.id, "✅ **Verification Successful!**", reply_markup=telebot.types.ReplyKeyboardRemove(), parse_mode="Markdown")
        show_main_menu(message.chat.id, user_id)

def show_main_menu(chat_id, user_id):
    user = get_user(user_id)
    is_admin = (user_id == ADMIN_ID)
    user_role = user.get("role", "Customer") if user else "Customer"
    
    welcome_text = (
        "👋 Welcome to Candid Store!\n\n"
        "🌟 — STORE HIGHLIGHTS — 🌟\n"
        "🔑 Bala Mod Configs (Instant Key Delivery)\n"
        "🔒 Secure Automated Checkout"
    )
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("📦 All Products", callback_data="all_products"))
    markup.add(telebot.types.InlineKeyboardButton("💳 Add Balance", callback_data="add_balance"),
               telebot.types.InlineKeyboardButton("📦 My Orders", callback_data="orders"))
    markup.add(telebot.types.InlineKeyboardButton("🎁 Referral", callback_data="referral"),
               telebot.types.InlineKeyboardButton("👑 Profile", callback_data="profile"))
    
    if is_admin or user_role == "Reseller":
        welcome_text += f"\n\n⚙️ [{user_role} Dashboard Unlocked]"
    if is_admin:
        markup.add(telebot.types.InlineKeyboardButton("⚡ Master Admin Panel", callback_data="admin_panel"))
        
    bot.send_message(chat_id, welcome_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    is_admin = (user_id == ADMIN_ID)
    user_role = user.get("role", "Customer") if user else "Customer"
    
    if call.data in ["all_products", "add_balance", "profile", "orders", "referral", "main_menu", "admin_panel"]:
        if user_id in waiting_for_custom_topup:
            del waiting_for_custom_topup[user_id]
        if user_id in admin_actions:
            del admin_actions[user_id]

    if call.data == "all_products":
        bot.answer_callback_query(call.id)
        catalog_text = (
            "🛍️ — **STORE CATALOG** — 🛍️\n\n"
            "Select a product below to view plans and pricing:"
        )
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("🎮 Bala Mod Config FF Nonroot (ID: 142)", callback_data="buy_config"))
        markup.add(telebot.types.InlineKeyboardButton("⚡ Bala Mod XYZ ~ V2 FF Nonroot (ID: 136)", callback_data="buy_v2"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text(catalog_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_config":
        bot.answer_callback_query(call.id)
        is_reseller = (user_role == "Reseller" or is_admin)
        
        p1 = 15 if is_reseller else 20
        p3 = 40 if is_reseller else 50
        p6 = 60 if is_reseller else 75
        p12 = 100 if is_reseller else 120
        p24 = 140 if is_reseller else 170
        
        card_text = (
            "━━━━━━━━━━━━━━━━━━\n"
            "🏷️ **BALA MOD CONFIG FF NONROOT**\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Choose a plan 👇"
        )
        
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"1 Hours — ₹{p1}", callback_data="cfg_1h"))
        markup.add(telebot.types.InlineKeyboardButton(f"3 Hours — ₹{p3}", callback_data="cfg_3h"))
        markup.add(telebot.types.InlineKeyboardButton(f"6 Hours — ₹{p6}", callback_data="cfg_6h"))
        markup.add(telebot.types.InlineKeyboardButton(f"12 Hours — ₹{p12}", callback_data="cfg_12h"))
        markup.add(telebot.types.InlineKeyboardButton(f"24 Hours — ₹{p24}", callback_data="cfg_24h"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        
        bot.edit_message_text(card_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "buy_v2":
        bot.answer_callback_query(call.id)
        is_reseller = (user_role == "Reseller" or is_admin)
        
        v2_1h = 20 if is_reseller else 30
        v2_3h = 50 if is_reseller else 70
        v2_6h = 80 if is_reseller else 100
        v2_12h = 130 if is_reseller else 160
        v2_1d = 200 if is_reseller else 250
        v2_2d = 380 if is_reseller else 450
        v2_3d = 550 if is_reseller else 650
        v2_5d = 850 if is_reseller else 1000
        v2_7d = 1100 if is_reseller else 1300
        
        card_text = (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚡ **BALA MOD XYZ ~ V2 FF NONROOT**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Choose a plan 👇"
        )
        
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"1 Hours — ₹{v2_1h}", callback_data="v2_1h"))
        markup.add(telebot.types.InlineKeyboardButton(f"3 Hours — ₹{v2_3h}", callback_data="v2_3h"))
        markup.add(telebot.types.InlineKeyboardButton(f"6 Hours — ₹{v2_6h}", callback_data="v2_6h"))
        markup.add(telebot.types.InlineKeyboardButton(f"12 Hours — ₹{v2_12h}", callback_data="v2_12h"))
        markup.add(telebot.types.InlineKeyboardButton(f"1 DayS — ₹{v2_1d}", callback_data="v2_1d"))
        markup.add(telebot.types.InlineKeyboardButton(f"2 DayS — ₹{v2_2d}", callback_data="v2_2d"))
        markup.add(telebot.types.InlineKeyboardButton(f"3 DayS — ₹{v2_3d}", callback_data="v2_3d"))
        markup.add(telebot.types.InlineKeyboardButton(f"5 DayS — ₹{v2_5d}", callback_data="v2_5d"))
        markup.add(telebot.types.InlineKeyboardButton(f"7 DayS — ₹{v2_7d}", callback_data="v2_7d"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="all_products"))
        
        bot.edit_message_text(card_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data.startswith("cfg_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        is_reseller = (user_role == "Reseller" or is_admin)
        
        cfg_map = {
            "cfg_1h": ("1 Hours", 15 if is_reseller else 20),
            "cfg_3h": ("3 Hours", 40 if is_reseller else 50),
            "cfg_6h": ("6 Hours", 60 if is_reseller else 75),
            "cfg_12h": ("12 Hours", 100 if is_reseller else 120),
            "cfg_24h": ("24 Hours", 140 if is_reseller else 170)
        }
        duration_text, price_inr = cfg_map[call.data]
        execute_purchase(call, user_id, user, product_id="142", duration_text=duration_text, price_inr=price_inr, product_name="Bala Mod Config")

    elif call.data.startswith("v2_"):
        bot.answer_callback_query(call.id, text="Processing order...")
        is_reseller = (user_role == "Reseller" or is_admin)
        
        v2_map = {
            "v2_1h": ("1 Hours", 20 if is_reseller else 30),
            "v2_3h": ("3 Hours", 50 if is_reseller else 70),
            "v2_6h": ("6 Hours", 80 if is_reseller else 100),
            "v2_12h": ("12 Hours", 130 if is_reseller else 160),
            "v2_1d": ("1 DayS", 200 if is_reseller else 250),
            "v2_2d": ("2 DayS", 380 if is_reseller else 450),
            "v2_3d": ("3 DayS", 550 if is_reseller else 650),
            "v2_5d": ("5 DayS", 850 if is_reseller else 1000),
            "v2_7d": ("7 DayS", 1100 if is_reseller else 1300)
        }
        duration_text, price_inr = v2_map[call.data]
        execute_purchase(call, user_id, user, product_id="136", duration_text=duration_text, price_inr=price_inr, product_name="Bala Mod V2")

    elif call.data == "add_balance":
        bot.answer_callback_query(call.id)
        waiting_for_custom_topup[user_id] = True
        markup = telebot.types.InlineKeyboardMarkup().add(
            telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")
        )
        bot.edit_message_text("💳 **Add Balance**\n\nPlease reply with the amount in Rupees you want to add (e.g. `100`):", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "cancel_topup":
        bot.answer_callback_query(call.id, text="Order cancelled.")
        add_abandon(user_id)
        if user_id in user_orders:
            del user_orders[user_id]
        bot.edit_message_text("❌ **Order Cancelled.**", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

    elif call.data == "check_topup":
        bot.answer_callback_query(call.id, text="Verifying payment...")
        if user_id not in user_orders:
            bot.send_message(call.message.chat.id, "❌ No active top-up session.")
            return
            
        order_id = user_orders[user_id]["order_id"]
        amount_inr = user_orders[user_id]["amount"]
        headers = {"Authorization": f"Bearer {FAMPAY_API_KEY}"}
        
        try:
            verify = requests.get(f"{FAMPAY_BASE_URL}/verify/{order_id}", headers=headers).json()
            if verify.get("status") == "success":
                user["balance"] += amount_inr
                save_user(user)
                del user_orders[user_id]
                bot.send_message(call.message.chat.id, f"✅ ₹{amount_inr} successfully added to your wallet!\n💳 New Balance: ₹{user['balance']:.2f}")
            else:
                bot.send_message(call.message.chat.id, "⏳ Payment is still pending...")
        except Exception:
            bot.send_message(call.message.chat.id, "⚠️ Verification check failed.")

    elif call.data == "profile":
        bot.answer_callback_query(call.id)
        role_display = "👑 Master Admin" if is_admin else user_role
        profile_text = (
            f"👤 — **YOUR PROFILE** — 👤\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"📛 Name: {user['name']}\n"
            f"👑 Account: {role_display}\n"
            f"💳 Balance: ₹{user['balance']:.2f}\n"
            f"📦 Orders: {user['orders_count']}\n"
            f"💸 Spent: ₹{user['total_spent']:.2f}\n"
            f"📅 Joined: {user['joined']}"
        )
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text(profile_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "orders":
        bot.answer_callback_query(call.id)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT duration, license_key, price, date FROM orders WHERE user_id = %s', (user_id,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not rows:
            history_text = "📦 You have no past orders."
        else:
            history_text = "🛍️ — **MY ORDERS** — 🛍️\n\n"
            for r in rows:
                history_text += f"🛒 **Mod Config Key**\n⏳ {r[0]}\n🔑 `{r[1]}`\n💰 ₹{r[2]} | 📅 {r[3]}\n-------------------\n"
                
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text(history_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "referral":
        bot.answer_callback_query(call.id)
        bot_username = bot.get_me().username
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        ref_text = (
            f"🎁 **REFERRAL PROGRAM**\n\n"
            f"✅ **Status:** ACTIVE\n"
            f"💰 Earn commission on purchases!\n\n"
            f"👥 Total Referrals: {user.get('total_referrals', 0)}\n"
            f"💳 Available Balance: ₹{user['balance']:.2f}\n\n"
            f"🔗 **Your Referral Link:**\n`{ref_link}`"
        )
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text(ref_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "main_menu":
        bot.answer_callback_query(call.id)
        user_role = user.get("role", "Customer") if user else "Customer"
        welcome_text = (
            "👋 Welcome to Candid Store!\n\n"
            "🌟 — STORE HIGHLIGHTS — 🌟\n"
            "🔑 Bala Mod Configs (Instant Key Delivery)\n"
            "🔒 Secure Automated Checkout"
        )
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("📦 All Products", callback_data="all_products"))
        markup.add(telebot.types.InlineKeyboardButton("💳 Add Balance", callback_data="add_balance"),
                   telebot.types.InlineKeyboardButton("📦 My Orders", callback_data="orders"))
        markup.add(telebot.types.InlineKeyboardButton("🎁 Referral", callback_data="referral"),
                   telebot.types.InlineKeyboardButton("👑 Profile", callback_data="profile"))
        
        if is_admin or user_role == "Reseller":
            welcome_text += f"\n\n⚙️ [{user_role} Dashboard Unlocked]"
        if is_admin:
            markup.add(telebot.types.InlineKeyboardButton("⚡ Master Admin Panel", callback_data="admin_panel"))
            
        bot.edit_message_text(welcome_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "admin_panel" and is_admin:
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("📋 Users Started List", callback_data="adm_users_list"))
        markup.add(telebot.types.InlineKeyboardButton("🤝 Toggle Reseller Role", callback_data="adm_toggle_reseller"))
        markup.add(telebot.types.InlineKeyboardButton("🔨 Ban / Unban User", callback_data="adm_ban_menu"))
        markup.add(telebot.types.InlineKeyboardButton("💰 Add Balance to User", callback_data="adm_addbal_menu"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.edit_message_text("👑 **MASTER ADMIN PANEL**", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

    elif call.data == "adm_users_list" and is_admin:
        bot.answer_callback_query(call.id)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, name, phone, role, joined FROM users')
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        
        text = "📋 — **BOT USERS** — 📋\n\n"
        for r in rows:
            text += f"🆔 `{r[0]}` | {r[1]} | 📱 {r[2]} | Role: {r[3]} | 📅 {r[4]}\n\n"
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel"))
        bot.edit_message_text(text[:4000], call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data in ["adm_toggle_reseller", "adm_ban_menu", "adm_addbal_menu"] and is_admin:
        bot.answer_callback_query(call.id)
        actions = {"adm_toggle_reseller": "reseller", "adm_ban_menu": "ban", "adm_addbal_menu": "addbal"}
        admin_actions[user_id] = actions[call.data]
        bot.send_message(call.message.chat.id, "💬 Send the target User ID (and Amount if adding balance):")

def execute_purchase(call, user_id, user, product_id, duration_text, price_inr, product_name):
    balance = user["balance"]
    if balance >= price_inr:
        proc_msg = bot.send_message(call.message.chat.id, f"⏳ Contacting Reseller Server for {product_name}...")
        
        user["balance"] -= price_inr
        user["orders_count"] += 1
        user["total_spent"] += price_inr
        save_user(user)
        
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
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO orders (user_id, duration, license_key, price, date) VALUES (%s, %s, %s, %s, %s)',
                    (user_id, duration_text, str(license_key), price_inr, current_time)
                )
                conn.commit()
                cursor.close()
                conn.close()
                
                bot.send_message(
                    call.message.chat.id,
                    f"🎉 **{product_name} Key Generated!**\n\n🔑 Key:\n`{license_key}`\n\n⏱️ Duration: {duration_text}\n💰 Cost: ₹{price_inr}\n💳 Remaining Balance: ₹{user['balance']:.2f}",
                    parse_mode="Markdown"
                )
            else:
                user["balance"] += price_inr
                user["orders_count"] -= 1
                user["total_spent"] -= price_inr
                save_user(user)
                bot.send_message(call.message.chat.id, f"❌ **API Error / Refunded**\nServer response: `{raw_response[:300]}`", parse_mode="Markdown")
        except Exception as e:
            try:
                bot.delete_message(call.message.chat.id, proc_msg.message_id)
            except Exception:
                pass
            user["balance"] += price_inr
            user["orders_count"] -= 1
            user["total_spent"] -= price_inr
            save_user(user)
            bot.send_message(call.message.chat.id, f"⚠️ Connection Exception, balance refunded: {str(e)}")
    else:
        bot.send_message(
            call.message.chat.id,
            f"❌ **Insufficient Balance!**\nRequired: ₹{price_inr} | Balance: ₹{balance:.2f}\n\nPlease add balance to your wallet.",
            parse_mode="Markdown",
            reply_markup=telebot.types.InlineKeyboardMarkup().add(
                telebot.types.InlineKeyboardButton("💳 Add Balance Now", callback_data="add_balance"),
                telebot.types.InlineKeyboardButton("🔙 Back to Shop", callback_data="all_products")
            )
        )

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
            
            user_orders[user_id] = {"order_id": order_id, "amount": amount_inr}
            
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("✅ I Have Paid", callback_data="check_topup"))
            markup.add(telebot.types.InlineKeyboardButton("❌ Cancel Order", callback_data="cancel_topup"))
            
            caption_text = (
                f"💳 **Top-Up Order:** ₹{amount_inr}\n"
                f"🆔 ID: `{order_id}`\n\n"
                f"🔗 **Payment Link:**\n`{pay_link}`\n\n"
                f"Scan the QR code above or copy the payment link into your UPI app, then click **I Have Paid**."
            )
            
            bot.send_photo(chat_id, qr_image_url, caption=caption_text, parse_mode="Markdown", reply_markup=markup)
        else:
            bot.send_message(chat_id, f"❌ FamAPI Error Response: {res_data}")
    except Exception as e:
        bot.send_message(chat_id, f"⚠️ Gateway Error: {str(e)}")

@bot.message_handler(func=lambda message: message.from_user.id in waiting_for_custom_topup)
def handle_custom_topup(message):
    user_id = message.from_user.id
    if user_id in waiting_for_custom_topup:
        del waiting_for_custom_topup[user_id]
        try:
            amount_inr = int(message.text.strip())
            if amount_inr < 10:
                bot.send_message(message.chat.id, "❌ Minimum top-up amount is ₹10.")
                return
            create_topup_order(message, user_id, amount_inr)
        except ValueError:
            bot.send_message(message.chat.id, "❌ Invalid amount. Please enter a number.")

@bot.message_handler(func=lambda message: message.from_user.id in admin_actions and message.from_user.id == ADMIN_ID)
def admin_input(message):
    admin_id = message.from_user.id
    action = admin_actions.pop(admin_id)
    text = message.text.strip()
    
    if action == "reseller":
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
                bot.send_message(message.chat.id, f"✅ User `{target_id}` status: **{status}**", parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, "❌ User not found.")
        except Exception:
            bot.send_message(message.chat.id, "❌ Invalid ID.")
    elif action == "addbal":
        try:
            parts = text.split()
            target_id, amount = int(parts[0]), float(parts[1])
            target = get_user(target_id)
            if target:
                target["balance"] += amount
                save_user(target)
                bot.send_message(message.chat.id, f"✅ Added ₹{amount} to `{target_id}`. New Balance: ₹{target['balance']:.2f}", parse_mode="Markdown")
            else:
                bot.send_message(message.chat.id, "❌ User not found.")
        except Exception:
            bot.send_message(message.chat.id, "❌ Format error! Use: `USER_ID AMOUNT`", parse_mode="Markdown")

print("Candid Store Bot is running lightning-fast with Supabase pooler!")
bot.infinity_polling()
