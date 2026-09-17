from uuid import UUID

from fastapi import APIRouter
from pydantic import Field

from app.core.auth import Ctx
from app.core.db import audit, get, insert, rows, wire
from app.core.errors import require
from app.core.schemas import Strict
from app.modules.resources import normalize

router = APIRouter(prefix="/api/v1/income-activities", tags=["income-activities"])


class IncomeActivity(Strict):
    user_id: UUID
    category_id: UUID
    keywords: list[str] = Field(default_factory=list, max_length=20)


@router.get("")
async def listing(ctx: Ctx):
    return wire({"data": await rows(ctx, "income_activity_profiles")})


@router.post("", status_code=201)
async def creating(body: IncomeActivity, ctx: Ctx):
    ctx.write(admin=True)
    member = await ctx.conn.fetchrow(
        "SELECT status FROM household_members WHERE user_id=$1", body.user_id
    )
    require(member and member["status"] == "ACTIVE", "Membro ativo não encontrado.")
    category = await get(ctx, "categories", body.category_id)
    require(category["kind"] == "INCOME" and not category["archived_at"], "Categoria de receita inválida.")
    keywords = list(dict.fromkeys(normalize(word) for word in body.keywords if word.strip()))
    require(all(2 <= len(word) <= 80 for word in keywords), "Palavra-chave inválida.")
    existing = await ctx.conn.fetchval(
        "SELECT id FROM income_activity_profiles WHERE user_id=$1 AND category_id=$2",
        body.user_id,
        body.category_id,
    )
    require(not existing, "Atividade já vinculada a esta pessoa.", "CONFLICT", 409)
    result = await insert(
        ctx,
        "income_activity_profiles",
        {"user_id": body.user_id, "category_id": body.category_id, "keywords": keywords},
    )
    await audit(ctx, "CREATE", "income_activity_profiles", result)
    return wire(result)


@router.delete("/{id}", status_code=204)
async def deleting(id: UUID, ctx: Ctx):
    ctx.write(admin=True)
    profile = await get(ctx, "income_activity_profiles", id)
    await audit(ctx, "DELETE", "income_activity_profiles", profile)
    await ctx.conn.execute("DELETE FROM income_activity_profiles WHERE id=$1", id)
