# Ingestão de áudio

## Contrato

```python
class TranscriptionProvider(Protocol):
    async def transcribe(self, audio: bytes, mime_type: str) -> TranscriptionResult: ...
```

TranscriptionResult: text, provider, model_version?, confidence?, duration_seconds?, language?, segments? (com incerteza, quando disponível). Confidence desconhecida permanece null. NormalizedText conserva input_kind=AUDIO e message_id. Regras de intenção e finanças são exatamente as do texto.

## Pipeline

1. Autenticar remetente e persistir mensagem com media_handle, sem baixar URL arbitrária do corpo.
2. Resolver mídia por adapter autenticado da integração. Permitir hosts/protocolos configurados, impedir redirects para destinos internos e limitar bytes durante download.
3. Validar assinatura real do arquivo, MIME suportado e duração; limites iniciais propostos: 15 MB e 5 min, configuráveis.
4. Usar arquivo temporário com permissão restrita; transcrever fora da transação SQL com timeout inicial de 90 s.
5. Persistir texto/metadados e marcar READY. Enfileirar sessão preservando sequência. Apagar temporário em finally; limpeza periódica cobre crash.
6. Silêncio, arquivo inválido, idioma não entendido ou erro permanente gera resposta para repetir ou enviar texto; não criar transação.

Não conservar áudio original por padrão. Temporários com TTL máximo de 1 h; nenhum backup de temporários. Transcrição segue a retenção de mensagens em [SECURITY.md](SECURITY.md). Debug de áudio só com consentimento explícito, acesso restrito e prazo configurado.

## Incerteza material

Baixa confiança em número, data, negação ou fonte requer confirmação específica. Não trocar “quinze” por “cinquenta” a partir do histórico. Parser pode normalizar números por extenso, mas evidência permanece vinculada à transcrição. Quando provider não oferece confiança por trecho, usar validação de consistência e confirmar interpretações materiais incertas; não inventar um score.

## Testes

Adapter falso retorna transcrições determinísticas; fixtures de áudio sintético cobrem pt-BR, ruído, silêncio, limite de tamanho e tipos inválidos. Teste de paridade compara candidato/estado/efeito financeiro de texto e áudio equivalente. Falha após transcrição e antes de processamento permite retry sem nova despesa. Não incluir voz real de familiares no repositório. Provider real é opcional e testado separadamente mediante configuração de implantação.
