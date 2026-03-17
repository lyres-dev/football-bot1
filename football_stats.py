import aiohttp
import asyncio
import logging
from typing import Optional, Dict, Any, List
from asyncpg import Connection
import time

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
        self._last_request_time = 0
        self._request_interval = 1.0  # Минимальный интервал между запросами (секунды)
        self._retry_after = 0  # Время ожидания при rate limit

    async def _get(self, endpoint: str, params: dict = None) -> dict:
        """Выполняет GET запрос с обработкой rate limiting"""
        if params is None:
            params = {}
            
        url = f"{BASE_URL}/{endpoint}"
        
        # Проверяем, не нужно ли подождать из-за rate limit
        if self._retry_after > 0:
            wait_time = self._retry_after - time.time()
            if wait_time > 0:
                logger.info(f"Waiting {wait_time:.1f}s due to rate limit")
                await asyncio.sleep(wait_time)
            self._retry_after = 0
        
        # Соблюдаем минимальный интервал между запросами
        elapsed = time.time() - self._last_request_time
        if elapsed < self._request_interval:
            await asyncio.sleep(self._request_interval - elapsed)
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=self.headers, params=params) as resp:
                    self._last_request_time = time.time()
                    
                    if resp.status == 429:  # Rate limit
                        retry_after = int(resp.headers.get('Retry-After', 60))
                        self._retry_after = time.time() + retry_after
                        text = await resp.text()
                        logger.error(f"Rate limited. Need to wait {retry_after}s: {text}")
                        return {}
                    
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error(f"football-data error {resp.status}: {text}")
                        return {}
                    
                    return await resp.json()
                    
            except aiohttp.ClientError as e:
                logger.error(f"Network error: {e}")
                return {}
            except asyncio.TimeoutError:
                logger.error("Request timeout")
                return {}

    async def search_team_id(self, team_name: str, league_code: str) -> int | None:
        """Поиск ID команды с обработкой ошибок"""
        try:
            data = await self._get(f"competitions/{league_code}/teams")
            if not data:
                return None
                
            teams = data.get("teams", [])
            team_name_lower = team_name.lower()
            
            for team in teams:
                if (team_name_lower in team["name"].lower() or
                    team_name_lower in team.get("shortName", "").lower() or
                    team_name_lower in team.get("tla", "").lower()):
                    logger.info(f"Found team: {team['name']} (id={team['id']})")
                    return team["id"]
                    
            logger.warning(f"Team not found: {team_name} in {league_code}")
            return None
            
        except Exception as e:
            logger.error(f"Error searching team {team_name}: {e}")
            return None

    async def get_last_matches(self, team_id: int, count: int = 5) -> list:
        """Получение последних матчей команды"""
        try:
            data = await self._get(f"teams/{team_id}/matches", {
                "status": "FINISHED",
                "limit": count,
            })
            
            if not data:
                return []
                
            matches = []
            all_matches = data.get("matches", [])
            
            for m in all_matches[-count:]:
                try:
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
                        "date": m["utcDate"][:10] if m.get("utcDate") else "unknown",
                        "home": home,
                        "away": away,
                        "score": f"{home_goals}:{away_goals}",
                        "team_goals": team_goals,
                        "opp_goals": opp_goals,
                        "result": result,
                        "venue": "home" if is_home else "away",
                    })
                except KeyError as e:
                    logger.warning(f"Missing data in match: {e}")
                    continue
                    
            logger.info(f"Got {len(matches)} matches for team {team_id}")
            return matches
            
        except Exception as e:
            logger.error(f"Error getting matches for team {team_id}: {e}")
            return []

    async def get_team_season_stats(self, team_id: int, league_code: str) -> dict:
        """Получение статистики сезона"""
        try:
            data = await self._get(f"competitions/{league_code}/standings")
            if not data:
                return {}
                
            standings = data.get("standings", [])
            
            for group in standings:
                for team in group.get("table", []):
                    if team.get("team", {}).get("id") == team_id:
                        played = team.get("playedGames", 0)
                        if played == 0:
                            return {
                                "played": 0,
                                "wins": 0,
                                "draws": 0,
                                "losses": 0,
                                "goals_for": 0,
                                "goals_against": 0,
                                "avg_goals_for": 0,
                                "avg_goals_against": 0,
                                "form": "",
                                "position": team.get("position", 0),
                                "points": team.get("points", 0),
                            }
                            
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
                            "avg_goals_for": round(goals_for / played, 2),
                            "avg_goals_against": round(goals_against / played, 2),
                            "form": form[-5:],
                            "position": team.get("position", 0),
                            "points": team.get("points", 0),
                        }
            return {}
            
        except Exception as e:
            logger.error(f"Error getting season stats for team {team_id}: {e}")
            return {}

    async def get_full_team_stats(self, team_name: str, league_key: str) -> dict:
        """Получение полной статистики команды"""
        try:
            league_code = LEAGUE_MAP.get(league_key)
            if not league_code:
                logger.warning(f"League not supported: {league_key}")
                return {}
                
            team_id = await self.search_team_id(team_name, league_code)
            if not team_id:
                return {}
                
            # Выполняем запросы параллельно
            last_matches_task = self.get_last_matches(team_id)
            season_stats_task = self.get_team_season_stats(team_id, league_code)
            
            last_matches, season_stats = await asyncio.gather(
                last_matches_task,
                season_stats_task,
                return_exceptions=True
            )
            
            # Обрабатываем возможные исключения
            if isinstance(last_matches, Exception):
                logger.error(f"Error getting last matches: {last_matches}")
                last_matches = []
                
            if isinstance(season_stats, Exception):
                logger.error(f"Error getting season stats: {season_stats}")
                season_stats = {}
                
            return {
                "team_id": team_id,
                "team_name": team_name,
                "last_matches": last_matches if isinstance(last_matches, list) else [],
                "season_stats": season_stats if isinstance(season_stats, dict) else {},
            }
            
        except Exception as e:
            logger.error(f"Error getting full stats for {team_name}: {e}")
            return {}

    async def get_match_result(self, home_team: str, away_team: str) -> dict | None:
        """Получение результата матча"""
        return None


# Решение проблемы с pgbouncer - добавим функцию для настройки соединения
async def init_db_connection(conn: Connection) -> None:
    """Инициализация соединения с БД для работы через pgbouncer"""
    # Отключаем подготовленные запросы для совместимости с pgbouncer
    await conn.execute("SET SESSION statement_timeout = '30s'")
    # Дополнительные настройки для pgbouncer
    await conn.execute("SET SESSION idle_in_transaction_session_timeout = '5min'")


# Пример использования при создании пула соединений:
"""
# Вместо стандартного создания пула:
pool = await asyncpg.create_pool(dsn, min_size=5, max_size=20)

# Используйте:
pool = await asyncpg.create_pool(
    dsn,
    min_size=5,
    max_size=20,
    statement_cache_size=0,  # Отключаем кэш подготовленных запросов
    max_cached_statement_lifetime=0,  # Отключаем кэширование
    init=init_db_connection  # Функция инициализации соединения
)
"""
