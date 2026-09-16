# Frontend React/TypeScript

## Navegação

Sidebar com cinco áreas: Visão Geral; Finanças (Transações, Contas, Cartões); Planejamento (Orçamento, Recorrentes, Metas, Calendário); Análises (Fluxo de Caixa, Gastos, Patrimônio, Saúde Financeira, Projeções); Configurações (família/membros, categorias/regras, integrações, preferências). Revisar lançamentos e Importar são acessíveis em Transações com badge de pendências, sem acrescentar uma área principal.

Rotas propostas: /, /finances/transactions, /finances/accounts, /finances/cards, /finances/cards/:id/invoices/:invoiceId, /planning/budgets, /planning/recurring, /planning/goals, /planning/calendar, /analytics/:view, /settings/:section e /finances/reconciliation.

## Visão geral

Seletor de família e período; cards Patrimônio, Disponível, Resultado, Taxa de poupança. Em sequência: receitas × despesas, orçado × realizado, fluxo projetado, distribuição de despesas, alertas, próximos vencimentos, metas e atividade recente. Mostrar data de atualização e base de cálculo. Zero receita torna taxa “—”, com explicação. Histórico insuficiente gera estado vazio com ação de importar/registrar, sem números fictícios.

## Transações

Filtros de período, pessoa, conta/cartão, categoria/subcategoria, merchant, tipo, origem, status e faixa de valor refletem URL e API. Busca paginada por cursor. Cada linha mostra data, descrição, hierarquia, fonte de pagamento, valor com sinal visual e badges de evidência. WhatsApp + Extrato representam duas origens; ✓ de conciliação só aparece se a decisão estiver aceita.

Detalhe apresenta histórico e origens, ação editar e excluir com impacto explícito. Formulário exige valor, data, tipo e fonte discriminada; campos dinâmicos distinguem transferência e cartão. Data pré-preenchida aparece visível e editável antes de salvar; esse aceite do formulário é evidência explícita. Não escolher conta/cartão por histórico sem mostrar a seleção e obter confirmação do usuário.

## Importação e conciliação

Wizard: arquivo → conta/cartão e mapeamento → preview → decisões → resultado. Erros indicam linha/coluna e não desaparecem ao voltar. Mostrar novos/duplicados/a revisar/ignorados, totais e convenção de sinais. Confirmar desabilitado enquanto faltam decisões obrigatórias; conclusão parcial oferece retentar apenas falhas.

Revisão lado a lado no desktop e empilhada no celular: WhatsApp/manual versus extrato; datas, valores, fonte e descrição; score rotulado Similaridade. Conciliar/Não são iguais enviam versão; conflito exige recarregar a proposta. Explicar qual transação será preservada.

## Conversas e planejamento

Pendências ficam em atividade/central de revisão com pergunta atual, prazo e ações responder/cancelar. Confirmação exibe resumo persistido, sem converter sugestão em sucesso otimista. Faturas mostram compras, parcelas, pagamentos e saldo restante. Calendário distingue previsto de pago. Metas distinguem alocação de movimentação. Diagnóstico apresenta quatro blocos com fórmulas acessíveis e qualidade dos dados, sem score geral.

## Estado, acessibilidade e validação

Tipos derivados do OpenAPI; valores monetários permanecem strings até formatação, sem usar Number para cálculo financeiro. Cache de consultas inclui household e filtros; trocar família limpa dados anteriores imediatamente. Requisições são canceladas/descartadas se contexto mudar. Nenhuma confirmação financeira usa atualização otimista que mostre sucesso antes da API.

Cada tela contempla loading, empty, error com retry, sem permissão, conflito e estado parcial. Navegação por teclado, labels, foco gerenciado em modal, mensagens anunciadas e cor acompanhada de texto/ícone. Layout responsivo com tabelas adaptadas. Gráficos possuem resumo textual/tabela. Dados de demonstração só em fixtures/storybook, nunca misturados a dados reais.

## Aceitação visual e funcional

Fluxos de registro manual, filtro compartilhável, importação parcial, conciliação, pendência e troca de família testados em desktop e viewport móvel. Nenhuma rota futura mostra indicador fabricado: apresentar indisponibilidade explícita até a entrega correspondente.
