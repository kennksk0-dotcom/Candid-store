import telebot
import requests
import sqlite3
from datetime import datetime, timedelta

# --- CONFIGURATION ---
BOT_TOKEN = "8980753842:AAG05SklWh3TshUWiJio1_MTWo2Net-ijiE"
ADMIN_ID = 7997110885

# 1. FamAPI / FreePanel Configuration
FAMPAY_API_KEY = "FAM_LIVE_sk_hRGdY9XAmPu7wzRg9HXjwa8pHdPhKNGB"
FAMPAY_BASE_URL = "https://py.freepanel.in/api/v1"

# 2. XYZ Cheats Reseller API Configuration
XYZ_API_URL = "https://xyzcheats.com/api/reseller_v1.php"
XYZ_API_KEY = "8dc220a22ee3ea0ba80340978c2f1248"
XYZ_MASTER_KEY = "a7f3e8b2c9d1f4a6b8c2d5e9f1a3b6c8"

bot = telebot.TeleBot(BOT_TOKEN)

# --- SECURE DATABASE SETUP (SQLite) ---
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            duration TEXT,
            license_key TEXT,
            price REAL,
            date TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS spam_tracker (
            user_id INTEGER PRIMARY KEY,
            abandon_count INTEGER DEFAULT 0,
            timeout_until TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_user(user_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0], "name": row[1], "phone": row[2], "joined": row[3],
            "balance": row[4], "total_spent": row[5], "orders_count": row[6],
            "role": row[7], "banned": bool(row[8]), "verified": bool(row[9]), "total_referrals": row[10]
        }
    return None

def save_user(user_data):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, name, phone, joined, balance, total_spent, orders_count, role, banned, verified, total_referrals)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_data["user_id"], user_data["name"], user_data.get("phone"), user_data["joined"],
        user_data["balance"], user_data["total_spent"], user_data["orders_count"],
        user_data["role"], int(user_data["banned"]), int(user_data["verified"]), user_data.get("total_referrals", 0)
    ))
    conn.commit()
    conn.close()

def check_timeout(user_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT timeout_until FROM spam_tracker WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row and row[0]:
        timeout_time = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        if datetime.now() < timeout_time:
            remaining = int((timeout_time - datetime.now()).total_seconds() / 60)
            return remaining
    return 0

def add_abandon(user_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT abandon_count FROM spam_tracker WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    count = (row[0] + 1) if row else 1
    
    # 7 skips/cancellations trigger a 15-minute timeout (doubling if repeated)
    if count >= 7:
        minutes = 15 * (2 ** (count - 7))
        timeout_until = (datetime.now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    else:
        timeout_until = None
        
    cursor.execute('INSERT OR REPLACE INTO spam_tracker (user_id, abandon_count, timeout_until) VALUES (?, ?, ?)', (user_id, count, timeout_until))
    conn.commit()
    conn.close()

user_orders = {}
waiting_for_custom_topup = {}
admin_actions = {}

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    
    timeout_mins = check_timeout(user_id)
    if timeout_mins > 0:
        bot.send_message(message.chat.id, f"⏳ **Temporarily Blocked!** Because you skipped/cancelled too many payment QR codes, you are timed out for another {timeout_mins} minutes.", parse_mode="Markdown")
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

    if not user or not user["verified"]:
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
        "🔑 Bala Mod Config (Instant Key Delivery)\n"
        "🔒 Secure Automated Checkout"
    )
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🎮 Buy Bala Mod Config", callback_data="buy_balamod"))
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
    
    if call.data == "buy_balamod":
        if check_timeout(user_id) > 0:
            bot.answer_callback_query(call.id, text="You are temporarily timed out for canceling/skipping QR codes!", show_alert=True)
            return
            
        bot.answer_callback_query(call.id)
        is_reseller = (user_role == "Reseller" or is_admin)
        
        p1 = 15 if is_reseller else 20
        p3 = 40 if is_reseller else 50
        p6 = 60 if is_reseller else 75
        p12 = 100 if is_reseller else 120
        p24 = 140 if is_reseller else 170
        
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton(f"⏱️ 1 Hour - ₹{p1}", callback_data="dur_1h"))
        markup.add(telebot.types.InlineKeyboardButton(f"⏱️ 3 Hours - ₹{p3}", callback_data="dur_3h"))
        markup.add(telebot.types.InlineKeyboardButton(f"⏱️ 6 Hours - ₹{p6}", callback_data="dur_6h"))
        markup.add(telebot.types.InlineKeyboardButton(f"⏱️ 12 Hours - ₹{p12}", callback_data="dur_12h"))
        markup.add(telebot.types.InlineKeyboardButton(f"⏱️ 24 Hours - ₹{p24}", callback_data="dur_24h"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu"))
        bot.send_message(call.chat.id, "🛒 **Bala Mod Config**\nSelect duration:", parse_mode="Markdown", reply_markup=markup)
        
    elif call.data.startswith("dur_"):
        bot.answer_callback_query(call.id)
        is_reseller = (user_role == "Reseller" or is_admin)
        
        duration_map = {
            "dur_1h": ("1 Hours", 15 if is_reseller else 20),
            "dur_3h": ("3 Hours", 40 if is_reseller else 50),
            "dur_6h": ("6 Hours", 60 if is_reseller else 75),
            "dur_12h": ("12 Hours", 100 if is_reseller else 120),
            "dur_24h": ("24 Hours", 140 if is_reseller else 170)
        }
        duration_text, price_inr = duration_map[call.data]
        
        balance = user["balance"]
        if balance >= price_inr:
            user["balance"] -= price_inr
            user["orders_count"] += 1
            user["total_spent"] += price_inr
            save_user(user)
            
            payload = {'api_key': XYZ_API_KEY, 'action': 'buy', 'product_id': '142', 'duration': duration_text}
            headers = {'Content-Type': 'application/x-www-form-urlencoded', 'x-master-key': XYZ_MASTER_KEY}
            
            try:
                api_res = requests.post(XYZ_API_URL, data=payload, headers=headers)
                res_json = api_res.json()
                if "key" in res_json or res_json.get("status") == "success":
                    license_key = res_json.get("key", res_json.get("message", "XYZ-KEY"))
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    conn = sqlite3.connect('database.db')
                    conn.cursor().execute('INSERT INTO orders (user_id, duration, license_key, price, date) VALUES (?, ?, ?, ?, ?)',
                                          (user_id, duration_text, license_key, price_inr, current_time))
                    conn.commit()
                    conn.close()
                    
                    bot.send_message(
                        call.message.chat.id,
                        f"🎉 **Key Generated Successfully!**\n\n🔑 Key:\n`{license_key}`\n\n⏱️ Duration: {duration_text}\n💰 Cost: ₹{price_inr}\n💳 Remaining Balance: ₹{user['balance']:.2f}",
                        parse_mode="Markdown"
                    )
                else:
                    bot.send_message(call.message.chat.id, f"❌ Key generation failed from provider: {res_json.get('message', 'Error')}")
            except Exception as e:
                bot.send_message(call.message.chat.id, f"⚠️ API Error: {str(e)}")
        else:
            bot.send_message(
                call.message.chat.id,
                f"❌ **Insufficient Balance!**\nRequired: ₹{price_inr} | Balance: ₹{balance:.2f}",
                parse_mode="Markdown",
                reply_markup=telebot.types.InlineKeyboardMarkup().add(
                    telebot.types.InlineKeyboardButton("💳 Add Balance Now", callback_data="add_balance"),
                    telebot.types.InlineKeyboardButton("🔙 Back", callback_data="main_menu")
                )
            )

    elif call.data == "add_balance":
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("➕ ₹50", callback_data="topup_50"))
        markup.add(telebot.types.InlineKeyboardButton("➕ ₹100", callback_data="topup_100"))
        markup.add(telebot.types.InlineKeyboardButton("➕ ₹500", callback_data="topup_500"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
        bot.send_message(call.chat.id, "💳 Select amount to add:", reply_markup=markup)

    elif call.data.startswith("topup_"):
        bot.answer_callback_query(call.id)
        amount_inr = int(call.data.split("_")[1])
        
        headers = {"Authorization": f"Bearer {FAMPAY_API_KEY}", "Content-Type": "application/json"}
        payload = {"amount": amount_inr * 100, "redirect_url": "https://t.me/"}
        try:
            resp = requests.post(f"{FAMPAY_BASE_URL}/orders", json=payload, headers=headers).json()
            if "payment_link" in resp:
                order_id = resp["id"]
                user_orders[user_id] = {"order_id": order_id, "amount": amount_inr}
                
                markup = telebot.types.InlineKeyboardMarkup()
                markup.add(telebot.types.InlineKeyboardButton("🔗 Pay Now via UPI", url=resp["payment_link"]))
                markup.add(telebot.types.InlineKeyboardButton("✅ I Have Paid", callback_data="check_topup"))
                markup.add(telebot.types.InlineKeyboardButton("❌ Cancel Order", callback_data="cancel_topup"))
                
                bot.send_message(call.message.chat.id, f"💳 **Top-Up Order:** ₹{amount_inr}\nID: `{order_id}`\n\nComplete payment or click Cancel if you changed your mind.", parse_mode="Markdown", reply_markup=markup)
        except Exception:
            bot.send_message(call.message.chat.id, "❌ Gateway error.")

    elif call.data == "cancel_topup":
        bot.answer_callback_query(call.id, text="Order cancelled successfully.")
        add_abandon(user_id)
        if user_id in user_orders:
            del user_orders[user_id]
        bot.send_message(call.message.chat.id, "❌ **Order Cancelled.** (Note: Canceling or skipping too many payment orders will result in a temporary timeout).", parse_mode="Markdown")

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
                bot.send_message(call.message.chat.id, f"✅ ₹{amount_inr} successfully added to your wallet! Balance: ₹{user['balance']:.2f}")
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
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, profile_text, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "orders":
        bot.answer_callback_query(call.id)
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('SELECT duration, license_key, price, date FROM orders WHERE user_id = ?', (user_id,))
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            bot.send_message(call.message.chat.id, "📦 You have no past orders.")
            return
            
        history_text = "🛍️ — **MY ORDERS** — 🛍️\n\n"
        for r in rows:
            history_text += f"🛒 **Bala Mod Config**\n⏳ {r[0]}\n🔑 `{r[1]}`\n💰 ₹{r[2]} | 📅 {r[3]}\n-------------------\n"
        markup = telebot.types.InlineKeyboardMarkup().add(telebot.types.InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
        bot.send_message(call.message.chat.id, history_text, parse_mode="Markdown", reply_markup=markup)

    elif call.data == "main_menu":
        bot.answer_callback_query(call.id)
        show_main_menu(call.message.chat.id, user_id)

    elif call.data == "admin_panel" and is_admin:
        bot.answer_callback_query(call.id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("📋 Users Started List", callback_data="adm_users_list"))
        markup.add(telebot.types.InlineKeyboardButton("🤝 Toggle Reseller Role", callback_data="adm_toggle_reseller"))
        markup.add(telebot.types.InlineKeyboardButton("🔨 Ban / Unban User", callback_data="adm_ban_menu"))
        markup.add(telebot.types.InlineKeyboardButton("💰 Add Balance to User", callback_data="adm_addbal_menu"))
        markup.add(telebot.types.InlineKeyboardButton("🔙 Back", callback_data="main_menu"))
        bot.send_message(call.chat.id, "👑 **MASTER ADMIN PANEL**", reply_markup=markup, parse_mode="Markdown")

    elif call.data == "adm_users_list" and is_admin:
        bot.answer_callback_query(call.id)
        conn = sqlite3.connect('database.db')
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, name, phone, role, joined FROM users')
        rows = cursor.fetchall()
        conn.close()
        
        text = "📋 — **BOT USERS** — 📋\n\n"
        for r in rows:
            text += f"🆔 `{r[0]}` | {r[1]} | 📱 {r[2]} | Role: {r[3]} | 📅 {r[4]}\n\n"
        bot.send_message(call.chat.id, text[:4000], parse_mode="Markdown")

    elif call.data in ["adm_toggle_reseller", "adm_ban_menu", "adm_addbal_menu"] and is_admin:
        bot.answer_callback_query(call.id)
        actions = {"adm_toggle_reseller": "reseller", "adm_ban_menu": "ban", "adm_addbal_menu": "addbal"}
        admin_actions[user_id] = actions[call.data]
        bot.send_message(call.chat.id, "💬 Send the target User ID (and Amount if adding balance):")

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

print("Secure Bot with 7-Cancellation Timeout Protection is running...")
bot.infinity_polling()
