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

def report_predictions_keyboard(predictions):
    buttons = []
    for pred in predictions:
        icon = "✅" if pred.get("is_correct") == True else ("❌" if pred.get("is_correct") == False else "⏳")
        label = f"{icon} {pred['home_team']} vs {pred['away_team']}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"report_detail:{pred['id']}")])
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="back:leagues")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

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
        "📋 Автоотчёт по всем прогнозам\n\n"
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
        "/report — полный автоотчёт по прогнозам\n"
        "/help — эта справка\n\n"
        "💡 <b>Как пользоваться:</b>\n"
        "1. Выбери лигу и матч\n"
        "2. Получи прогноз — сохранится автоматически\n"
        "3. /report — бот сам проверит все матчи и покажет отчёт\n\n"
        "⚠️ <i>Прогнозы носят информационный характер.</i>"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("report"))
async def cmd_report(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("⏳ Проверяю результаты матчей...")
    await generate_auto_report(message.from_user.id, message.answer)

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
        f"🤖 <b>Анализирую:</b> {home} vs {away}\n"
        f"⏳ {ANALYSIS_NAMES.get(analysis_type)}...\n"
        f"<i>Загружаю статистику и считаю Эло...</i>",
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
            elo_data=elo_data, value_bets=value_bets
        )

        pred_id = await db.save_prediction(callback.from_user.id, match, analysis_type, result)

        back_btn = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Другой анализ", callback_data=f"match:{data.get('match_idx', 0)}")],
            [InlineKeyboardButton(text="📊 Отчёт", callback_data="report:auto")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back:leagues")],
        ])
        await callback.message.edit_text(
            result + f"\n\n<i>💾 Прогноз сохранён (#{pred_id})</i>",
            parse_mode="HTML", reply_markup=back_btn
        )
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        await callback.message.edit_text("❌ Ошибка анализа. Попробуй ещё раз.", reply_markup=analysis_keyboard())

async def generate_auto_report(user_id: int, reply_func):
    """Показываем отчёт сразу из базы, проверку запускаем в фоне."""
    all_preds = await db.get_all_predictions(user_id)

    if not all_preds:
        await reply_func("📊 У тебя ещё нет прогнозов. Выбери матч и получи первый прогноз!")
        return

    # Сначала показываем что уже есть в базе
    resolved = [p for p in all_preds if p.get("is_correct") is not None]
    pending = [p for p in all_preds if p.get("is_correct") is None]
    correct = [p for p in resolved if p.get("is_correct") == True]

    pct = round(len(correct) / len(resolved) * 100) if resolved else 0
    emoji = "🔥" if pct >= 60 else "👍" if pct >= 40 else "📉"

    text = f"📊 <b>ОТЧЁТ ПО ПРОГНОЗАМ</b>\n\n"
    text += f"Всего прогнозов: {len(all_preds)}\n"
    text += f"Проверено: {len(resolved)}\n"
    text += f"Ожидают результата: {len(pending)}\n"
    text += f"Точных: {len(correct)}\n"

    if resolved:
        text += f"{emoji} Точность: <b>{pct}%</b>\n\n"

        by_type = {}
        for p in resolved:
            t = p["analysis_type"]
            if t not in by_type:
                by_type[t] = {"total": 0, "correct": 0}
            by_type[t]["total"] += 1
            if p.get("is_correct"):
                by_type[t]["correct"] += 1

        text += "━━━━━━━━━━━━━━━━━━━━\n"
        text += "📈 <b>По типам:</b>\n"
        for t, v in by_type.items():
            p2 = round(v["correct"] / v["total"] * 100)
            text += f"{ANALYSIS_NAMES.get(t, t)}: {v['correct']}/{v['total']} ({p2}%)\n"

        text += "\n━━━━━━━━━━━━━━━━━━━━\n"
        text += "🕐 <b>Результаты матчей:</b>\n"
        for p in resolved[-10:]:
            icon = "✅" if p["is_correct"] else "❌"
            score = f"{p['result_home']}:{p['result_away']}" if p.get("result_home") is not None else "—"
            text += f"{icon} {p['home_team']} vs {p['away_team']} [{score}] — {ANALYSIS_NAMES.get(p['analysis_type'], p['analysis_type'])}\n"
    else:
        text += "\n⏳ Результаты матчей ещё проверяются...\n"

    if pending:
        text += f"\n🔄 <i>Фоновая проверка {len(pending)} матчей запущена — результаты появятся автоматически</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="report:auto")],
        [InlineKeyboardButton(text="📋 Детали по матчу", callback_data="report:list")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back:leagues")],
    ])

    await reply_func(text, parse_mode="HTML", reply_markup=kb)

    # Запускаем проверку в фоне — не блокирует ответ
    if pending and stats_client:
        asyncio.create_task(check_pending_in_background(user_id, pending))


async def check_pending_in_background(user_id: int, pending: list):
    """Фоновая проверка результатов — не блокирует бота."""
    for pred in pending:
        try:
            result = await stats_client.find_match_result(
                pred["home_team"], pred["away_team"],
                str(pred["match_date"])[:10] if pred["match_date"] else None,
                pred.get("sport", "soccer_epl")
            )
            if result:
                from scheduler import check_prediction_correct
                is_correct, explanation = await check_prediction_correct(
                    pred, result["home_score"], result["away_score"]
                )
                await db.resolve_prediction(
                    pred["id"], result["home_score"], result["away_score"], is_correct
                )
                icon = "✅" if is_correct else "❌"
                await bot.send_message(
                    user_id,
                    f"{icon} <b>Результат найден!</b>\n\n"
                    f"⚽ {pred['home_team']} {result['home_score']}:{result['away_score']} {pred['away_team']}\n"
                    f"🎯 {ANALYSIS_NAMES.get(pred['analysis_type'], pred['analysis_type'])}\n"
                    f"📊 {explanation}\n\n"
                    f"<i>Нажми /report чтобы увидеть обновлённый отчёт</i>",
                    parse_mode="HTML"
                )
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Background check error for pred {pred['id']}: {e}")


    # Перезагружаем с обновлёнными данными
    all_preds = await db.get_all_predictions(user_id)
    resolved = [p for p in all_preds if p.get("is_correct") is not None]
    pending = [p for p in all_preds if p.get("is_correct") is None]
    correct = [p for p in resolved if p.get("is_correct") == True]

    pct = round(len(correct) / len(resolved) * 100) if resolved else 0
    emoji = "🔥" if pct >= 60 else "👍" if pct >= 40 else "📉"

    text = f"📊 <b>ПОЛНЫЙ ОТЧЁТ ПО ПРОГНОЗАМ</b>\n\n"
    text += f"Всего прогнозов: {len(all_preds)}\n"
    text += f"Проверено: {len(resolved)}\n"
    text += f"Ожидают результата: {len(pending)}\n"
    text += f"Точных: {len(correct)}\n"

    if resolved:
        text += f"{emoji} Точность: <b>{pct}%</b>\n\n"

        # По типам
        by_type = {}
        for p in resolved:
            t = p["analysis_type"]
            if t not in by_type:
                by_type[t] = {"total": 0, "correct": 0}
            by_type[t]["total"] += 1
            if p.get("is_correct"):
                by_type[t]["correct"] += 1

        text += "━━━━━━━━━━━━━━━━━━━━\n"
        text += "📈 <b>По типам:</b>\n"
        for t, v in by_type.items():
            p2 = round(v["correct"] / v["total"] * 100)
            text += f"{ANALYSIS_NAMES.get(t, t)}: {v['correct']}/{v['total']} ({p2}%)\n"

        # Последние результаты
        text += "\n━━━━━━━━━━━━━━━━━━━━\n"
        text += "🕐 <b>Результаты матчей:</b>\n"
        for p in resolved[-10:]:
            icon = "✅" if p["is_correct"] else "❌"
            score = f"{p['result_home']}:{p['result_away']}" if p.get("result_home") is not None else "—"
            text += f"{icon} {p['home_team']} vs {p['away_team']} [{score}] — {ANALYSIS_NAMES.get(p['analysis_type'], p['analysis_type'])}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Детали по матчу", callback_data="report:list")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back:leagues")],
    ])
    await reply_func(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "report:auto")
async def handle_report_auto(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("⏳ Проверяю результаты матчей...")
    await generate_auto_report(callback.from_user.id, callback.message.edit_text)

@dp.callback_query(lambda c: c.data == "report:list")
async def handle_report_list(callback: types.CallbackQuery, state: FSMContext):
    all_preds = await db.get_all_predictions(callback.from_user.id)
    if not all_preds:
        await callback.answer("Нет прогнозов")
        return
    await callback.message.edit_text(
        "📋 <b>Все прогнозы:</b>\n\nВыбери матч для деталей:",
        parse_mode="HTML",
        reply_markup=report_predictions_keyboard(all_preds[-15:])
    )

@dp.callback_query(lambda c: c.data.startswith("report_detail:"))
async def handle_report_detail(callback: types.CallbackQuery, state: FSMContext):
    pred_id = int(callback.data.split(":")[1])
    pred = await db.get_prediction_by_id(pred_id, callback.from_user.id)
    if not pred:
        await callback.answer("Прогноз не найден")
        return

    icon = "✅" if pred.get("is_correct") == True else ("❌" if pred.get("is_correct") == False else "⏳")
    score = f"{pred['result_home']}:{pred['result_away']}" if pred.get("result_home") is not None else "Ещё не сыгран"
    status = "Зашёл" if pred.get("is_correct") == True else ("Не зашёл" if pred.get("is_correct") == False else "Ожидает")

    text = (
        f"{icon} <b>{pred['home_team']} vs {pred['away_team']}</b>\n\n"
        f"🎯 Тип: {ANALYSIS_NAMES.get(pred['analysis_type'], pred['analysis_type'])}\n"
        f"📅 Дата матча: {pred['match_date']}\n"
        f"⚽ Счёт: {score}\n"
        f"📊 Статус: {status}\n\n"
        f"<b>Текст прогноза:</b>\n{pred['prediction_text'][:800]}..."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="report:list")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back:leagues")],
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

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
