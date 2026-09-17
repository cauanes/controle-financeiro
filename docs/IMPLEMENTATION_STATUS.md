# Estado da implementação — 17/09/2026

O plano original permanece como especificação de produto. As migrations foram agrupadas de modo diferente dos números propostos no plano; o esquema aplicado é o dos arquivos em `backend/migrations/001` a `014`. A tabela abaixo registra o que existe e o que ainda depende de validação real. Não considerar uma etapa concluída apenas porque seu endpoint existe.

| Etapa | Entrega implementada | Validação / limite atual |
| --- | --- | --- |
| 01 Identidade | API FastAPI, login, sessões, papéis, RLS, famílias, convites, frontend e Compose. | Testes de autorização e banco passam. Acesso inicial criado e copiado para o banco persistente. |
| 02 Ledger manual | Contas, categorias, receitas, despesas, transferências, precisão Decimal, versões, auditoria e origem. | Testes de saldo, idempotência e conflito passam. |
| 03 Cartões | Cartões, ciclo de fatura, parcelas e pagamentos. | Testes de calendário e parcelamento passam; uso real ainda sem lançamentos. |
| 04 Classificação | Parser determinístico em português, evidência por campo, regras de categoria/merchant e atividades de receita por pessoa. | “Paciente” sugere Psicologia; a associação entre pessoa e trabalho é configurada por família. Não há parser semântico externo configurado. |
| 05 Conversação | Sessões, pendências, perguntas, confirmação/cancelamento, expiração e executor comum. | Receita exige pessoa responsável, atividade, conta, valor e data, e sempre apresenta o resumo completo antes de registrar. Perguntas usam opções numeradas no WhatsApp e botões clicáveis na tela Conversar. |
| 06 Evolution texto | Webhook autenticado, recibos idempotentes, vínculo por código, worker de saída. O cacauwebproduct encaminha eventos da instância `cacauweb`. | Mensagem real do grupo processada e pergunta de esclarecimento entregue no próprio grupo. Mensagens enviadas pelo número conectado são aceitas quando pertencem a membro vinculado; ecos do bot são ignorados. |
| 07 Áudio | Download limitado, assinatura MIME, transcrição configurável, baixa confiança pede confirmação do texto. | Testes com provider falso passam; `TRANSCRIPTION_URL` real não foi configurada. |
| 08 Correções/consultas | Consulta de saldo/gastos e mutação com alvo explícito e confirmação. | Testes de conversa passam; validar frases reais adicionais com a família. |
| 09 Importação | OFX/CSV/XLSX e imagens de fatura por OCR local, preview, mapeamento, revisão e confirmação. | Cinco prints reais foram lidos por código; a confirmação via WhatsApp foi coberta por teste de integração. A leitura de outros bancos e fotos reais ainda precisa de amostras e validação. |
| 10 Conciliação | Candidatos com pontuação, revisão manual, aceite/rejeição. | Testes cobrem fluxo base; auto conciliação fica desabilitada. |
| 11 Planejamento | Orçamentos, recorrências, metas, calendário e scheduler. | Testes de calendário/planejamento passam; recorrência não é marcada paga sozinha. |
| 12 Patrimônio/analytics | Ativos, passivos, snapshots, dashboard e métricas explicáveis. | Testes de agregações passam; indicadores reais ficam vazios enquanto não há dados. |
| 13 Projeções/alertas | Forecast determinístico, regras, alertas, opt-in e quiet hours. | Testes do motor passam; envio real depende de canal funcional e consentimento. |
| 14 Operação | Compose, CI, health, retenção, runbook e backup/restore testados. | API e interface `ready`; restauração em base separada confirmou usuários, família e categorias. Monitorar backlog e entrega real do WhatsApp. |

## Grupo WhatsApp

O grupo **Cacau - Finanças** (`120363431389141338@g.us`) está ativo na instância `cacauweb`, com três participantes segundo `findGroupInfos`, e está vinculado à família no Finance. Três identidades WhatsApp estão ativas no banco. O vínculo recebeu registro de auditoria em 17/09/2026. Uma mensagem real de receita enviada pelo número conectado foi recuperada da Evolution após a correção do tratamento de `fromMe`, processada uma vez e resultou em pergunta de esclarecimento entregue no grupo. A ação está em `WAITING_INFORMATION`; nenhuma transação foi criada antes da resposta do usuário. O eco da pergunta não gerou novo recibo.

As categorias de receita **Ensino**, **Psicologia** e **Programação** e quatro vínculos de atividade foram configurados: Carla → Ensino/Psicologia; Cauan → Psicologia/Programação. “Recebi 770 Paciente Alice” sugere Psicologia, mas pergunta de quem é a receita porque ambos são psicólogos. O banco ainda não possui uma conta financeira; a receita real permanece pendente até a conta ser cadastrada e o usuário confirmar o resumo no grupo.

## Checks executados

- `backend/.venv/bin/pytest -q backend/tests`: 32 testes passaram em 17/09/2026.
- `backend/.venv/bin/ruff check backend/app backend/tests`: passou.
- `npm run build` em `frontend`: passou.
- `docker compose --env-file .env -f infra/compose.yaml config --quiet`: passou.
- `GET http://localhost:8080/health/ready`: HTTP 200.
- `pg_dump`/`pg_restore` em uma base separada: restauração confirmou 2 usuários, 1 família e 10 categorias no momento do teste.
- Webhook primário do cacauwebproduct: HTTP 200; encaminhamento ao Finance autenticado, com resposta 403 esperada para número sintético não vinculado.
