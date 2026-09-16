# Regras financeiras

## Dinheiro, datas e gravação

Usar Decimal no backend e numeric(18,2) no banco. API transmite dinheiro como string decimal (“287.40”), nunca float. Valores de Transaction são estritamente positivos. Formatação pt-BR ocorre na UI. Rejeitar precisão excedente em entrada manual; adapters documentam qualquer arredondamento do arquivo e exibem no preview.

Data é obrigatória. “Hoje” e “ontem” resolvem no fuso da família usando received_at, não o relógio do worker. Sem data explícita, oferecer “Foi hoje?”; confirmação torna a data explícita. Data futura cria PLANNED e não afeta saldo realizado. Marcar como pago é ação explícita; passagem do tempo não prova pagamento.

## Efeito financeiro

Saldo(account, data) = opening_balance + receitas POSTED + transferências recebidas POSTED − despesas de conta POSTED − transferências enviadas POSTED, considerando data até o corte e ignorando VOIDED. Abertura possui opening_balance_date; rejeitar lançamentos anteriores até ajuste explícito da abertura. Saldo disponível exclui limites de crédito.

| Operação | Caixa | Resultado por competência | Obrigação do cartão |
|---|---|---|---|
| Despesa de conta 100 | −100 na conta | despesa 100 | 0 |
| Receita 100 | +100 na conta | receita 100 | 0 |
| Transferência A → B 100 | −100 A, +100 B | 0 | 0 |
| Compra no cartão 100 | 0 | despesa 100 | +100 |
| Pagamento de fatura 100 | −100 na conta | 0 | −100 |

Pagamento de fatura é transferência especial com invoice_id e InvoicePayment, nunca despesa. Limitar pagamentos ao saldo devedor no MVP; bloquear pagamento excedente até suporte explícito a créditos. Fatura parcial permanece aberta/PARTIALLY_PAID. Saldos de cartão e fatura são derivados de compras e pagamentos; materializações devem ser reconstruíveis.

## Cartão e parcelas

Cartão requer fechamento e vencimento. Datas reais da fatura podem ser ajustadas explicitamente; algoritmo inicial usa closing_day e due_day, limitando ao último dia do mês. Compra no dia do fechamento entra, por convenção visível, na fatura que fecha nesse dia; permitir correção manual porque a liquidação bancária pode divergir. Vencimento é a primeira ocorrência do due_day estritamente após o fechamento.

Compra parcelada requer total, número de parcelas, cartão e data. Gerar parcelas ligadas por installment_group_id, com soma exata igual ao total; distribuir centavos residuais nas primeiras parcelas (100/3 → 33.34, 33.33, 33.33). Primeiro vencimento segue a fatura de compra; demais em meses sucessivos. Não criar também uma despesa do total. Cada parcela tem transaction_date da compra e competence_date no ciclo da parcela; realizado por competência usa competence_date. Obrigações incluem todas as parcelas POSTED, mesmo com competência futura; projeção de caixa considera apenas saldo de cada fatura no vencimento.

## Orçamento, metas e patrimônio

Orçamento compara despesas POSTED por competence_date, incluindo cartão e excluindo transferências/VOIDED. Categorias pai agregam descendentes sem duplicação. Planejado é apresentado à parte. Meta registra alocação/contribuição e pode referenciar transferência; não cria despesa automaticamente.

Patrimônio = contas + ativos independentes − dívida de cartões − passivos independentes. Asset ligado a Account é representação descritiva e não se soma novamente. Liability ligada a Card também não se soma. Aporte entre contas próprias não é despesa. Valorização de ativo não é receita operacional.

## Correção e conciliação

Correções materiais pelo WhatsApp exigem proposta antes/depois e confirmação vinculada à versão. HTTP requer expected_version em mutações para evitar atualização perdida. Excluir significa VOIDED; auditar reversão. MVP não oferece estorno bancário automático nem multimoeda: encaminhar operação não suportada sem modificar o ledger.

Valor/data/conta incompatíveis nunca são conciliados automaticamente. Evidência externa não altera silenciosamente valor ou data do registro existente. Parcelas, pagamento de fatura e transferência demandam tipos compatíveis. Rejeições de pareamento persistem para que o mesmo par não reapareça automaticamente.
