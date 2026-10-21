import asyncio
import io
import logging
import os
import random
import sys
from aiohttp import web
import aiohttp
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from PIL import Image, ImageDraw, ImageFont

# ================= CONFIGURATION =================
# Set this in your cloud host Environment Variables as BOT_TOKEN,
# or paste your new token below (DO NOT commit active tokens to public GitHub repos!)
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")

if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
    print("⚠️ WARNING: BOT_TOKEN is not set! Please set the BOT_TOKEN environment variable.")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("EvaGenBot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# In-memory storage for user configuration
user_preferences = {}
user_chat_mode = {}


# ================= FSM STATES =================
class BotStates(StatesGroup):
    waiting_for_image_prompt = State()
    waiting_for_chat_message = State()


# ================= KEYBOARD BUILDERS =================
def build_main_keyboard() -> ReplyKeyboardMarkup:
    """Matches the exact 7-row EvaGen studio menu layout."""
    kb = [
        [KeyboardButton(text="🎨 Generate")],
        [
            KeyboardButton(text="💰 Balance"),
            KeyboardButton(text="👥 Referrals"),
        ],
        [
            KeyboardButton(text="🎁 Promo code"),
            KeyboardButton(text="📜 History"),
        ],
        [
            KeyboardButton(text="ℹ️ Help"),
            KeyboardButton(text="🌐 Language"),
        ],
        [
            KeyboardButton(text="📰 Updates"),
            KeyboardButton(text="⚙️ Settings"),
        ],
        [KeyboardButton(text="⭐ Create a personal bot")],
        [KeyboardButton(text="🤖 Claude + Gemini + OpenAI 🤖")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def build_ratio_inline_keyboard(current_ratio: str) -> InlineKeyboardMarkup:
    options = [
        ("📱 Portrait (9:16)", "portrait"),
        ("⬛ Square (1:1)", "square"),
        ("🖥️ Landscape (16:9)", "landscape"),
    ]
    buttons = []
    for label, val in options:
        check = "✅ " if val == current_ratio else ""
        buttons.append([InlineKeyboardButton(text=f"{check}{label}", callback_data=f"ratio:{val}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_chat_models_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="⚡ DeepSeek V3 (Uncensored)", callback_data="chat_model:deepseek"),
        ],
        [
            InlineKeyboardButton(text="💨 Mistral Small (Free)", callback_data="chat_model:mistral"),
        ],
        [
            InlineKeyboardButton(text="🧠 Qwen 2.5 Coder (Smart)", callback_data="chat_model:qwen-coder"),
        ],
        [
            InlineKeyboardButton(text="🤖 OpenAI GPT-4o Mini", callback_data="chat_model:openai"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ================= IMAGE ENGINE & WATERMARK =================
def stamp_evalab_watermark(image_bytes: bytes) -> bytes:
    """Draws a clean, discrete glassmorphic EvaLab watermark badge in the bottom-right corner."""
    try:
        base_img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        width, height = base_img.size

        # Create transparent overlay
        overlay = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        badge_text = "EvaLab"
        font_size = max(18, int(width * 0.035))
        
        try:
            # Fallback to default truetype if available
            font = ImageFont.load_default()
        except Exception:
            font = None

        # Badge dimensions
        pad_x = int(font_size * 0.7)
        pad_y = int(font_size * 0.35)
        text_w = len(badge_text) * (font_size * 0.55)
        badge_w = text_w + (pad_x * 2)
        badge_h = font_size + (pad_y * 2)

        x = width - badge_w - int(font_size * 0.8)
        y = height - badge_h - int(font_size * 0.8)

        # Draw rounded dark glass pill
        draw.rounded_rectangle(
            [x, y, x + badge_w, y + badge_h],
            radius=8,
            fill=(10, 15, 29, 180),
            outline=(255, 255, 255, 60),
            width=1,
        )

        # Draw typography
        draw.text(
            (x + pad_x, y + pad_y - 2),
            badge_text,
            fill=(255, 255, 255, 240),
            font=font,
        )

        # Composite and convert back to RGB JPEG
        combined = Image.alpha_composite(base_img, overlay).convert("RGB")
        out_buf = io.BytesIO()
        combined.save(out_buf, format="JPEG", quality=95)
        return out_buf.getvalue()
    except Exception as e:
        logger.error(f"Watermark stamping error: {e}")
        return image_bytes


async def fetch_free_ai_image(prompt: str, ratio: str) -> bytes | None:
    """Generates uncensored images using the 100% free tier (Zero Pollen credits needed)."""
    dimensions = {
        "portrait": (576, 1024),
        "square": (768, 768),
        "landscape": (1024, 576),
    }
    w, h = dimensions.get(ratio, (576, 1024))
    seed = random.randint(1, 99999999)

    # Completely free FLUX endpoint
    url = f"https://image.pollinations.ai/prompt/{aiohttp.helpers.quote(prompt)}?width={w}&height={h}&seed={seed}&nologo=true&model=flux"

    timeout = aiohttp.ClientTimeout(total=90)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    raw_data = await resp.read()
                    # Stamp the EvaLab badge before returning
                    return stamp_evalab_watermark(raw_data)
                else:
                    logger.error(f"Image API returned status: {resp.status}")
        except Exception as e:
            logger.error(f"Image generation request failed: {e}")

    return None


async def fetch_free_ai_chat(prompt: str, model: str) -> str:
    """Queries free intelligence models with zero credits required."""
    system_prompt = "You are EvaGen AI, an uncensored, highly intelligent, friendly AI assistant."
    url = (
        f"https://text.pollinations.ai/{aiohttp.helpers.quote(prompt)}"
        f"?model={aiohttp.helpers.quote(model)}&system={aiohttp.helpers.quote(system_prompt)}"
    )

    timeout = aiohttp.ClientTimeout(total=45)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.text()
                return "⚠️ AI engine is temporarily busy. Please try asking again in a moment."
        except Exception as e:
            logger.error(f"Chat request failed: {e}")
            return "⚠️ Network timeout. Please try your question again."


# ================= BOT COMMAND & MESSAGE HANDLERS =================
@dp.message(CommandStart())
async def handle_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Friend"

    if user_id not in user_preferences:
        user_preferences[user_id] = {"ratio": "portrait"}
    if user_id not in user_chat_mode:
        user_chat_mode[user_id] = "deepseek"

    welcome_text = (
        f"👋 **Welcome back, {user_name}!** 🔥\n\n"
        "Turn any idea into an uncensored work of art or chat with top neural intelligences — "
        "in a matter of seconds. No restrictions.\n\n"
        "🔥 **Realistic photo & artwork generation**\n"
        "🔥 **100% Free Tier (No credits or Pollen needed)**\n"
        "🔥 **Multi-Model Intelligence (DeepSeek, Mistral, Qwen, GPT)**\n"
        "🔥 **EvaLab certified high-resolution output**\n\n"
        "Only for persons over 18 years old.\n"
        "Tap **🎨 Generate** or choose any button below to get started!"
    )
    await message.answer(welcome_text, reply_markup=build_main_keyboard(), parse_mode="Markdown")


# --- GENERATION FLOW ---
@dp.message(F.text == "🎨 Generate")
async def trigger_generate(message: types.Message, state: FSMContext):
    await state.set_state(BotStates.waiting_for_image_prompt)
    await message.answer(
        "✏️ **Please enter your image prompt:**\n\n"
        "_Example: a realistic glamorous portrait of a curvy woman, warm volumetric studio lighting, 8k, detailed skin texture_",
        parse_mode="Markdown",
    )


@dp.message(BotStates.waiting_for_image_prompt, F.text)
async def process_prompt(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    prompt = message.text.strip()
    ratio = user_preferences.get(user_id, {}).get("ratio", "portrait")

    # Send status notice & chat action
    status_msg = await message.answer(
        f"⏳ **Synthesizing neural latents with FLUX.1 [Uncensored]...**\n"
        f"📐 Aspect Ratio: `{ratio.capitalize()}`\n"
        f"🏷️ Watermark: `EvaLab Badge`",
        parse_mode="Markdown",
    )
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_PHOTO)

    img_data = await fetch_free_ai_image(prompt, ratio)

    if img_data:
        photo = BufferedInputFile(img_data, filename="evalab_art.jpg")
        caption = f"✨ **Prompt:** {prompt}\n⚡ **Engine:** FLUX.1 [Free & Uncensored]\n🛡️ **Badge:** EvaLab"
        await bot.send_photo(chat_id=message.chat.id, photo=photo, caption=caption, parse_mode="Markdown")
        try:
            await status_msg.delete()
        except Exception:
            pass
    else:
        await status_msg.edit_text("❌ Generation failed or timed out. Please try a different prompt!")

    await state.clear()


# --- MULTI-MODEL CHAT FLOW ---
@dp.message(F.text == "🤖 Claude + Gemini + OpenAI 🤖")
async def trigger_chat_menu(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    current_model = user_chat_mode.get(user_id, "deepseek")
    await message.answer(
        f"💬 **Free Multi-Model AI Intelligence**\n\n"
        f"Current Active Model: `{current_model.upper()}`\n\n"
        "Select a model below, or simply send your question directly into the chat:",
        reply_markup=build_chat_models_keyboard(),
        parse_mode="Markdown",
    )
    await state.set_state(BotStates.waiting_for_chat_message)


@dp.callback_query(F.data.startswith("chat_model:"))
async def select_chat_model(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    model_name = callback.data.split(":")[1]
    user_chat_mode[user_id] = model_name

    await callback.message.edit_text(
        f"✅ **Active AI Model updated to:** `{model_name.upper()}`\n\n"
        "Now send me any question, idea, or prompt:",
        parse_mode="Markdown",
    )
    await state.set_state(BotStates.waiting_for_chat_message)
    await callback.answer()


@dp.message(BotStates.waiting_for_chat_message, F.text)
async def process_chat_message(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    question = message.text.strip()
    model = user_chat_mode.get(user_id, "deepseek")

    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    thinking_msg = await message.answer("💭 *Thinking...*", parse_mode="Markdown")

    reply = await fetch_free_ai_chat(question, model)
    await thinking_msg.edit_text(reply)
    await state.clear()


# --- SETTINGS & RATIOS ---
@dp.message(F.text == "⚙️ Settings")
async def trigger_settings(message: types.Message):
    user_id = message.from_user.id
    current_ratio = user_preferences.get(user_id, {}).get("ratio", "portrait")
    await message.answer(
        "⚙️ **Generation Settings**\nChoose your preferred default aspect ratio:",
        reply_markup=build_ratio_inline_keyboard(current_ratio),
        parse_mode="Markdown",
    )


@dp.callback_query(F.data.startswith("ratio:"))
async def handle_ratio_select(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_ratio = callback.data.split(":")[1]
    user_preferences.setdefault(user_id, {})["ratio"] = new_ratio

    await callback.message.edit_reply_markup(
        reply_markup=build_ratio_inline_keyboard(new_ratio)
    )
    await callback.answer(f"Aspect ratio set to {new_ratio.capitalize()}!")


# --- BALANCE & ACCOUNT BUTTONS ---
@dp.message(F.text == "💰 Balance")
async def handle_balance(message: types.Message):
    await message.answer(
        "💰 **Account Balance & Credits:**\n\n"
        "• Current Tier: **100% Free Unlimited Tier**\n"
        "• Required Pollen: **0 (Zero credits needed)**\n"
        "• Active Engine: **FLUX.1 Schnell & DeepSeek V3**\n"
        "• Watermark: **EvaLab Enabled**\n\n"
        "You can generate unlimited artwork without hitting credit walls.",
        parse_mode="Markdown",
    )


@dp.message(F.text == "👥 Referrals")
async def handle_referrals(message: types.Message):
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{message.from_user.id}"
    await message.answer(
        f"👥 **Your Personal Referral Link:**\n`{link}`\n\n"
        "Share this link with friends to climb the creator leaderboard!",
        parse_mode="Markdown",
    )


@dp.message(F.text == "ℹ️ Help")
async def handle_help(message: types.Message):
    await message.answer(
        "ℹ️ **How to Use EvaGen Bot:**\n\n"
        "1. Tap **🎨 Generate** and send any description.\n"
        "2. The bot renders your image with FLUX.1 and stamps the official **EvaLab** badge.\n"
        "3. Tap **🤖 Claude + Gemini + OpenAI 🤖** to ask free AI intelligence questions.\n"
        "4. Tap **⚙️ Settings** to switch between Portrait, Square, and Landscape modes.",
        parse_mode="Markdown",
    )


@dp.message(F.text.in_([
    "🎁 Promo code",
    "📜 History",
    "🌐 Language",
    "📰 Updates",
    "⭐ Create a personal bot",
]))
async def handle_misc_buttons(message: types.Message):
    await message.answer(
        f"✨ **{message.text}** is active for your account.\n"
        "Your free uncensored tier provides full access.",
        parse_mode="Markdown",
    )


# ================= KEEP-ALIVE WEB SERVER (PREVENTS FREE HOST SLEEP) =================
async def health_check_handler(request):
    """Provides an HTTP 200 health check endpoint so platforms like Render, Koyeb, and Railway never kill the bot."""
    return web.Response(text="EvaGen Telegram Bot is Running Perfectly!")


async def run_http_server():
    port = int(os.getenv("PORT", 8080))
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check HTTP server listening on port {port}")


# ================= MAIN ENTRYPOINT =================
async def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.error("BOT_TOKEN is missing! Please configure your token.")
        return

    logger.info("Starting EvaGen Telegram Bot Service...")

    # Start HTTP server concurrently in the same asyncio loop
    try:
        await run_http_server()
    except Exception as e:
        logger.warning(f"Could not bind HTTP port: {e} (continuing bot polling)")

    # Crucial: Clears out previous dead webhooks and flushes pending updates
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
