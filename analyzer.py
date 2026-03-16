import aiohttp
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

class FootballAnalyzer:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _format_odds_for_prompt(self, match: dict) -> str:
        home = match["home_team"]
        away = match["away_team"]
        h2h = match.get("h2h_odds", {})
        totals = match.get("total_odds", {})
        btts = match.get("btts_odds", {})

        lines = []

        # H2H odds
        if h2h:
            home_odd = h2h.get(home, "N/A")
            away_odd = h2h.get(away, "N/A")
            draw_odd = h2h.get("Draw", "N/A")
            lines.append(f"Коэффициенты 1X2: {home} ({home_odd}) | Ничья ({draw_odd}) | {away} ({away_odd})")

            # Implied probabilities from odds
            try:
                home_prob = round(1 / float(home_odd) * 100, 1) if home_odd != "N/A" else "?"
                draw_prob = round(1 / float(draw_odd) * 100, 1) if draw_odd != "N/A" else "?"
                away_prob = round(1 / float(away_odd) * 100, 1) if away_odd != "N/A" else "?"
                lines.append(f"Вероятности (по коэффициентам): {home} {home_prob}% | Ничья {draw_prob}% | {away} {away_prob}%")
            except:
                pass

        # Total goals odds
        if totals:
            total_lines = []
            for key, odd in totals.items():
                total_lines.append(f"{key.replace('_', ' ')} — {odd}")
            lines.append("Тотал голов: " + " | ".join(total_lines[:4]))

        # BTTS odds
        if btts:
            yes_odd = btts.get("Yes", "N/A")
            no_odd = btts.get("No", "N/A")
            lines.append(f"Обе забьют: Да ({yes_odd}) | Нет ({no_odd})")

        return "\n".join(lines)

    def _build_prompt(self, match: dict, analysis_type: str) -> str:
        home = match["home_team"]
        away = match["away_team"]
        date = match.get("commence_time_str", "")
        odds_info = self._format_odds_for_prompt(match)

        base_context = f"""Матч: {home} vs {away}
Дата: {date}

Данные букмекеров:
{odds_info}

Ты — профессиональный аналитик футбольных матчей. Используй коэффициенты как основной источник данных (они отражают реальную вероятность исходов по мнению рынка). Дай глубокий анализ."""

        prompts = {
            "winner": f"""{base_context}

Задача: Определи наиболее вероятного победителя матча.

Ответ дай в формате:
🏆 ПРОГНОЗ ПОБЕДИТЕЛЯ

📊 Анализ коэффициентов: [разбери что говорят коэффициенты]
🔍 Факторы в пользу {home}: [2-3 фактора]
🔍 Факторы в пользу {away}: [2-3 фактора]
⚖️ Фактор ничьей: [оценка]

✅ ИТОГ: [победитель или ничья] — [уверенность: низкая/средняя/высокая]
💡 Ставка: [рекомендуемый исход с коэффициентом]
⚠️ Риски: [главные факторы неопределённости]""",

            "score": f"""{base_context}

Задача: Спрогнозируй наиболее вероятный счёт матча.

Ответ дай в формате:
⚽ ПРОГНОЗ СЧЁТА

📊 Атакующий потенциал {home}: [оценка]
📊 Атакующий потенциал {away}: [оценка]
🔢 Ожидаемое кол-во голов: [анализ]

🎯 ОСНОВНОЙ ПРОГНОЗ: [X:Y]
🎯 АЛЬТЕРНАТИВА: [X:Y]
💡 Обоснование: [краткое объяснение]
⚠️ Риск: [вероятность другого развития]""",

            "stats": f"""{base_context}

Задача: Дай детальную статистику и анализ обеих команд.

Ответ дай в формате:
📊 АНАЛИЗ КОМАНД

🏠 {home} (хозяева):
• Позиция на рынке ставок: [что говорят коэффициенты]
• Атака: [оценка]
• Защита: [оценка]
• Форма: [предположение на основе коэффициентов]

✈️ {away} (гости):
• Позиция на рынке ставок: [что говорят коэффициенты]
• Атака: [оценка]
• Защита: [оценка]
• Форма: [предположение]

⚔️ Исторические встречи: [анализ по косвенным признакам]
🎯 Ключевые факторы матча: [3 главных момента]""",

            "total": f"""{base_context}

Задача: Проанализируй тотал голов в матче (больше/меньше 2.5).

Ответ дай в формате:
🎯 АНАЛИЗ ТОТАЛА ГОЛОВ

📊 Что говорят коэффициенты на тотал: [разбор]
⚽ Голевой потенциал {home}: [оценка]
⚽ Голевой потенциал {away}: [оценка]
🏟️ Фактор хозяев/гостей: [анализ]

✅ ПРОГНОЗ: [Больше/Меньше 2.5]
📈 Уверенность: [%]
💡 Дополнительно: [ТБ/ТМ 1.5 и 3.5 если есть данные]
⚠️ Риски: [факторы неопределённости]""",

            "btts": f"""{base_context}

Задача: Проанализируй рынок "Обе команды забьют" (BTTS).

Ответ дай в формате:
🔥 ОБЕ КОМАНДЫ ЗАБЬЮТ?

📊 Коэффициенты BTTS: Да vs Нет — [разбор]
⚽ Атакующая угроза {home}: [оценка]
⚽ Атакующая угроза {away}: [оценка]
🛡️ Надёжность защит: [сравнение]

✅ ПРОГНОЗ: [Да/Нет]
📈 Уверенность: [%]
💡 Обоснование: [главные аргументы]
⚠️ Ключевой риск: [что может изменить прогноз]""",

            "full": f"""{base_context}

Задача: Дай ПОЛНЫЙ комплексный анализ матча по всем направлениям.

Ответ дай в формате:
📋 ПОЛНЫЙ АНАЛИЗ МАТЧА
{home} vs {away}

━━━━━━━━━━━━━━━━━━━━
🏆 ПОБЕДИТЕЛЬ
[Прогноз с обоснованием]

━━━━━━━━━━━━━━━━━━━━
⚽ СЧЁТ
[Основной и альтернативный прогноз]

━━━━━━━━━━━━━━━━━━━━
🎯 ТОТАЛ ГОЛОВ
[Больше или меньше 2.5 с уверенностью]

━━━━━━━━━━━━━━━━━━━━
🔥 ОБЕ ЗАБЬЮТ
[Да/Нет с уверенностью]

━━━━━━━━━━━━━━━━━━━━
💎 ЛУЧШАЯ СТАВКА
[Конкретная рекомендация с коэффициентом и обоснованием]

━━━━━━━━━━━━━━━━━━━━
⚠️ ОТКАЗ ОТ ОТВЕТСТВЕННОСТИ
Прогноз носит информационный характер.""",
        }

        return prompts.get(analysis_type, prompts["full"])

    async def analyze(self, match: dict, analysis_type: str) -> str:
        prompt = self._build_prompt(match, analysis_type)

        url = f"{GEMINI_API_URL}?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {
                "parts": [{"text": (
                    "Ты профессиональный футбольный аналитик. Пиши на русском языке. "
                    "Используй эмодзи для структуры. Будь конкретным и давай чёткие прогнозы. "
                    "Коэффициенты букмекеров — главный источник данных о вероятностях."
                )}]
            },
            "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.7}
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Gemini API error {resp.status}: {text}")
                    raise Exception(f"Gemini API error: {resp.status}")

                data = await resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
