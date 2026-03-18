import asyncio
import logging
from datetime import datetime, timezone, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import db
import os

logger = logging.getLogger(__name__)

CHECK_DELAY_HOURS = 3
CHECK_INTERVAL_SECONDS = 300

ANALYSIS_NAMES = {
    "winner": "🏆 Победитель",
    "score": "⚽ Счёт",
    "stats": "📊 Статистика",
    "total": "🎯 Тотал",
    "btts": "🔥 Обе забьют",
    "full": "📋 Полный анализ",
}

async def check_prediction_correct(pred: dict, home_score: int, away_score: int) -> tuple[bool, str]:
    analysis_type = pred["analysis_type"]
    home = pred["home_team"]
    away = pred["away_team"]
    text = pred["prediction_text"].lower()

    result = False
    explanation = ""

    if analysis_type == "winner":
        if home_score > away_score:
            actual_winner = home
        elif away_score > home_score:
            actual_winner = away
        else:
            actual_winner = "ничья"
        if actual_winner == "ничья":
            result = "ничья" in text or "draw" in text
        else:
            result = actual_winner.lower() in text
        explanation = f"Победил: {actual_winner} ({home_score}:{away_score})"

    elif analysis_type == "score":
        result = f"{home_score}:{away_score}" in text
        explanation = f"Счёт: {home_score}:{away_score}"

    elif analysis_type == "total":
        total = home_score + away_score
        over = total > 2.5
        if over:
            result = "больше" in text or "тб" in text
        else:
            result = "меньше" in text or "тм" in text
        explanation = f"Тотал: {total} голов ({'больше' if over else 'меньше'} 2.5)"

    elif analysis_type == "btts":
        both_scored = home_score > 0 and away_score > 0
        if both_scored:
            result = "да" in text[:500]
        else:
            result = "нет" in text[:500]
        explanation = f"Обе забили: {'да' if both_scored else 'нет'} ({home_score}:{away_score})"

    elif analysis_type in ("stats", "full"):
        if home_score > away_score:
            actual_winner = home
        elif away_score > home_score:
            actual_winner = away
        else:
            actual_winner = "ничья"
        result = actual_winner.lower() in text or "ничья" in text
        explanation = f"Итог: {home} {home_score}:{away_score} {away}"

    return result, explanation


class MatchScheduler:
    def __init__(self, bot: Bot, stats_client=None):
        self.bot = bot
        self.stats_client = stats_client

    async def start(self):
        logger.info("Scheduler started")
        asyncio.create_task(self._loop())

    async def _loop(self):
        while True:
            try:
                await self._check_pending_matches()
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def _check_pending_matches(self):
        pending = await db.get_predictions_to_check(CHECK_DELAY_HOURS)
        if not pending:
            return

        logger.info(f"Checking {len(pending)} predictions...")
        results_cache = {}

        for pred in pending:
            try:
                cache_key = f"{pred['home_team']}_{pred['away_team']}_{str(pred['match_date'])[:10]}"

                if cache_key not in results_cache:
                    if self.stats_client:
                        result = await self.stats_client.find_match_result(
                            pred["home_team"],
                            pred["away_team"],
                            str(pred["match_date"])[:10] if pred["match_date"] else None,
                            pred.get("sport", "soccer_epl")
                        )
                        await asyncio.sleep(1)
                    else:
                        result = None
                    results_cache[cache_key] = result
                else:
                    result = results_cache[cache_key]

                if not result:
                    await db.mark_prediction_checked(pred["id"])
                    logger.info(f"Match result not found for prediction {pred['id']}")
                    continue

                home_score = result["home_score"]
                away_score = result["away_score"]

                is_correct, explanation = await check_prediction_correct(pred, home_score, away_score)
                await db.resolve_prediction(pred["id"], home_score, away_score, is_correct)
                await self._notify_user(pred, home_score, away_score, is_correct, explanation)
                logger.info(f"Prediction {pred['id']} resolved: {is_correct} — {explanation}")

            except Exception as e:
                logger.error(f"Error checking prediction {pred['id']}: {e}")
                await db.mark_prediction_checked(pred["id"])

    async def _notify_user(self, pred: dict, home_score: int, away_score: int,
                           is_correct: bool, explanation: str):
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
