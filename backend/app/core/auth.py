import secrets
from typing import Annotated
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.core.db import Context, digest, set_scope
from app.core.errors import require

hasher = PasswordHasher()
DUMMY_HASH = hasher.hash("constant-time-invalid-user-placeholder")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class Login(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tenant: str | None = None
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=512)


def check_origin(request):
    origin = request.headers.get("origin")
    require(origin in settings.allowed_origins.split(","), "Origem não autorizada.", "CSRF_REJECTED", 403)


def cookies(response, access, refresh, csrf):
    for name, value, age, http_only in [
        ("ff_access", access, 1800, True),
        ("ff_refresh", refresh, 2592000, True),
        ("ff_csrf", csrf, 2592000, False),
    ]:
        response.set_cookie(
            name,
            value,
            max_age=age,
            httponly=http_only,
            secure=settings.cookie_secure,
            samesite="strict",
            path="/",
        )


@router.post("/login")
async def login(body: Login, request: Request, response: Response):
    check_origin(request)
    tenant_slug = body.tenant.lower() if body.tenant else None
    throttle_key = digest((tenant_slug + ":" if tenant_slug else "") + body.email.lower())
    async with request.app.state.pool.acquire() as conn:
        allowed = await conn.fetchval(
            "SELECT throttle_login($1)", throttle_key
        )
        require(allowed, "Muitas tentativas. Aguarde 15 minutos.", "RATE_LIMITED", 429)
        user = await conn.fetchrow(
            "SELECT * FROM login_lookup($1,$2)", tenant_slug, body.email.lower()
        )
        import asyncio

        try:
            valid = await asyncio.to_thread(
                hasher.verify, user["password_hash"] if user else DUMMY_HASH, body.password
            )
        except VerificationError:
            valid = False
        require(valid and user, "Credenciais inválidas.", "UNAUTHENTICATED", 401)
        access, refresh, csrf = (secrets.token_urlsafe(32) for _ in range(3))
        await conn.execute(
            "SELECT new_session($1,$2,$3,$4,$5,$6,$7)",
            uuid4(),
            user["tenant_id"],
            user["id"],
            digest(access),
            digest(refresh),
            digest(csrf),
            uuid4(),
        )
    cookies(response, access, refresh, csrf)
    return {"status": "authenticated"}


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    check_origin(request)
    require(
        request.cookies.get("ff_csrf")
        and secrets.compare_digest(
            request.cookies.get("ff_csrf", ""), request.headers.get("x-csrf-token", "")
        ),
        "CSRF inválido.",
        "CSRF_REJECTED",
        403,
    )
    access, token, csrf = (secrets.token_urlsafe(32) for _ in range(3))
    async with request.app.state.pool.acquire() as conn:
        valid = await conn.fetchval(
            "SELECT rotate_session($1,$2,$3,$4,$5)",
            digest(request.cookies.get("ff_refresh", "")),
            uuid4(),
            digest(access),
            digest(token),
            digest(csrf),
        )
    require(valid, "Sessão expirada. Entre novamente.", "UNAUTHENTICATED", 401)
    cookies(response, access, token, csrf)
    return {"status": "authenticated"}


async def identity(request):
    async with request.app.state.pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT resolve_session($1)", digest(request.cookies.get("ff_access", ""))
        )
    require(result, "Entre para continuar.", "UNAUTHENTICATED", 401)
    return result


@router.get("/me")
async def me(request: Request):
    result = await identity(request)
    return {k: v for k, v in result.items() if k not in ("csrf_hash", "id")}


@router.post("/logout")
async def logout(request: Request, response: Response):
    check_origin(request)
    result = await identity(request)
    require(
        secrets.compare_digest(result["csrf_hash"], digest(request.headers.get("x-csrf-token", ""))),
        "CSRF inválido.",
        "CSRF_REJECTED",
        403,
    )
    async with request.app.state.pool.acquire() as conn:
        await conn.execute("SELECT revoke_session($1)", digest(request.cookies.get("ff_access", "")))
    for name in ("ff_access", "ff_refresh", "ff_csrf"):
        response.delete_cookie(name, path="/")
    return {"status": "signed_out"}


async def context(request: Request):
    async with request.app.state.pool.acquire() as conn, conn.transaction():
        auth = await conn.fetchval("SELECT resolve_session($1)", digest(request.cookies.get("ff_access", "")))
        require(auth, "Entre para continuar.", "UNAUTHENTICATED", 401)
        selected = request.headers.get("x-household-id", "")
        house = next((h for h in auth["households"] if h["id"] == selected), None)
        require(house, "Família não encontrada.", "NOT_FOUND", 404)
        mutating = request.method not in ("GET", "HEAD", "OPTIONS")
        if mutating:
            check_origin(request)
            require(
                secrets.compare_digest(auth["csrf_hash"], digest(request.headers.get("x-csrf-token", ""))),
                "CSRF inválido.",
                "CSRF_REJECTED",
                403,
            )
        await set_scope(conn, auth["tenant_id"], selected)
        ctx = Context(
            conn,
            UUID(auth["tenant_id"]),
            UUID(selected),
            UUID(auth["user_id"]),
            house["role"],
            house["timezone"],
        )
        if mutating:
            ctx.write()
            await ctx.lock()
            # Recheck membership after waiting on concurrent revocation.
            member = await conn.fetchrow(
                "SELECT role FROM household_members WHERE user_id=$1 AND status='ACTIVE'", ctx.user_id
            )
            require(member, "Associação revogada.", "FORBIDDEN", 403)
            ctx.role = member["role"]
            ctx.write()
        yield ctx


Ctx = Annotated[Context, Depends(context, scope="function")]


class InviteAcceptance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=16, max_length=200)


class InvitedUserRegistration(InviteAcceptance):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=512)


@router.post("/invitations/register", status_code=201)
async def register_invited_user(body: InvitedUserRegistration, request: Request):
    check_origin(request)
    import asyncio

    password_hash = await asyncio.to_thread(hasher.hash, body.password)
    async with request.app.state.pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT register_invited_user($1,$2,$3,$4)",
            digest(body.token), body.email.strip().lower(), body.display_name.strip(), password_hash,
        )
    require(result, "Convite inválido, vencido ou e-mail já cadastrado.")
    return result


@router.post("/invitations/accept")
async def accept_invitation(body: InviteAcceptance, request: Request):
    check_origin(request)
    auth = await identity(request)
    require(
        secrets.compare_digest(auth["csrf_hash"], digest(request.headers.get("x-csrf-token", ""))),
        "CSRF inválido.",
        "CSRF_REJECTED",
        403,
    )
    async with request.app.state.pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT accept_member_invite($1,$2)",
            digest(body.token),
            digest(request.cookies.get("ff_access", "")),
        )
    require(result, "Convite inválido, vencido ou destinado a outro e-mail.")
    return result
