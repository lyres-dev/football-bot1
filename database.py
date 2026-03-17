import asyncpg
import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(
    os.getenv("DATABASE_URL"),
    ssl="require",
    statement_cache_size=0
)

        await self.create_tables()
        logger.info("Database connected")

    async def create_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS predictions (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    match_id TEXT NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    analysis_type TEXT NOT NULL,
                    prediction_text TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW(),
                    match_date TEXT,
                    match_timestamp TIMESTAMP,
                    result_home INT DEFAULT NULL,
                    result_away INT DEFAULT NULL,
                    is_correct BOOLEAN DEFAULT NULL,
                    resolved_at TIMESTAMP DEFAULT NULL,
                    auto_checked BOOLEAN DEFAULT FALSE
                )
            """)

    async def save_prediction(self, user_id: int, match: dict,
                               analysis_type: str, prediction_text: str) -> int:
        match_timestamp = None
        try:
            raw = match.get("commence_time", "")
            if raw:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                match_timestamp = dt.replace(tzinfo=None)
        except:
            pass

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO predictions
                  (user_id, match_id, home_team, away_team, analysis_type,
                   prediction_text, match_date, match_timestamp)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                RETURNING id
            """, user_id, match["id"], match["home_team"], match["away_team"],
                analysis_type, prediction_text,
                match.get("commence_time_str", ""), match_timestamp)
            return row["id"]

    async def get_predictions_to_check(self, delay_hours: int = 3) -> list:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=delay_hours)
        cutoff_naive = cutoff.replace(tzinfo=None)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM predictions
                WHERE is_correct IS NULL
                  AND match_timestamp IS NOT NULL
                  AND match_timestamp <= $1
                ORDER BY match_timestamp ASC
                LIMIT 50
            """, cutoff_naive)
            return [dict(r) for r in rows]

    async def get_pending_predictions(self, user_id: int) -> list:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM predictions
                WHERE user_id = $1 AND is_correct IS NULL
                ORDER BY created_at DESC LIMIT 20
            """, user_id)
            return [dict(r) for r in rows]

    async def resolve_prediction(self, pred_id: int, home_score: int,
                                  away_score: int, is_correct: bool):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE predictions
                SET result_home=$1, result_away=$2, is_correct=$3,
                    resolved_at=NOW(), auto_checked=TRUE
                WHERE id=$4
            """, home_score, away_score, is_correct, pred_id)

    async def get_stats(self, user_id: int) -> dict:
        async with self.pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM predictions WHERE user_id=$1", user_id)
            resolved = await conn.fetchval(
                "SELECT COUNT(*) FROM predictions WHERE user_id=$1 AND is_correct IS NOT NULL", user_id)
            correct = await conn.fetchval(
                "SELECT COUNT(*) FROM predictions WHERE user_id=$1 AND is_correct=TRUE", user_id)
            by_type = await conn.fetch("""
                SELECT analysis_type,
                       COUNT(*) as total,
                       SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct
                FROM predictions
                WHERE user_id=$1 AND is_correct IS NOT NULL
                GROUP BY analysis_type
            """, user_id)
            recent = await conn.fetch("""
                SELECT home_team, away_team, analysis_type, is_correct,
                       result_home, result_away, resolved_at, auto_checked
                FROM predictions
                WHERE user_id=$1 AND is_correct IS NOT NULL
                ORDER BY resolved_at DESC LIMIT 5
            """, user_id)
            return {
                "total": total, "resolved": resolved, "correct": correct,
                "by_type": [dict(r) for r in by_type],
                "recent": [dict(r) for r in recent],
            }

    async def get_prediction_by_id(self, pred_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM predictions WHERE id=$1 AND user_id=$2", pred_id, user_id)
            return dict(row) if row else None

db = Database()
