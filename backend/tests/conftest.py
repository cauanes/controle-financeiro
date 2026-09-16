import os
from uuid import uuid4

import asyncpg
import httpx
import pytest_asyncio

from app.bootstrap import bootstrap
from app.core.db import make_pool
from app.main import app
from app.migrate import migrate


@pytest_asyncio.fixture
async def database():
    url = os.environ.get(
        "TEST_ADMIN_DATABASE_URL", "postgresql://postgres@/postgres?host=/tmp/cacau-finance-pg"
    )
    admin = await asyncpg.connect(url)
    name = "ff_test_" + uuid4().hex[:12]
    await admin.execute(f"CREATE DATABASE {name}")
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    test_url = urlunsplit((parts.scheme, parts.netloc, "/" + name, parts.query, ""))
    await migrate(test_url)
    conn = await asyncpg.connect(test_url)
    await conn.execute(
        "DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='ff_test_runtime') THEN CREATE ROLE ff_test_runtime LOGIN PASSWORD 'testpass' NOSUPERUSER NOBYPASSRLS; ELSE ALTER ROLE ff_test_runtime WITH PASSWORD 'testpass'; END IF; END $$; GRANT ff_app TO ff_test_runtime"
    )
    await conn.close()
    host_part = parts.netloc.split("@")[-1]
    runtime_url = urlunsplit((parts.scheme, f"ff_test_runtime:testpass@{host_part}", "/" + name, parts.query, ""))
    pool = await make_pool(runtime_url)
    app.state.pool = pool
    yield test_url, pool
    await pool.close()
    await admin.execute(f"DROP DATABASE {name} WITH (FORCE)")
    await admin.close()


@pytest_asyncio.fixture
async def family(database):
    url, pool = database
    slug = "test-" + uuid4().hex[:12]
    data = await bootstrap(url, slug, slug + "@example.com", "correct-horse-battery-2026")
    return data | {"slug": slug, "email": slug + "@example.com", "pool": pool, "admin_url": url}


@pytest_asyncio.fixture
async def client(family):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Origin": "http://localhost:5173"},
    ) as client:
        res = await client.post(
            "/api/v1/auth/login",
            json={
                "tenant": family["slug"],
                "email": family["email"],
                "password": "correct-horse-battery-2026",
            },
        )
        assert res.status_code == 200, res.text
        client.headers.update(
            {"X-Household-Id": family["household_id"], "X-CSRF-Token": client.cookies["ff_csrf"]}
        )
        yield client
