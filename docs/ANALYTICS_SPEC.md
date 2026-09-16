# Analytics

## Contrato temporal

Todos os endpoints recebem from/to inclusivos como datas civis, household do contexto autenticado, filtros opcionais e basis quando aplicável. Resposta informa currency, timezone, basis, as_of, calculation_version e data_quality (pendências e importações não concluídas). Ausência de histórico não vira zero conhecido: série sem observações informa estado insuficiente.

## Indicadores

| Indicador | Definição |
|---|---|
| Receitas | soma INCOME POSTED por competence_date no período |
| Despesas | soma EXPENSE POSTED por competence_date, incluindo parcelas do ciclo |
| Resultado | receitas − despesas |
| Saving rate | resultado / receitas × 100; null quando receitas = 0 |
| Disponível | saldo atual agregado de contas, sem limite de crédito |
| Patrimônio | contas + ativos independentes − obrigação de cartões − passivos independentes |
| Free cash flow | entradas efetivas externas − saídas efetivas externas no período; pagamento de fatura incluído uma vez |
| Reserva | saldo das contas explicitamente designadas como reserva; sem designação, null |
| Runway | reserva / média mensal de despesas essenciais dos últimos 3 meses completos; null se base insuficiente/zero |
| Custos fixos | despesas vinculadas a recorrências classificadas como fixas |
| Comprometimento | obrigações futuras conhecidas, discriminando dívida e parcelas sem somar total e parcelas novamente |

Designação de reserva e essencialidade precisa de configuração explícita: acrescentar accounts.is_emergency_reserve boolean default false e categories.is_essential boolean nullable na entrega de diagnóstico; recorrência tem cost_class FIXED/VARIABLE/UNKNOWN. Sem configuração, apresentar “não configurado”. Variação patrimonial 12 meses exige snapshots comparáveis nos dois cortes; expor cobertura.

## Recursos

- /analytics/summary: patrimônio, disponível, receitas, despesas, resultado, saving rate.
- /analytics/cashflow: buckets diários/mensais de entradas, saídas e saldo de caixa; transferências internas zeram no total, mas aparecem por conta.
- /analytics/categories: árvore com realizado e percentuais; pai agrega folhas uma vez; Sem categoria é bucket próprio.
- /analytics/net-worth: componentes e série de snapshots com datas de avaliação.
- /analytics/financial-health: fluxo, segurança, comprometimento e patrimônio; sem nota arbitrária.

Orçado × realizado usa as mesmas categorias e competence_date do orçamento. Receita × despesa no dashboard é competência; fluxo de caixa é caixa. Rótulos precisam explicitar a base. Não somar compra de cartão à saída de caixa antes do pagamento.

## Qualidade, cache e testes

Cache por tenant, família, filtros e watermark; nunca compartilhar resultado entre usuários com escopos distintos. Eventos invalidam ou avançam watermark. Snapshots reconstruíveis incluem versão de cálculo e entradas usadas. Alteração retroativa marca períodos afetados para recálculo.

Fixture de referência: abertura 1.000, receita 500, despesa de conta 100, compra cartão 200 e pagamento dessa fatura 200 → disponível 1.200; obrigação cartão 0; patrimônio 1.200; resultado 200; saving rate 40%; saída de caixa 300. Transferir 50 entre contas não muda esses totais. Essa fixture deve validar API e domínio.
