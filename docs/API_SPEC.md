# API HTTP v1

## Convenções

Prefixo /api/v1. JSON UTF-8; IDs UUID; dinheiro string decimal; datas ISO 8601; timestamps com offset UTC. Contexto familiar em X-Household-Id, sempre validado contra sessão autenticada. Tenant vem da identidade, não de campo editável do body. Login identifica tenant por slug e usuário por email. Cookies de sessão HttpOnly/Secure e proteção CSRF para mutações do dashboard; política completa em [SECURITY.md](SECURITY.md).

Listas usam cursor opaco estável (data,id), limit padrão 50/máximo 200, data[], next_cursor. Filtros combinam por AND; listas de valores de um filtro, por OR. Validação do servidor rejeita campos desconhecidos materiais. POST de comandos aceita Idempotency-Key, obrigatório para transações, confirmação de ação, importação e conciliação. Reuso com outro corpo retorna 409. PATCH/DELETE/confirm recebem expected_version; desatualizado retorna 409 com código VERSION_CONFLICT sem dados fora do escopo.

Erros: {error:{code,message,fields?,correlation_id}}. Códigos HTTP: 400 envelope, 401 não autenticado, 403 papel insuficiente, 404 recurso não visível/inexistente, 409 conflito/estado, 422 validação de domínio, 429 limite, 503 indisponibilidade transitória. POST cria 201; jobs retornam 202 com job_id; GET/PATCH 200; exclusão lógica 200 com status VOIDED e versão. OpenAPI gerado do FastAPI deve refletir esses contratos.

## Recursos e comandos

| Recurso | Métodos e caminhos (relativos ao prefixo) | Comportamento |
|---|---|---|
| Auth | POST /auth/login, /auth/refresh, /auth/logout; GET /auth/me | login por tenant/email, sessão rotativa e revogação |
| Famílias | GET/POST /households; GET/PATCH /households/{id} | criar implica owner, mudança de moeda bloqueada com ledger |
| Membros | GET/POST /members; PATCH/DELETE /members/{id} | convite/vinculação controlada; proteger último owner |
| Contas | GET/POST /accounts; GET/PATCH /accounts/{id}; POST /accounts/{id}/archive | abertura explícita e moeda |
| Cartões | GET/POST /cards; GET/PATCH /cards/{id}; POST /cards/{id}/archive | fechamento, vencimento e conta sugerida |
| Faturas | GET /invoices; GET/PATCH /invoices/{id}; POST /invoices/{id}/payments | PATCH datas com confirmação visível; payment cria transferência especial |
| Transações | GET/POST /transactions; GET/PATCH/DELETE /transactions/{id}; POST /transactions/{id}/post | filtros e histórico; post confirma pagamento de PLANNED |
| Categorias | GET/POST /categories; PATCH /categories/{id}; POST /categories/{id}/archive | hierarquia, sem ciclos |
| Estabelecimentos | GET/POST /merchants; PATCH /merchants/{id} | nome normalizado |
| Regras | GET/POST /category-rules e /merchant-rules; PATCH /{recurso}/{id} | escopo/prioridade e enabled |
| Orçamento | GET/POST /budgets; GET/PATCH /budgets/{id} | categorias e período; comparação com realizado |
| Metas | GET/POST /goals; GET/PATCH /goals/{id}; POST /goals/{id}/contributions | alocação com direction e amount |
| Recorrentes | GET/POST /recurring; GET/PATCH /recurring/{id} | template, frequência e pausa |
| Patrimônio | GET/POST /assets e /liabilities; GET/PATCH /{recurso}/{id} | avaliação e vínculo para evitar dupla contagem |
| Importações | POST /imports; GET /imports e /imports/{id}; GET /imports/{id}/rows; POST /imports/{id}/preview, /confirm, /cancel | multipart upload, mapping/versão, decisões por linha |
| Templates | GET/POST /import-templates; GET /import-templates/{id} | versões imutáveis |
| Conciliação | GET /reconciliation; POST /reconciliation/{match_id}/accept e /reject | aceitar com expected_version do candidato |
| Conversas | GET /conversations; GET /conversations/{id}/messages; GET /pending-actions | somente membros autorizados; conteúdo com acesso auditado |
| Pendências | POST /pending-actions/{id}/answer, /confirm, /cancel | mesmos serviços do canal; confirmar a proposta vigente |
| Analytics | GET /analytics/summary, /cashflow, /categories, /net-worth, /financial-health | definições no documento de analytics |
| Forecast | GET /forecast/cashflow e /forecast/categories | cenários e hipóteses |
| Alertas | GET /alerts; GET/POST /alert-rules; PATCH /alert-rules/{id} | preferências e opt-in |
| Integrações | GET/POST /integrations; PATCH /integrations/{id}; POST /integrations/{id}/test, /sync, /disconnect, /link-token | admin configura; link-token do próprio membro; sync assíncrono |
| Auditoria | GET /transactions/{id}/audit | diffs e ator, sem segredos |

`/{recurso}/{id}` é notação da tabela, não rota literal. DELETE de membro revoga associação, sem apagar usuário/histórico. Convites exigem implementação de token hash/expiração na entrega de identidade; não enviar convite a terceiros automaticamente durante desenvolvimento.

Webhooks fora do prefixo: POST /webhooks/evolution e /webhooks/financial-provider. Segundo endpoint só é ativado com adapter e contrato de autenticação implementados; por padrão indisponível. GET /health/live e /health/ready não expõem configuração.

## Exemplo de lançamento

```json
{
  "type": "EXPENSE",
  "status": "POSTED",
  "amount": "128.00",
  "currency": "BRL",
  "transaction_date": "2026-09-16",
  "competence_date": "2026-09-16",
  "description": "Abastecimento",
  "financial_source": {"kind": "CREDIT_CARD", "id": "<uuid-do-cartao>"},
  "category_id": "<uuid-combustivel>"
}
```

financial_source é união discriminada: ACCOUNT, CREDIT_CARD, ACCOUNT_TRANSFER (source_id,destination_id), INVOICE_PAYMENT (account_id,invoice_id). Backend resolve invoice_id para compra, verificando calendário. Resposta inclui id, version, campos efetivos, invoice_id?, sources[], reconciliation_status e created_at. Placeholders acima são ilustrativos; validação real exige UUID.

PATCH contém expected_version e changes; API calcula e retorna efeitos em contas/faturas. DELETE recebe expected_version e reason como parâmetros definidos no OpenAPI. Para UI, confirmação local precede a chamada; WhatsApp persiste proposta no servidor.

## Filtros de transações

from/to, date_basis (transaction/competence), responsible_user_id, account_id, card_id, category_id (include_descendants), merchant_id, type, source_type, status, reconciliation_status, min_amount, max_amount e q. Origem usa EXISTS para não duplicar transações com várias TransactionSources. Exportação, se adicionada, usa os mesmos filtros e protege CSV contra execução de fórmulas.

## Comandos assíncronos

Upload responde job_id/status/version. Preview recebe template_id ou mapping, target source e expected_version. Confirm recebe expected_version, decisions[{row_id,action,match_id?}], onde action é IMPORT/RECONCILE/SKIP; linha inválida não pode IMPORT. Resposta de job expõe counts, erros por linha e resultados já persistidos. Repetir confirmação retorna o mesmo job.

Pending answer recebe text + expected_version; retorna action_id, status, question?, missing_fields, summary? e execution_result?. Confirm recebe expected_version e prompt_message_id quando originado de canal. Nunca aceitar extracted_data arbitrário enviado como confirmação.
