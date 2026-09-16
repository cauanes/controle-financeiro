# Modelo de domínio

## Agregados e responsabilidade

| Agregado | Entidades associadas | Invariantes |
|---|---|---|
| Tenant | Household, User, HouseholdMember | associação ativa e escopo explícito em cada operação |
| Account | transações de caixa | moeda igual à da família; arquivar preserva histórico |
| CreditCard | CreditCardInvoice, InvoicePayment | compra afeta obrigação, pagamento afeta caixa |
| Transaction | TransactionSource, TransactionMatch | valor positivo; sem exclusão física; origem não movimenta saldo |
| ConversationSession | ConversationMessage, PendingFinancialAction | uma pendência ativa; processamento ordenado |
| ImportJob | ImportRow, ImportTemplate | preview imutável após confirmação; linha idempotente |
| Budget | BudgetCategory | valores por categoria e período sem dupla contagem |
| Goal | GoalContribution | alocação não é despesa por si só |
| RecurringTransaction | ocorrências de Transaction | geração idempotente por vencimento |
| Asset / Liability | FinancialSnapshot | não repetir saldo já representado por conta/cartão |
| Integration | identidades externas | segredos fora do payload de domínio |

## Tipos e estados

Transaction.type: EXPENSE, INCOME, TRANSFER. Transaction.status: PLANNED, POSTED, VOIDED. Conciliação é uma dimensão separada: UNRECONCILED, RECONCILED, NEEDS_REVIEW, derivada das evidências e decisões. Uma transação POSTED pode não ter sido conciliada.

Fonte de despesa: exatamente uma conta ou cartão. Receita entra em conta. Transferência tem conta de saída e de entrada distintas; pagamento de fatura tem conta de saída e invoice_id, com subtype INVOICE_PAYMENT e tipo TRANSFER. transferências entre cartões e estornos específicos exigem expansão futura; primeira versão permite corrigir/estornar contabilmente com ação auditada e regras explícitas, sem aceitar valores negativos como atalho.

PendingFinancialAction: WAITING_INFORMATION, WAITING_CONFIRMATION, CONFIRMED, CANCELLED, EXPIRED. CONFIRMED só existe após execução bem-sucedida. Campo execution_result aponta os registros produzidos. Proposta vencida ou baseada em versão antiga não pode executar.

## Valor e proveniência

Money = Decimal de duas casas + currency. Date é data civil no fuso da família; timestamps de infraestrutura são UTC. FieldEvidence = value, confidence (0..1 ou null), source, evidence_message_id, requires_confirmation. Fontes: user_explicit, keyword_rule, transcription, historical_pattern, provider, user_confirmed. Confiança é sinal de roteamento e não prova de verdade.

StructuredCandidate contém intent, schema_version, fields, unresolved_references, missing_fields, ambiguous_fields e target_transaction_ids. IDs só são resolvidos contra registros autorizados, ativos e compatíveis; o parser não inventa UUIDs válidos.

## Relacionamentos

Tenant 1:N Household; User N:M Household via HouseholdMember dentro de um tenant. Household 1:N Account, CreditCard, Category, Transaction. Transaction 1:N TransactionSource. ImportRow N:1 Transaction após importação/conciliação. Card 1:N Invoice; Invoice 1:N compras e pagamentos. Session 1:N Message e Action; mensagens registram action_id quando associadas.

## Responsável e visibilidade

actor_user_id identifica quem fez a operação; responsible_user_id indica de quem é o lançamento quando informado. São conceitos distintos. No MVP todos os membros ativos visualizam as finanças da família; owner/admin gerem membros e integrações, member registra e corrige, viewer apenas consulta. Privacidade por membro é uma extensão e não deve ser simulada com filtros de frontend.

## Arquivamento e mudanças

Conta/cartão/categoria usados são arquivados, não apagados. Reclassificar preserva auditoria. Exclusão financeira marca VOIDED com motivo e reverte efeito derivado sobre saldos; fontes permanecem para evitar reimportação. Mudanças em item conciliado marcam NEEDS_REVIEW quando alterarem valor, data ou fonte. Eventos são produzidos na unidade de trabalho do agregado.
