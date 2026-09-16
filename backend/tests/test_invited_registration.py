from uuid import uuid4

import httpx
import pytest

from app.main import app


@pytest.mark.asyncio
async def test_invite_registers_only_matching_email_and_can_log_in(client, family):
    email = f"member-{uuid4().hex[:12]}@example.com"
    invited = await client.post("/api/v1/members", json={"email": email, "role": "MEMBER"})
    assert invited.status_code == 201, invited.text
    token = invited.json()["token"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Origin": "http://localhost:5173"},
    ) as guest:
        wrong = await guest.post(
            "/api/v1/auth/invitations/register",
            json={"token": token, "email": "other@example.com", "display_name": "Other", "password": "a-long-test-password"},
        )
        assert wrong.status_code == 422
        registered = await guest.post(
            "/api/v1/auth/invitations/register",
            json={"token": token, "email": email, "display_name": "Family member", "password": "a-long-test-password"},
        )
        assert registered.status_code == 201, registered.text
        assert registered.json()["tenant"] == family["slug"]
        replay = await guest.post(
            "/api/v1/auth/invitations/register",
            json={"token": token, "email": email, "display_name": "Family member", "password": "a-long-test-password"},
        )
        assert replay.status_code == 422
        login = await guest.post(
            "/api/v1/auth/login",
            json={"tenant": family["slug"], "email": email, "password": "a-long-test-password"},
        )
        assert login.status_code == 200, login.text
        member = await guest.get("/api/v1/auth/me")
        assert member.status_code == 200, member.text
        assert member.json()["households"][0]["role"] == "MEMBER"
