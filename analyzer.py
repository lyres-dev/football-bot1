import aiohttp
import logging

logger = logging.getLogger(__name__)

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent"


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
        if h2h:
            home_odd = h2h.get(home, "N/A")
            away_odd = h2h.get(away, "N/A")
            draw_odd = h2h.get("Draw", "N/A")
            lines.append(f"Коэффициенты 1X2: {home} ({home_odd}) | Ничья ({draw_odd}) | {away} ({away_odd})")
            try:
                home_prob = round(1 / float(home_odd) * 100, 1)
                draw_prob = round(1 / float(draw_odd) * 100, 1)
                away_prob = round(1 / float(away_odd) * 100, 1)
                lines.append(f"Вероятности: {home} {home_prob}% | Ничья {draw_prob}% | {away} {away_prob}%")
            except:
                pass
        if totals:
            total_lines = [f"{k.replace('_', ' ')} — {v}" for k, v in list(totals.items())[:4]]
            lines.append("Тотал голов: " + " | ".join(total_lines))
        if btts:
            lines.append(f"Обе забьют (расчётно): Да ({btts.get('Yes', 'N/A')}) | Нет ({btts.get('No', 'N/A')})")
        return "\n".join(lines)

    def _build_prompt(self, match: dict, analysis_type: str) -> str:
        home = match["home_team"]
        away = match["away_team"]
        date = match.get("commence_time_str", "")
        odds_info = self._format_odds_for_prompt(match)

        base_context = f"""Ты профессиональный футбольный аналитик. Пиши на русском языке. Используй эмодзи. Давай чёткие конкретные прогнозы. Коэффициенты букмекеров — главный источник данных.

Матч: {home} vs {away}
Дата: {date}

Данные букмекеров:
{odds_info}"""

        prompts = {
            "winner": f"""{base_context}

Задача: определи наиболее вероятного победителя.

Формат ответа:
🏆 ПРОГНОЗ ПОБЕДИТЕЛЯ

📊 Анализ коэффициентов: ...
🔍 Факторы за {home}: ...
🔍 Факторы за {away}: ...
⚖️ Фактор ничьей: ...

✅ ИТОГ: [победитель] — [уверенность: низкая/средняя/высокая]
💡 Ставка: [исход с коэффициентом]
⚠️ Риски: ...""",

            "score": f"""{base_context}

Задача: спрогнозируй наиболее вероятный счёт.

Формат ответа:
⚽ ПРОГНОЗ СЧЁТА

📊 Атака {home}: ...
📊 Атака {away}: ...
🔢 Ожидаемых голов: ...

🎯 ОСНОВНОЙ ПРОГНОЗ: X:Y
🎯 АЛЬТЕРНАТИВА: X:Y
💡 Обоснование: ...
⚠️ Риск: ...""",

            "stats": f"""{base_context}

Задача: дай детальный анализ обеих команд.

Формат ответа:
📊 АНАЛИЗ КОМАНД

🏠 {home} (хозяева):
• Рыночная позиция: ...
• Атака: ...
• Защита: ...

✈️ {away} (гости):
• Рыночная позиция: ...
• Атака: ...
• Защита: ...

⚔️ Ключевые факторы матча: ...""",

            "total": f"""{base_context}

Задача: проанализируй тотал голов (больше/меньше 2.5).

Формат ответа:
🎯 АНАЛИЗ ТОТАЛА

📊 Коэффициенты тотала: ...
⚽ Голевой потенциал {home}: ...
⚽ Голевой потенциал {away}: ...

✅ ПРОГНОЗ: Больше/Меньше 2.5
📈 Уверенность: X%
⚠️ Риски: ...""",

            "btts": f"""{base_context}

Задача: проанализируй рынок "обе команды забьют".

Формат ответа:
🔥 ОБЕ КОМАНДЫ ЗАБЬЮТ?

📊 Расчётные коэффициенты BTTS: ...
⚽ Атака {home}: ...
⚽ Атака {away}: ...
🛡️ Надёжность защит: ...

✅ ПРОГНОЗ: Да/Нет
📈 Уверенность: X%
⚠️ Риск: ...""",

            "full": f"""{base_context}

Задача: дай полный комплексный анализ матча.

Формат ответа:
📋 ПОЛНЫЙ АНАЛИЗ: {home} vs {away}

━━━━━━━━━━━━━━━━━━━━
🏆 ПОБЕДИТЕЛЬ
[прогноз с обоснованием]

━━━━━━━━━━━━━━━━━━━━
⚽ СЧЁТ
[основной и альтернативный]

━━━━━━━━━━━━━━━━━━━━
🎯 ТОТАЛ ГОЛОВ
[больше или меньше 2.5]

━━━━━━━━━━━━━━━━━━━━
🔥 ОБЕ ЗАБЬЮТ
[да/нет с уверенностью]

━━━━━━━━━━━━━━━━━━━━
💎 ЛУЧШАЯ СТАВКА
[конкретная рекомендация]

⚠️ Прогноз носит информационный характер.""",
        }
        return prompts.get(analysis_type, prompts["full"])

    async def analyze(self, match: dict, analysis_type: str) -> str:
        prompt = self._build_prompt(match, analysis_type)
        url = f"{GEMINI_API_URL}?key={self.api_key}"

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 1000,
                "temperature": 0.7
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Gemini API error {resp.status}: {text}")
                    raise Exception(f"Gemini API error: {resp.status}")
                data = await resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
