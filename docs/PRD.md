# Family Finance Hub — PRD

Status: proposta técnica implementável, versão 1, 16/09/2026. Origem: PRD fornecido pelo usuário. Este pacote especifica o produto; não representa funcionalidades já implementadas.

## Objetivo e público

Centralizar a gestão financeira de uma família, com registro por WhatsApp (texto e áudio), conferência pelo dashboard e confirmação por extratos. Preparar isolamento entre famílias e tenants sem introduzir microserviços. Stack definida: FastAPI, React/TypeScript, PostgreSQL, Redis e Evolution API.

## Regra de produto

**Nunca presuma silenciosamente uma informação que altere materialmente o registro financeiro.** Texto e áudio geram o mesmo objeto normalizado e percorrem o mesmo motor. Conta, cartão, valor, crédito versus débito, data ambígua e responsável relevante exigem esclarecimento. Histórico sugere, mas não comprova. Nenhuma transação é gravada enquanto faltar um dado material.

Uma mensagem pendente deve dizer “Entendi R$ 180,00 em Supermercado. De onde saiu o pagamento?”, nunca “Registrei”. Sucesso só pode ser informado depois do commit financeiro.

## Escopo e prioridade

| Entrega | Conteúdo |
|---|---|
| Núcleo inicial | Autenticação, família, membros, contas, cartões, categorias, lançamentos manuais, auditoria e saldos |
| Captura conversacional | Texto, áudio, esclarecimento, confirmação, cancelamento, expiração, correção e exclusão confirmadas |
| Conferência | Preview OFX/CSV/XLSX, mapeamentos, deduplicação, conciliação e múltiplas origens |
| Planejamento e análise | Orçamentos, recorrências, metas, faturas, patrimônio, fluxo projetado e alertas |
| Futuro | Open Finance real, simulações, amortização, diagnóstico assistido e previsões estatísticas |

O catálogo completo de intenções está em [CONVERSATION_ENGINE.md](CONVERSATION_ENGINE.md). Reconhecer uma intenção ainda não implementada gera uma resposta de indisponibilidade, nunca execução aproximada.

## Jornadas de aceitação

1. “Gastei 270 no mercado” abre pendência; “Nubank” continua ambíguo se existir conta e cartão; “crédito” resolve a fonte. Se a data também estiver ausente, solicitar ou confirmar uma data proposta. Registrar uma única vez após todos os dados materiais resolvidos.
2. “128 de gasolina hoje no crédito” pergunta o cartão. Texto ou transcrição equivalente produzem o mesmo candidato e a mesma pergunta.
3. “240 na Amazon” não usa Amazon como categoria. Perguntar o item comprado; permitir que a pessoa escolha explicitamente “Sem categoria”.
4. “Aquele mercado de 270 foi Itaú” localiza candidatos visíveis ao usuário, desambigua quando necessário e mostra antes/depois para confirmação.
5. Extrato correspondente a um lançamento do WhatsApp acrescenta evidência à mesma transação sem duplicar despesa ou saldo.
6. Transferência própria não aumenta receita ou despesa. Pagamento de fatura não conta compras novamente.
7. Dois usuários ou reenvios do webhook não conseguem confirmar a mesma ação duas vezes.

## Requisitos de experiência

Perguntar um ponto por vez, priorizando a informação material bloqueante. Mostrar apenas opções da família autorizada. Permitir cancelar e retomar pelo identificador da ação. Uma nova despesa durante uma pendência não deve sobrescrevê-la. Dashboard e WhatsApp refletem o mesmo estado persistido.

## Metas de qualidade propostas

- Zero duplicações em testes de retries e concorrência; zero acesso entre tenants em testes de autorização.
- 100% dos lançamentos e alterações com auditoria e origem rastreável.
- Webhook autenticado é persistido antes do ACK; orçamento inicial de latência p95 de 2 s para recepção e 10 s para resposta textual assíncrona, sem promessa de SLA externo.
- Medir tempo para concluir ação, perguntas por ação, cancelamentos, falhas de transcrição, revisão de conciliação e sugestões corrigidas. Calibrar os objetivos após uso real.

## Decisões e limites

BRL, família no fuso America/Sao_Paulo por padrão e suporte inicial a uma moeda por família. Valores monetários exatos; moeda estrangeira e câmbio ficam fora da primeira versão. Datas relativas usam o instante de recepção no fuso da família; ausência de data não significa silenciosamente “hoje”. Categoria incerta pode ser resolvida por pergunta ou pela escolha explícita “Sem categoria”; campos opcionais nunca bloqueiam gravação.

Provider de transcrição, hospedagem, canal de login e custos externos serão configurados na implantação. Adapters falsos permitem desenvolvimento e testes sem credenciais. O uso real do WhatsApp depende de provisionamento e teste de contrato da Evolution API escolhida.

## Navegação do pacote

[Arquitetura](ARCHITECTURE.md), [domínio](DOMAIN_MODEL.md), [banco](DATABASE_SCHEMA.md), [regras financeiras](FINANCIAL_RULES.md), [API](API_SPEC.md), [frontend](FRONTEND_SPEC.md), [segurança](SECURITY.md), [testes](TESTING_STRATEGY.md) e [plano](CODEX_IMPLEMENTATION_PLAN.md).
