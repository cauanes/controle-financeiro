from urllib.parse import quote, urlparse

import httpx

from app.core.config import settings
from app.core.errors import require
from app.modules.ingestion.audio import MAX_BYTES, decode_audio


class EvolutionAdapter:
    """Evolution v2 envelope. Base URL is deployment-owned, never copied from a webhook."""

    def __init__(self):
        self.base = settings.evolution_base_url.rstrip("/")
        self.headers = {"apikey": settings.evolution_api_key}

    def configured(self):
        require(
            self.base and settings.evolution_api_key,
            "Evolution API não configurada.",
            "PROVIDER_UNAVAILABLE",
            503,
        )
        parsed = urlparse(self.base)
        require(
            parsed.scheme == "https" or (settings.environment != "production" and parsed.scheme == "http"),
            "Evolution precisa de HTTPS em produção.",
        )

    async def media(self, instance, message):
        self.configured()
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            async with client.stream(
                "POST",
                self.base + "/chat/getBase64FromMediaMessage/" + quote(instance, safe=""),
                headers=self.headers,
                json={"message": {"key": message["key"]}, "convertToMp4": False},
            ) as res:
                require(res.is_success, "Falha ao baixar áudio.", "MEDIA_FAILED", 503)
                chunks = bytearray()
                async for chunk in res.aiter_bytes():
                    chunks.extend(chunk)
                    require(len(chunks) <= MAX_BYTES * 2, "Mídia excede limite.")
                import json

                body = json.loads(chunks)
        mime = body.get("mimetype") or message.get("mime_type", "audio/ogg")
        return decode_audio(body.get("base64", ""), mime, message.get("duration")), mime

    async def send(self, instance, recipient, text):
        self.configured()
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            res = await client.post(
                self.base + "/message/sendText/" + quote(instance, safe=""),
                headers=self.headers,
                json={
                    "number": recipient if recipient.endswith("@g.us") else recipient.split("@")[0],
                    "text": text,
                },
            )
        require(res.is_success, "Falha no envio ao WhatsApp.", "DELIVERY_FAILED", 503)
    async def send_reaction(self, instance, key_id, remote_jid, emoji):
        if not (self.base and settings.evolution_api_key):
            return
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                await client.post(
                    self.base + "/message/sendReaction/" + quote(instance, safe=""),
                    headers=self.headers,
                    json={"key": {"id": key_id, "remoteJid": remote_jid, "fromMe": False}, "reaction": emoji},
                )
        except Exception:
            pass

    async def create_group(self, instance, subject, participants, description):
        self.configured()
        async with httpx.AsyncClient(timeout=35, follow_redirects=False) as client:
            res = await client.post(
                self.base + "/group/create/" + quote(instance, safe=""),
                headers=self.headers,
                json={"subject": subject, "description": description, "participants": participants},
            )
        require(
            res.is_success,
            "Evolution não conseguiu criar o grupo. Verifique a conexão do WhatsApp.",
            "GROUP_CREATE_FAILED",
            503,
        )
        group = res.json()
        require(
            isinstance(group.get("id"), str) and group["id"].endswith("@g.us"),
            "Evolution não retornou o identificador do grupo.",
            "GROUP_CREATE_FAILED",
            503,
        )
        return group

    async def group_info(self, instance, group_jid):
        self.configured()
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            res = await client.get(
                self.base + "/group/findGroupInfos/" + quote(instance, safe=""),
                headers=self.headers,
                params={"groupJid": group_jid},
            )
        require(res.is_success, "Grupo não encontrado na instância Evolution.", "GROUP_NOT_FOUND", 404)
        return res.json()

    async def test(self, instance):
        self.configured()
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            res = await client.get(
                self.base + "/instance/connectionState/" + quote(instance, safe=""), headers=self.headers
            )
        require(res.is_success, "Não foi possível consultar a conexão.", "PROVIDER_UNAVAILABLE", 503)
        return res.json()
