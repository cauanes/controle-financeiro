"""Provision the limited API role after migrations, using the migration connection."""

import asyncio
import os

import asyncpg


async def setup():
    password = os.environ["APP_DB_PASSWORD"]
    if not password:
        raise ValueError("APP_DB_PASSWORD não pode estar vazio")
    conn = await asyncpg.connect(os.environ["MIGRATION_DATABASE_URL"])
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname='finance_runtime'")
        command = "ALTER ROLE" if exists else "CREATE ROLE"
        statement = await conn.fetchval(
            "SELECT format($1::text, $2::text)", f"{command} finance_runtime LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L", password
        )
        await conn.execute(statement)
        await conn.execute("GRANT ff_app TO finance_runtime")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(setup())
