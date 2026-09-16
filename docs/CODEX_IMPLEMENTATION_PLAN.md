# Plano de implementação para Codex

Este plano implementa o PRD por entregas verificáveis. O repositório contém apenas especificações neste momento. As pastas e migrations abaixo são propostas; criar código somente na execução das etapas. Não tentar implementar todas as áreas em uma única mudança.

## Regras de execução

Ler PRD, FINANCIAL_RULES, DATABASE_SCHEMA e SECURITY antes da primeira entrega. Preservar a regra de não presumir fatos materiais. Fazer cada etapa compilar e passar seus checks antes da próxima, com adapters falsos quando um serviço externo ainda não estiver configurado. Não introduzir endpoints/UI que retornem dados fictícios em produção. Não adiar tenant, idempotência, auditoria ou precisão monetária para o fim.

Cada entrega termina com descrição do comportamento, migrations aplicadas em teste, comandos executados, critérios comprovados e limitações. Segredos/instância externa são configuração de implantação, não bloqueio para implementação e teste local. Escolher versões de bibliotecas no bootstrap e fixá-las; não interpretar os números deste pacote como requisitos de versões de software.

A sequência de migrations abaixo prevalece sobre agrupamentos lógicos do esquema. Extensões de colunas e FKs entram quando a tabela destino existir, sem relaxar isolamento das tabelas já operacionais. Não manter constraints temporariamente permissivas após concluir uma entrega.

## 01 — Base executável e identidade

**Objetivo:** Ter API, frontend e worker locais com família autenticada e isolamento desde a primeira escrita.

**Arquivos:** backend/app/{main.py,core/*,modules/identity/*}; backend/migrations/*; frontend/src/{app/*,features/auth/*}; infra/compose.yaml; .env.example; README.md

**Implementação:** Configurar dependências fixadas, conexão SQL, unit of work, sessão, papéis, CI e health. Criar família inicial via comando administrativo explícito; nenhum cadastro público por padrão.

**Migrations:** 001: tenants, users, households, members, auth_sessions, member_invites; 002: audit_logs, outbox_events, processed_events, idempotency_keys e políticas RLS iniciais.

**Endpoints:** /auth/*, /households, /members, /health/*.

**Frontend:** Login, seletor de família, shell e estados sem acesso.

**Testes:** Migrations vazias, login/revogação, último owner, RLS com dois tenants e duas famílias no mesmo tenant.

**Critérios de aceitação:** Subir ambiente pelo README; member/viewer limitados; nenhuma consulta cruza família; outbox recupera trabalho sem Redis.

## 02 — Ledger manual de contas

**Objetivo:** Registrar receita, despesa e transferência com dinheiro exato.

**Arquivos:** backend/app/modules/ledger/{domain,application,infrastructure,api}/*; frontend/src/features/{accounts,transactions}/*

**Implementação:** Implementar Money, abertura, regras de forma, POSTED/PLANNED/VOIDED, versões, origem manual e auditoria atômica.

**Migrations:** 003: accounts, categories, merchants, transactions (formas de conta), transaction_sources; estender checks de forma na etapa de cartões.

**Endpoints:** /accounts, /transactions, /transactions/{id}/post, /transactions/{id}/audit, /categories, /merchants.

**Frontend:** Cadastro de conta, formulário e lista com filtros básicos, detalhe e exclusão lógica.

**Testes:** Saldo, transferência neutra, valor inválido, data faltante, retry de criação e conflito de versão.

**Critérios de aceitação:** Saldo coincide com ledger; nenhuma pendência/formulário inválido é gravada; origem e auditoria sempre presentes.

## 03 — Cartões, faturas e parcelas

**Objetivo:** Representar crédito e pagamento de fatura sem dupla contagem.

**Arquivos:** backend/app/modules/ledger/*; frontend/src/features/cards/*

**Implementação:** Calendário de fatura, divisão exata de parcelas, pagamento parcial e locks de fatura.

**Migrations:** 004: credit_cards, invoices, invoice_payments; FKs/checks e campos de parcelamento de transactions.

**Endpoints:** /cards, /invoices, /invoices/{id}/payments; ampliar /transactions.

**Frontend:** Cartões, faturas, parcelas e pagamento com conta explícita.

**Testes:** Dia 31/fevereiro, 100 dividido em 3, pagamentos concorrentes e fixture financeira.

**Critérios de aceitação:** Compra aumenta obrigação, pagamento reduz caixa/obrigação e não cria nova despesa; soma de parcelas exata.

## 04 — Classificação e contrato de parser

**Objetivo:** Produzir candidato com proveniência e referências autorizadas.

**Arquivos:** backend/app/modules/{categorization,conversations}/domain/*; backend/app/modules/conversations/application/parser.py; frontend/src/features/settings/categories/*

**Implementação:** IntentEngine e parser injetável com adapter determinístico para exemplos do PRD; schema estrito; normalização pt-BR; resolução de nomes. Adapter semântico real é configurável e não pode ampliar permissões.

**Migrations:** 005: category_rules, merchant_rules, user_financial_preferences.

**Endpoints:** /category-rules, /merchant-rules; sem endpoint público irrestrito de parser.

**Frontend:** Regras e hierarquia de categorias.

**Testes:** Amazon, acentos, valores por extenso, conta/cartão homônimos, histórico material e instruções maliciosas.

**Critérios de aceitação:** Texto vira candidato validado; qualquer dado material incerto é marcado; sugestões históricas não executam.

## 05 — Conversação textual interna

**Objetivo:** Concluir pendências e confirmações por canal falso antes de integrar WhatsApp.

**Arquivos:** backend/app/modules/conversations/*; backend/app/workers/conversations.py; frontend/src/features/pending-actions/*

**Implementação:** Máquina de estados, uma ação ativa, ordem de mensagens, expiração, proposta versionada e executor financeiro comum. Integração INTERNAL restrita a desenvolvimento para adapter falso.

**Migrations:** 006: integrations, channel_identities, sessions, messages, pending_actions, outgoing_messages; FKs circulares criadas ao final.

**Endpoints:** /conversations, /pending-actions e comandos answer/confirm/cancel.

**Frontend:** Central de pendências com resumo persistido e resposta textual.

**Testes:** Jornadas do PRD, data ausente, nova intenção durante pendência, sim antigo, retry e crash.

**Critérios de aceitação:** Zero ledger antes de completude; confirmação única; sucesso apenas após commit; cancelamento não registra despesa.

## 06 — Evolution API em texto

**Objetivo:** Receber e responder mensagens privadas autenticadas com idempotência.

**Arquivos:** backend/app/modules/ingestion/evolution/*; backend/app/modules/integrations/*; backend/app/workers/outgoing.py; frontend/src/features/settings/integrations/*

**Implementação:** Adapter versionado, vínculo por código, validação de evento, receipt durável, retry e envio incerto. Testar contrato contra instância configurada antes do uso real.

**Migrations:** 007: webhook_receipts, channel_link_tokens; ampliar integrations com configuração validada.

**Endpoints:** /webhooks/evolution; /integrations e test/disconnect/link-token.

**Frontend:** Configuração de integração, vinculação e status sem revelar segredo.

**Testes:** Webhook falso, número desconhecido, grupo/fromMe, 20 retries, remoção de membro e timeout de saída.

**Critérios de aceitação:** Mensagem válida atravessa o mesmo motor da etapa 05; reenvio não duplica lançamento; falha de provider é visível.

## 07 — Áudio

**Objetivo:** Converter áudio em NormalizedText com paridade e descarte de mídia.

**Arquivos:** backend/app/modules/ingestion/audio/*; backend/app/modules/integrations/transcription/*; backend/tests/contract/audio/*

**Implementação:** TranscriptionProvider falso e adapter configurável, download restrito, validação de MIME/tamanho, timeout e limpeza.

**Migrations:** 008 somente se necessário para metadados/retention de mensagens; sem tabela de áudio permanente.

**Endpoints:** Mesmo webhook; nenhum endpoint financeiro específico para áudio.

**Frontend:** Estado de transcrição e erro recuperável na conversa.

**Testes:** Paridade texto/áudio, silêncio, número ambíguo, SSRF, MIME falso, crash/cleanup e sequência com áudio lento.

**Critérios de aceitação:** Transcrição usa executor comum; mídia descartada; falha não gera fato financeiro.

## 08 — Correções e consultas conversacionais

**Objetivo:** Editar/excluir mediante confirmação e consultar registros existentes.

**Arquivos:** backend/app/modules/conversations/application/{target_resolution,queries,mutations}.py; frontend/src/features/transactions/*

**Implementação:** Busca contextual com desambiguação, proposta antes/depois, revalidação de versão; consultas básicas sobre ledger.

**Migrations:** Sem nova tabela; índices contextuais se plano de consulta justificar.

**Endpoints:** UPDATE/DELETE pelos serviços existentes; /pending-actions/confirm; consultas em API de ledger.

**Frontend:** Histórico de alterações e conflitos com recarga.

**Testes:** Zero/um/vários candidatos, mesma compra em duas famílias, confirmação expirada e mudança material em conciliado.

**Critérios de aceitação:** Correção confirmada emite TransactionUpdated com audit antes/depois; múltiplos alvos nunca resolvidos silenciosamente.

## 09 — Importação com preview

**Objetivo:** Importar OFX/CSV/XLSX sem alterar saldo antes da confirmação.

**Arquivos:** backend/app/modules/ingestion/imports/*; frontend/src/features/imports/*

**Implementação:** Adapters, mapping versionado, normalização, detecção de duplicação, jobs por linha e retry parcial. Transferência/fatura incertas exigem revisão.

**Migrations:** 009: import_templates, import_jobs, import_rows e vínculo source/import_row.

**Endpoints:** /imports, rows, preview, confirm, cancel; /import-templates.

**Frontend:** Wizard completo e relatório parcial.

**Testes:** Mesmo arquivo, linhas iguais legítimas, sinais, locale, arquivo inválido, limites XLSX e confirmação concorrente.

**Critérios de aceitação:** Preview preserva ledger; cada linha confirmada tem resultado/origem único; inválidas nunca importam silenciosamente.

## 10 — Conciliação

**Objetivo:** Unir evidências de extrato e registro existente sem duplicar finanças.

**Arquivos:** backend/app/modules/reconciliation/*; frontend/src/features/reconciliation/*

**Implementação:** Score explicável, bloqueios materiais, aceite/rejeição, versão e idempotência. Auto desabilitado inicialmente.

**Migrations:** 010: transaction_matches e constraints de aceitação; estado de conciliação.

**Endpoints:** /reconciliation e accept/reject.

**Frontend:** Comparação lado a lado e decisões.

**Testes:** Duas origens/uma transação, concorrência, rejeição persistida, diferença de conta, parcela e candidato alterado.

**Critérios de aceitação:** Aceite só anexa origem; saldo e despesa não mudam; proposta ambígua exige usuário.

## 11 — Planejamento

**Objetivo:** Gerenciar orçamento, recorrências e metas com obrigações previsíveis.

**Arquivos:** backend/app/modules/planning/*; frontend/src/features/planning/*

**Implementação:** Orçamento por competência, geração idempotente de PLANNED, alocação de metas, calendário.

**Migrations:** 011: budgets, budget_categories, recurring_transactions (cost_class), goals, goal_contributions; FK recorrência em transactions.

**Endpoints:** /budgets, /recurring, /goals e contributions.

**Frontend:** Orçado × realizado, recorrentes, metas e calendário.

**Testes:** Categoria pai/filho, recorrência em fevereiro, geração paralela, aporte que não cria despesa.

**Critérios de aceitação:** Scheduler nunca marca pago sozinho; orçamento usa parcela do ciclo; intenções CREATE/QUERY correspondentes habilitadas.

## 12 — Patrimônio e analytics

**Objetivo:** Exibir indicadores auditáveis com fórmulas comuns.

**Arquivos:** backend/app/modules/analytics/*; frontend/src/features/{dashboard,analytics}/*

**Implementação:** Agregações, buckets, snapshots e recálculo retroativo; ativos/passivos sem duplicação de vínculos.

**Migrations:** 012: assets, liabilities, financial_snapshots; accounts.is_emergency_reserve e categories.is_essential.

**Endpoints:** /assets, /liabilities, /analytics/*; habilitar QUERY_NET_WORTH.

**Frontend:** Dashboard e quatro blocos de diagnóstico.

**Testes:** Fixture de referência, receita zero, história insuficiente, vínculo conta/ativo e cache entre famílias.

**Critérios de aceitação:** Indicadores conferem com ledger e fórmulas; bases temporais visíveis; nenhum score de saúde arbitrário.

## 13 — Projeções e alertas

**Objetivo:** Mostrar caixa futuro e avisar eventos com consentimento.

**Arquivos:** backend/app/modules/{analytics,notifications}/*; backend/app/workers/scheduler.py; frontend/src/features/{forecast,alerts}/*

**Implementação:** Forecast determinístico, extrapolação separada, dedup de ocorrências/faturas, quiet hours e opt-in.

**Migrations:** 013: alert_rules, alerts; índices de deduplicação e agendamento.

**Endpoints:** /forecast/*, /alerts, /alert-rules; habilitar QUERY_CASHFLOW.

**Frontend:** Cenários com hipóteses, alertas e preferências.

**Testes:** Fatura parcial, recorrência materializada, vencido, aviso concorrente e opt-out antes do envio.

**Critérios de aceitação:** Fluxo futuro não duplica compromisso; aviso distingue fato de estimativa e respeita destinatário/janela.

## 14 — Preparação para uso real

**Objetivo:** Validar operação, recuperação e limites antes de ativar canais externos.

**Arquivos:** infra/*; backend/tests/{integration,contract,e2e}/*; docs/runbooks/*; README.md

**Implementação:** Backup/restore, retenção, observabilidade, carga representativa, revisão de permissões e contratos de providers. Open Finance permanece interface desabilitada até adapter dedicado.

**Migrations:** Somente correções aditivas justificadas; verificar todas as migrations e roles desde banco vazio.

**Endpoints:** Readiness e administração já definidos; nada de endpoint genérico privilegiado.

**Frontend:** Acessibilidade, móvel, estados vazios/parciais e mensagens de indisponibilidade.

**Testes:** Matriz crítica completa, restore, perda de Redis, outbox atrasada, worker reiniciado e pool reutilizado.

**Critérios de aceitação:** Registrar evidências dos checks, configuração de implantação e limitações; não afirmar suporte a provider sem smoke real.

## Fora desta sequência

Conectores financeiros reais recebem entrega própria por provider com autenticação/consentimento, cursores, fixtures e teste de contrato. Simulação de compra, amortização, previsões estatísticas, multimoeda, estorno bancário automático e conciliação de duas transações já lançadas requerem extensão explícita das regras e testes. Reconhecimento de intenção não significa funcionalidade habilitada.
