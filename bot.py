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
from football_stats import FootballStatsClient
from database import db
from scheduler import MatchScheduler
from elo import elo

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
API_FOOTBALL_KEY = os.getenv("FOOTBALL_DATA_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

odds_client = OddsAPIClient(ODDS_API_KEY)
analyzer = FootballAnalyzer(GROQ_API_KEY)
stats_client = FootballStatsClient(API_FOOTBALL_KEY) if API_FOOTBALL_KEY else None

class MatchStates(StatesGroup):
    choosing_league = State()
    choosing_match = State()
    choosing_analysis = State()

class ResultStates(StatesGroup):
    choosing_prediction = State()
    entering_score = State()
    confirming_correct = State()

LEAGUES = {
    "soccer_epl": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 АПЛ",
    "soccer_spain_la_liga": "🇪🇸 Ла Лига",
    "soccer_germany_bundesliga": "🇩🇪 Бундеслига",
    "soccer_italy_serie_a": "🇮🇹 Серия А",
    "soccer_france_ligue_one": "🇫🇷 Лига 1",
    "soccer_uefa_champs_league": "🏆 Лига Чемпионов",
    "soccer_russia_premier_league": "🇷🇺 РПЛ",
}

ANALYSIS_NAMES = {
    "winner": "🏆 Победитель",
    "score": "⚽ Счёт",
    "stats": "📊 Статистика",
    "total": "🎯 Тотал",
    "btts": "🔥 Обе забьют",
    "full": "📋 Полный анализ",
}

def leagues_keyboard():
    buttons = [[InlineKeyboardButton(text=name, callback_data=f"league:{key}")] for key, name in LEAGUES.items()]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def matches_keyboard(matches):
    buttons = []
    for i, match in enumerate(matches[:10]):
        label = f"{match.get('home_team','?')} vs {match.get('away_team','?')}"
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

def pending_predictions_keyboard(predictions):
    buttons = []
    for pred in predictions:
        label = f"{pred['home_team']} vs {pred['away_team']} — {ANALYSIS_NAMES.get(pred['analysis_type'], pred['analysis_type'])}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"resolve:{pred['id']}")])
    buttons.append([InlineKeyboardButton(text="📊 Полный отчёт", callback_data="stats:show")])
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="back:leagues")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def correct_keyboard(pred_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Зашло", callback_data=f"correct:{pred_id}:yes"),
            InlineKeyboardButton(text="❌ Не зашло", callback_data=f"correct:{pred_id}:no"),
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="results:menu")],
    ])

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    text = (
        "👋 Привет! Я <b>Football Predictor Bot</b> 🤖⚽\n\n"
        "🏆 Прогноз победителя\n"
        "⚽ Точный счёт\n"
        "🎯 Тотал голов\n"
        "🔥 Обе команды забьют\n"
        "📊 Статистика + Рейтинг Эло\n"
        "💎 Value Bet детектор\n"
        "📋 Автоотчёт по прогнозам\n\n"
        "Выбери лигу для начала:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=leagues_keyboard())
    await state.set_state(MatchStates.choosing_league)

@dp.message(Command("leagues"))
async def cmd_leagues(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🌍 Выбери лигу:", reply_markup=leagues_keyboard())
    await state.set_state(MatchStates.choosing_league)

@dp.message(Command("results"))
async def cmd_results(message: types.Message, state: FSMContext):
    await state.clear()
    await show_results_menu(message.answer, message.from_user.id, state)

@dp.message(Command("report"))
async def cmd_report(message: types.Message, state: FSMContext):
    await state.clear()
    await show_full_report(message.answer, message.from_user.id)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    text = (
        "📖 <b>Команды бота:</b>\n\n"
        "/start — начать работу\n"
        "/leagues — выбрать лигу\n"
        "/results — ввести результаты вручную\n"
        "/report — полный отчёт по прогнозам\n"
        "/help — эта справка\n\n"
        "💡 <b>Как пользоваться:</b>\n"
        "1. Выбери лигу и матч\n"
        "2. Получи прогноз — он сохранится\n"
        "3. Бот автоматически проверит результат через 3 часа\n"
        "4. /report — смотри точность своих прогнозов\n\n"
        "⚠️ <i>Прогнозы носят информационный характер.</i>"
    )
    await message.answer(text, parse_mode="HTML")

@dp.callback_query(lambda c: c.data.startswith("league:"))
async def handle_league_choice(callback: types.CallbackQuery, state: FSMContext):
    league_key = callback.data.split(":", 1)[1]
    league_name = LEAGUES.get(league_key, "")
    await callback.message.edit_text(f"⏳ Загружаю матчи {league_name}...")
    try:
        matches = await odds_client.get_upcoming_matches(league_key)
        if not matches:
            await callback.message.edit_text(
                f"😔 Нет предстоящих матчей для {league_name}.",
                reply_markup=leagues_keyboard()
            )
            return
        await state.update_data(matches=matches, league_key=league_key, league_name=league_name)
        await state.set_state(MatchStates.choosing_match)
        await callback.message.edit_text(
            f"📅 <b>Ближайшие матчи — {league_name}:</b>\n\nВыбери матч:",
            parse_mode="HTML", reply_markup=matches_keyboard(matches)
        )
    except Exception as e:
        logger.error(f"Error fetching matches: {e}")
        await callback.message.edit_text("❌ Ошибка загрузки матчей.", reply_markup=leagues_keyboard())

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
    date_str = match.get("commence_time_str", "")
    await callback.message.edit_text(
        f"⚽ <b>{home} vs {away}</b>\n🕐 {date_str}\n\nВыбери тип анализа:",
        parse_mode="HTML", reply_markup=analysis_keyboard()
    )

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
    await callback.message.edit_text(
        f"🤖 <b>Анализирую:</b> {home} vs {away}\n⏳ {ANALYSIS_NAMES.get(analysis_type)}...\n<i>Загружаю статистику и считаю Эло...</i>",
        parse_mode="HTML"
    )
    try:
        home_stats, away_stats = None, None
        if stats_client:
            league_key = data.get("league_key", "soccer_epl")
            try:
                home_stats, away_stats = await asyncio.gather(
                    stats_client.get_full_team_stats(home, league_key),
                    stats_client.get_full_team_stats(away, league_key),
                    return_exceptions=True
                )
                if isinstance(home_stats, Exception): home_stats = None
                if isinstance(away_stats, Exception): away_stats = None
            except Exception as e:
                logger.warning(f"Stats fetch error: {e}")

        elo_data = elo.predict_match(home, away, home_stats, away_stats)
        value_bets = elo.detect_value_bets(elo_data, match)

        result = await analyzer.analyze_with_elo(
            match, analysis_type, home_stats, away_stats,
            elo_data=elo_data,
            value_bets=value_bets
        )

        pred_id = await db.save_prediction(callback.from_user.id, match, analysis_type, result)

        back_btn = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Другой анализ", callback_data=f"match:{data.get('match_idx', 0)}")],
            [InlineKeyboardButton(text="📋 Мои прогнозы", callback_data="results:menu")],
            [InlineKeyboardButton(text="📊 Отчёт", callback_data="stats:show")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back:leagues")],
        ])
        await callback.message.edit_text(
            result + f"\n\n<i>💾 Прогноз сохранён (#{pred_id})</i>",
            parse_mode="HTML", reply_markup=back_btn
        )
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        await callback.message.edit_text("❌ Ошибка анализа. Попробуй ещё раз.", reply_markup=analysis_keyboard())

async def show_results_menu(reply_func, user_id: int, state: FSMContext):
    predictions = await db.get_pending_predictions(user_id)
    if not predictions:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Полный отчёт", callback_data="stats:show")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back:leagues")],
        ])
        await reply_func(
            "📋 <b>Нет прогнозов без результата</b>\n\nВсе матчи уже проверены автоматически!",
            parse_mode="HTML", reply_markup=kb
        )
        return
    text = "📋 <b>Прогнозы без результата:</b>\n\nВыбери матч чтобы ввести счёт вручную:"
    await reply_func(text, parse_mode="HTML", reply_markup=pending_predictions_keyboard(predictions))
    await state.set_state(ResultStates.choosing_prediction)

async def show_full_report(reply_func, user_id: int):
    stats = await db.get_stats(user_id)
    if stats["resolved"] == 0:
        await reply_func(
            "📊 <b>Статистика пуста</b>\n\nПолучи прогнозы — бот автоматически проверит результаты через 3 часа после матча!",
            parse_mode="HTML"
        )
        return
    pct = round(stats["correct"] / stats["resolved"] * 100)
    emoji = "🔥" if pct >= 60 else "👍" if pct >= 40 else "📉"
    text = f"📊 <b>ОТЧЁТ ПО ПРОГНОЗАМ</b>\n\n"
    text += f"Всего прогнозов: {stats['total']}\n"
    text += f"Проверено: {stats['resolved']}\n"
    text += f"Точных: {stats['correct']}\n"
    text += f"{emoji} Точность: <b>{pct}%</b>\n\n"
    if stats["by_type"]:
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        text += "📈 <b>По типам прогнозов:</b>\n"
        for row in stats["by_type"]:
            t = row["total"]
            c = row["correct"] or 0
            p = round(c / t * 100) if t > 0 else 0
            name = ANALYSIS_NAMES.get(row["analysis_type"], row["analysis_type"])
            text += f"{name}: {c}/{t} ({p}%)\n"
    if stats["recent"]:
        text += "\n━━━━━━━━━━━━━━━━━━━━\n"
        text += "🕐 <b>Последние результаты:</b>\n"
        for r in stats["recent"]:
            icon = "✅" if r["is_correct"] else "❌"
            score = f"{r['result_home']}:{r['result_away']}" if r["result_home"] is not None else "—"
            auto = " 🤖" if r.get("auto_checked") else ""
            text += f"{icon}{auto} {r['home_team']} vs {r['away_team']} [{score}]\n"
    await reply_func(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Ввести вручную", callback_data="results:menu")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back:leagues")],
        ])
    )

@dp.callback_query(lambda c: c.data == "results:menu")
async def handle_results_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await show_results_menu(callback.message.edit_text, callback.from_user.id, state)

@dp.callback_query(lambda c: c.data.startswith("resolve:"))
async def handle_resolve(callback: types.CallbackQuery, state: FSMContext):
    pred_id = int(callback.data.split(":")[1])
    pred = await db.get_prediction_by_id(pred_id, callback.from_user.id)
    if not pred:
        await callback.answer("Прогноз не найден")
        return
    await state.update_data(resolving_pred_id=pred_id, resolving_pred=pred)
    await state.set_state(ResultStates.entering_score)
    await callback.message.edit_text(
        f"⚽ <b>{pred['home_team']} vs {pred['away_team']}</b>\n"
        f"📅 {pred['match_date']}\n"
        f"🎯 Тип: {ANALYSIS_NAMES.get(pred['analysis_type'], pred['analysis_type'])}\n\n"
        f"Введи счёт в формате <b>2:1</b>:",
        parse_mode="HTML"
    )

@dp.message(ResultStates.entering_score)
async def handle_score_input(message: types.Message, state: FSMContext):
    text = message.text.strip().replace("-", ":").replace(" ", "")
    try:
        parts = text.split(":")
        home_score = int(parts[0])
        away_score = int(parts[1])
    except:
        await message.answer("❌ Неверный формат. Введи счёт как <b>2:1</b>", parse_mode="HTML")
        return
    data = await state.get_data()
    pred = data.get("resolving_pred")
    pred_id = data.get("resolving_pred_id")
    await state.update_data(home_score=home_score, away_score=away_score)
    await state.set_state(ResultStates.confirming_correct)
    await message.answer(
        f"⚽ Счёт: <b>{pred['home_team']} {home_score}:{away_score} {pred['away_team']}</b>\n\n"
        f"Прогноз «{ANALYSIS_NAMES.get(pred['analysis_type'])}» — зашёл?",
        parse_mode="HTML",
        reply_markup=correct_keyboard(pred_id)
    )

@dp.callback_query(lambda c: c.data.startswith("correct:"))
async def handle_correct(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    pred_id = int(parts[1])
    is_correct = parts[2] == "yes"
    data = await state.get_data()
    home_score = data.get("home_score", 0)
    away_score = data.get("away_score", 0)
    await db.resolve_prediction(pred_id, home_score, away_score, is_correct)
    await state.clear()
    result_text = "✅ Зашло! 🎉" if is_correct else "❌ Не зашло"
    stats = await db.get_stats(callback.from_user.id)
    pct = round(stats["correct"] / stats["resolved"] * 100) if stats["resolved"] > 0 else 0
    await callback.message.edit_text(
        f"{result_text}\n\n"
        f"📊 Статистика: <b>{stats['correct']}/{stats['resolved']} ({pct}%)</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Ещё результаты", callback_data="results:menu")],
            [InlineKeyboardButton(text="📊 Полный отчёт", callback_data="stats:show")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back:leagues")],
        ])
    )

@dp.callback_query(lambda c: c.data == "stats:show")
async def handle_stats(callback: types.CallbackQuery, state: FSMContext):
    await show_full_report(callback.message.edit_text, callback.from_user.id)

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
                parse_mode="HTML", reply_markup=matches_keyboard(matches)
            )
        else:
            await callback.message.edit_text("🌍 Выбери лигу:", reply_markup=leagues_keyboard())

async def main():
    await db.connect()
    if stats_client:
        scheduler = MatchScheduler(bot, stats_client)
        await scheduler.start()
        logger.info("Match result scheduler started")
    logger.info("Starting Football Predictor Bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

