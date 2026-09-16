# Segurança e operação de dados

Este documento define controles do produto, sem afirmar conformidade legal certificada. Configuração de implantação e políticas de retenção precisam ser registradas antes do uso real.

## Ameaças e controles

| Ameaça | Controle obrigatório |
|---|---|
| Acesso entre famílias | associação verificada no servidor, FKs compostas, RLS e testes negativos |
| Webhook falsificado/repetido | autenticação da integração, recibo único e remetente vinculado |
| Número indevidamente vinculado | token de uso único/expiração, limite de tentativas e revogação |
| Parser ou áudio malicioso | saída estruturada validada; parser sem acesso direto a banco, ferramentas ou segredos |
| Download de mídia abusivo | adapter/hosts permitidos, bloqueio de endereços internos e limites de download |
| Arquivo malicioso | parser sem execução, limites descompactados, nomes internos aleatórios e armazenamento privado |
| Alteração concorrente | locks, expected_version e confirmação vinculada à proposta |
| Credencial em log | secret_ref, redaction e revisão de observabilidade |

## Identidade e autorização

Login inicial com tenant slug/email/senha, hash de senha com algoritmo dedicado e parâmetros configuráveis, limitação de tentativas, sessão curta e refresh rotativo armazenado apenas como hash. Revogar cadeia em reuso detectado de refresh. Cookies HttpOnly/Secure, SameSite apropriado à topologia e token CSRF em toda mutação de navegador; validar Origin e CORS por allowlist. Não guardar tokens de sessão em localStorage. Fixar biblioteca e parâmetros na implementação e validar a configuração antes de produção.

OWNER/ADMIN gerem membros, integrações e regras familiares. MEMBER cria/edita finanças visíveis da família; VIEWER consulta. Remoção de membro cancela suas pendências e revoga acesso/canal antes do próximo processamento. Nenhum request aceita papel/tenant autoritativos do cliente. Funções privilegiadas de login/roteamento são pequenas e não expõem leitura genérica fora de escopo.

## Segredos e processamento externo

Segredos em secret manager ou variáveis de implantação, referenciados por secret_ref. Não versionar .env real; fornecer .env.example sem valores válidos. TLS nas fronteiras externas. Provider de transcrição recebe apenas áudio necessário; parser recebe texto e contexto mínimo, evitando histórico financeiro completo. Metadados de provider e política de retenção são documentados para a instalação. Sem credencial configurada, falhar explicitamente ou usar adapter falso apenas no ambiente de teste.

## Retenção proposta e exclusão

Áudio temporário: até 1 h. Arquivo de importação bruto: 30 dias após conclusão, com opção de remoção antecipada; dados normalizados e origens preservam rastreabilidade. Texto/transcrições: 90 dias por padrão, configurável; após expiração, remover conteúdo de mensagens, pending.raw_message/transcription, evidências JSON e outgoing.text, preservando IDs, estados e dados financeiros confirmados. Campos de texto sujeitos a remoção devem aceitar null na migration correspondente, mesmo quando obrigatórios na criação.

Auditoria financeira e transações permanecem até política explícita de exclusão da família; não copiar mensagens brutas para audit log. Exportação/exclusão de família exige fluxo autenticado próprio com plano de backup e retenção, fora do CRUD comum. Backup proposto diário, criptografado, retenção 30 dias; registrar que remoção em produção só se completa nos backups conforme expiração. Testar restore isolado periodicamente.

## Observabilidade e abuso

Logs contêm IDs técnicos, duração, código de erro e correlation_id; telefone mascarado, sem tokens, áudio, transcrição ou corpo integral por padrão. Auditoria de alterações contém antes/depois estritamente financeiros, ator, origem e instante. Monitorar autenticação falha, fila parada, dead letters, divergências de conciliação e erros de autorização. Rate limits por integração, identidade e usuário sem depender apenas de IP.

## Implantação

Role de migration separada; API/worker sem bypass RLS; conexões com SET LOCAL e rollback garantido no pool. Cópias de produção não entram em testes. Endpoints de diagnóstico não expõem segredos. Retentativas externas têm teto e timeout. Restaurar backup e verificar isolamento são requisitos de liberação, assim como contrato de webhook na versão provisionada.
