import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Request
from pydantic import Field

from app.core.auth import Ctx, identity
from app.core.db import audit, digest, get, insert, update, wire
from app.core.errors import require
from app.core.schemas import Patch, Strict

router = APIRouter(prefix="/api/v1", tags=["identity"])


class HouseholdInput(Strict):
    name: str = Field(min_length=1, max_length=100)
    timezone: str = "America/Sao_Paulo"


@router.get("/households")
async def households(request: Request):
    return {"data": (await identity(request))["households"]}


@router.post("/households", status_code=201)
async def create_household(body: HouseholdInput, ctx: Ctx):
    ctx.write(admin=True)
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        require(False, "Fuso horário inválido.")
    new_id = uuid4()
    from app.core.db import set_scope

    await set_scope(ctx.conn, ctx.tenant_id, new_id)
    await ctx.conn.execute(
        "INSERT INTO households(id,tenant_id,name,timezone) VALUES($1,$2,$3,$4)",
        new_id,
        ctx.tenant_id,
        body.name,
        body.timezone,
    )
    old = ctx.household_id
    ctx.household_id = new_id
    await insert(ctx, "household_members", {"user_id": ctx.user_id, "role": "OWNER"})
    result = {"id": new_id, "name": body.name, "timezone": body.timezone}
    await audit(ctx, "CREATE", "households", result)
    ctx.household_id = old
    await set_scope(ctx.conn, ctx.tenant_id, old)
    return wire(result)


@router.get("/members")
async def members(ctx: Ctx):
    return wire(
        {
            "data": [
                dict(r)
                for r in await ctx.conn.fetch(
                    "SELECT m.*,u.email,u.display_name FROM household_members m JOIN users u ON u.id=m.user_id ORDER BY m.created_at"
                )
            ]
        }
    )


class Invite(Strict):
    email: str = Field(min_length=3, max_length=254)
    role: str = "MEMBER"


@router.post("/members", status_code=201)
async def invite(body: Invite, ctx: Ctx):
    ctx.write(admin=True)
    require(body.role in ("ADMIN", "MEMBER", "VIEWER"), "Papel inválido.")
    token = secrets.token_urlsafe(32)
    record = await insert(
        ctx,
        "member_invites",
        {
            "email": body.email.lower(),
            "role": body.role,
            "token_hash": digest(token),
            "expires_at": datetime.now(timezone.utc) + timedelta(days=2),
            "invited_by": ctx.user_id,
        },
    )
    await audit(ctx, "INVITE", "member_invites", record)
    return {"id": str(record["id"]), "token": token, "expires_at": record["expires_at"].isoformat()}


async def revoke_access(ctx, user_id):
    await ctx.conn.execute(
        "UPDATE pending_financial_actions SET status='CANCELLED',version=version+1 WHERE user_id=$1 AND status IN ('WAITING_INFORMATION','WAITING_CONFIRMATION')",
        user_id,
    )
    await ctx.conn.execute(
        "UPDATE channel_identities SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", user_id
    )


@router.patch("/members/{id}")
async def edit_member(id: UUID, body: Patch, ctx: Ctx):
    ctx.write(admin=True)
    require(set(body.changes) <= {"role", "status"}, "Campos de membro inválidos.")
    old = await get(ctx, "household_members", id)
    new = old | body.changes
    require(
        new["role"] in ("OWNER", "ADMIN", "MEMBER", "VIEWER") and new["status"] in ("ACTIVE", "REVOKED"),
        "Papel ou estado inválido.",
    )
    if old["role"] == "OWNER" or new["role"] == "OWNER":
        require(ctx.role == "OWNER", "Somente owner pode mudar proprietários.", "FORBIDDEN", 403)
    if (
        old["role"] == "OWNER"
        and old["status"] == "ACTIVE"
        and (new["role"] != "OWNER" or new["status"] != "ACTIVE")
    ):
        count = await ctx.conn.fetchval(
            "SELECT count(*) FROM household_members WHERE role='OWNER' AND status='ACTIVE'"
        )
        require(count > 1, "A família precisa de pelo menos um owner.")
    record = await update(ctx, "household_members", id, body.changes, expected_version=body.expected_version)
    if new["status"] == "REVOKED" or new["role"] == "VIEWER":
        await revoke_access(ctx, old["user_id"])
    await audit(ctx, "UPDATE", "household_members", record, old)
    return wire(record)


@router.delete("/members/{id}")
async def delete_member(id: UUID, ctx: Ctx, expected_version: int):
    return await edit_member(id, Patch(expected_version=expected_version, changes={"status": "REVOKED"}), ctx)
