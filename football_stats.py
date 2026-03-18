import aiohttp
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_URL = "https://api.football-data.org/v4"

# football-data.org competition codes
LEAGUE_MAP = {
    "soccer_epl": "PL",
    "soccer_spain_la_liga": "PD",
    "soccer_germany_bundesliga": "BL1",
    "soccer_italy_serie_a": "SA",
    "soccer_france_ligue_one": "FL1",
    "soccer_uefa_champs_league": "CL",
    "soccer_russia_premier_league": None,  # не поддерживается бесплатно
}

class FootballStatsClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"X-Auth-Token": api_key}

    async def _get(self, endpoint: str, params: dict = {}) -> dict:
        url = f"{BASE_URL}/{endpoint}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"football-data error {resp.status}: {text[:200]}")
                    return {}
                return await resp.json()

    async def search_team_in_competition(self, team_name: str, competition_code: str) -> dict | None:
        """Найти команду в конкретной лиге."""
        data = await self._get(f"competitions/{competition_code}/teams")
        teams = data.get("teams", [])
        team_name_lower = team_name.lower()
        for team in teams:
            if (team_name_lower in team["name"].lower() or
                team_name_lower in team.get("shortName", "").lower() or
                team_name_lower in team.get("tla", "").lower()):
                logger.info(f"Found team: {team['name']} (id={team['id']}) for '{team_name}'")
                return team
        logger.warning(f"Team not found: {team_name} in {competition_code}")
        return None

    async def get_last_matches(self, team_id: int, count: int = 5) -> list:
        """Последние N матчей команды."""
        data = await self._get(f"teams/{team_id}/matches", {
            "status": "FINISHED",
            "limit": count,
        })
        matches_raw = data.get("matches", [])
        # Берём последние по дате
        matches_raw = sorted(matches_raw, key=lambda x: x["utcDate"], reverse=True)[:count]

        matches = []
        for m in matches_raw:
            home = m["homeTeam"]["name"]
            away = m["awayTeam"]["name"]
            home_id = m["homeTeam"]["id"]
            score = m.get("score", {})
            full = score.get("fullTime", {})
            home_goals = full.get("home", 0) or 0
            away_goals = full.get("away", 0) or 0
            is_home = home_id == team_id
            team_goals = home_goals if is_home else away_goals
            opp_goals = away_goals if is_home else home_goals

            if team_goals > opp_goals:
                result = "W"
            elif team_goals < opp_goals:
                result = "L"
            else:
                result = "D"

            date_str = m["utcDate"][:10]
            matches.append({
                "date": date_str,
                "home": home,
                "away": away,
                "score": f"{home_goals}:{away_goals}",
                "team_goals": team_goals,
                "opp_goals": opp_goals,
                "result": result,
                "venue": "home" if is_home else "away",
            })

        logger.info(f"Got {len(matches)} matches for team {team_id}")
        return matches

    async def get_team_season_stats(self, team_id: int, competition_code: str) -> dict:
        """Статистика команды в текущем сезоне."""
        data = await self._get(f"teams/{team_id}/matches", {
            "status": "FINISHED",
            "competitions": competition_code,
            "limit": 50,
        })
        matches = data.get("matches", [])
        if not matches:
            return {}

        played = wins = draws = losses = goals_for = goals_against = 0
        form_list = []

        for m in sorted(matches, key=lambda x: x["utcDate"]):
            score = m.get("score", {})
            full = score.get("fullTime", {})
            home_goals = full.get("home", 0) or 0
            away_goals = full.get("away", 0) or 0
            is_home = m["homeTeam"]["id"] == team_id
            tg = home_goals if is_home else away_goals
            og = away_goals if is_home else home_goals

            played += 1
            goals_for += tg
            goals_against += og

            if tg > og:
                wins += 1
                form_list.append("W")
            elif tg < og:
                losses += 1
                form_list.append("L")
            else:
                draws += 1
                form_list.append("D")

        return {
            "played": played,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "avg_goals_for": round(goals_for / played, 2) if played else 0,
            "avg_goals_against": round(goals_against / played, 2) if played else 0,
            "form": "".join(form_list[-5:]),
        }

    async def get_full_team_stats(self, team_name: str, league_key: str) -> dict:
        competition_code = LEAGUE_MAP.get(league_key)
        if not competition_code:
            logger.warning(f"League not supported: {league_key}")
            return {}

        team = await self.search_team_in_competition(team_name, competition_code)
        if not team:
            return {}

        team_id = team["id"]
        last_matches, season_stats = await asyncio.gather(
            self.get_last_matches(team_id),
            self.get_team_season_stats(team_id, competition_code),
            return_exceptions=True
        )
        return {
            "team_id": team_id,
            "team_name": team["name"],
            "last_matches": last_matches if isinstance(last_matches, list) else [],
            "season_stats": season_stats if isinstance(season_stats, dict) else {},
        }

    async def get_match_result(self, home_team: str, away_team: str) -> dict | None:
        """Получить результат завершённого матча."""
        # Ищем через недавние матчи одной из команд
        # Используем поиск по всем лигам
        for league_key, code in LEAGUE_MAP.items():
            if not code:
                continue
            team = await self.search_team_in_competition(home_team, code)
            if not team:
                continue
            team_id = team["id"]
            data = await self._get(f"teams/{team_id}/matches", {
                "status": "FINISHED",
                "limit": 10,
            })
            for m in data.get("matches", []):
                h_name = m["homeTeam"]["name"].lower()
                a_name = m["awayTeam"]["name"].lower()
                if home_team.lower() in h_name and away_team.lower() in a_name:
                    full = m.get("score", {}).get("fullTime", {})
                    return {
                        "home_score": full.get("home", 0),
                        "away_score": full.get("away", 0),
                        "status": "FT",
                    }
        return None
