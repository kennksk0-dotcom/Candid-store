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
import uuid

# ==============================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ==============================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8980753842:AAG05SklWh3TshUWiJio1_MTWo2Net-ijiE"
ADMIN_ID = int(os.environ.get("ADMIN_ID") or 7997110885)

# Supabase PostgreSQL Pool URL
SUPABASE_DB_URL = os.environ.get("DATABASE_URL")

# FamPay UPI Gateway
FAMPAY_API_KEY = os.environ.get("FAMPAY_API_KEY") or "FAM_LIVE_sk_hRGdY9XAmPu7wzRg9HXjwa8pHdPhKNGB"
FAMPAY_BASE_URL = "https://py.freepanel.in/api/v1"

# Cuppon'sHub Reseller API Config
CUPPON_BASE_URL = "https://cupponhub.shop/reseller/api/"
CUPPON_API_KEY = os.environ.get("CUPPON_API_KEY") or "ch_live_K4i-1AIpG9u-tGzIHhl8uUlIQx7aL9UGdqfqzrkJs0"

# Currency Conversion & Markup (Wholesale USDT -> Selling INR)
USDT_TO_INR_RATE = float(os.environ.get("USDT_TO_INR_RATE", "92.0"))  # Base USDT to INR conversion
PROFIT_MARGIN = float(os.environ.get("PROFIT_MARGIN", "1.25"))        # 25% profit margin multiplier

# Optional fallback fixed INR pricing for specific products (Product Key: Price in ₹)
FIXED_INR_PRICING = {
    "gemini_link": 49.0,
}

STORE_UNDER_MAINTENANCE = False

# ==============================================================================
# BOT & DATABASE POOL INITIALIZATION
# ==============================================================================
bot = telebot.TeleBot(BOT_TOKEN, num_threads=20, threaded=True)

db_pool = None
if SUPABASE_DB_URL:
    try:
        db_pool = pool.ThreadedConnectionPool(2, 25, SUPABASE_DB_URL, sslmode='require', connect_timeout=10)
        print("Supabase connection pool successfully initialized.")
    except Exception as e:
        print(f"Supabase pool initialization error: {e}")
else:
    print("Warning: DATABASE_URL environment variable is missing!")

def get_db_connection():
    if db_pool:
        try:
            return db_pool.getconn()
        except Exception as e:
            print(f"Error fetching connection from pool: {e}")
    return None

def release_db_connection(conn, close=False):
    if db_pool and conn:
        try:
            db_pool.putconn(conn, close=close)
        except Exception:
            pass

# In-Memory State Trackers
admin_actions = {}
admin_coupon_flow = {}
user_orders = {}
waiting_for_custom_topup = {}
waiting_for_support_ticket = {}
waiting_for_coupon_code = {}

# Safe edit message helper to avoid Telegram 'message not modified' exceptions
def safe_edit_message_text(text, chat_id, message_id, **kwargs):
    try:
        return bot.edit_message_text(text, chat_id, message_id, **kwargs)
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" in str(e).lower():
            return None
        raise e

# ==============================================================================
# DATABASE SCHEMA SETUP
# ==============================================================================
def init_db():
    conn = get_db_connection()
    if not conn:
        print("Database not reachable during init_db, skipping.")
        return
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
                product_name TEXT,
                delivered_item TEXT,
                price REAL,
                reseller_order_id TEXT,
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
        conn.commit()
        cur.close()
        print("Supabase schema verified successfully.")
    except Exception as e:
        print(f"DB Init Error: {e}")
    finally:
        release_db_connection(conn)

init_db()

# ==============================================================================
# DATABASE TRANSACTION HELPERS
# ==============================================================================
def log_bot_transaction(user_id, tx_type, amount, details):
    conn = get_db_connection()
    if not conn:
        return
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
    if not conn:
        return None
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
    if not conn:
        return
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
    if not conn:
        return False
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

# ==============================================================================
# CUPPON'SHUB RESELLER API CLIENT
# ==============================================================================
def cuppon_headers(idempotency_key=None):
    headers = {
        "X-API-Key": CUPPON_API_KEY,
        "User-Agent": "CandidStore-TelegramBot/2.0"
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
        headers["Content-Type"] = "application/json"
    return headers

def cuppon_get_balance():
    try:
        r = requests.get(f"{CUPPON_BASE_URL}?action=balance", headers=cuppon_headers(), timeout=10)
        data = r.json()
        if data.get("ok"):
            return float(data.get("balance_usdt", 0.0))
    except Exception as e:
        print(f"Cuppon balance fetch error: {e}")
    return None

def cuppon_get_products():
    try:
        r = requests.get(f"{CUPPON_BASE_URL}?action=products", headers=cuppon_headers(), timeout=10)
        data = r.json()
        if data.get("ok"):
            return data.get("products", [])
    except Exception as e:
        print(f"Cuppon products fetch error: {e}")
    return []

def cuppon_purchase_product(product_key, quantity=1):
    idempotency = f"tg-order-{uuid.uuid4().hex[:14]}"
    payload = {
        "product": product_key,
        "quantity": int(quantity)
    }
    try:
        r = requests.post(
            f"{CUPPON_BASE_URL}?action=purchase",
            headers=cuppon_headers(idempotency_key=idempotency),
            json=payload,
            timeout=25
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def calculate_inr_price(product_key, wholesale_usdt_str):
    if product_key in FIXED_INR_PRICING:
        return FIXED_INR_PRICING[product_key]
    try:
        usdt_val = float(wholesale_usdt_str)
        price_inr = round(usdt_val * USDT_TO_INR_RATE * PROFIT_MARGIN, 0)
        return max(price_inr, 10.0)
    except Exception:
        return 49.0

# ==============================================================================
# BOT COMMAND HANDLERS
# ==============================================================================
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if user and user["banned"]:
        bot.send_message(message.chat.id, "❌ **Access Denied:** Your account has been suspended.", parse_mode="Markdown")
        return

    # Handle Referral System
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1].split("_")[1])
            if referrer_id != user_id and not user:
                conn = get_db_connection()
                if conn:
                    try:
                        cur = conn.cursor()
                        cur.execute('UPDATE users SET total_referrals = total_referrals + 1, bonus_spins = bonus_spins + 1 WHERE user_id = %s', (referrer_id,))
                        conn.commit()
                        cur.close()
                    finally:
                        release_db_connection(conn)
        except Exception:
            pass

    # First time registration check
    if not user:
        save_user_profile(user_id, message.from_user.first_name, None, verified=True)

    show_main_menu(message.chat.id, user_id)

def show_main_menu(chat_id, user_id):
    user = get_user(user_id)
    if user and user["banned"]:
        return

    is_admin = (user_id == ADMIN_ID)
    user_role = user.get("role", "Customer") if user else "Customer"
    user_bal = user["balance"] if user else 0.0

    welcome_text = (
        "⚡ **AI SUBSCRIPTION ACTIVATION STORE** ⚡\n\n"
        "Get instant, genuine activation links for premium AI platforms (Google Gemini Advanced, ChatGPT Plus, Claude & more).\n\n"
        f"💳 **Your Wallet:** `₹{user_bal:.2f}`\n"
        f"👤 **Account Tier:** `{user_role}`\n\n"
        "✨ **Perks:**\n"
        "• ⚡ Instant delivery direct to chat\n"
        "• 🛡️ 100% replacement warranty on unactivated links\n"
        "• 💸 Instant UPI top-ups via QR\n\n"
        "👇 **Choose an option below to get started:**"
    )

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🚀 BROWSE AI ACTIVATION LINKS", callback_data="ai_catalog"))
    markup.add(
        telebot.types.InlineKeyboardButton("💳 Add Wallet Funds", callback_data="add_balance"),
        telebot.types.InlineKeyboardButton("📦 My Orders", callback_data="orders")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("🎡 Lucky Spin", callback_data="lucky_spin"),
        telebot.types.InlineKeyboardButton("🎁 Refer Friends", callback_data="referral")
    )
    markup.add(
        telebot.types.InlineKeyboardButton("🏷️ Redeem Coupon", callback_data="redeem_coupon"),
        telebot.types.InlineKeyboardButton("🎟️ Support Ticket", callback_data="support_ticket")
    )
    markup.add(telebot.types.InlineKeyboardButton("👤 Full Account Dashboard", callback_data="profile"))

    if is_admin:
        markup.add(telebot.types.InlineKeyboardButton("👑 Master Admin Panel", callback_data="admin_panel"))

    bot.send_message(chat_id, welcome_text, reply_markup=markup, parse_mode="Markdown")

# ==============================================================================
# CALLBACK QUERY DISPATCHER
# ==============================================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    if call.data not in ["do_lucky_spin"]:
        try:
            bot.answer_callback_query(call.id)
        except Exception:
            pass

    user_id = call.from_user.id
    user = get_user(user_id)
    if user and user["banned"]:
        try:
            bot.answer_callback_query(call.id, text="❌ Access Denied: Suspended.", show_alert=True)
        except Exception:
            pass
        return

    is_admin = (user_id == ADMIN_ID)
    global STORE_UNDER_MAINTENANCE

    admin_bypass = ["admin_panel", "adm_toggle_maintenance", "main_menu", "profile", "orders", "add_balance"]
    if STORE_UNDER_MAINTENANCE and not is_admin and call.data not in admin_bypass:
        bot.send_message(call.message.chat.id, "🛠️ **STORE UNDER MAINTENANCE**\n\nUpgrading inventory servers. Check back shortly!", parse_mode="Markdown")
        return

    # Clear lingering text reply states
    if call.data in ["ai_catalog", "add_balance", "profile", "orders", "referral", "support_ticket", "main_menu", "admin_panel"]:
        waiting_for_custom_topup.pop(user_id, None)
        waiting_for_support_ticket.pop(user_id, None)
        waiting_for_coupon_code.pop(user_id, None)
        admin_actions.pop(user_id, None)
        admin_coupon_flow.pop(user_id, None)

    # Navigation Router
    if call.data == "main_menu":
        show_main_menu(call.message.chat.id, user_id)

    # 1. CATALOG FLOW
    elif call.data == "ai_catalog":
        products = cuppon_get_products()
        if not products:
            markup = telebot.types.InlineKeyboardMarkup().add(
                telebot.types.InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu")
            )
            safe_edit_message_text("⚠️ Catalog is updating. Please try again in a few moments.", call.message.chat.id, call.message.message_id, reply_markup=markup)
            return

        markup = telebot.types.InlineKeyboardMarkup()
        for p in products:
            pkey = p.get("key")
            pname = p.get("name", "AI Product")
            stock = p.get("stock", 0)
            usdt_price = p.get("price_usdt_from", "0.0")
            price_inr = calculate_inr_price(pkey, usdt_price)

            status_icon = "🟢" if stock > 0 else "🔴"
            btn_text = f"{status_icon} {pname} — ₹{int(price_inr)} ({stock} in stock)"
            markup.add(telebot.types.InlineKeyboardButton(btn_text, callback_data=f"view_prod_{pkey}"))

        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu"))
        safe_edit_message_text(
            "🚀 **AVAILABLE AI ACTIVATION LINKS**\n\n"
            "Select an AI subscription below to view details and activate:",
            call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup
        )

    elif call.data.startswith("view_prod_"):
        pkey = call.data.replace("view_prod_", "")
        products = cuppon_get_products()
        prod = next((p for p in products if p.get("key") == pkey), None)

        if not prod:
            bot.send_message(call.message.chat.id, "❌ Product not found or out of stock.")
            return

        pname = prod.get("name", "AI Link")
        stock = prod.get("stock", 0)
        usdt_price = prod.get("price_usdt_from", "0.0")
        price_inr = calculate_inr_price(pkey, usdt_price)

        markup = telebot.types.InlineKeyboardMarkup()
        if stock > 0:
            markup.add(telebot.types.InlineKeyboardButton(f"⚡ Buy Now for ₹{int(price_inr)}", callback_data=f"buy_link_{pkey}"))
        else:
            markup.add(telebot.types.InlineKeyboardButton("❌ Out of Stock", callback_data="out_of_stock_alert"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="ai_catalog"))

        text = (
            f"💎 **PRODUCT: {pname}**\n\n"
            f"📦 **Current Stock:** `{stock} available`\n"
            f"💰 **Price:** `₹{int(price_inr)}`\n"
            f"⚡ **Delivery:** Instant Bot Delivery (Direct Activation Link)\n\n"
            "📌 *Once bought, tap the delivered link while logged into your Google/AI account to upgrade seamlessly.*"
        )
        safe_edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "out_of_stock_alert":
        try:
            bot.answer_callback_query(call.id, text="⚠️ This product is currently out of stock! Restocking shortly.", show_alert=True)
        except Exception:
            pass

    elif call.data.startswith("buy_link_"):
        pkey = call.data.replace("buy_link_", "")
        products = cuppon_get_products()
        prod = next((p for p in products if p.get("key") == pkey), None)
        if not prod:
            bot.send_message(call.message.chat.id, "❌ Product unavailable.")
            return

        pname = prod.get("name", "AI Product")
        usdt_price = prod.get("price_usdt_from", "0.0")
        price_inr = calculate_inr_price(pkey, usdt_price)

        # Balance check
        fresh_user = get_user(user_id)
        if not fresh_user or fresh_user["balance"] < price_inr:
            cur_bal = fresh_user["balance"] if fresh_user else 0.0
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("💳 Add Wallet Funds", callback_data="add_balance"))
            markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="ai_catalog"))
            safe_edit_message_text(
                f"❌ **Insufficient Wallet Balance!**\n\n"
                f"Item: **{pname}**\n"
                f"Cost: `₹{price_inr:.2f}`\n"
                f"Your Balance: `₹{cur_bal:.2f}`\n\n"
                "Please add funds to your wallet to complete the purchase.",
                call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup
            )
            return

        # Atomic debit prior to API request
        atomic_update_balance(user_id, -price_inr, spend_add=price_inr, order_add=1)
        proc_msg = bot.send_message(call.message.chat.id, f"⏳ Generating secure activation link for **{pname}**...")

        # Purchase through Cuppon'sHub API
        res = cuppon_purchase_product(pkey, quantity=1)

        try:
            bot.delete_message(call.message.chat.id, proc_msg.message_id)
        except Exception:
            pass

        if res.get("ok") and "order" in res:
            order_info = res["order"]
            items = order_info.get("items", [])
            delivered_item = items[0] if items else "Link generation pending - check My Orders"
            reseller_order_id = order_info.get("order_id", "N/A")

            # Save in database
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn = get_db_connection()
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute(
                        'INSERT INTO orders (user_id, product_name, delivered_item, price, reseller_order_id, date) VALUES (%s, %s, %s, %s, %s, %s)',
                        (user_id, pname, str(delivered_item), price_inr, reseller_order_id, now_str)
                    )
                    conn.commit()
                    cur.close()
                finally:
                    release_db_connection(conn)

            log_bot_transaction(user_id, "PURCHASE", price_inr, f"Bought {pname} (Order: {reseller_order_id})")

            upd_user = get_user(user_id)
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("📦 View All Orders", callback_data="orders"))
            markup.add(telebot.types.InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu"))

            success_text = (
                "🎉 **ACTIVATION LINK READY!**\n\n"
                f"🏷️ **Product:** {pname}\n"
                f"🆔 **Order ID:** `{reseller_order_id}`\n\n"
                f"🔗 **Your Activation Link:**\n`{delivered_item}`\n\n"
                "*(Tap the link above to copy, or open it in your browser while logged into your account to activate.)*\n\n"
                f"💰 Amount Charged: `₹{price_inr:.2f}`\n"
                f"💳 Remaining Balance: `₹{upd_user['balance']:.2f}`"
            )
            bot.send_message(call.message.chat.id, success_text, parse_mode="Markdown", reply_markup=markup)

        else:
            # Automated refund on failure
            atomic_update_balance(user_id, price_inr, spend_add=-price_inr, order_add=-1)
            err_msg = res.get("error", "Stock unavailable or server error")
            log_bot_transaction(user_id, "REFUND", price_inr, f"Auto-refunded: {err_msg}")

            markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Catalog", callback_data="ai_catalog"))
            bot.send_message(
                call.message.chat.id,
                f"❌ **Purchase Failed (Funds Refunded)**\n\nReason: `{err_msg}`\nYour wallet balance was not deducted.",
                parse_mode="Markdown", reply_markup=markup
            )

    # 2. ORDERS LIST
    elif call.data == "orders":
        conn = get_db_connection()
        rows = []
        if conn:
            try:
                cur = conn.cursor()
                cur.execute('SELECT product_name, delivered_item, price, date, reseller_order_id FROM orders WHERE user_id = %s ORDER BY id DESC LIMIT 10', (user_id,))
                rows = cur.fetchall()
                cur.close()
            except Exception:
                rows = []
            finally:
                release_db_connection(conn)

        if not rows:
            text_hist = "📦 **You have no past orders.**\nVisit the catalog to purchase AI activation links!"
        else:
            text_hist = "🛍️ **— YOUR PAST ORDERS (Last 10) —**\n\n"
            for r in rows:
                text_hist += (
                    f"🏷️ **{r[0]}**\n"
                    f"🔗 `{r[1]}`\n"
                    f"🆔 Order: `{r[4]}` | 💰 ₹{r[2]} | 📅 {r[3]}\n"
                    "------------------------------------\n"
                )
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu"))
        safe_edit_message_text(text_hist[:4000], call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # 3. WALLET TOPUP
    elif call.data == "add_balance":
        waiting_for_custom_topup[user_id] = True
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        fresh_user = get_user(user_id)
        current_bal = fresh_user['balance'] if fresh_user else 0.0
        safe_edit_message_text(
            f"💰 **— ADD WALLET BALANCE —**\n\n"
            f"💳 Current Balance: `₹{current_bal:.2f}`\n\n"
            "👇 **Type the exact amount in Rupees you want to deposit (e.g. `100`):**",
            call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup
        )

    elif call.data == "cancel_topup":
        user_orders.pop(user_id, None)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        bot.send_message(call.message.chat.id, "❌ Deposit request canceled.", reply_markup=telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")))

    # 4. PROFILE DASHBOARD
    elif call.data == "profile":
        fresh = get_user(user_id)
        if not fresh:
            return
        role = "👑 Master Admin" if is_admin else f"👤 {fresh['role']}"
        status_badge = "🚫 Suspended" if fresh["banned"] else "🟢 Active & Verified"

        profile_text = (
            "╔═══════════════════════════════╗\n"
            "      👤 **USER ACCOUNT DASHBOARD**\n"
            "╚═══════════════════════════════╝\n\n"
            f"🏷️ **User:** {fresh['name']}\n"
            f"🆔 **Telegram ID:** `{user_id}`\n"
            f"🎖️ **Account Tier:** `{role}`\n"
            f"🛡️ **Status:** {status_badge}\n"
            f"📅 **Member Since:** `{fresh['joined']}`\n\n"
            "┌─── 💳 **WALLET & PURCHASES** ───────┐\n"
            f"│ 💰 **Current Balance:**  ₹{fresh['balance']:.2f}\n"
            f"│ 💸 **Lifetime Spent:**   ₹{fresh['total_spent']:.2f}\n"
            f"│ 📦 **Orders Completed:** {fresh['orders_count']}\n"
            "└────────────────────────────────┘\n\n"
            "┌─── 🎁 **REWARDS & BONUSES** ────────┐\n"
            f"│ 👥 **Total Referrals:**  {fresh.get('total_referrals', 0)}\n"
            f"│ 🎡 **Bonus Spins:**      {fresh.get('bonus_spins', 0)}\n"
            f"│ ⏱️ **Daily Spin Status:** `{fresh.get('last_spin_time') or 'Ready to spin!'}`\n"
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
        safe_edit_message_text(profile_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # 5. REFERRAL SYSTEM
    elif call.data == "referral":
        bot_username = bot.get_me().username
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        safe_edit_message_text(
            f"🎁 **REFERRAL & EARN PROGRAM**\n\n"
            "Share your exclusive referral link with friends. For every friend who registers, you receive **1 Free Lucky Spin**!\n\n"
            f"🔗 **Your Referral Link:**\n`{ref_link}`",
            call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup
        )

    # 6. LUCKY SPIN
    elif call.data == "lucky_spin":
        fresh = get_user(user_id)
        bonus_spins = fresh.get("bonus_spins", 0) if fresh else 0
        last_spin = fresh.get("last_spin_time") if fresh else None
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
            markup.add(telebot.types.InlineKeyboardButton("🎯 SPIN WHEEL NOW", callback_data="do_lucky_spin"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        safe_edit_message_text("🎡 **DAILY LUCKY SPIN**\n\nSpin daily to win free wallet rewards of up to ₹10!", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "do_lucky_spin":
        reward = random.choice([0, 0, 1, 1, 2, 5, 10])
        atomic_update_balance(user_id, float(reward))
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db_connection()
        if conn:
            try:
                cur = conn.cursor()
                cur.execute('UPDATE users SET last_spin_time = %s WHERE user_id = %s', (now_str, user_id))
                conn.commit()
                cur.close()
            except Exception:
                pass
            finally:
                release_db_connection(conn)

        try:
            bot.answer_callback_query(call.id, text=f"🎉 Result: ₹{reward} reward!", show_alert=True)
        except Exception:
            pass
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        res_text = f"🎉 Congratulations! ₹{reward} credited to your wallet balance." if reward > 0 else "😢 Better luck next time! Spin again tomorrow."
        safe_edit_message_text(f"🎡 **SPIN RESULT**\n\n{res_text}", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # 7. SUPPORT TICKETS
    elif call.data == "support_ticket":
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("💳 Payment Issue", callback_data="tkt_Payment"))
        markup.add(telebot.types.InlineKeyboardButton("🔗 Activation Link Help", callback_data="tkt_Link"))
        markup.add(telebot.types.InlineKeyboardButton("💬 Other Inquiries", callback_data="tkt_Other"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        safe_edit_message_text("🎟️ **CUSTOMER SUPPORT**\n\nSelect your inquiry topic:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data.startswith("tkt_"):
        cat = call.data.replace("tkt_", "")
        waiting_for_support_ticket[user_id] = cat
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Cancel", callback_data="main_menu"))
        safe_edit_message_text(f"🎟️ Category: `{cat}`\n\n👇 **Reply with your issue and details:**", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # 8. COUPONS
    elif call.data == "redeem_coupon":
        waiting_for_coupon_code[user_id] = True
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Cancel", callback_data="main_menu"))
        safe_edit_message_text("🏷️ **REDEEM COUPON**\n\n👇 Type your promotional code below:", call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    # ==========================================================================
    # MASTER ADMIN PANEL
    # ==========================================================================
    elif call.data == "admin_panel" and is_admin:
        m_status = "🔴 OFF (Store Active)" if not STORE_UNDER_MAINTENANCE else "🟢 ON (Under Maintenance)"
        reseller_bal = cuppon_get_balance()
        bal_str = f"${reseller_bal:.2f} USDT" if reseller_bal is not None else "⚠️ Connection Failed"

        admin_text = (
            "👑 **MASTER ADMIN DASHBOARD**\n\n"
            f"🌐 **Cuppon'sHub Reseller Balance:** `{bal_str}`\n"
            f"🛠️ **Maintenance Mode:** `{m_status}`\n\n"
            "Select an administrative action:"
        )

        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"🛠️ Toggle Maintenance: {m_status}", callback_data="adm_toggle_maintenance"))
        markup.add(telebot.types.InlineKeyboardButton("🎟️ View Support Tickets", callback_data="adm_view_tickets"))
        markup.add(telebot.types.InlineKeyboardButton("🏷️ Create Promo Coupon", callback_data="adm_create_coupon"))
        markup.add(telebot.types.InlineKeyboardButton("📋 Registered Users", callback_data="adm_users_list_1"))
        markup.add(telebot.types.InlineKeyboardButton("📊 Recent Transactions", callback_data="adm_all_transactions"))
        markup.add(telebot.types.InlineKeyboardButton("🔍 Inspect User Profile", callback_data="adm_check_user"))
        markup.add(telebot.types.InlineKeyboardButton("💰 Credit Balance", callback_data="adm_addbal_menu"))
        markup.add(telebot.types.InlineKeyboardButton("✂️ Debit Balance", callback_data="adm_cutbal_menu"))
        markup.add(telebot.types.InlineKeyboardButton("🔨 Ban / Unban User", callback_data="adm_ban_menu"))
        markup.add(telebot.types.InlineKeyboardButton("📢 Send Global Broadcast", callback_data="adm_broadcast"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Main Menu", callback_data="main_menu"))
        safe_edit_message_text(admin_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "adm_toggle_maintenance" and is_admin:
        STORE_UNDER_MAINTENANCE = not STORE_UNDER_MAINTENANCE
        handle_callback(type('obj', (object,), {'from_user': call.from_user, 'message': call.message, 'data': 'admin_panel', 'id': call.id}))

    elif call.data == "adm_create_coupon" and is_admin:
        admin_coupon_flow[user_id] = {"step": "code"}
        bot.send_message(call.message.chat.id, "🏷️ **CREATE PROMO CODE**\n\nReply with the code name (e.g. `WELCOME50`):", parse_mode="Markdown")

    elif call.data.startswith("adm_coupon_type_") and is_admin:
        r_type = call.data.split("_")[3]
        if user_id in admin_coupon_flow:
            admin_coupon_flow[user_id]["type"] = r_type
            admin_coupon_flow[user_id]["step"] = "value"
            val_prompt = "💳 Enter the **Rupee amount** (e.g. `50`):" if r_type == "balance" else "🎡 Enter the **Bonus Spins count** (e.g. `3`):"
            bot.send_message(call.message.chat.id, val_prompt, parse_mode="Markdown")

    elif call.data == "adm_view_tickets" and is_admin:
        conn = get_db_connection()
        rows = []
        if conn:
            try:
                cur = conn.cursor()
                cur.execute('SELECT id, user_id, category, message, date FROM support_tickets ORDER BY id DESC LIMIT 10')
                rows = cur.fetchall()
                cur.close()
            except Exception:
                rows = []
            finally:
                release_db_connection(conn)
        t_text = "🎟️ **RECENT TICKETS**\n\n" + ("\n".join([f"#{r[0]} | User `{r[1]}` [{r[2]}]\n💬 {r[3]}" for r in rows]) if rows else "No open tickets.")
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel"))
        safe_edit_message_text(t_text[:4000], call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data.startswith("adm_users_list_") and is_admin:
        conn = get_db_connection()
        rows = []
        if conn:
            try:
                cur = conn.cursor()
                cur.execute('SELECT user_id, name, balance FROM users ORDER BY joined DESC LIMIT 15')
                rows = cur.fetchall()
                cur.close()
            except Exception:
                rows = []
            finally:
                release_db_connection(conn)
        u_text = "📋 **REGISTERED USERS (Recent 15)**\n\n" + "\n".join([f"`{r[0]}` | {r[1]} | ₹{r[2]:.2f}" for r in rows])
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back to Admin", callback_data="admin_panel"))
        safe_edit_message_text(u_text, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "adm_all_transactions" and is_admin:
        conn = get_db_connection()
        rows = []
        if conn:
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
        safe_edit_message_text(t_text[:4000], call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "adm_broadcast" and is_admin:
        admin_actions[user_id] = "broadcast"
        bot.send_message(call.message.chat.id, "📢 Send the announcement message to broadcast:")

    elif call.data in ["adm_addbal_menu", "adm_cutbal_menu", "adm_check_user", "adm_ban_menu"] and is_admin:
        act = {
            "adm_addbal_menu": "addbal",
            "adm_cutbal_menu": "cutbal",
            "adm_check_user": "checkuser",
            "adm_ban_menu": "ban"
        }[call.data]
        admin_actions[user_id] = act
        prompt = "Format: `USER_ID AMOUNT`" if act in ["addbal", "cutbal"] else "Format: `USER_ID`"
        bot.send_message(call.message.chat.id, f"💬 {prompt}", parse_mode="Markdown")

# ==============================================================================
# FAMPAY UPI DEPOSIT SYSTEM (QR + AUTO-POLL)
# ==============================================================================
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
                caption=f"💳 **Deposit Request:** ₹{amount_inr}\n🆔 Order ID: `{order_id}`\n\n🔗 [Tap Here to Pay via UPI]({pay_link})\n⏱️ QR code expires in 5 minutes.",
                parse_mode="Markdown", reply_markup=markup
            )
            user_orders[user_id] = {"order_id": order_id}

            def poll_payment(uid, oid, amt, mid):
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
                            cur_b = up['balance'] if up else amt
                            bot.send_message(chat_id, f"🎉 **Payment Verified!**\n₹{amt:.2f} credited to your wallet.\n💳 New Balance: ₹{cur_b:.2f}")
                            break
                    except Exception:
                        pass

            threading.Thread(target=poll_payment, args=(user_id, order_id, amount_inr, sent.message_id), daemon=True).start()
    except Exception as e:
        bot.send_message(chat_id, f"Gateway Error: {str(e)}")

# ==============================================================================
# USER TEXT INPUT HANDLERS
# ==============================================================================
@bot.message_handler(func=lambda m: m.from_user.id in waiting_for_custom_topup)
def handle_topup_input(message):
    uid = message.from_user.id
    waiting_for_custom_topup.pop(uid, None)
    try:
        amt = int(message.text.strip())
        if amt < 10:
            bot.send_message(message.chat.id, "❌ Minimum deposit amount is ₹10.")
            return
        create_topup_order(message, uid, amt)
    except Exception:
        bot.send_message(message.chat.id, "❌ Please enter a valid number.")

@bot.message_handler(func=lambda m: m.from_user.id in waiting_for_support_ticket)
def handle_ticket_input(message):
    uid = message.from_user.id
    cat = waiting_for_support_ticket.pop(uid, "General")
    msg = message.text.strip()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute('INSERT INTO support_tickets (user_id, category, message, status, date) VALUES (%s, %s, %s, %s, %s)', (uid, cat, msg, 'Open', now_str))
            conn.commit()
            cur.close()
        finally:
            release_db_connection(conn)

    bot.send_message(message.chat.id, "✅ Ticket submitted successfully! Our support staff will review it shortly.")
    try:
        bot.send_message(ADMIN_ID, f"🚨 New Support Ticket from `{uid}` [{cat}]:\n{msg}")
    except Exception:
        pass

@bot.message_handler(func=lambda m: m.from_user.id in waiting_for_coupon_code)
def handle_coupon_input(message):
    uid = message.from_user.id
    waiting_for_coupon_code.pop(uid, None)
    code = message.text.strip().upper()
    conn = get_db_connection()
    if not conn:
        bot.send_message(message.chat.id, "Database temporarily unavailable.")
        return
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('SELECT * FROM coupons WHERE code = %s', (code,))
        c = cur.fetchone()
        if not c or (c["expires_at"] and datetime.now() > datetime.strptime(c["expires_at"], "%Y-%m-%d %H:%M:%S")) or c["uses_count"] >= c["max_uses"]:
            bot.send_message(message.chat.id, "❌ Invalid or expired coupon code.")
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
            bot.send_message(message.chat.id, f"🎉 Coupon applied! ₹{val:.2f} credited to your wallet.")
        elif c["reward_type"] == "spin":
            cur.execute('UPDATE users SET bonus_spins = bonus_spins + %s WHERE user_id = %s', (int(val), uid))
            bot.send_message(message.chat.id, f"🎉 Coupon applied! {int(val)} bonus spins added.")

        cur.execute('UPDATE coupons SET uses_count = uses_count + 1 WHERE code = %s', (code,))
        cur.execute('INSERT INTO coupon_redemptions (user_id, code, used_count) VALUES (%s, %s, 1) ON CONFLICT (user_id, code) DO UPDATE SET used_count = coupon_redemptions.used_count + 1', (uid, code))
        conn.commit()
        cur.close()
    except Exception as e:
        bot.send_message(message.chat.id, f"Coupon redemption error: {e}")
    finally:
        release_db_connection(conn)

# ==============================================================================
# ADMIN FLOW HANDLERS
# ==============================================================================
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
            bot.send_message(message.chat.id, "👥 Enter maximum total global redemptions (e.g. `10`):")
        except ValueError:
            bot.send_message(message.chat.id, "❌ Send a valid numeric value.")

    elif flow["step"] == "max_users":
        try:
            flow["max_users"] = int(text)
            flow["step"] = "hours"
            bot.send_message(message.chat.id, "⏳ Enter validity duration in hours (e.g. `48`):")
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
            if conn:
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

            bot.send_message(message.chat.id, f"✅ **Coupon `{code}` Created!**\nReward: {r_type} ({val})\nMax Uses: {max_uses}\nExpires: {expires_at}", parse_mode="Markdown")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Error: {e}")

@bot.message_handler(func=lambda m: m.from_user.id in admin_actions and m.from_user.id == ADMIN_ID)
def handle_admin_action(message):
    admin_id = message.from_user.id
    action = admin_actions.pop(admin_id)
    text = message.text.strip()

    if action == "broadcast":
        conn = get_db_connection()
        users = []
        if conn:
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
                bot.send_message(u[0], f"📢 **OFFICIAL ANNOUNCEMENT**\n\n{text}", parse_mode="Markdown")
                sent += 1
            except Exception:
                fail += 1
        bot.send_message(message.chat.id, f"✅ Broadcast finished. Sent: {sent} | Failed: {fail}")

    elif action in ["addbal", "cutbal"]:
        try:
            target_id, amt = int(text.split()[0]), float(text.split()[1])
            change = amt if action == "addbal" else -amt
            atomic_update_balance(target_id, change)
            log_bot_transaction(target_id, "ADMIN_MOD", change, "Admin manual balance adjustment")
            bot.send_message(message.chat.id, f"Balance adjusted by {change} for `{target_id}`.")
        except Exception:
            bot.send_message(message.chat.id, "Format: `USER_ID AMOUNT`")

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
                if conn:
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

# ==============================================================================
# BOT RUNNER WITH AUTOMATIC RESTART
# ==============================================================================
if __name__ == "__main__":
    print("Initiating safe Telegram connection...")
    try:
        bot.delete_webhook(drop_pending_updates=True)
        print("Webhook cleared successfully.")
    except Exception as e:
        print(f"Webhook notice: {e}")

    print("AI Subscription Bot is running...")
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except Exception as err:
            print(f"Polling encountered an error, restarting in 3 seconds: {err}")
            time.sleep(3)
