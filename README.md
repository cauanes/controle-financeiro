# Cacau Finanças da Família

Aplicação de finanças familiares com FastAPI, PostgreSQL, Redis, React e conversas por WhatsApp via Evolution API. Texto e áudio passam pelo mesmo motor; dados materiais incertos ficam pendentes até o usuário confirmar.

## Iniciar localmente

Requisitos: Docker com Compose e a rede `cacauweb-net` do cacauwebproduct já criada. Em ambiente local, crie `.env` a partir de [`.env.example`](.env.example), substitua as duas senhas do banco e execute:

```bash
cp .env.example .env
docker compose --env-file .env -f infra/compose.yaml up -d --build
docker compose --env-file .env -f infra/compose.yaml ps
```

Crie o primeiro tenant, família e usuário. O comando pede a senha inicial sem exibi-la:

```bash
docker compose --env-file .env -f infra/compose.yaml run --rm migrate python -m app.bootstrap --tenant minha-familia --email voce@exemplo.com --name "Minha família"
```

A interface fica em <http://localhost:8080>, a API em <http://localhost:8002>, e a documentação interativa da API em <http://localhost:8002/docs>. O identificador pedido no login é o valor de `--tenant`. Para rodar os testes locais, use `cd backend && uv sync --group dev && uv run pytest`; eles exigem uma instância PostgreSQL local conforme [estratégia de testes](docs/TESTING_STRATEGY.md).

O Compose inicia banco, Redis, migrações, API, worker e frontend. A API usa o papel `finance_runtime`, sem privilégio de superusuário ou bypass de RLS. O serviço de migração usa credencial separada. Configure `ENVIRONMENT=production`, origem HTTPS e `COOKIE_SECURE=true` antes de expor o serviço à internet.

## WhatsApp e grupo da família

A integração precisa de uma instância Evolution conectada e de webhook autenticado. Cada pessoa entra por convite, vincula seu próprio número enviando `vincular <código>` em conversa privada e, depois, um administrador cria o grupo em **Configurações → WhatsApp e integrações**. O bot responde no grupo apenas a participantes vinculados; mensagens de conversa comum não acionam lançamentos. Veja o [guia do grupo](docs/runbooks/WHATSAPP_GROUP.md) para configuração, reconexão e limites.

O áudio requer um serviço de transcrição configurado em `TRANSCRIPTION_URL`. Sem ele, o usuário pode continuar por texto. Conectores Open Finance não estão ativos nesta versão.

## Documentação

- [PRD](docs/PRD.md) e [plano de implementação](docs/CODEX_IMPLEMENTATION_PLAN.md)
- [Regras financeiras](docs/FINANCIAL_RULES.md), [segurança](docs/SECURITY.md), [esquema](docs/DATABASE_SCHEMA.md)
- [Conversação](docs/CONVERSATION_ENGINE.md), [WhatsApp](docs/WHATSAPP_SPEC.md), [áudio](docs/AUDIO_INGESTION.md)
- [Frontend](docs/FRONTEND_SPEC.md), [API](docs/API_SPEC.md), [testes](docs/TESTING_STRATEGY.md)
