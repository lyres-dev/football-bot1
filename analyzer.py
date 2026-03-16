import aiohttp
import logging

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "llama-3.3-70b-versatile"

class FootballAnalyzer:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _format_odds(self, match: dict) -> str:
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
            lines.append(f"1X2: {home} ({home_odd}) | Ничья ({draw_odd}) | {away} ({away_odd})")
            try:
                hp = round(1 / float(home_odd) * 100, 1)
                dp = round(1 / float(draw_odd) * 100, 1)
                ap = round(1 / float(away_odd) * 100, 1)
                lines.append(f"Вероятности по рынку: {home} {hp}% | Ничья {dp}% | {away} {ap}%")
            except:
                pass
        if totals:
            tl = [f"{k.replace('_',' ')} ({v})" for k, v in list(totals.items())[:4]]
            lines.append("Тотал: " + " | ".join(tl))
        if btts:
            lines.append(f"Обе забьют: Да ({btts.get('Yes','N/A')}) | Нет ({btts.get('No','N/A')})")
        return "\n".join(lines)

    def _format_team_stats(self, stats: dict, team_name: str) -> str:
        if not stats:
            return f"{team_name}: статистика недоступна"

        lines = [f"📊 {team_name}:"]
        s = stats.get("season_stats", {})
        if s:
            lines.append(
                f"  Сезон: {s.get('played',0)} игр | "
                f"П{s.get('wins',0)} Н{s.get('draws',0)} П{s.get('losses',0)} | "
                f"Голы: {s.get('goals_for',0)}-{s.get('goals_against',0)} | "
                f"Avg: {s.get('avg_goals_for',0)}/{s.get('avg_goals_against',0)} | "
                f"Форма: {s.get('form','—')}"
            )

        last = stats.get("last_matches", [])
        if last:
            lines.append("  Последние 5 матчей:")
            for m in last:
                venue = "🏠" if m["venue"] == "home" else "✈️"
                res_icon = "✅" if m["result"] == "W" else ("🟡" if m["result"] == "D" else "❌")
                lines.append(f"    {venue} {res_icon} {m['home']} {m['score']} {m['away']} ({m['date']})")

        return "\n".join(lines)

    def _build_prompt(self, match: dict, analysis_type: str,
                      home_stats: dict = None, away_stats: dict = None) -> str:
        home = match["home_team"]
        away = match["away_team"]
        date = match.get("commence_time_str", "")
        odds_info = self._format_odds(match)
        home_stats_text = self._format_team_stats(home_stats or {}, home)
        away_stats_text = self._format_team_stats(away_stats or {}, away)

        base = f"""Матч: {home} vs {away}
Дата: {date}

=== КОЭФФИЦИЕНТЫ БУКМЕКЕРОВ ===
{odds_info}

=== СТАТИСТИКА КОМАНД ===
{home_stats_text}

{away_stats_text}"""

        prompts = {
            "winner": f"""{base}

Задача: определи наиболее вероятного победителя, опираясь на статистику и коэффициенты.

🏆 ПРОГНОЗ ПОБЕДИТЕЛЯ

📊 Анализ формы {home}: [последние матчи, тренд]
📊 Анализ формы {away}: [последние матчи, тренд]
⚖️ Сравнение: [кто в лучшей форме и почему]
💹 Что говорит рынок: [анализ коэффициентов]

✅ ИТОГ: [победитель] — [уверенность: низкая/средняя/высокая]
💡 Ставка: [исход с коэффициентом]
⚠️ Риски: ...""",

            "score": f"""{base}

Задача: спрогнозируй счёт на основе статистики голов и формы.

⚽ ПРОГНОЗ СЧЁТА

🔢 Среднее голов {home} за/против: [из статистики]
🔢 Среднее голов {away} за/против: [из статистики]
📈 Тренд последних матчей: [анализ]

🎯 ОСНОВНОЙ ПРОГНОЗ: X:Y
🎯 АЛЬТЕРНАТИВА: X:Y
💡 Обоснование: ...
⚠️ Риск: ...""",

            "stats": f"""{base}

Задача: детальный анализ статистики обеих команд.

📊 АНАЛИЗ КОМАНД

🏠 {home}:
• Форма (последние 5): [W/D/L разбор]
• Атака: [голы за, среднее]
• Защита: [голы против, среднее]
• Тренд: [улучшение/ухудшение]

✈️ {away}:
• Форма (последние 5): [W/D/L разбор]
• Атака: [голы за, среднее]
• Защита: [голы против, среднее]
• Тренд: [улучшение/ухудшение]

⚔️ Ключевые выводы: ...""",

            "total": f"""{base}

Задача: прогноз тотала на основе реальной статистики голов.

🎯 АНАЛИЗ ТОТАЛА

📊 Среднее голов в матчах {home}: [расчёт]
📊 Среднее голов в матчах {away}: [расчёт]
📈 Ожидаемый тотал: [расчёт на основе средних]
💹 Коэффициенты букмекеров: [сравнение с расчётом]

✅ ПРОГНОЗ: Больше/Меньше 2.5
📈 Уверенность: X%
⚠️ Риски: ...""",

            "btts": f"""{base}

Задача: прогноз "обе забьют" на основе статистики.

🔥 ОБЕ КОМАНДЫ ЗАБЬЮТ?

⚽ Голевая активность {home}: [анализ]
⚽ Голевая активность {away}: [анализ]
🛡️ Надёжность защит: [сравнение]
📊 В скольких последних матчах обе забивали: [из данных]

✅ ПРОГНОЗ: Да/Нет
📈 Уверенность: X%
⚠️ Риск: ...""",

            "full": f"""{base}

Задача: полный комплексный анализ на основе статистики и коэффициентов.

📋 ПОЛНЫЙ АНАЛИЗ: {home} vs {away}

━━━━━━━━━━━━━━━━━━━━
🏆 ПОБЕДИТЕЛЬ
[прогноз с анализом формы]

━━━━━━━━━━━━━━━━━━━━
⚽ СЧЁТ
[основной и альтернативный на основе голевой статистики]

━━━━━━━━━━━━━━━━━━━━
🎯 ТОТАЛ ГОЛОВ
[расчёт на основе средних показателей]

━━━━━━━━━━━━━━━━━━━━
🔥 ОБЕ ЗАБЬЮТ
[да/нет с обоснованием по статистике]

━━━━━━━━━━━━━━━━━━━━
💎 ЛУЧШАЯ СТАВКА
[конкретная рекомендация с обоснованием]

⚠️ Прогноз носит информационный характер.""",
        }
        return prompts.get(analysis_type, prompts["full"])

    async def analyze(self, match: dict, analysis_type: str,
                      home_stats: dict = None, away_stats: dict = None) -> str:
        prompt = self._build_prompt(match, analysis_type, home_stats, away_stats)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты профессиональный футбольный аналитик. Пиши на русском языке. "
                        "Используй эмодзи для структуры. Давай чёткие конкретные прогнозы. "
                        "Опирайся прежде всего на реальную статистику команд, "
                        "а коэффициенты используй как дополнительный индикатор."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 1200,
            "temperature": 0.7,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(GROQ_API_URL, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Groq API error {resp.status}: {text}")
                    raise Exception(f"Groq API error: {resp.status}")
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
