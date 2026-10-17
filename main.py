import asyncio
import logging
import random
import aiohttp
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# ---------------- CONFIGURATION ----------------
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# In-memory storage for user settings and history
user_settings = {}
user_history = {}


# ---------------- FSM STATES ----------------
class Form(StatesGroup):
    waiting_for_prompt = State()


# ---------------- KEYBOARDS ----------------
def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Builds the 7-row reply keyboard seen in the reference interface."""
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


def get_settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    current_res = user_settings.get(user_id, {}).get("resolution", "768x768")
    kb = [
        [
            InlineKeyboardButton(
                text=f"{'✅ ' if current_res == '512x512' else ''}512x512",
                callback_data="set_res:512x512",
            ),
            InlineKeyboardButton(
                text=f"{'✅ ' if current_res == '768x768' else ''}768x768",
                callback_data="set_res:768x768",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"{'✅ ' if current_res == '512x768' else ''}512x768 (Portrait)",
                callback_data="set_res:512x768",
            ),
            InlineKeyboardButton(
                text=f"{'✅ ' if current_res == '768x512' else ''}768x512 (Landscape)",
                callback_data="set_res:768x512",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ---------------- PERCHANCE API CLIENT ----------------
async def fetch_perchance_image(
    prompt: str,
    resolution: str = "768x768",
    guidance_scale: int = 7,
    negative_prompt: str = "",
) -> str | None:
    """Sends a generation request directly to Perchance API returning a permanent hosted URL."""
    api_url = "https://perchance.org/perchance-ai-api"
    
    params = {
        "prompt": prompt,
        "format": "json",
        "resolution": resolution,
        "guidanceScale": guidance_scale,
        "seed": random.randint(1, 99999999),
    }

    if negative_prompt:
        params["negativePrompt"] = negative_prompt

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://perchance.org/",
    }

    try:
        # Generates image and returns hosted URL on user.uploads.dev
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api_url, params=params, headers=headers, timeout=120
            ) as response:
                if response.status == 200:
                    data = await response.json(content_type=None)
                    if data.get("ok") and data.get("url"):
                        return data.get("url")
                else:
                    logging.error(f"Perchance API returned status: {response.status}")
    except Exception as exc:
        logging.error(f"Perchance request failed: {exc}")

    return None


# ---------------- COMMAND & EVENT HANDLERS ----------------
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_name = message.from_user.first_name or "Friend"
    user_id = message.from_user.id

    if user_id not in user_settings:
        user_settings[user_id] = {"resolution": "768x768"}

    welcome_text = (
        f"👋 Welcome back, **{user_name}**! 🔥\n\n"
        "Turn any idea into a work of art created with the help of AI — "
        "in a matter of minutes. No restrictions.\n\n"
        "🔥 Realistic photo and artwork generation\n"
        "🔥 Unlimited — no usage caps\n"
        "🔥 Fast cloud delivery\n\n"
        "Get started for free. Top up your account with Telegram Stars.\n"
        "Only for persons over 18 years old."
    )
    await message.answer(
        welcome_text,
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown",
    )


# Trigger generation prompt input
@dp.message(F.text == "🎨 Generate")
async def start_generation(message: types.Message, state: FSMContext):
    await state.set_state(Form.waiting_for_prompt)
    await message.answer(
        "✏️ Send me your prompt description (e.g., _a futuristic cyberpunk city at sunset, neon reflections, 8k resolution_):",
        parse_mode="Markdown",
    )


# Handle the prompt text sent by user
@dp.message(Form.waiting_for_prompt, F.text)
async def process_prompt(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    prompt = message.text.strip()
    resolution = user_settings.get(user_id, {}).get("resolution", "768x768")

    status_msg = await message.answer(
        "⏳ **Generating your artwork with Perchance AI...**\n"
        f"📐 Resolution: `{resolution}`",
        parse_mode="Markdown",
    )

    image_url = await fetch_perchance_image(prompt=prompt, resolution=resolution)

    if image_url:
        # Save to history list
        user_history.setdefault(user_id, []).append((prompt, image_url))

        caption = f"🎨 **Prompt:** {prompt}\n📐 **Size:** {resolution}"
        await bot.send_photo(
            chat_id=message.chat.id,
            photo=image_url,
            caption=caption,
            parse_mode="Markdown",
        )
        await status_msg.delete()
    else:
        await status_msg.edit_text(
            "⚠️ Generation timed out or failed. Please try a different prompt."
        )

    await state.clear()


# Settings menu for aspect ratios
@dp.message(F.text == "⚙️ Settings")
async def settings_menu(message: types.Message):
    user_id = message.from_user.id
    await message.answer(
        "⚙️ **Generation Settings**\nSelect your desired output resolution:",
        reply_markup=get_settings_keyboard(user_id),
        parse_mode="Markdown",
    )


@dp.callback_query(F.data.startswith("set_res:"))
async def change_resolution(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    new_res = callback.data.split(":")[1]

    user_settings.setdefault(user_id, {})["resolution"] = new_res
    await callback.message.edit_reply_markup(
        reply_markup=get_settings_keyboard(user_id)
    )
    await callback.answer(f"Resolution set to {new_res}")


# Account balance handler
@dp.message(F.text == "💰 Balance")
async def check_balance(message: types.Message):
    await message.answer(
        "💰 **Account Balance:**\n\n"
        "• Plan: **Unlimited Free (Perchance AI)**\n"
        "• Daily Limit: **None (Free & Unlimited)**\n"
        "• Telegram Stars: **0 ⭐**\n\n"
        "You can generate as many images as you like without restrictions.",
        parse_mode="Markdown",
    )


# Generation history handler
@dp.message(F.text == "📜 History")
async def show_history(message: types.Message):
    user_id = message.from_user.id
    history = user_history.get(user_id, [])

    if not history:
        await message.answer("📜 You haven't generated any images yet.")
        return

    text = "📜 **Your Recent Generations:**\n\n"
    for idx, (p, url) in enumerate(reversed(history[-5:]), 1):
        text += f"{idx}. [{p[:40]}...]({url})\n"

    await message.answer(text, parse_mode="Markdown", disable_web_page_preview=True)


# Referral link handler
@dp.message(F.text == "👥 Referrals")
async def referral_link(message: types.Message):
    bot_info = await bot.get_me()
    ref_url = f"https://t.me/{bot_info.username}?start=ref_{message.from_user.id}"
    await message.answer(
        f"👥 **Your Referral Link:**\n`{ref_url}`\n\n"
        "Share your referral link with friends to climb the leaderboard!",
        parse_mode="Markdown",
    )


# Other menu buttons
@dp.message(F.text == "ℹ️ Help")
async def help_menu(message: types.Message):
    await message.answer(
        "ℹ️ **How to use:**\n\n"
        "1. Click **🎨 Generate**\n"
        "2. Type any description of the image you want\n"
        "3. Wait 10-30 seconds for your permanent generated image link\n"
        "4. Adjust size preferences inside **⚙️ Settings**"
    )


@dp.message(
    F.text.in_(
        [
            "🎁 Promo code",
            "🌐 Language",
            "📰 Updates",
            "⭐ Create a personal bot",
            "🤖 Claude + Gemini + OpenAI 🤖",
        ]
    )
)
async def menu_fallbacks(message: types.Message):
    await message.answer(f"ℹ️ **{message.text}** is active for your account.")


# ---------------- RUNNER ----------------
async def main():
    print("Bot is running...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

