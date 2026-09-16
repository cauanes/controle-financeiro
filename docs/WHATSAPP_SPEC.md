# WhatsApp e Evolution API

## Fronteira do adapter

POST /webhooks/evolution recebe eventos do provider e os traduz para IncomingMessage: provider_event_key, provider_message_id, instance_key, sender_key, kind, text?, media_handle?, received_at, from_me, is_group. O payload real e o mecanismo de autenticação serão fixados por versão no teste de contrato da implantação. Não presumir HMAC nativo: validar o segredo/mecanismo suportado pela instância ou autenticação forte no gateway que a protege.

Roteamento usa instance_key previamente cadastrado em Integration e ChannelIdentity verificada. tenant_id/user_id/household_id recebidos no corpo nunca autorizam acesso. MVP aceita apenas conversa privada de remetente vinculado; grupos, status, mensagens próprias, eventos de recibo e tipos não suportados não disparam parser financeiro. Usuário desconhecido recebe no máximo instrução genérica de vinculação, sem dados da família.

## Vinculação

Admin configura integração pelo dashboard; membro autenticado gera código de uso único, armazenado como hash, com expiração de 10 min e limite de tentativas. Código enviado pelo número cria ChannelIdentity na integração/família escolhida. Reuso, número já associado e tentativa cruzada são recusados. Desvincular revoga identidade e cancela pendências. Adicionar tabela channel_link_tokens (scope, user_id, token_hash UNIQUE, expires_at, used_at?, attempts) na migration de integração.

## Recepção e idempotência

Autenticar, limitar tamanho e validar envelope antes de persistir. Evento relevante recebe ACK 202 apenas após receipt, message e outbox duráveis. Duplicado conhecido recebe 200 e não recria trabalho. Evento autenticado ignorável recebe 204. Falha temporária de persistência retorna 503 para retry; assinatura/segredo inválido retorna 401/403 sem processar; envelope inválido retorna 400. Chave usa identificador estável do provider com instância e tipo de evento; se versão não fornecer identificador confiável, adapter precisa definir e testar composição antes do uso real.

## Respostas

- Pendência: “Entendi R$ 270,00 em Supermercado. Qual conta ou cartão você usou?”
- Ambiguidade: “Você usou a conta Nubank no débito ou o cartão Nubank no crédito?”
- Data ausente: “Essa compra foi hoje, 16/09?”
- Sugestão histórica: “Foi R$ 128,00 de combustível no cartão Nubank?”
- Sucesso após commit: “✅ R$ 128,00 registrado em Transporte › Combustível — Cartão Nubank, 16/09.”
- Cancelamento: “Lançamento pendente cancelado.”
- Falha de áudio: “Não consegui entender o valor no áudio. Pode informar o valor?”

Escapar/limitar texto de usuário antes de compor mensagem. Enviar valores completos somente ao destinatário verificado. Uma pergunta por vez. ID curto da ação pode ser mostrado para suporte sem expor IDs internos.

## Saída e recuperação

OutgoingMessage é gravada na transação que produz a resposta. Worker envia com client_message_id estável. Retentar falhas transitórias, respeitando rate limit do provider; 5 tentativas iniciais propostas com backoff. Em timeout após possível aceite, marcar UNKNOWN e consultar status quando suportado antes de reenviar. Se o provider não resolver a incerteza, registrar para revisão; não duplicar automaticamente mensagens indefinidamente. Falha de envio jamais desfaz lançamento confirmado.

Métricas: duplicados recebidos, fila por sessão, latência, envio incerto, erros de autenticação e volume rejeitado. Não registrar corpo bruto ou telefone em logs comuns.
