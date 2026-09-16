from fastapi import APIRouter

from app.core.auth import Ctx
from app.core.db import rows, wire

router = APIRouter(prefix="/api/v1", tags=["alerts"])


@router.get("/alerts")
async def alerts(ctx: Ctx):
    return wire({"data": await rows(ctx, "alerts")})
