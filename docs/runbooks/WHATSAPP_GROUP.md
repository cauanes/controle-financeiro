# Grupo WhatsApp da família

O Finance usa a instância `cacauweb` da Evolution API, conforme solicitado. O webhook da Evolution continua apontando para o cacauwebproduct. O cacauwebproduct encaminha uma cópia autenticada dos eventos para o Finance por uma tarefa Celery separada; uma falha no Finance não altera o processamento de ofertas do webproduct. Os dois sistemas compartilham a sessão WhatsApp, mas mantêm dados e bancos separados.

## Configuração atual

- Interface Finance: <http://localhost:8080>. API: <http://localhost:8002>. O acesso inicial que já existia no banco local foi copiado para o banco persistente do Compose, mantendo o hash da senha. Faça login novamente; sessões antigas não foram copiadas.
- A família no Finance foi ligada à instância `cacauweb`. A API e o worker do Finance participam da rede `cacauweb-net`; o Compose guarda `EVOLUTION_BASE_URL`, `EVOLUTION_API_KEY` e `EVOLUTION_WEBHOOK_SECRET` no `.env` local, ignorado pelo controle de versão.
- O cacauwebproduct mantém seu próprio webhook da Evolution e usa `FINANCE_WEBHOOK_URL` e `FINANCE_WEBHOOK_SECRET` no `.env` local para encaminhar eventos ao Finance. O worker de envio participa também da rede `cacau-finance_default` para alcançar a API do Finance.

## Criar o grupo

1. Em **Configurações → Pessoas da família**, convide os participantes. Quem ainda não tem acesso usa **Recebi um convite** na tela inicial. O código deve ser entregue pelo administrador; não há envio automático.
2. Cada membro abre **Configurações → WhatsApp e integrações**, seleciona `cacauweb`, gera um código de vínculo e envia `vincular <código>` em conversa privada ao número do cacauwebproduct. O código expira em dez minutos. Para cada membro, confirme que a mensagem foi encaminhada ao Finance antes de criar o grupo.
3. O grupo atual, **Cacau - Finanças**, já está vinculado pelo ID `120363431389141338@g.us`. Para uma nova família, um administrador escolhe apenas membros vinculados e cria o grupo na mesma tela. Um grupo existente também pode ser vinculado pelo ID `@g.us`.
4. O bot só executa intenções financeiras de participantes vinculados e ativos. Mensagens de grupos não associados e conversa comum são ignoradas. Cada mensagem no grupo é visível a todos os participantes. Ao revogar o acesso de alguém no Finance, remova também a pessoa do grupo WhatsApp; isso não é automatizado.

## Conexão `Connection Closed`

Verifique o contêiner `cacauweb_evolution`. `GET /instance/connectionState/cacauweb` pode responder `open` mesmo quando `GET /group/fetchAllGroups/cacauweb?getParticipants=false` falha com `Connection Closed` ou fica sem resposta. A listagem total pode demorar em contas com muitos grupos; para este grupo, prefira `GET /group/findGroupInfos/cacauweb?groupJid=120363431389141338%40g.us`. Reiniciar a instância via `POST /instance/restart/cacauweb` e reiniciar o contêiner são tentativas reversíveis. Se a consulta do grupo específico também falhar, o titular do número pode precisar re-parear a mesma instância no painel da Evolution por QR code. Evite `logout` ou `delete` sem preparar o novo pareamento, pois afetam a sessão já usada pelo webproduct.

Em 16/09/2026, a primeira listagem e tentativa de criação responderam HTTP 500 `Connection Closed`. Após reiniciar o contêiner, a listagem total ficou sem resposta no timeout e os logs mostraram `rate-overlimit` ao buscar metadados de vários grupos. Em 17/09/2026, a consulta direta do grupo **Cacau - Finanças** respondeu HTTP 200 com três participantes; o grupo também está ativo no banco do Finance, com três identidades WhatsApp vinculadas. Uma mensagem real de receita foi processada e recebeu uma pergunta no grupo; a transação segue pendente de informação e confirmação.

## Escolhas no grupo

Quando precisa escolher pessoa, atividade ou conta, o bot envia uma lista numerada. Quem iniciou a conversa pode responder `1`, `2` etc. ou escrever o nome da opção. A confirmação de receita também oferece `1. Confirmar e registrar` e `2. Cancelar`. Uma opção inválida ou pertencente a uma pergunta anterior não registra transação. O Finance interpreta respostas interativas recebidas, mas usa texto numerado no grupo. Na tela **Conversar** do aplicativo, as mesmas opções aparecem como botões clicáveis.

Em 17/09/2026, a instância compartilhada estava na Evolution **2.3.7 / Baileys 7.0.0-rc.9**. Os endpoints de botões e listas existem, mas há relatos reproduzíveis da mesma combinação com HTTP 400 `this.isZero is not a function` ou HTTP 201 sem entrega: [falha em 2.3.7](https://github.com/evolution-foundation/evolution-api/issues/2390), [mensagem aceita sem entrega](https://github.com/evolution-foundation/evolution-api/issues/2404). A [versão 2.4.0-rc1](https://github.com/evolution-foundation/evolution-api/releases/tag/2.4.0-rc1) anuncia correções específicas de renderização de botões/listas e do erro `this.isZero`, mas é pré-lançamento e exige ativação de licença. Esses dados não provam que todo botão falha nesta instância nem que a versão nova funciona neste grupo. Antes de trocar o envio numerado por controles nativos, validar entrega e resposta num teste isolado em Android, iPhone e WhatsApp Web, sem atualizar a instância `cacauweb` usada pelo webproduct apenas para isso.

## Imagens de fatura

Envie fotos ou prints JPG/PNG/WebP no grupo. O worker baixa a mídia da Evolution, executa Tesseract OCR local em português/inglês, descarta os bytes e propõe apenas os itens que conseguiu ler com separador decimal explícito. Prints sobrepostos da mesma fatura são unidos na pendência. A resposta mostra cartão, total, vencimento, fechamento, despesas com comerciante/valor/data/categoria sugerida e pagamentos/créditos excluídos da importação de despesas. Regras de categoria configuradas pela família (inclusive CNPJ) têm prioridade sobre sugestões por nome; SearXNG local é fallback opcional para nomes desconhecidos.

Quando faltar o nome do cartão, responda `cartão Sam's Club` (ou outro nome). Se houver mais de um cartão do mesmo emissor, o bot só escolhe sozinho quando os quatro últimos dígitos identificam um cartão único; caso contrário, pede o nome. Para corrigir a proposta, use `corrigir 2 34,17`, `categoria 2 Supermercado`, `adicionar 01/08/2026 AMAZON BR 34,17` ou `remover 2`. `sim` só importa quando o resumo está completo e não há divergências. Se a soma das despesas não bater com o total ou houver possível duplicata, a resposta exige `confirmar mesmo assim` após revisão. `cancelar` encerra a proposta sem importar. A importação de uma parcela preserva a data da compra e usa o ciclo de fechamento da fatura enviada; não gera parcelas passadas/futuras por suposição. Mais de 20 despesas em uma proposta não são confirmadas no grupo. Prints com total, vencimento, fechamento ou emissor incompatíveis não são unidos à proposta em andamento.

Imagens sem texto legível, mídias não compatíveis e comandos não entendidos recebem resposta clara sem lançamento. PDF, vídeo e figurinhas ainda não são lidos nesse fluxo. Uma pendência financeira anterior ocupa a conversa: a imagem recebe aviso, mas não substitui essa pendência; conclua ou envie `cancelar` e reenvie as fotos. Para evitar classificação indevida, OCR de imagem não é encaminhado automaticamente ao parser de mensagens de receita/despesa. Confira cada item exibido, pois OCR pode omitir texto que não conseguiu reconhecer.

## Operação

Monitore `/health/ready`, falhas de webhook, `outbox_events` pendentes e `outgoing_messages` em `UNKNOWN`. Mensagens `UNKNOWN` exigem verificação antes de reenviar. Faça backup do PostgreSQL com `pg_dump` e teste restauração em ambiente separado. Áudio requer `TRANSCRIPTION_URL`; os bytes são descartados após a transcrição e o texto tem retenção de 90 dias. O encaminhamento no webproduct usa retries para falhas de transporte ou HTTP 5xx; respostas 4xx de números ainda não vinculados são esperadas e não interrompem o fluxo de ofertas.
