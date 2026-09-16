import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import asyncpg

from app.core.config import settings
from app.core.errors import require


def json_default(value):
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(type(value).__name__)


def wire(value):
    return json.loads(json.dumps(value, default=json_default))


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


async def init_connection(conn):
    for typ in ("json", "jsonb"):
        await conn.set_type_codec(
            typ,
            encoder=lambda x: json.dumps(x, default=json_default),
            decoder=json.loads,
            schema="pg_catalog",
        )


async def reset_connection(conn):
    await conn.execute("SELECT set_config('app.tenant_id', '', false), set_config('app.household_id', '', false)")


async def make_pool(url=None):
    return await asyncpg.create_pool(
        url or settings.database_url, min_size=1, max_size=10, init=init_connection, reset=reset_connection
    )


async def set_scope(conn, tenant_id, household_id):
    await conn.execute(
        "SELECT set_config('app.tenant_id',$1,true),set_config('app.household_id',$2,true)",
        str(tenant_id),
        str(household_id),
    )


@dataclass
class Context:
    conn: asyncpg.Connection
    tenant_id: UUID
    household_id: UUID
    user_id: UUID
    role: str = "MEMBER"
    timezone: str = "America/Sao_Paulo"
    origin: str = "MANUAL"

    def today(self):
        return datetime.now(ZoneInfo(self.timezone)).date()

    def write(self, admin=False):
        require(
            self.role in (("OWNER", "ADMIN") if admin else ("OWNER", "ADMIN", "MEMBER")),
            "Sem permissão para essa operação.",
            "FORBIDDEN",
            403,
        )

    async def lock(self):
        # A stable household lock serializes financial commands, including idempotent retries.
        await self.conn.fetchval("SELECT id FROM households WHERE id=$1 FOR UPDATE", self.household_id)


@asynccontextmanager
async def system_context(pool, tenant_id, household_id, user_id=None):
    async with pool.acquire() as conn, conn.transaction():
        await set_scope(conn, tenant_id, household_id)
        house = await conn.fetchrow("SELECT * FROM households WHERE id=$1", household_id)
        ctx = Context(conn, tenant_id, household_id, user_id, "OWNER", house["timezone"])
        await ctx.lock()
        yield ctx


# Only static, server-owned table/column names may enter SQL identifiers.
TABLES = set(
    "household_members member_invites whatsapp_groups accounts categories merchants credit_cards credit_card_invoices transactions transaction_sources invoice_payments category_rules merchant_rules user_financial_preferences integrations channel_identities conversation_sessions conversation_messages pending_financial_actions outgoing_messages webhook_receipts channel_link_tokens import_templates import_jobs import_rows transaction_matches budgets budget_categories recurring_transactions goals goal_contributions assets liabilities financial_snapshots alert_rules alerts audit_logs outbox_events processed_events idempotency_keys".split()
)


def table_name(table):
    assert table in TABLES, table
    return table


async def get(ctx, table, id, *, lock=False):
    row = await ctx.conn.fetchrow(
        f"SELECT * FROM {table_name(table)} WHERE id=$1" + (" FOR UPDATE" if lock else ""), UUID(str(id))
    )
    require(row is not None, "Registro não encontrado.", "NOT_FOUND", 404)
    return dict(row)


async def rows(ctx, table):
    return [
        dict(r) for r in await ctx.conn.fetch(f"SELECT * FROM {table_name(table)} ORDER BY created_at,id")
    ]


async def insert(ctx, table, values):
    values = {"id": uuid4(), "tenant_id": ctx.tenant_id, "household_id": ctx.household_id, **values}
    keys = list(values)
    assert all(k.replace("_", "").isalnum() for k in keys)
    sql = f"INSERT INTO {table_name(table)} ({','.join(keys)}) VALUES ({','.join(f'${i}' for i in range(1, len(keys) + 1))}) RETURNING *"
    return dict(await ctx.conn.fetchrow(sql, *values.values()))


async def update(ctx, table, id, values, *, expected_version=None):
    current = await get(ctx, table, id, lock=True)
    if expected_version is not None:
        require(
            current["version"] == expected_version,
            "O registro mudou. Recarregue antes de confirmar.",
            "VERSION_CONFLICT",
            409,
        )
    assert not {"id", "tenant_id", "household_id", "version", "created_at"} & values.keys()
    keys = list(values)
    assert all(k.replace("_", "").isalnum() for k in keys)
    setters = ",".join(f"{k}=${i}" for i, k in enumerate(keys, 2))
    if setters:
        setters += ","
    return dict(
        await ctx.conn.fetchrow(
            f"UPDATE {table_name(table)} SET {setters}version=version+1,updated_at=now() WHERE id=$1 RETURNING *",
            current["id"],
            *values.values(),
        )
    )


async def audit(ctx, action, table, after, before=None):
    # Financial diffs only; integrations and conversation payloads may contain private content.
    safe = table not in {
        "integrations",
        "conversation_messages",
        "pending_financial_actions",
        "member_invites",
        "channel_link_tokens",
    }
    await insert(
        ctx,
        "audit_logs",
        {
            "actor_user_id": ctx.user_id,
            "action": action,
            "entity_type": table,
            "entity_id": after["id"],
            "before": wire(before) if before and safe else None,
            "after": wire(after) if safe else {"id": str(after["id"])},
            "origin": ctx.origin,
            "correlation_id": uuid4(),
        },
    )


async def emit(ctx, event_type, aggregate_id, payload=None):
    return await insert(
        ctx,
        "outbox_events",
        {"event_type": event_type, "aggregate_id": aggregate_id, "payload": payload or {}},
    )


async def idempotent(ctx, route, key, body, execute):
    require(key and 1 <= len(key) <= 160, "Idempotency-Key é obrigatório (até 160 caracteres).")
    await ctx.lock()
    hashed = digest(json.dumps(wire(body), sort_keys=True))
    old = await ctx.conn.fetchrow(
        "SELECT * FROM idempotency_keys WHERE user_id=$1 AND route=$2 AND key=$3", ctx.user_id, route, key
    )
    if old:
        require(
            old["request_hash"] == hashed,
            "Chave reutilizada com dados diferentes.",
            "IDEMPOTENCY_CONFLICT",
            409,
        )
        return old["response_body"]
    result = wire(await execute())
    from datetime import timedelta, timezone

    await insert(
        ctx,
        "idempotency_keys",
        {
            "user_id": ctx.user_id,
            "route": route,
            "key": key,
            "request_hash": hashed,
            "response_body": result,
            "expires_at": datetime.now(timezone.utc) + timedelta(days=30),
        },
    )
    return result
