from app.db.db_pool import DatabasePool


async def check_health(pool: DatabasePool) -> dict[str, str]:
    row = await pool.fetch_one("SELECT 1 AS ok")
    return {
        "database": "ok" if row and row["ok"] == 1 else "error"
    }
