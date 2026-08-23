import telebot
import requests

# --- CONFIGURATION ---
BOT_TOKEN = "PASTE_YOUR_BOTFATHER_TOKEN_HERE"
ADMIN_ID = 7997110885

# XYZ Cheats Reseller API Details
XYZ_API_URL = "https://xyzcheats.com/api/reseller_v1.php"
XYZ_API_KEY = "8dc220a22ee3ea0ba80340978c2f1248"
XYZ_MASTER_KEY = "a7f3e8b2c9d1f4a6b8c2d5e9f1a3b6c8"

bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    is_admin = (user_id == ADMIN_ID)
    
    welcome_text = (
        "👋 Welcome to Candid Store!\n\n"
        "🌟 — STORE HIGHLIGHTS — 🌟\n"
        "🔑 Bala Mod XYZ FF (Non-Root)\n"
        "⚡ Instant Delivery via UPI / FamPay\n"
        "🔒 Secure Automated Checkout"
    )
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("🎮 Buy Bala Mod", callback_data="buy_balamod"))
    markup.add(telebot.types.InlineKeyboardButton("📦 My Orders", callback_data="orders"),
               telebot.types.InlineKeyboardButton("👑 Profile", callback_data="profile"))
    
    if is_admin:
        welcome_text += "\n\n⚙️ [Master Admin Dashboard Unlocked]"
        markup.add(telebot.types.InlineKeyboardButton("⚡ Admin Panel", callback_data="admin_panel"))
        
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    
    if call.data == "buy_balamod":
        bot.answer_callback_query(call.id)
        # Show duration selection for Bala Mod (Product ID: 142)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("1 Hour", callback_data="get_1h"))
        markup.add(telebot.types.InlineKeyboardButton("24 Hours (1 Day)", callback_data="get_1d"))
        bot.send_message(call.chat.id, "🛒 **Bala Mod XYZ FF Non-Root**\nSelect your duration:", parse_mode="Markdown", reply_markup=markup)
        
    elif call.data in ["get_1h", "get_1d"]:
        bot.answer_callback_query(call.id)
        duration = "1 Hours" if call.data == "get_1h" else "1 Day"
        bot.send_message(call.chat.id, f"📱 Please send your **Android ID** to proceed with your {duration} key generation:", parse_mode="Markdown")
        # Next step would capture the Android ID and trigger the XYZ API request below.

print("Bot is running...")
bot.infinity_polling()
