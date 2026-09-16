# Estratégia de testes

## Camadas

Unitários para Money, datas, ciclos de fatura, parcelas, validação, interpretação de respostas e fórmulas. Integração com PostgreSQL real para constraints, RLS, locks, idempotência, migrations e outbox; SQLite não substitui esses testes. Contrato para Evolution, transcrição e importadores com fixtures sanitizadas. E2E para jornadas financeiras completas pela API/UI e canal falso.

Relógio, parser, transcrição e canal são injetáveis. Testes determinísticos não dependem de provider pago nem internet. Smoke de provider real é separado e requer ambiente configurado. Fixar versões de dependências no bootstrap; os comandos abaixo são alvos planejados, não resultados já executados.

## Matriz de aceitação

| Cenário | Resultado verificável | Camada |
|---|---|---|
| Mercado 270 → Nubank → crédito → confirmação de data | uma transação; antes do fim, zero transações | integração/conversa |
| Texto e áudio equivalentes | mesmo candidato, pergunta e efeito financeiro | contrato + integração |
| Amazon sem item | categoria não inventada; escolha explícita Sem categoria permitida | unitário/E2E |
| “sim” antigo, ação expirada, membro removido | nenhum efeito financeiro | integração |
| Correção simultânea | confirmação antiga retorna conflito; sem sobrescrita | integração |
| 20 retries paralelos do mesmo webhook | um receipt/mensagem/lançamento efetivo | integração |
| Crash após commit antes de envio | ledger preservado e resposta recuperável | integração |
| Duas compras iguais no mesmo dia | ambas possíveis; fingerprint não elimina dado legítimo | importação |
| WhatsApp + OFX correspondente | uma transação, duas origens, mesmo saldo | integração/E2E |
| Match recusado ou candidato alterado | não autoaceitar novamente | integração |
| Conta de outra família no mesmo tenant e de outro tenant | negar leitura/escrita e FK inválida | integração |
| Role real sem contexto RLS e pool reutilizado | zero vazamento | integração |
| Compra, transferência e pagamento de fatura | fórmula da fixture de analytics sem dupla contagem | unitário/integração |
| 100 em 3 parcelas e fevereiro | soma exata e datas válidas | propriedades |
| Importação parcial + retry | linhas prontas únicas; erros continuam visíveis | integração/E2E |
| Silêncio, MIME falso, URL interna, XLSX excessivo | rejeição controlada, sem ledger | contrato |
| Alertas concorrentes/quiet hours/opt-out | uma entrega autorizada por chave | integração |

## Migrations e operação

Aplicar migrations em banco vazio e atualizar a partir da entrega anterior com dados. Verificar índices únicos, FKs compostas e políticas com role da aplicação. Mudanças destrutivas exigem migração de dados e estratégia de recuperação; downgrade que perde informação deve ser explicitamente não suportado, com restore testado. Ensaio de restore verifica contagem, integridade e isolamento.

## Frontend

Testes de formulário e estados de erro onde houver lógica; E2E para transação manual, importação, revisão, confirmação e mudança de família durante fetch. Verificar teclado/foco e viewport móvel. Não criar testes que espelhem classes CSS ou scores fixos sem verificar comportamento.

## Comandos previstos e gates

Backend: pytest (unit/integration), linter e typecheck escolhidos no bootstrap. Frontend: typecheck, lint, build e runner de E2E configurados na primeira entrega. CI executa testes determinísticos, migrations PostgreSQL e build; adapters externos são gate separado de implantação. Cada entrega registra os comandos efetivamente executados e limitações. Cobertura percentual não substitui a matriz financeira.

## Validação deste pacote

Por ser entrega documental, verificar presença dos 19 documentos, links locais, consistência entre campos/estados/rotas e critérios por etapa. Não afirmar testes de software ou migrations concluídos antes de existir implementação.
