# Motor de conciliação

## Unidade de comparação

Comparar ImportRow ainda não importada com Transaction existente no mesmo tenant/família/fonte/moeda. Se há correspondência aceita, vincular TransactionSource à transação existente. Não criar duas transações para depois esconder uma em relatórios. Conciliação de dois registros já lançados fica para fluxo manual específico posterior.

## Candidatos e score inicial proposto

Bloqueios: valor deve ser exato, mesma moeda, direção/tipo compatível, mesma conta ou cartão resolvido, diferença de data até 3 dias. Falhar em qualquer bloqueio impede auto-conciliação. Descrição não compensa fonte diferente. Para parcelas comparar parcela e fatura, não total da compra.

Score = 0.40 × amount_exact + 0.25 × source_exact + 0.15 × date_similarity + 0.10 × merchant_similarity + 0.10 × description_similarity. date_similarity = max(0, 1 − abs(delta_days)/4). Similaridades textuais entre 0 e 1 com algoritmo determinístico versionado. Ausência de merchant pontua zero; não renormalizar para inflar confiança. Pesos somam 1 e ficam em configuração versionada.

- Auto: score >= 0.97, evidências materiais compatíveis, único candidato e margem >= 0.10 para o segundo, nenhuma rejeição anterior.
- Revisão: score >= 0.75 ou ambiguidade entre candidatos.
- Sem match: inferior; oferecer importar novo no preview.

Esses limiares são hipótese inicial, não precisão medida. Auto-conciliação começa desabilitada e só é habilitada após avaliação com decisões reais. Identidade externa confiável já vinculada é deduplicação, não previsão por score.

## Algoritmo

```text
find_candidates(row):
  scope authorized household and exact source/currency/amount/type
  exclude VOIDED and rejected pairs
  restrict date window and installment compatibility
  score each candidate, keeping per-feature evidence and algorithm version
  sort; classify as review / eligible_auto / unmatched

accept(match_id, expected_transaction_version):
  begin; lock import row then target transaction in stable order
  recheck permissions, row unresolved, target version and compatibility
  insert source with unique source_key
  mark match ACCEPTED; row RECONCILED; transaction RECONCILED
  append audit and TransactionReconciled; commit

reject(match_id):
  persist REJECTED and actor; do not write ledger
```

Versão desatualizada marca STALE e solicita recálculo. Rejeitar par não marca a linha importada: usuário escolhe outro candidato ou cria novo. VOIDED permanece como evidência de possível reimportação e exige revisão, evitando ressuscitar lançamento excluído.

## Interface e aprendizado

Exibir os dois lados com valor, data, fonte, descrição, categoria e fatores do score; percentual é similaridade, não probabilidade garantida. Ações Conciliar e Não são iguais. Aceite não substitui automaticamente categoria ou descrição; sugestão de atualização é ação separada. Guardar decisões para calibrar pesos e regras; nunca aprender em outro tenant ou ativar mudança de política sem avaliação.

## Testes

Compra WhatsApp 287.40 em 15/09 + extrato 16/09 gera uma despesa e duas origens após aceite. Diferença de valor ou conta bloqueia automático. Dois candidatos iguais exigem revisão. Dois workers não vinculam a mesma linha duas vezes. Rejeição não reaparece; edição do candidato torna proposta antiga inválida.
