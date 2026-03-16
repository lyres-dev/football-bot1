import aiohttp
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"

class OddsAPIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _estimate_btts(self, h2h_odds: dict, total_odds: dict) -> dict:
        try:
            over_key = next((k for k in total_odds if k.startswith("Over")), None)
            over_prob = (1 / total_odds[over_key]) if over_key else 0.45
            draw_odd = h2h_odds.get("Draw", 0)
            draw_prob = (1 / draw_odd) if draw_odd else 0.25
            btts_yes_prob = min(0.85, over_prob * 0.7 + draw_prob * 0.5)
            btts_no_prob = 1 - btts_yes_prob
            return {"Yes": round(1 / btts_yes_prob, 2), "No": round(1 / btts_no_prob, 2)}
        except Exception:
            return {"Yes": 1.85, "No": 1.95}

    async def get_upcoming_matches(self, sport: str, days_ahead: int = 7) -> list[dict]:
        url = f"{BASE_URL}/sports/{sport}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": "eu",
            "markets": "h2h,totals",
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

                h2h_odds = {}
                total_odds = {}

                for bookmaker in event.get("bookmakers", [])[:3]:
                    for market in bookmaker.get("markets", []):
                        if market["key"] == "h2h" and not h2h_odds:
                            for outcome in market["outcomes"]:
                                h2h_odds[outcome["name"]] = outcome["price"]
                        elif market["key"] == "totals" and not total_odds:
                            for outcome in market["outcomes"]:
                                key = f"{outcome['name']}_{outcome.get('point', 2.5)}"
                                total_odds[key] = outcome["price"]

                btts_odds = self._estimate_btts(h2h_odds, total_odds)
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
        url = f"{BASE_URL}/sports"
        params = {"apiKey": self.api_key}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                return await resp.json()
