import aiohttp
import asyncio
import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://api.football-data.org/v4"

LEAGUE_MAP = {
    "soccer_epl": "PL",
    "soccer_spain_la_liga": "PD",
    "soccer_germany_bundesliga": "BL1",
    "soccer_italy_serie_a": "SA",
    "soccer_france_ligue_one": "FL1",
    "soccer_uefa_champs_league": "CL",
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
                    logger.error(f"football-data error {resp.status}: {text}")
                    return {}
                return await resp.json()

    async def search_team_id(self, team_name: str, league_code: str) -> int | None:
    data = await self._get(f"competitions/{league_code}/teams")
    teams = data.get("teams", [])
    team_name_lower = team_name.lower().strip()
    
    # Сначала точное совпадение
    for team in teams:
        names = [
            team.get("name", "").lower(),
            team.get("shortName", "").lower(),
            team.get("tla", "").lower(),
        ]
        if team_name_lower in names:
            logger.info(f"Found team: {team['name']} (id={team['id']})")
            return team["id"]
    
    # Потом частичное совпадение
    for team in teams:
        names = [
            team.get("name", "").lower(),
            team.get("shortName", "").lower(),
        ]
        for name in names:
            if team_name_lower in name or name in team_name_lower:
                logger.info(f"Found team: {team['name']} (id={team['id']})")
                return team["id"]
    
    # Совпадение по первому слову
    first_word = team_name_lower.split()[0]
    for team in teams:
        if first_word in team.get("name", "").lower():
            logger.info(f"Found team by first word: {team['name']} (id={team['id']})")
            return team["id"]
    
    logger.warning(f"Team not found: {team_name} in {league_code}")
    return None

    async def get_last_matches(self, team_id: int, count: int = 5) -> list:
        data = await self._get(f"teams/{team_id}/matches", {
            "status": "FINISHED",
            "limit": count,
        })
        matches = []
        for m in data.get("matches", [])[-count:]:
            home = m["homeTeam"]["name"]
            away = m["awayTeam"]["name"]
            home_id = m["homeTeam"]["id"]
            score = m.get("score", {}).get("fullTime", {})
            home_goals = score.get("home", 0) or 0
            away_goals = score.get("away", 0) or 0
            is_home = home_id == team_id
            team_goals = home_goals if is_home else away_goals
            opp_goals = away_goals if is_home else home_goals
            if team_goals > opp_goals:
                result = "W"
            elif team_goals < opp_goals:
                result = "L"
            else:
                result = "D"
            matches.append({
                "date": m["utcDate"][:10],
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

    async def get_team_season_stats(self, team_id: int, league_code: str) -> dict:
        data = await self._get(f"competitions/{league_code}/standings")
        standings = data.get("standings", [])
        for group in standings:
            for team in group.get("table", []):
                if team["team"]["id"] == team_id:
                    played = team.get("playedGames", 0)
                    wins = team.get("won", 0)
                    draws = team.get("draw", 0)
                    losses = team.get("lost", 0)
                    goals_for = team.get("goalsFor", 0)
                    goals_against = team.get("goalsAgainst", 0)
                    form = team.get("form", "") or ""
                    return {
                        "played": played,
                        "wins": wins,
                        "draws": draws,
                        "losses": losses,
                        "goals_for": goals_for,
                        "goals_against": goals_against,
                        "avg_goals_for": round(goals_for / played, 2) if played else 0,
                        "avg_goals_against": round(goals_against / played, 2) if played else 0,
                        "form": form[-5:],
                        "position": team.get("position", 0),
                        "points": team.get("points", 0),
                    }
        return {}

    async def get_full_team_stats(self, team_name: str, league_key: str) -> dict:
        league_code = LEAGUE_MAP.get(league_key)
        if not league_code:
            logger.warning(f"League not supported: {league_key}")
            return {}
        team_id = await self.search_team_id(team_name, league_code)
        if not team_id:
            return {}
        last_matches, season_stats = await asyncio.gather(
            self.get_last_matches(team_id),
            self.get_team_season_stats(team_id, league_code),
            return_exceptions=True
        )
        return {
            "team_id": team_id,
            "team_name": team_name,
            "last_matches": last_matches if isinstance(last_matches, list) else [],
            "season_stats": season_stats if isinstance(season_stats, dict) else {},
        }

    async def get_match_result(self, home_team: str, away_team: str) -> dict | None:
        return None
