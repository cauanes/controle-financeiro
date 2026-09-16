from datetime import date
from uuid import UUID

from fastapi import APIRouter, Query

from app.core.auth import Ctx
from app.core.db import get, rows, wire
from app.modules.analytics import forecast, service

router = APIRouter(prefix="/api/v1", tags=["analytics"])


@router.get("/analytics/summary")
async def summary(ctx: Ctx, from_: date | None = Query(None, alias="from"), to: date | None = None):
    return wire(await service.summary(ctx, from_, to))


@router.get("/analytics/categories")
async def categories(ctx: Ctx, from_: date | None = Query(None, alias="from"), to: date | None = None):
    return wire(await service.categories(ctx, from_, to))


@router.get("/analytics/cashflow")
async def cashflow(
    ctx: Ctx,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    account_id: UUID | None = None,
):
    if account_id:
        await get(ctx, "accounts", account_id)
    return wire(await service.cashflow(ctx, from_, to, account_id))


@router.get("/analytics/net-worth")
async def net_worth(ctx: Ctx):
    result = await service.summary(ctx)
    snapshots = [
        s for s in await rows(ctx, "financial_snapshots") if not s["calculation_version"].startswith("stale:")
    ]
    return wire(
        {
            "net_worth": result["net_worth"],
            "available": result["available"],
            "assets": result["independent_assets"],
            "liabilities": result["independent_liabilities"],
            "card_debt": result["card_debt"],
            "as_of": ctx.today(),
            "snapshots": snapshots,
        }
    )


@router.get("/analytics/financial-health")
async def health(ctx: Ctx, from_: date | None = Query(None, alias="from"), to: date | None = None):
    return wire(await service.health(ctx, from_, to))


@router.get("/forecast/cashflow")
async def forecast_cash(
    ctx: Ctx,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    account_id: UUID | None = None,
):
    return wire(await forecast.cashflow(ctx, from_, to, account_id))


@router.get("/forecast/categories")
async def forecast_categories(ctx: Ctx, month: str | None = None):
    return wire(await forecast.categories(ctx, month))
