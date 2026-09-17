# Cacau Finanças da Família

Aplicação de finanças familiares com FastAPI, PostgreSQL, Redis, React e conversas por WhatsApp via Evolution API. Texto, áudio e imagens de fatura são recebidos pelo grupo; dados materiais incertos ficam pendentes até o usuário confirmar.

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

Para receitas, o bot usa os vínculos entre membro e atividade em `GET/POST /api/v1/income-activities`. Uma frase como `Recebi 770 Paciente Alice` pode sugerir Psicologia, mas o bot pergunta se a receita pertence à Carla ou ao Cauan quando ambos exercem essa atividade. Ele pede conta ou outra informação ausente e sempre mostra pessoa, atividade, valor, conta, data e descrição para confirmação antes de criar a transação.

Esses vínculos aparecem em **Configurações → Atividades de receita**. No WhatsApp, as perguntas oferecem opções numeradas (`1`, `2`...) e aceitam também o nome; na tela **Conversar**, as opções são botões clicáveis. A instância atual usa Evolution 2.3.7 com Baileys 7.0.0-rc.9, combinação com relatos de falha em botões nativos; veja o [guia do grupo](docs/runbooks/WHATSAPP_GROUP.md).

O áudio requer um serviço de transcrição configurado em `TRANSCRIPTION_URL`. Sem ele, o usuário pode continuar por texto. Conectores Open Finance não estão ativos nesta versão.

Fotos e prints JPG/PNG/WebP são lidos localmente com Tesseract OCR, sem serviço de IA. O bot propõe despesas com valor, data, comerciante e categoria sugerida; também avisa sobre valores ilegíveis, possíveis duplicatas e diferença entre a soma dos itens e o total da fatura. Nada é importado antes de uma confirmação explícita. Enquanto houver outro lançamento pendente na mesma conversa, o bot lê a imagem, informa o conflito e pede para concluir ou cancelar a pendência antes de reenviar a fatura. Veja os comandos de revisão no [guia do grupo](docs/runbooks/WHATSAPP_GROUP.md).

## Documentação

- [PRD](docs/PRD.md) e [plano de implementação](docs/CODEX_IMPLEMENTATION_PLAN.md)
- [Estado de cada entrega](docs/IMPLEMENTATION_STATUS.md)
- [Regras financeiras](docs/FINANCIAL_RULES.md), [segurança](docs/SECURITY.md), [esquema](docs/DATABASE_SCHEMA.md)
- [Conversação](docs/CONVERSATION_ENGINE.md), [WhatsApp](docs/WHATSAPP_SPEC.md), [áudio](docs/AUDIO_INGESTION.md)
- [Frontend](docs/FRONTEND_SPEC.md), [API](docs/API_SPEC.md), [testes](docs/TESTING_STRATEGY.md)
