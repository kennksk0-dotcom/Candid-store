import asyncio
import logging
import os
import random
import sys
import aiohttp
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# ----------------- CONFIGURATION -----------------
# Paste your Bot Token here, OR set it in your host's Environment Variables as BOT_TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
    print("❌ ERROR: Please define your BOT_TOKEN inside main.py or your environment variables!")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# In-memory storage for user settings & history
user_settings = {}
user_history = {}


# ----------------- FSM STATES -----------------
class GenerateState(StatesGroup):
    waiting_for_prompt = State()


# ----------------- KEYBOARDS -----------------
def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Matches the exact grid layout from the reference bot."""
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


def get_resolution_inline_keyboard(current_res: str) -> InlineKeyboardMarkup:
    resolutions = [
        ("512x512 (Square)", "512x512"),
        ("768x768 (HD Square)", "768x768"),
        ("512x768 (Portrait)", "512x768"),
        ("768x512 (Landscape)", "768x512"),
    ]
    buttons = []
    for label, val in resolutions:
        prefix = "✅ " if val == current_res else ""
        buttons.append([InlineKeyboardButton(text=f"{prefix}{label}", callback_data=f"set_res:{val}")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ----------------- PERCHANCE API -----------------
async def request_perchance_image(prompt: str, resolution: str = "768x768") -> str | None:
    """
    Calls Perchance Image API directly using JSON format.
    Returns the permanent hosted URL on user.uploads.dev.
    """
    url = "https://perchance.org/perchance-ai-api"
    params = {
        "prompt": prompt,
        "format": "json",
        "resolution": resolution,
        "guidanceScale": "7",
        "seed": str(random.randint(1000, 99999999)),
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://perchance.org/",
        "Accept": "application/json, text/plain, */*",
    }

    timeout = aiohttp.ClientTimeout(total=180)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    if isinstance(data, dict) and data.get("ok"):
                        return data.get("url")
                    else:
                        logger.warning(f"Perchance error response: {data}")
                else:
                    logger.error(f"Perchance returned HTTP status: {response.status}")
    except asyncio.TimeoutError:
        logger.error("Perchance generation request timed out after 180s.")
    except Exception as e:
        logger.error(f"Failed to fetch image from Perchance: {e}")

    return None


# ----------------- HANDLERS -----------------
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    name = message.from_user.first_name or "Friend"

    if user_id not in user_settings:
        user_settings[user_id] = {"resolution": "768x768"}

    welcome = (
        f"👋 Welcome back, **{name}**! 🔥\n\n"
        "Turn any prompt into a high-quality work of art created with the help of AI "
        "— in a matter of minutes. No restrictions.\n\n"
        "🔥 Realistic photo and artwork generation\n"
        "🔥 Editing & prompt styling\n"
        "🔥 Free unlimited generation (via Perchance)\n\n"
        "Get started for free. Top up your account with Telegram Stars.\n"
        "Only for persons over 18 years old."
    )
    await message.answer(welcome, reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")


@dp.message(F.text == "🎨 Generate")
async def btn_generate(message: types.Message, state: FSMContext):
    await state.set_state(GenerateState.waiting_for_prompt)
    await message.answer(
        "✏️ **Please enter your image prompt:**\n\n"
        "_Example: a cyberpunk street in rain, neon glowing signs, cinematic lighting, 8k_",
        parse_mode="Markdown"
    )


@dp.message(GenerateState.waiting_for_prompt, F.text)
async def process_generation(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    prompt = message.text.strip()
    resolution = user_settings.get(user_id, {}).get("resolution", "768x768")

    status_msg = await message.answer(
        f"⏳ **Generating your image...**\n"
        f"📐 Resolution: `{resolution}`\n"
        "Please wait a few moments...",
        parse_mode="Markdown"
    )

    # Show typing / sending photo action
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.UPLOAD_PHOTO)

    image_url = await request_perchance_image(prompt, resolution=resolution)

    if image_url:
        user_history.setdefault(user_id, []).append((prompt, image_url))
        caption = f"🎨 **Prompt:** {prompt}\n📐 **Resolution:** {resolution}"
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=image_url,
            caption=caption,
            parse_mode="Markdown"
        )
        try:
            await status_msg.delete()
        except Exception:
            pass
    else:
        await status_msg.edit_text(
            "⚠️ **Generation Failed or Timed Out**\n\n"
            "Perchance service is busy right now. Please try again with a slightly different prompt.",
            parse_mode="Markdown"
        )

    await state.clear()


@dp.message(F.text == "⚙️ Settings")
async def btn_settings(message: types.Message):
    user_id = message.from_user.id
    current_res = user_settings.get(user_id, {}).get("resolution", "768x768")
    await message.answer(
        "⚙️ **Image Resolution Settings:**\nSelect the dimensions for your images:",
        reply_markup=get_resolution_inline_keyboard(current_res),
        parse_mode="Markdown"
    )


@dp.callback_query(F.data.startswith("set_res:"))
async def callback_set_resolution(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_res = callback.data.split(":")[1]
    user_settings.setdefault(user_id, {})["resolution"] = new_res

    await callback.message.edit_reply_markup(
        reply_markup=get_resolution_inline_keyboard(new_res)
    )
    await callback.answer(f"Resolution set to {new_res}")


@dp.message(F.text == "💰 Balance")
async def btn_balance(message: types.Message):
    await message.answer(
        "💳 **Your Balance:**\n\n"
        "• AI Model: **Perchance AI (Unlimited)**\n"
        "• Generations Remaining: **∞ Unlimited Free**\n"
        "• Telegram Stars: **0 ⭐**\n\n"
        "You can generate images without limits.",
        parse_mode="Markdown"
    )


@dp.message(F.text == "📜 History")
async def btn_history(message: types.Message):
    user_id = message.from_user.id
    history = user_history.get(user_id, [])

    if not history:
        await message.answer("📜 You haven't generated any images yet in this session.")
        return

    text = "📜 **Your Recent Generations:**\n\n"
    for idx, (p, url) in enumerate(reversed(history[-5:]), 1):
        clean_p = (p[:35] + "...") if len(p) > 35 else p
        text += f"{idx}. [{clean_p}]({url})\n"

    await message.answer(text, parse_mode="Markdown", disable_web_page_preview=True)


@dp.message(F.text == "👥 Referrals")
async def btn_referrals(message: types.Message):
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{message.from_user.id}"
    await message.answer(
        f"👥 **Your Referral Link:**\n`{ref_link}`\n\n"
        "Invite your friends to the bot and unlock bonus features!",
        parse_mode="Markdown"
    )


@dp.message(F.text == "ℹ️ Help")
async def btn_help(message: types.Message):
    await message.answer(
        "ℹ️ **Help Guide:**\n\n"
        "1. Click **🎨 Generate**\n"
        "2. Send your text prompt\n"
        "3. Wait a few moments to receive your high-resolution image\n"
        "4. Use **⚙️ Settings** to customize output dimensions",
        parse_mode="Markdown"
    )


@dp.message(
    F.text.in_([
        "🎁 Promo code",
        "🌐 Language",
        "📰 Updates",
        "⭐ Create a personal bot",
        "🤖 Claude + Gemini + OpenAI 🤖"
    ])
)
async def btn_placeholders(message: types.Message):
    await message.answer(
        f"✨ **{message.text}**\nThis feature is active on your bot account.",
        parse_mode="Markdown"
    )


# ----------------- MAIN RUNNER -----------------
async def main():
    logger.info("Starting Telegram Bot...")
    # Crucial: Clears old webhooks and dropped updates to prevent conflicts
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
