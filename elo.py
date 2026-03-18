import math
import logging

logger = logging.getLogger(__name__)

# Начальный рейтинг Эло для всех команд
DEFAULT_ELO = 1500
HOME_ADVANTAGE = 100  # очков преимущества дома
K_FACTOR = 32  # чувствительность рейтинга

# Предустановленные рейтинги топ-команд (на основе реальных данных)
INITIAL_RATINGS = {
    # АПЛ
    "Manchester City": 1950,
    "Arsenal": 1880,
    "Liverpool": 1900,
    "Chelsea": 1820,
    "Manchester United": 1800,
    "Tottenham Hotspur": 1780,
    "Newcastle United": 1760,
    "Aston Villa": 1750,
    "West Ham United": 1720,
    "Brighton & Hove Albion": 1730,
    # Ла Лига
    "Real Madrid": 1980,
    "Barcelona": 1940,
    "Atletico Madrid": 1880,
    "Athletic Club": 1780,
    "Real Sociedad": 1770,
    "Villarreal": 1760,
    "Sevilla": 1750,
    # Бундеслига
    "Bayer Leverkusen": 1900,
    "Bayern Munich": 1960,
    "Borussia Dortmund": 1880,
    "RB Leipzig": 1840,
    "Eintracht Frankfurt": 1780,
    # Серия А
    "Inter Milan": 1900,
    "Juventus": 1870,
    "AC Milan": 1860,
    "Napoli": 1850,
    "AS Roma": 1800,
    "Lazio": 1790,
    "Atalanta": 1820,
    # Лига 1
    "Paris Saint-Germain": 1950,
    "Monaco": 1820,
    "Marseille": 1800,
    "Lyon": 1790,
    "Lille": 1780,
    # ЛЧ участники (общие)
    "Porto": 1820,
    "Benfica": 1830,
    "Ajax": 1820,
    "PSV Eindhoven": 1800,
}

class EloRating:
    def __init__(self):
        self.ratings = dict(INITIAL_RATINGS)

    def get_rating(self, team: str) -> float:
        """Получить рейтинг команды."""
        # Точное совпадение
        if team in self.ratings:
            return self.ratings[team]
        # Частичное совпадение
        team_lower = team.lower()
        for name, rating in self.ratings.items():
            if team_lower in name.lower() or name.lower() in team_lower:
                return rating
        return DEFAULT_ELO

    def expected_score(self, rating_a: float, rating_b: float) -> float:
        """Ожидаемый результат команды A против B (вероятность победы)."""
        return 1 / (1 + 10 ** ((rating_b - rating_a) / 400))

    def update_ratings(self, team_a: str, team_b: str, score_a: int, score_b: int):
        """Обновить рейтинги после матча."""
        ra = self.get_rating(team_a)
        rb = self.get_rating(team_b)
        ea = self.expected_score(ra, rb)

        if score_a > score_b:
            sa = 1.0
        elif score_a < score_b:
            sa = 0.0
        else:
            sa = 0.5

        self.ratings[team_a] = ra + K_FACTOR * (sa - ea)
        self.ratings[team_b] = rb + K_FACTOR * ((1 - sa) - (1 - ea))

    def predict_match(self, home_team: str, away_team: str,
                      home_stats: dict = None, away_stats: dict = None) -> dict:
        """
        Полный прогноз матча с учётом:
        - Рейтинга Эло
        - Фактора домашнего поля
        - Реальной статистики команд
        - Коэффициентов букмекеров
        """
        elo_home = self.get_rating(home_team)
        elo_away = self.get_rating(away_team)

        # Учитываем фактор домашнего поля
        elo_home_adjusted = elo_home + HOME_ADVANTAGE

        # Базовая вероятность победы хозяев по Эло
        p_home_win_elo = self.expected_score(elo_home_adjusted, elo_away)

        # Корректируем на основе реальной статистики если есть
        p_home_win = p_home_win_elo
        p_away_win = 1 - p_home_win_elo

        if home_stats and away_stats:
            home_season = home_stats.get("season_stats", {})
            away_season = away_stats.get("season_stats", {})

            if home_season.get("played", 0) > 0 and away_season.get("played", 0) > 0:
                # Форма команд из последних матчей
                home_form_score = self._calc_form_score(home_stats.get("last_matches", []))
                away_form_score = self._calc_form_score(away_stats.get("last_matches", []))

                # Win rate в сезоне
                home_wr = home_season["wins"] / home_season["played"]
                away_wr = away_season["wins"] / away_season["played"]

                # Взвешенная вероятность: 50% Эло + 30% форма + 20% сезонный WR
                p_home_win = (
                    0.50 * p_home_win_elo +
                    0.30 * (home_form_score / (home_form_score + away_form_score + 0.001)) +
                    0.20 * (home_wr / (home_wr + away_wr + 0.001))
                )
                p_away_win = 1 - p_home_win

        # Вероятность ничьей (модель Диксона-Коулса)
        p_draw = self._calc_draw_probability(elo_home, elo_away)

        # Нормализуем
        total = p_home_win + p_away_win + p_draw
        p_home_win /= total
        p_away_win /= total
        p_draw /= total

        # Ожидаемые голы (модель Пуассона)
        avg_goals = self._calc_expected_goals(home_stats, away_stats)
        exp_home_goals = avg_goals["home"]
        exp_away_goals = avg_goals["away"]

        # Тотал и BTTS
        exp_total = exp_home_goals + exp_away_goals
        p_over_25 = 1 - self._poisson_cdf(2, exp_total)
        p_btts = (1 - math.exp(-exp_home_goals)) * (1 - math.exp(-exp_away_goals))

        return {
            "elo_home": round(elo_home),
            "elo_away": round(elo_away),
            "p_home_win": round(p_home_win * 100, 1),
            "p_draw": round(p_draw * 100, 1),
            "p_away_win": round(p_away_win * 100, 1),
            "exp_home_goals": round(exp_home_goals, 2),
            "exp_away_goals": round(exp_away_goals, 2),
            "exp_total": round(exp_total, 2),
            "p_over_25": round(p_over_25 * 100, 1),
            "p_btts": round(p_btts * 100, 1),
        }

    def _calc_form_score(self, last_matches: list) -> float:
        """Считаем очки формы из последних матчей (W=3, D=1, L=0)."""
        if not last_matches:
            return 1.5  # нейтральное значение
        score = 0
        weights = [1.0, 0.9, 0.8, 0.7, 0.6]  # последние матчи важнее
        for i, match in enumerate(last_matches[:5]):
            w = weights[i] if i < len(weights) else 0.5
            result = match.get("result", "D")
            if result == "W":
                score += 3 * w
            elif result == "D":
                score += 1 * w
        return score

    def _calc_draw_probability(self, elo_home: float, elo_away: float) -> float:
        """Вероятность ничьей зависит от близости рейтингов."""
        diff = abs(elo_home - elo_away)
        # Чем ближе рейтинги — тем выше вероятность ничьей
        base_draw = 0.25
        if diff < 50:
            return base_draw + 0.05
        elif diff < 150:
            return base_draw
        elif diff < 300:
            return base_draw - 0.05
        else:
            return base_draw - 0.08

    def _calc_expected_goals(self, home_stats: dict, away_stats: dict) -> dict:
        """Ожидаемые голы на основе статистики сезона."""
        default = {"home": 1.45, "away": 1.15}

        if not home_stats or not away_stats:
            return default

        home_season = home_stats.get("season_stats", {})
        away_season = away_stats.get("season_stats", {})

        if not home_season.get("played") or not away_season.get("played"):
            return default

        # Средние голы за матч
        home_attack = home_season.get("avg_goals_for", 1.45)
        home_defence = home_season.get("avg_goals_against", 1.15)
        away_attack = away_season.get("avg_goals_for", 1.15)
        away_defence = away_season.get("avg_goals_against", 1.45)

        # Лига-средние
        league_avg_home = 1.45
        league_avg_away = 1.15

        # Модель Диксона-Коулса
        exp_home = (home_attack / league_avg_home) * (away_defence / league_avg_away) * league_avg_home
        exp_away = (away_attack / league_avg_away) * (home_defence / league_avg_home) * league_avg_away

        return {
            "home": max(0.3, min(4.0, exp_home)),
            "away": max(0.3, min(4.0, exp_away)),
        }

    def _poisson_cdf(self, k: int, lam: float) -> float:
        """CDF распределения Пуассона P(X <= k)."""
        result = 0
        for i in range(k + 1):
            result += (lam ** i * math.exp(-lam)) / math.factorial(i)
        return result

    def detect_value_bets(self, prediction: dict, match: dict) -> list:
        """
        Находим value bets — ставки где наша вероятность выше букмекерской.
        Value = (наша вероятность * коэффициент) - 1
        Если Value > 0 — ставка выгодная!
        """
        value_bets = []
        h2h = match.get("h2h_odds", {})
        home = match.get("home_team", "")
        away = match.get("away_team", "")

        checks = [
            (home, "p_home_win", "Победа хозяев"),
            ("Draw", "p_draw", "Ничья"),
            (away, "p_away_win", "Победа гостей"),
        ]

        for outcome_key, prob_key, label in checks:
            odds = h2h.get(outcome_key, 0)
            our_prob = prediction.get(prob_key, 0) / 100

            if not odds or not our_prob:
                continue

            # Вероятность букмекера
            bookie_prob = 1 / odds

            # Value
            value = (our_prob * odds) - 1

            if value > 0.05:  # минимум 5% преимущество
                value_bets.append({
                    "label": label,
                    "odds": odds,
                    "our_prob": round(our_prob * 100, 1),
                    "bookie_prob": round(bookie_prob * 100, 1),
                    "value": round(value * 100, 1),
                    "rating": "🔥 Отличная" if value > 0.15 else ("✅ Хорошая" if value > 0.08 else "👍 Небольшая"),
                })

        value_bets.sort(key=lambda x: x["value"], reverse=True)
        return value_bets

# Глобальный экземпляр
elo = EloRating()
