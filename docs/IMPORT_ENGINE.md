# Motor de importação

## Contrato e estados

OFX, CSV, XLSX e providers produzem NormalizedImportRow: row_id, external_id?, amount (string positiva), direction, transaction_date, competence_date?, description, merchant_hint?, source_reference, currency e raw_reference sanitizada. Sinal no arquivo é convertido para tipo; semântica de débito/crédito depende do template e deve aparecer no preview. Nunca usar valor absoluto sem preservar direção.

ImportJob: UPLOADED → PARSING → PREVIEW → PROCESSING → COMPLETED ou PARTIAL. Parsing pode terminar FAILED; antes de PROCESSING pode cancelar. ImportRow possui estado independente; falha de uma linha não desfaz as já confirmadas e é exposta em PARTIAL. Reprocessamento atua só em linhas pendentes, com idempotência.

## Fluxo

1. Upload autenticado e limites (propostos: 20 MB, 50 mil linhas, XLSX descompactado até 100 MB); armazenar arquivo privado com hash e prazo de retenção.
2. Detectar formato por conteúdo, validar encoding/delimitador. OFX não resolve entidades externas; XLSX não executa fórmulas/macros nem links externos. CSV não avalia fórmulas.
3. Selecionar conta/cartão real da família e template versionado. Se não houver template, UI mapeia data, descrição, valor e direção, incluindo locale e formato de data.
4. Normalizar sem gravar ledger. Linhas inválidas mostram número da linha e motivo; datas 03/04 exigem mapeamento explícito, nunca heurística silenciosa.
5. Classificar por regras, procurar duplicados e candidatos de conciliação. Preview mostra novos, duplicados, inválidos e a revisar, com totais por tipo.
6. Usuário confirma job_id + expected_version + lista de decisões. Worker congela preview e valida referências novamente.
7. Por linha, em transação: bloquear linha, resolver decisão, criar transação ou anexar origem, gravar auditoria/outbox e marcar resultado. Reexecutar linha concluída devolve resultado anterior.

## Deduplicação

Primeiro comparar identificador externo estável no namespace de integração/conta/formato. Se ausente, fingerprint combina fonte, data, valor, direção e descrição normalizada. Fingerprint é indício, não constraint global: duas compras iguais no mesmo dia podem ser legítimas. Reimportação do mesmo arquivo/mapeamento/fonte identifica as mesmas linhas; hash sozinho não deve confundir arquivos aplicados a contas diferentes. Diferentes arquivos com fingerprint igual entram em revisão salvo identidade externa comprovada.

source_key é determinística: namespace externo + external_id quando confiável; senão hash do arquivo + versão do mapping + conta/cartão + número de linha. Se mapping mudou, mostrar linhas previamente importadas para revisão; não tratar automaticamente a nova chave como compra nova.

## Templates e conectores

ImportTemplate guarda nomes/posições de colunas, locale, formato de data, convenção de sinal e versão. Alterar template cria versão nova, não muda jobs anteriores. Templates Nubank e outros só entram após fixtures reais anonimizadas validadas; não presumir layout por nome de banco.

FinancialDataProvider emite o mesmo modelo e cursor de sync. Persistir cursor somente após persistência de todas as linhas do lote; reenvio precisa ser seguro. Tokens e consentimento pertencem ao adapter. Nenhuma regra de classificação ou saldo depende do fornecedor.

## Aceitação

Mesmo arquivo duas vezes não duplica ledger; duas compras legítimas iguais sobrevivem; transferência e pagamento de fatura não viram despesa por sinal negativo; preview não movimenta saldo; arquivo malformado não impede jobs posteriores; confirmação concorrente importa cada linha uma vez; tenant distinto não acessa arquivo ou job.
