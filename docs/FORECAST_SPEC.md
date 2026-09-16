# Projeções

## Primeira versão

Projeção determinística de caixa por dia, com horizonte padrão de 90 dias e máximo inicial de 365. Não é promessa de saldo futuro. Entrada: saldo de contas no corte, PLANNED com data de vencimento, ocorrências futuras ainda não materializadas, saldo de faturas e obrigações explicitamente configuradas. Receitas incertas aparecem separadas como cenário, nunca saldo realizado.

saldo_projetado[d] = saldo_projetado[d−1] + entradas_previstas[d] − saídas_previstas[d]. Transferências próprias zeram no consolidado. Compras de cartão entram pela obrigação da fatura no vencimento, não também pela despesa individual. Subtrair pagamentos já POSTED do saldo de fatura; excluir parcelas canceladas.

## Identidade e incerteza

Cada fluxo possui origin_type, origin_id e occurrence_key. Se recorrência já gerou Transaction, usar apenas a transação. Se pagamento planejado cobre fatura, usar fluxo líquido da fatura e não ambos. Eventos vencidos sem confirmação ficam como “vencido em aberto” e são alocados ao primeiro dia projetado em cenário explícito, sem fingir data real.

Projeção de categoria: realizado até hoje / dias decorridos do mês × dias totais, disponível somente após 7 dias e com dados no período; mostrar hipótese de ritmo uniforme. Custos recorrentes conhecidos devem ser mostrados separadamente; não adicioná-los novamente sobre extrapolação que já os inclui. V1 usa extrapolação simples como cenário separado da projeção por compromissos.

## API e apresentação

GET /api/v1/forecast/cashflow?from=&to=&account_id= devolve opening_balance, daily[], overdue[], assumptions[], data_quality e generated_at. GET /api/v1/forecast/categories?month=YYYY-MM devolve realizado, projeção linear, orçamento e dias observados. UI distingue conhecido de estimado por legenda e lista de hipóteses. Horizonte insuficiente ou orçamento ausente não produz alerta de excesso inventado.

## Testes

Fatura parcialmente paga, parcela futura, fevereiro/dia 31, recorrência já materializada, transferência interna, compromisso vencido e receita estimada opcional. Confirmar que um evento participa no máximo uma vez de cada cenário. Previsões estatísticas, simulação de compra e amortização ficam fora do MVP.
