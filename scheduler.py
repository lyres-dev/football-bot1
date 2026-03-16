import asyncio
import logging
from datetime import datetime, timezone, timedelta
from aiogram import Bot
from database import db
from football_stats import FootballStatsClient
import os

logger = logging.getLogger(__name__)

CHECK_DELAY_HOURS = 3  # Проверять через 3 часа после начала матча
CHECK_INTERVAL_SECONDS = 300  # Каждые 5 минут проверяем очередь

# Результат матча → структурированная проверка прогноза
async def check_prediction_correct(pred: dict, home_score: int, away_score: int) -> tuple[bool, str]:
    """Автоматически проверяет зашёл ли прогноз по типу анализа."""
    analysis_type = pred["analysis_type"]
    home = pred["home_team"]
    away = pred["away_team"]
    text = pred["prediction_text"].lower()

    result = None
    explanation = ""

    if analysis_type == "winner":
        if home_score > away_score:
            actual_winner = home
        elif away_score > home_score:
            actual_winner = away
        else:
            actual_winner = "ничья"

        # Ищем прогноз в тексте
        if "ничья" in actual_winner:
            result = "ничья" in text or "draw" in text
        else:
            result = actual_winner.lower() in text
        explanation = f"Победил: {actual_winner} ({home_score}:{away_score})"

    elif analysis_type == "score":
        predicted_score = f"{home_score}:{away_score}"
        alt_score = f"{home_score}-{away_score}"
        result = predicted_score in text or alt_score in text
        explanation = f"Счёт: {home_score}:{away_score}"

    elif analysis_type == "total":
        total = home_score + away_score
        over = total > 2.5
        if over:
            result = "больше" in text or "over" in text or "тб" in text
        else:
            result = "меньше" in text or "under" in text or "тм" in text
        explanation = f"Тотал: {total} голов ({'больше' if over else 'меньше'} 2.5)"

    elif analysis_type == "btts":
        both_scored = home_score > 0 and away_score > 0
        if both_scored:
            result = "да" in text[:500] or "yes" in text[:500]
        else:
            result = "нет" in text[:500] or "no" in text[:500]
        explanation = f"Обе забили: {'да' if both_scored else 'нет'} ({home_score}:{away_score})"

    elif analysis_type in ("stats", "full"):
        # Для статистики и полного анализа — проверяем победителя
        if home_score > away_score:
            actual_winner = home
        elif away_score > home_score:
            actual_winner = away
        else:
            actual_winner = "ничья"
        result = actual_winner.lower() in text or "ничья" in text
        explanation = f"Итог: {home} {home_score}:{away_score} {away}"

    return (result or False), explanation


class MatchScheduler:
    def __init__(self, bot: Bot, stats_client: FootballStatsClient):
        self.bot = bot
        self.stats_client = stats_client
        self.running = False

    async def start(self):
        self.running = True
        logger.info("Scheduler started")
        asyncio.create_task(self._loop())

    async def _loop(self):
        while self.running:
            try:
                await self._check_pending_matches()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def _check_pending_matches(self):
        """Проверяем матчи которые должны были завершиться."""
        pending = await db.get_predictions_to_check(CHECK_DELAY_HOURS)
        if not pending:
            return

        logger.info(f"Checking {len(pending)} predictions...")
        checked_fixtures = {}  # кэш чтобы не дублировать запросы

        for pred in pending:
            try:
                fixture_id = pred.get("fixture_id")
                match_key = f"{pred['home_team']}_{pred['away_team']}_{pred['match_date']}"

                # Получаем результат матча (с кэшем)
                if match_key not in checked_fixtures:
                    result = await self.stats_client.get_match_result(
                        pred["home_team"], pred["away_team"]
                    )
                    checked_fixtures[match_key] = result
                else:
                    result = checked_fixtures[match_key]

                if not result:
                    logger.info(f"Match not finished yet: {match_key}")
                    continue

                home_score = result["home_score"]
                away_score = result["away_score"]

                # Автоматически проверяем прогноз
                is_correct, explanation = await check_prediction_correct(pred, home_score, away_score)

                # Сохраняем результат
                await db.resolve_prediction(pred["id"], home_score, away_score, is_correct)

                # Отправляем уведомление пользователю
                await self._notify_user(pred, home_score, away_score, is_correct, explanation)

            except Exception as e:
                logger.error(f"Error checking prediction {pred['id']}: {e}")

    async def _notify_user(self, pred: dict, home_score: int, away_score: int,
                           is_correct: bool, explanation: str):
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        ANALYSIS_NAMES = {
            "winner": "🏆 Победитель",
            "score": "⚽ Счёт",
            "stats": "📊 Статистика",
            "total": "🎯 Тотал",
            "btts": "🔥 Обе забьют",
            "full": "📋 Полный анализ",
        }

        icon = "✅" if is_correct else "❌"
        result_word = "ЗАШЁЛ" if is_correct else "НЕ ЗАШЁЛ"

        text = (
            f"{icon} <b>Прогноз {result_word}!</b>\n\n"
            f"⚽ {pred['home_team']} {home_score}:{away_score} {pred['away_team']}\n"
            f"🎯 Тип: {ANALYSIS_NAMES.get(pred['analysis_type'], pred['analysis_type'])}\n"
            f"📊 {explanation}\n\n"
            f"<i>Прогноз #{pred['id']}</i>"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 Мой отчёт", callback_data="stats:show")],
        ])

        try:
            await self.bot.send_message(pred["user_id"], text, parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            logger.error(f"Failed to notify user {pred['user_id']}: {e}")
