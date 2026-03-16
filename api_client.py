import aiohttp
import asyncio
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"

class OddsAPIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    async def get_upcoming_matches(self, sport: str, days_ahead: int = 7) -> list[dict]:
        """Fetch upcoming matches with odds from The Odds API."""
        url = f"{BASE_URL}/sports/{sport}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "eu",
            "markets": "h2h,totals,btts",
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Odds API error {resp.status}: {text}")
                    raise Exception(f"API error: {resp.status}")
                data = await resp.json()

        matches = []
        now = datetime.now(timezone.utc)

        for event in data:
            try:
                commence_time = datetime.fromisoformat(
                    event["commence_time"].replace("Z", "+00:00")
                )
                if commence_time < now:
                    continue

                # Parse odds from bookmakers
                h2h_odds = {}
                total_odds = {}
                btts_odds = {}

                for bookmaker in event.get("bookmakers", [])[:3]:
                    for market in bookmaker.get("markets", []):
                        if market["key"] == "h2h" and not h2h_odds:
                            for outcome in market["outcomes"]:
                                h2h_odds[outcome["name"]] = outcome["price"]
                        elif market["key"] == "totals" and not total_odds:
                            for outcome in market["outcomes"]:
                                key = f"{outcome['name']}_{outcome.get('point', 2.5)}"
                                total_odds[key] = outcome["price"]
                        elif market["key"] == "btts" and not btts_odds:
                            for outcome in market["outcomes"]:
                                btts_odds[outcome["name"]] = outcome["price"]

                # Format date string for Moscow time (UTC+3)
                moscow_time = commence_time.replace(tzinfo=timezone.utc)
                date_str = commence_time.strftime("%d.%m.%Y %H:%M UTC")

                matches.append({
                    "id": event["id"],
                    "sport": event["sport_key"],
                    "home_team": event["home_team"],
                    "away_team": event["away_team"],
                    "commence_time": event["commence_time"],
                    "commence_time_str": date_str,
                    "h2h_odds": h2h_odds,
                    "total_odds": total_odds,
                    "btts_odds": btts_odds,
                })
            except Exception as e:
                logger.warning(f"Error parsing event: {e}")
                continue

        matches.sort(key=lambda x: x["commence_time"])
        return matches[:15]

    async def get_sports(self) -> list[dict]:
        """Get list of available sports/leagues."""
        url = f"{BASE_URL}/sports"
        params = {"apiKey": self.api_key}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()
