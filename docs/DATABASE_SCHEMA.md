# Esquema PostgreSQL

Modelo lógico normativo para migrations; as declarações abaixo são especificações de colunas e constraints, não uma migration executada. Nomes físicos em snake_case. Toda migration deve incluir upgrade, política de rollback e teste no PostgreSQL real.

## Convenções obrigatórias

- PK id uuid, gerado pela aplicação; created_at e updated_at timestamptz NOT NULL. IDs nunca substituem autorização.
- Salvo exceções explícitas, tabelas da família têm tenant_id uuid NOT NULL e household_id uuid NOT NULL, com FK composta para households(tenant_id,id). Cada tabela referenciada por outra oferece UNIQUE(tenant_id,household_id,id).
- Toda referência a entidade familiar é FK composta (tenant_id,household_id,entity_id), nunca apenas entity_id. Referência a user usa (tenant_id,user_id); responsible_user_id valida também associação à família. Colunas opcionais estão marcadas com `?`; demais são NOT NULL, salvo timestamps de ciclo de vida ainda não ocorrido.
- money = numeric(18,2); currency char(3), restrita a BRL no MVP. confidence numeric(5,4) nullable com CHECK entre 0 e 1. JSONB recebe schema_version e validação de aplicação; checks protegem estrutura básica.
- Estados implementados por text + CHECK nomeado para facilitar evolução. Todas as datas de negócio são date; instantes, timestamptz.
- ON DELETE RESTRICT para entidades financeiras e origens. Arquivamento por archived_at nullable. Nenhum cascade pode apagar ledger ou auditoria.
- Índices começam pelo escopo de consulta (tenant_id,household_id). FKs de uso frequente possuem índice no lado filho.

## Identidade (exceções ao escopo padrão)

| Tabela | Colunas além de id e timestamps | Restrições |
|---|---|---|
| tenants | name text, status text | status ACTIVE/SUSPENDED |
| users | tenant_id uuid, email text, display_name text, password_hash text?, auth_subject text?, status text | UNIQUE(tenant_id,id), UNIQUE(tenant_id,email normalizado); senha ou identidade externa obrigatória |
| households | tenant_id uuid, name text, currency char(3), timezone text | UNIQUE(tenant_id,id); timezone IANA validado |
| household_members | user_id uuid, role text, status text | UNIQUE(tenant_id,household_id,user_id); role OWNER/ADMIN/MEMBER/VIEWER |
| auth_sessions | tenant_id uuid, user_id uuid, refresh_token_hash text, expires_at timestamptz, revoked_at timestamptz? | sem household_id; hash único; FK composta de user |

users não compartilha identidade entre tenants no MVP. Email repetido em tenants distintos requer tenant/slug no login. Alteração/remoção do último owner é bloqueada com lock da família.

## Ledger e classificação

| Tabela | Colunas específicas | Constraints / índices |
|---|---|---|
| accounts | name text, kind text, currency, opening_balance money, opening_balance_date date, archived_at? | kind CHECKING/SAVINGS/CASH/INVESTMENT; nome normalizado único entre ativas |
| credit_cards | name text, issuer text?, limit_amount money?, closing_day smallint, due_day smallint, default_payment_account_id uuid?, archived_at? | dias 1..31; limite >= 0 |
| credit_card_invoices | credit_card_id uuid, period_start date, closing_date date, due_date date, status text, version int | UNIQUE(scope,credit_card_id,closing_date); period_start <= closing_date < due_date; OPEN/CLOSED/PARTIALLY_PAID/PAID |
| categories | parent_id uuid?, name text, kind text, archived_at? | kind EXPENSE/INCOME; impedir ciclos e pai de outro kind; nome único por pai, inclusive raiz via índice parcial |
| merchants | name text, normalized_name text, archived_at? | UNIQUE(scope,normalized_name) |
| category_rules | user_id uuid?, pattern text, match_type text, category_id uuid, priority int, confidence, enabled boolean | EXACT/CONTAINS; regex fora do MVP; sem empates silenciosos |
| merchant_rules | pattern text, match_type text, merchant_id uuid, priority int, enabled boolean | índices por escopo e prioridade |
| transactions | type text, subtype text?, status text, amount money, currency, transaction_date date, competence_date date, due_date date?, description text, account_id uuid?, destination_account_id uuid?, credit_card_id uuid?, invoice_id uuid?, category_id uuid?, merchant_id uuid?, responsible_user_id uuid?, actor_user_id uuid, notes text?, tags jsonb, installment_group_id uuid?, installment_number int?, installment_count int?, recurring_transaction_id uuid?, occurrence_date date?, reconciliation_status text, version int, voided_at timestamptz?, void_reason text? | amount > 0; version >= 1; regras de forma abaixo |
| transaction_sources | transaction_id uuid, source_type text, integration_id uuid?, source_key text, external_id text?, import_row_id uuid?, conversation_message_id uuid?, evidence jsonb, observed_at timestamptz | source_type MANUAL/WHATSAPP/OFX/CSV/XLSX/PROVIDER; UNIQUE(scope,source_type,source_key); índice transaction_id |
| transaction_matches | transaction_id uuid, import_row_id uuid, score numeric(5,4), score_details jsonb, status text, decided_by uuid?, decided_at timestamptz?, transaction_version int | UNIQUE(scope,transaction_id,import_row_id); PROPOSED/ACCEPTED/REJECTED/STALE; apenas um ACCEPTED por import_row via índice parcial |
| invoice_payments | invoice_id uuid, transaction_id uuid, amount money | amount > 0; UNIQUE(scope,transaction_id); mesmo valor da transferência validado atomicamente |

`scope` nas constraints significa tenant_id,household_id. CHECK de forma de transactions:

```sql
CHECK (
  (type = 'EXPENSE' AND destination_account_id IS NULL
    AND ((account_id IS NOT NULL AND credit_card_id IS NULL AND invoice_id IS NULL)
      OR (account_id IS NULL AND credit_card_id IS NOT NULL AND invoice_id IS NOT NULL)))
  OR (type = 'INCOME' AND account_id IS NOT NULL
    AND destination_account_id IS NULL AND credit_card_id IS NULL AND invoice_id IS NULL)
  OR (type = 'TRANSFER' AND account_id IS NOT NULL AND credit_card_id IS NULL
    AND ((subtype = 'INVOICE_PAYMENT' AND invoice_id IS NOT NULL AND destination_account_id IS NULL)
      OR (subtype IS NULL AND invoice_id IS NULL AND destination_account_id IS NOT NULL
        AND destination_account_id <> account_id)))
)
```

Validar invoice.credit_card_id igual ao cartão da compra com FK composta adicional (scope,credit_card_id,invoice_id). Parcelas exigem os três campos de parcelamento juntos, 1 <= número <= quantidade, UNIQUE(scope,installment_group_id,installment_number). Transferências não possuem categoria. VOIDED exige voided_at e motivo. Rotinas de escrita bloqueiam fatura/contas em ordem estável e verificam totais de pagamento; checks entre linhas requerem transação e testes de concorrência.

Índices transactions: (scope,transaction_date DESC,id), (scope,competence_date,type,status), (scope,account_id,transaction_date), (scope,credit_card_id,invoice_id), (scope,category_id,competence_date), (scope,responsible_user_id,transaction_date). UNIQUE parcial (scope,recurring_transaction_id,occurrence_date) quando recorrência não nula.

## Planejamento e patrimônio

| Tabela | Colunas específicas | Constraints |
|---|---|---|
| budgets | name text, period_start date, period_end date, currency, version int | fim >= início; um orçamento familiar por período no MVP; sobreposição bloqueada no serviço sob lock |
| budget_categories | budget_id uuid, category_id uuid, amount money | >= 0; UNIQUE(scope,budget_id,category_id); rejeitar pai e filho simultâneos no mesmo orçamento |
| recurring_transactions | template jsonb, frequency text, interval_count int, start_date date, end_date date?, next_due_date date, enabled boolean, version int | MONTHLY/WEEKLY/YEARLY; interval_count > 0; template segue regras financeiras |
| goals | name text, target_amount money, target_date date?, status text | target > 0; ACTIVE/COMPLETED/ARCHIVED |
| goal_contributions | goal_id uuid, amount money, contribution_date date, transaction_id uuid?, direction text | amount > 0; ADD/WITHDRAW; retirada não pode superar alocado |
| assets | name text, kind text, valuation money, valuation_date date, linked_account_id uuid?, archived_at? | valuation >= 0; uma representação por conta via UNIQUE parcial |
| liabilities | name text, outstanding_amount money, valuation_date date, linked_credit_card_id uuid?, due_date date?, archived_at? | outstanding >= 0; UNIQUE parcial por cartão |
| financial_snapshots | snapshot_date date, metrics jsonb, calculation_version text, input_watermark timestamptz | UNIQUE(scope,snapshot_date,calculation_version); reconstruível |

## Integração, importação e conversação

| Tabela | Colunas específicas | Constraints / índices |
|---|---|---|
| integrations | provider text, instance_key text, status text, config jsonb, secret_ref text?, last_synced_at timestamptz? | UNIQUE(provider,instance_key) global para rotear webhook sem aceitar tenant do payload |
| channel_identities | integration_id uuid, user_id uuid, channel text, sender_key text, verified_at timestamptz, revoked_at timestamptz? | UNIQUE(integration_id,sender_key) ativa; identidade liga uma integração a uma família |
| import_templates | name text, format text, mapping jsonb, version int, user_id uuid? | UNIQUE(scope,name,version) |
| import_jobs | integration_id uuid?, template_id uuid?, file_hash text, file_ref text?, format text, status text, target_account_id uuid?, target_credit_card_id uuid?, counts jsonb, errors jsonb, confirmed_by uuid?, confirmed_at timestamptz?, version int | UPLOADED/PARSING/PREVIEW/PROCESSING/COMPLETED/PARTIAL/FAILED/CANCELLED; uma fonte alvo compatível obrigatória antes de confirmar |
| import_rows | import_job_id uuid, row_number int, external_id text?, fingerprint text, normalized_data jsonb, validation_errors jsonb, status text, transaction_id uuid? | UNIQUE(scope,import_job_id,row_number); fingerprint indexado, não único por si só; READY/INVALID/DUPLICATE/REVIEW/IMPORTED/RECONCILED/SKIPPED |
| conversation_sessions | integration_id uuid, channel_identity_id uuid, user_id uuid, channel text, status text, next_sequence bigint, version int, last_activity_at timestamptz | UNIQUE(scope,channel_identity_id) ativa; ACTIVE/CLOSED |
| conversation_messages | session_id uuid, integration_id uuid, provider_message_id text, direction text, sequence bigint, kind text, raw_text text?, normalized_text text?, transcription_metadata jsonb?, pending_action_id uuid?, processing_status text, received_at timestamptz, processed_at timestamptz? | UNIQUE(integration_id,provider_message_id,direction); UNIQUE(scope,session_id,sequence); TEXT/AUDIO; RECEIVED/TRANSCRIBING/READY/PROCESSED/FAILED |
| pending_financial_actions | session_id uuid, user_id uuid, intent text, raw_message text, transcription text?, extracted_data jsonb, missing_fields jsonb, ambiguous_fields jsonb, confidence, status text, expires_at timestamptz, version int, confirmation_prompt_message_id uuid?, target_transaction_id uuid?, target_version int?, execution_result jsonb? | estados definidos no domínio; índice único parcial por session_id para WAITING_INFORMATION/WAITING_CONFIRMATION; índice status,expires_at |
| user_financial_preferences | user_id uuid, context_key text, suggested_fields jsonb, observations int, confidence, last_confirmed_at timestamptz?, enabled boolean | UNIQUE(scope,user_id,context_key); nunca substitui confirmação de fonte material |

Uma sessão tem somente uma ação ativa no MVP. Colunas circulares message/action são criadas com FKs em etapa posterior da mesma migration. Evento de webhook de número desconhecido é rejeitado antes de criar sessão. Para eventos autenticados relevantes sem mensagem processável, registrar recibo técnico sanitizado.

## Alertas, auditoria e infraestrutura

| Tabela | Colunas específicas | Constraints |
|---|---|---|
| alert_rules | kind text, config jsonb, channel text, enabled boolean, quiet_hours jsonb, recipient_user_id uuid | regra versionada, destinatário com opt-in |
| alerts | alert_rule_id uuid, dedup_key text, payload jsonb, status text, triggered_at timestamptz, sent_at timestamptz?, attempts int | UNIQUE(scope,dedup_key); PENDING/SENT/FAILED/SUPPRESSED |
| audit_logs | actor_user_id uuid?, action text, entity_type text, entity_id uuid, before jsonb?, after jsonb?, origin text, correlation_id uuid, occurred_at timestamptz | append-only; sem segredos; índice scope,entity_type,entity_id,occurred_at |
| webhook_receipts | integration_id uuid, provider_event_key text, payload_hash text, message_id uuid?, status text, received_at timestamptz | UNIQUE(integration_id,provider_event_key); sanitizar payload |
| outbox_events | event_type text, aggregate_id uuid, aggregate_version int, schema_version int, payload jsonb, correlation_id uuid, available_at timestamptz, published_at timestamptz?, completed_at timestamptz?, attempts int | índice parcial available_at onde completed_at IS NULL |
| processed_events | consumer text, event_id uuid, processed_at timestamptz | UNIQUE(consumer,event_id); FK evento; escopo familiar |
| idempotency_keys | user_id uuid, route text, key text, request_hash text, response_status int?, response_body jsonb?, expires_at timestamptz | UNIQUE(scope,user_id,route,key); mesma chave e corpo diferente retorna 409 |
| outgoing_messages | session_id uuid?, integration_id uuid, recipient_identity_id uuid, client_message_id uuid, text text, status text, provider_message_id text?, attempts int, available_at timestamptz, sent_at timestamptz? | UNIQUE(client_message_id); PENDING/SENDING/SENT/FAILED/UNKNOWN; timeout incerto usa UNKNOWN |

## RLS e permissões

Habilitar e forçar RLS em tabelas familiares. Política USING e WITH CHECK por tenant/household de contexto verificado; sem contexto, negar. Exemplo conceitual:

```sql
USING (
 tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
 AND household_id = nullif(current_setting('app.household_id', true), '')::uuid
)
```

API verifica associação antes de SET LOCAL dentro da transação. Pool nunca usa SET de sessão persistente. Users/sessions usam política própria de tenant e usuário; login e roteamento de integração usam funções/repository privilegiados estritamente limitados. Worker recebe escopo do evento persistido, não do payload externo. Role de aplicação sem BYPASSRLS nem propriedade das tabelas; role de migration separada. Auditoria sem UPDATE/DELETE para aplicação.

## Ordem das migrations

001 identidade e famílias; 002 contas/categorias/cartões/faturas/ledger; 003 planejamento e patrimônio; 004 integrações e conversas; 005 imports, fontes e matches; 006 outbox/auditoria/idempotência/alertas; 007 políticas RLS e índices adicionais. Ao dividir por entregas, infraestrutura de auditoria/outbox deve existir antes da primeira mutação financeira: o plano de implementação reorganiza esses blocos para respeitar essa dependência. Seeds de categorias são por família e idempotentes; não inserir contas/cartões supostos.

## Extensões normativas das entregas

- tenants.slug text NOT NULL UNIQUE, normalizado, usado no login; name continua nome de exibição.
- member_invites: id/timestamps/scope, email text, role text, token_hash text UNIQUE, expires_at timestamptz, accepted_at timestamptz?, invited_by uuid. Papel permitido ADMIN/MEMBER/VIEWER; aceite autenticado verifica email e token; não permite elevar a OWNER.
- channel_link_tokens: id/timestamps/scope, user_id uuid, token_hash text UNIQUE, expires_at timestamptz, used_at timestamptz?, attempts int default 0 CHECK >= 0. Índice de expiração; consumo com lock, máximo de tentativas configurável.
- accounts.is_emergency_reserve boolean NOT NULL default false; categories.is_essential boolean nullable; recurring_transactions.cost_class text NOT NULL default UNKNOWN com CHECK FIXED/VARIABLE/UNKNOWN.
- Conteúdos sujeitos a retenção (pending.raw_message, pending.transcription, outgoing.text, textos de messages) são obrigatórios quando aplicável na criação, porém nullable fisicamente para expurgo auditado. JSON de evidência não pode copiar conteúdo bruto sem a mesma política de limpeza.
- Nome de conta/categoria normalizado usa índice funcional coerente com a normalização da aplicação; unicidade de raízes de categoria é índice parcial próprio, evitando semântica de NULL que permitiria duplicatas.
