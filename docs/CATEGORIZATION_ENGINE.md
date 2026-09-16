# Motor de categorização

## Ordem e contratos

CategorizationResult: category_id?, merchant_id?, confidence?, source, matched_rule_id?, alternatives[], requires_clarification. Ordem: escolha explícita do usuário → regra explícita pessoal → regra da família → palavra-chave inequívoca → sugestão de histórico → parser semântico. Empates ou contradições produzem alternativas, sem escolha silenciosa.

Merchant representa estabelecimento; categoria representa natureza. “Amazon” resolve merchant, mas pergunta compra. “Gasolina/posto” pode inferir Transporte › Combustível. “Mercado” pode inferir Alimentação › Supermercado. Correspondência usa limites de palavras e normalização de acentos; não corresponder substrings acidentais. Descrição original permanece disponível na evidência.

## Política

Sugestão de categoria >= 0.90 sem conflito pode ser aplicada com proveniência. Abaixo disso, pergunta curta depois de resolver fonte/valor/data. “Não sei” oferece Sem categoria; a escolha explícita grava category_id nulo com evidência de decisão. Conta e cartão históricos sempre exigem confirmação, independentemente do score.

Correção de categoria atualiza somente a transação confirmada. Oferecer regra futura exige aceite explícito com contexto visível; nunca reclassificar histórico automaticamente. UserFinancialPreference usa somente decisões confirmadas, conta observações e decai/revisa padrões antigos; sugestão de fonte é desativável.

## Regras e validação

CategoryRule contém padrão EXACT/CONTAINS, categoria, prioridade, escopo pessoal/familiar e enabled. Categorias hierárquicas impedem ciclos e incompatibilidade receita/despesa. Categoria arquivada aparece no histórico, não em novas sugestões. Regras conflitantes geram diagnóstico no dashboard.

Testar palavras com acentos, Amazon sem item, empate, categoria arquivada, regra de outra família, sugestão histórica de cartão sem confirmação e resposta “Sem categoria”. Não criar testes que simplesmente fixem um score arbitrário; verificar decisão e efeito financeiro.
