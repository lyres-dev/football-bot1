import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import os
from dotenv import load_dotenv

from api_client import OddsAPIClient
from analyzer import FootballAnalyzer

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
CLAUDE_API_KEY = os.getenv("GEMINI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

odds_client = OddsAPIClient(ODDS_API_KEY)
analyzer = FootballAnalyzer(CLAUDE_API_KEY)

# ─── States ───────────────────────────────────────────────────────────────────

class MatchStates(StatesGroup):
    choosing_league = State()
    choosing_match = State()
    choosing_analysis = State()

# ─── Keyboards ────────────────────────────────────────────────────────────────

LEAGUES = {
    "soccer_epl": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ",
    "soccer_spain_la_liga": "🇪🇸 Ла Лига",
    "soccer_germany_bundesliga": "🇩🇪 Бундеслига",
    "soccer_italy_serie_a": "🇮🇹 Серия А",
    "soccer_france_ligue_one": "🇫🇷 Лига 1",
    "soccer_uefa_champs_league": "🏆 Лига Чемпионов",
    "soccer_russia_premier_league": "🇷🇺 РПЛ",
}

def leagues_keyboard():
    buttons = []
    for key, name in LEAGUES.items():
        buttons.append([InlineKeyboardButton(text=name, callback_data=f"league:{key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def matches_keyboard(matches):
    buttons = []
    for i, match in enumerate(matches[:10]):
        home = match.get("home_team", "?")
        away = match.get("away_team", "?")
        label = f"{home} vs {away}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"match:{i}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back:leagues")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def analysis_keyboard():
    buttons = [
        [InlineKeyboardButton(text="🏆 Прогноз победителя", callback_data="analysis:winner")],
        [InlineKeyboardButton(text="⚽ Прогноз счёта", callback_data="analysis:score")],
        [InlineKeyboardButton(text="📊 Статистика команд", callback_data="analysis:stats")],
        [InlineKeyboardButton(text="🎯 Тотал голов", callback_data="analysis:total")],
        [InlineKeyboardButton(text="🔥 Обе забьют?", callback_data="analysis:btts")],
        [InlineKeyboardButton(text="📋 Полный анализ", callback_data="analysis:full")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back:matches")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ─── Handlers ─────────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    text = (
        "👋 Привет! Я <b>Football Predictor Bot</b> 🤖⚽\n\n"
        "Анализирую матчи с помощью реальных данных + ИИ и даю прогнозы:\n\n"
        "🏆 Победитель матча\n"
        "⚽ Точный счёт\n"
        "🎯 Тотал голов (больше/меньше 2.5)\n"
        "🔥 Обе команды забьют\n"
        "📊 Статистика и форма команд\n\n"
        "Выбери лигу для начала:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=leagues_keyboard())
    await state.set_state(MatchStates.choosing_league)

@dp.message(Command("leagues"))
async def cmd_leagues(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🌍 Выбери лигу:", reply_markup=leagues_keyboard())
    await state.set_state(MatchStates.choosing_league)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "📖 <b>Команды бота:</b>\n\n"
        "/start — начать работу\n"
        "/leagues — выбрать лигу\n"
        "/help — эта справка\n\n"
        "💡 <b>Как пользоваться:</b>\n"
        "1. Выбери лигу\n"
        "2. Выбери матч\n"
        "3. Выбери тип прогноза\n\n"
        "⚠️ <i>Прогнозы носят информационный характер и не являются рекомендацией к ставкам.</i>"
    )
    await message.answer(text, parse_mode="HTML")

@dp.callback_query(lambda c: c.data.startswith("league:"))
async def handle_league_choice(callback: types.CallbackQuery, state: FSMContext):
    league_key = callback.data.split(":", 1)[1]
    league_name = LEAGUES.get(league_key, "Неизвестная лига")

    await callback.message.edit_text(f"⏳ Загружаю матчи {league_name}...")

    try:
        matches = await odds_client.get_upcoming_matches(league_key)
        if not matches:
            await callback.message.edit_text(
                f"😔 Нет предстоящих матчей для {league_name}.\n\nВыбери другую лигу:",
                reply_markup=leagues_keyboard()
            )
            return

        await state.update_data(matches=matches, league_key=league_key, league_name=league_name)
        await state.set_state(MatchStates.choosing_match)

        text = f"📅 <b>Ближайшие матчи — {league_name}:</b>\n\nВыбери матч для анализа:"
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=matches_keyboard(matches))

    except Exception as e:
        logger.error(f"Error fetching matches: {e}")
        await callback.message.edit_text(
            "❌ Ошибка загрузки матчей. Попробуй позже.",
            reply_markup=leagues_keyboard()
        )

@dp.callback_query(lambda c: c.data.startswith("match:"))
async def handle_match_choice(callback: types.CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    matches = data.get("matches", [])

    if idx >= len(matches):
        await callback.answer("Матч не найден")
        return

    match = matches[idx]
    await state.update_data(selected_match=match, match_idx=idx)
    await state.set_state(MatchStates.choosing_analysis)

    home = match.get("home_team", "?")
    away = match.get("away_team", "?")
    date_str = match.get("commence_time_str", "Дата неизвестна")

    text = (
        f"⚽ <b>{home} vs {away}</b>\n"
        f"🕐 {date_str}\n\n"
        f"Выбери тип анализа:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=analysis_keyboard())

@dp.callback_query(lambda c: c.data.startswith("analysis:"))
async def handle_analysis_choice(callback: types.CallbackQuery, state: FSMContext):
    analysis_type = callback.data.split(":", 1)[1]
    data = await state.get_data()
    match = data.get("selected_match")

    if not match:
        await callback.answer("Матч не найден, начни заново /start")
        return

    home = match.get("home_team", "?")
    away = match.get("away_team", "?")

    type_names = {
        "winner": "🏆 Прогноз победителя",
        "score": "⚽ Прогноз счёта",
        "stats": "📊 Статистика команд",
        "total": "🎯 Тотал голов",
        "btts": "🔥 Обе забьют?",
        "full": "📋 Полный анализ",
    }

    await callback.message.edit_text(
        f"🤖 <b>Анализирую:</b> {home} vs {away}\n"
        f"⏳ {type_names.get(analysis_type, 'Анализ')}...\n\n"
        f"<i>Подключаю ИИ и собираю данные...</i>",
        parse_mode="HTML"
    )

    try:
        result = await analyzer.analyze(match, analysis_type)
        back_btn = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Другой анализ", callback_data=f"match:{data.get('match_idx', 0)}")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back:leagues")],
        ])
        await callback.message.edit_text(result, parse_mode="HTML", reply_markup=back_btn)

    except Exception as e:
        logger.error(f"Analysis error: {e}")
        await callback.message.edit_text(
            "❌ Ошибка анализа. Попробуй ещё раз.",
            reply_markup=analysis_keyboard()
        )

@dp.callback_query(lambda c: c.data.startswith("back:"))
async def handle_back(callback: types.CallbackQuery, state: FSMContext):
    target = callback.data.split(":", 1)[1]

    if target == "leagues":
        await state.set_state(MatchStates.choosing_league)
        await callback.message.edit_text("🌍 Выбери лигу:", reply_markup=leagues_keyboard())

    elif target == "matches":
        data = await state.get_data()
        matches = data.get("matches", [])
        league_name = data.get("league_name", "")
        if matches:
            await state.set_state(MatchStates.choosing_match)
            await callback.message.edit_text(
                f"📅 <b>Ближайшие матчи — {league_name}:</b>",
                parse_mode="HTML",
                reply_markup=matches_keyboard(matches)
            )
        else:
            await callback.message.edit_text("🌍 Выбери лигу:", reply_markup=leagues_keyboard())

async def main():
    logger.info("Starting Football Predictor Bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
