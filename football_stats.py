import aiohttp
import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://v3.football.api-sports.io"

# Маппинг лиг The Odds API -> API-Football league ID
LEAGUE_MAP = {
    "soccer_epl": 39,
    "soccer_spain_la_liga": 140,
    "soccer_germany_bundesliga": 78,
    "soccer_italy_serie_a": 135,
    "soccer_france_ligue_one": 61,
    "soccer_uefa_champs_league": 2,
    "soccer_russia_premier_league": 235,
}

CURRENT_SEASON = 2024

class FootballStatsClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "x-apisports-key": api_key,
        }

    async def _get(self, endpoint: str, params: dict) -> dict:
        url = f"{BASE_URL}/{endpoint}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers, params=params) as resp:
                if resp.status != 200:
                    logger.error(f"API-Football error {resp.status}")
                    return {}
                return await resp.json()

    async def search_team(self, team_name: str) -> int | None:
        """Find team ID by name."""
        data = await self._get("teams", {"search": team_name})
        results = data.get("response", [])
        if results:
            return results[0]["team"]["id"]
        return None

    async def get_last_matches(self, team_id: int, count: int = 5) -> list:
        """Get last N matches for a team."""
        data = await self._get("fixtures", {
            "team": team_id,
            "last": count,
            "status": "FT",
        })
        matches = []
        for fixture in data.get("response", []):
            f = fixture["fixture"]
            home = fixture["teams"]["home"]
            away = fixture["teams"]["away"]
            goals = fixture["goals"]
            is_home = home["id"] == team_id
            team_goals = goals["home"] if is_home else goals["away"]
            opp_goals = goals["away"] if is_home else goals["home"]
            team_won = home["winner"] if is_home else away["winner"]

            matches.append({
                "date": f["date"][:10],
                "home": home["name"],
                "away": away["name"],
                "score": f"{goals['home']}:{goals['away']}",
                "team_goals": team_goals,
                "opp_goals": opp_goals,
                "result": "W" if team_won else ("L" if team_won is False else "D"),
                "venue": "home" if is_home else "away",
            })
        return matches

    async def get_team_season_stats(self, team_id: int, league_id: int) -> dict:
        """Get team season statistics."""
        data = await self._get("teams/statistics", {
            "team": team_id,
            "league": league_id,
            "season": CURRENT_SEASON,
        })
        resp = data.get("response", {})
        if not resp:
            return {}

        fixtures = resp.get("fixtures", {})
        goals = resp.get("goals", {})
        form = resp.get("form", "")

        played = fixtures.get("played", {}).get("total", 0)
        wins = fixtures.get("wins", {}).get("total", 0)
        draws = fixtures.get("draws", {}).get("total", 0)
        losses = fixtures.get("loses", {}).get("total", 0)
        goals_for = goals.get("for", {}).get("total", {}).get("total", 0)
        goals_against = goals.get("against", {}).get("total", {}).get("total", 0)

        return {
            "played": played,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "avg_goals_for": round(goals_for / played, 2) if played else 0,
            "avg_goals_against": round(goals_against / played, 2) if played else 0,
            "form": form[-5:] if form else "",
        }

    async def get_full_team_stats(self, team_name: str, league_key: str) -> dict:
        """Get all stats for a team: last matches + season stats."""
        team_id = await self.search_team(team_name)
        if not team_id:
            logger.warning(f"Team not found: {team_name}")
            return {}

        league_id = LEAGUE_MAP.get(league_key, 39)

        last_matches, season_stats = await asyncio.gather(
            self.get_last_matches(team_id),
            self.get_team_season_stats(team_id, league_id),
            return_exceptions=True
        )

        return {
            "team_id": team_id,
            "team_name": team_name,
            "last_matches": last_matches if isinstance(last_matches, list) else [],
            "season_stats": season_stats if isinstance(season_stats, dict) else {},
        }

import asyncio

    async def get_match_result(self, home_team: str, away_team: str) -> dict | None:
        """Получить результат завершённого матча по названиям команд."""
        # Ищем ID команд
        home_id = await self.search_team(home_team)
        away_id = await self.search_team(away_team)
        if not home_id or not away_id:
            return None

        # Ищем последний матч между ними
        data = await self._get("fixtures", {
            "team": home_id,
            "last": 10,
            "status": "FT",
        })

        for fixture in data.get("response", []):
            teams = fixture["teams"]
            fhome_id = teams["home"]["id"]
            faway_id = teams["away"]["id"]

            # Проверяем что это именно нужный матч
            if (fhome_id == home_id and faway_id == away_id) or \
               (fhome_id == away_id and faway_id == home_id):
                goals = fixture["goals"]
                # Нормализуем — home_team всегда первый
                if fhome_id == home_id:
                    return {
                        "home_score": goals["home"],
                        "away_score": goals["away"],
                        "status": "FT",
                    }
                else:
                    return {
                        "home_score": goals["away"],
                        "away_score": goals["home"],
                        "status": "FT",
                    }
        return None
