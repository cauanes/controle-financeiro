import asyncio
import hashlib
import os
from pathlib import Path

import asyncpg


async def migrate(url=None):
    conn = await asyncpg.connect(url or os.environ["MIGRATION_DATABASE_URL"])
    try:
        await conn.execute("SELECT pg_advisory_lock(78290411)")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations(name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for path in sorted((Path(__file__).parent.parent / "migrations").glob("*.sql")):
            sql = path.read_text()
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            old = await conn.fetchval("SELECT checksum FROM schema_migrations WHERE name=$1", path.name)
            if old:
                if old != checksum:
                    raise RuntimeError(f"Migration modificada após aplicação: {path.name}")
                continue
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations(name,checksum) VALUES($1,$2)", path.name, checksum
                )
            print(f"Applied {path.name}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(migrate())
