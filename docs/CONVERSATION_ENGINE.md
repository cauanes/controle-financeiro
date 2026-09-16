# Motor conversacional

## Contrato comum

NormalizedText: text, message_id, session_id, user_id, tenant_id, household_id, received_at, timezone, input_kind, transcription_metadata?. Contexto autenticado é anexado pelo servidor. StructuredCandidate possui schema_version, intent e mapa fields de FieldEvidence. Serializar amount como string decimal.

Campos materiais de despesa: amount, type, transaction_date, financial_source. financial_source resolve account_id ou credit_card_id e payment_method coerente. Em transferência: origem e destino; pagamento de fatura: conta e invoice_id. Responsável é obrigatório quando solicitado, houver múltiplos candidatos relevantes ou regra familiar explícita. Nunca equiparar automaticamente autor a responsável.

Campos inferíveis: categoria, subcategoria (representada por categories.parent_id), estabelecimento e descrição. Categoria baixa/ambígua pergunta após os materiais; a resposta “Sem categoria” resolve a classificação. notes, tags e location não bloqueiam. Localização fica em metadado opcional, sem captura automática.

## Intenções e disponibilidade

| Grupo | Intenções | Entrega |
|---|---|---|
| Registro | CREATE_EXPENSE, CREATE_INCOME, CREATE_TRANSFER | núcleo conversacional |
| Edição | UPDATE_TRANSACTION, DELETE_TRANSACTION | correções confirmadas |
| Consulta | QUERY_BALANCE, QUERY_EXPENSES, QUERY_INCOME, QUERY_CATEGORY, QUERY_CREDIT_CARD | consultas básicas |
| Planejamento | CREATE_BUDGET, CREATE_GOAL, QUERY_BUDGET | módulo planejamento |
| Análise | QUERY_CASHFLOW, QUERY_NET_WORTH | analytics |
| Controle | CONFIRM, CANCEL, CORRECT, UNKNOWN | desde o primeiro fluxo |
| Futuro | SIMULATE_PURCHASE, SIMULATE_AMORTIZATION, FORECAST, FINANCIAL_DIAGNOSIS | reconhecer e informar indisponibilidade |

## Confiança e precedência

Dados explicitamente confirmados prevalecem sobre inferência. Contradição explícita invalida confirmação anterior e exige nova validação. Default proposto para categoria inferível: >= 0.90 e sem ambiguidade; abaixo disso perguntar. Histórico material sempre exige confirmação mesmo com 0.99. Confiança de transcrição ausente é null, nunca 1.00. Detecção de conflito tem prioridade sobre score. Limiares versionados e calibrados com correções observadas.

## Estados e transições

| Estado | Evento | Próximo estado / efeito |
|---|---|---|
| sem ação | candidato incompleto | WAITING_INFORMATION e pergunta |
| sem ação | completo e confiável | executar e criar ação CONFIRMED para rastreabilidade |
| sem ação | completo mas exige confirmação | WAITING_CONFIRMATION e resumo |
| WAITING_INFORMATION | resposta parcial | mesclar evidência e perguntar restante |
| WAITING_INFORMATION | dados completos | confirmar se necessário ou executar |
| WAITING_CONFIRMATION | sim vinculado à proposta vigente | executar atomicamente → CONFIRMED |
| WAITING_CONFIRMATION | correção | invalidar proposta, mesclar, revalidar |
| estado ativo | cancelar | CANCELLED, sem ledger |
| estado ativo | relógio >= expires_at | EXPIRED, sem ledger |
| terminal | sim/retry | informar resultado existente; não executar novamente |

Expiração proposta: 24 h após última resposta relevante, com limite absoluto de 7 dias desde criação. Confirmação de alteração financeira expira em 30 min ou imediatamente se a versão do alvo mudar. Perguntas não prolongam prazo sem ação do usuário. Uma nova intenção durante pendência pergunta se deseja cancelar a atual antes de iniciar; mensagem nova é preservada e só promovida após escolha explícita.

## Processamento detalhado

```text
ingest(authenticated_event):
  resolve integration and verified sender; reject unsupported/group/fromMe events
  transaction:
    insert receipt with unique provider_event_key; on conflict return prior ACK
    insert message with session sequence
    insert outbox NormalizeMessage(message_id)
  return ACK

normalize(message):
  if audio: transcribe through provider outside SQL locks
  validate transcript; persist normalized text or failure
  enqueue ProcessSession; never write ledger here

process_session(session_id):
  begin transaction; lock session
  next = earliest unprocessed sequence
  if next not READY: stop (or fail timed-out normalization with explicit response)
  lock active pending action; expire if necessary
  detect CANCEL / CORRECT / new independent intent before interpreting short answer
  if independent intent and action active: ask how to proceed; preserve input; stop
  candidate = merge_answer(action, next) or parse(next)
  resolve references inside authorized household
  validate monetary shape, dates, sources, confidence, ambiguity and permissions
  if missing/ambiguous: save WAITING_INFORMATION and enqueue one question
  else if mutation target uncertain: ask target selection
  else if needs confirmation: save WAITING_CONFIRMATION and prompt version
  else: execute(candidate)
  mark message processed; commit

execute(candidate):
  recheck permissions, expiration, expected versions and constraints
  write financial changes + TransactionSource + AuditLog
  mark action CONFIRMED with execution_result
  append domain event and success message to outbox in same transaction
```

Na confirmação, recuperar a proposta persistida; “sim” não fornece novo objeto financeiro. CONFIRM só vale para a sessão/usuário e versão de proposta ativa; quoted reply a mensagem antiga é rejeitado. Sem quoted reply, aceitar apenas a proposta mais recente ainda ativa e sem resposta intermediária que a invalide.

## Correções e consultas

Buscar transações por filtros extraídos no escopo familiar, usando contexto recente apenas para ordenar. Zero candidatos: informar e pedir detalhe. Mais de um: mostrar data, valor, descrição e fonte para seleção. Um candidato: proposta antes/depois, incluindo efeitos em fatura e conta. Update/delete sempre requer confirmação no canal. Mudança concorrente retorna nova proposta. Consultas aplicam mesmas fórmulas e permissões da API e não criam pendência financeira, salvo filtro temporal ambíguo.

## Casos negativos obrigatórios

“Sim” sem proposta não registra nada; “Nubank” sem tipo quando conta/cartão coexistem continua pendente; “cento e vinte ou cento e trinta” pede valor; mensagem de outro membro não completa sessão; retry após commit devolve resultado; falha do parser gera esclarecimento seguro sem fatos fabricados; instrução no texto para ignorar autorização não altera controles do servidor.
