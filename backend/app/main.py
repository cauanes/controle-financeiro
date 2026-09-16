from contextlib import asynccontextmanager
from uuid import uuid4

import asyncpg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.core.auth import router as auth_router
from app.core.config import settings
from app.core.db import make_pool
from app.core.errors import DomainError
from app.modules.analytics.api import router as analytics_router
from app.modules.conversations.api import router as conversations_router
from app.modules.identity.api import router as identity_router
from app.modules.ingestion.api import router as imports_router
from app.modules.integrations.api import router as integrations_router
from app.modules.ledger.api import router as ledger_router
from app.modules.notifications.api import router as alerts_router
from app.modules.planning.api import router as planning_router
from app.modules.resources import router as resources_router


@asynccontextmanager
async def lifespan(app):
    settings.validate_runtime()
    app.state.pool = await make_pool()
    async with app.state.pool.acquire() as conn:
        unsafe = await conn.fetchval(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user"
        )
        if unsafe:
            raise RuntimeError("API must use a non-superuser role without BYPASSRLS")
    yield
    await app.state.pool.close()


app = FastAPI(title="Family Finance Hub", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Household-Id", "X-CSRF-Token", "Idempotency-Key"],
)


@app.middleware("http")
async def request_headers(request: Request, call_next):
    request.state.correlation_id = str(uuid4())
    length = request.headers.get("content-length", "0")
    if length.isdigit() and int(length) > 22 * 1024 * 1024:
        return JSONResponse({"error": {"code": "TOO_LARGE", "message": "Requisição excede o limite."}}, 413)
    response = await call_next(request)
    response.headers["X-Correlation-Id"] = request.state.correlation_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


def error_response(request, status, code, message, fields=None):
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "fields": fields,
                "correlation_id": getattr(request.state, "correlation_id", None),
            }
        },
        status_code=status,
    )


@app.exception_handler(DomainError)
async def domain_error(request, exc):
    return error_response(request, exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
@app.exception_handler(ValidationError)
async def validation_error(request, exc):
    return error_response(
        request,
        422,
        "VALIDATION_ERROR",
        "Confira os campos informados.",
        [{"field": ".".join(str(x) for x in e["loc"]), "message": e["msg"]} for e in exc.errors()],
    )


@app.exception_handler(asyncpg.IntegrityConstraintViolationError)
async def constraint_error(request, exc):
    return error_response(
        request, 409, "INTEGRITY_CONFLICT", "Operação incompatível com os registros existentes."
    )


@app.get("/health/live")
async def live():
    return {"status": "ok"}


@app.get("/health/ready")
async def ready(request: Request):
    from redis.asyncio import Redis

    try:
        async with request.app.state.pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        async with Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1) as redis:
            await redis.ping()
        return {"status": "ready"}
    except (OSError, ConnectionError, __import__("redis").exceptions.RedisError):
        return JSONResponse({"status": "degraded"}, 503)


for router in (auth_router, identity_router, ledger_router, resources_router):
    app.include_router(router)

for router in (
    analytics_router,
    conversations_router,
    imports_router,
    integrations_router,
    alerts_router,
    planning_router,
):
    app.include_router(router)
