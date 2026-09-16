# Motor de alertas

## Regras iniciais

BUDGET_THRESHOLD (80% e 100%), DUE_SOON (amanhã no fuso familiar), BUDGET_FORECAST_EXCEEDED (cenário linear acima do orçamento) e LOW_PROJECTED_BALANCE (limite explicitamente configurado). Configuração define destinatário com opt-in, canal, thresholds, janela de silêncio e enabled. Sem integração autorizada, exibir no dashboard; não tentar enviar por outro canal.

## Execução

Eventos financeiros e scheduler reavaliam regras usando serviços analytics/forecast compartilhados. Criar Alert + outbox na mesma transação, com dedup_key = regra + período/obrigação + threshold + destinatário. Retry reusa a mesma chave. Orçamento reduzido ou transação corrigida recalcula estado; não emitir repetidamente enquanto o limite permanece ultrapassado. Nova etapa (80 → 100) permite novo aviso.

Quiet hours padrão proposto: 22h–8h, no fuso da família; enfileirar para próximo horário permitido e revalidar antes de enviar. Limite inicial configurável de 3 alertas por destinatário/dia, agregando vencimentos em uma mensagem. Opt-out bloqueia envios já enfileirados; canal e associação são revalidados no envio.

## Conteúdo

“Alimentação atingiu 80% do orçamento de setembro: R$ 1.440,00 de R$ 1.800,00.”

“Amanhã vencem R$ 842,30 em compromissos cadastrados.”

“Mantido o ritmo observado até 16/09, Alimentação pode chegar a R$ 2.180,00, acima do orçamento de R$ 1.800,00.”

Distinguir fato de projeção e informar data de referência. Não afirmar que uma obrigação foi paga por decurso do vencimento. Alertas não alteram ledger nem fazem recomendações de investimento.

## Testes e operação

Clock falso cobre virada do mês, fuso, janela noturna e deduplicação. Concorrência scheduler/evento gera um alerta por chave. Falha de provider retenta mensagem sem novo Alert. Monitorar fila atrasada, supressões, opt-out e falhas definitivas.
