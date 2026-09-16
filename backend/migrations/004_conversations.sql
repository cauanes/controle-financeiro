CREATE TABLE integrations (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 provider text NOT NULL CHECK(provider IN ('EVOLUTION','INTERNAL')), instance_key text NOT NULL, status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','DISCONNECTED')), config jsonb NOT NULL DEFAULT '{}', secret_ref text, last_synced_at timestamptz,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, UNIQUE(provider,instance_key)
);
CREATE TABLE channel_identities (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 integration_id uuid NOT NULL, user_id uuid NOT NULL, channel text NOT NULL, sender_key text NOT NULL, verified_at timestamptz NOT NULL DEFAULT now(), revoked_at timestamptz,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,integration_id) REFERENCES integrations(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,user_id) REFERENCES users(tenant_id,id)
);
CREATE UNIQUE INDEX identity_active ON channel_identities(integration_id,sender_key) WHERE revoked_at IS NULL;
CREATE TABLE conversation_sessions (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 integration_id uuid NOT NULL, channel_identity_id uuid NOT NULL, user_id uuid NOT NULL, channel text NOT NULL, status text NOT NULL DEFAULT 'ACTIVE', next_sequence bigint NOT NULL DEFAULT 1, last_activity_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,integration_id) REFERENCES integrations(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,channel_identity_id) REFERENCES channel_identities(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,channel_identity_id)
);
CREATE TABLE conversation_messages (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 session_id uuid NOT NULL, integration_id uuid NOT NULL, provider_message_id text NOT NULL, direction text NOT NULL DEFAULT 'IN', sequence bigint NOT NULL, kind text NOT NULL CHECK(kind IN ('TEXT','AUDIO')), raw_text text, normalized_text text, transcription_metadata jsonb, media jsonb, pending_action_id uuid, processing_status text NOT NULL DEFAULT 'READY' CHECK(processing_status IN ('RECEIVED','TRANSCRIBING','READY','PROCESSED','FAILED')), received_at timestamptz NOT NULL DEFAULT now(), processed_at timestamptz, response jsonb,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,session_id) REFERENCES conversation_sessions(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,integration_id) REFERENCES integrations(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(integration_id,provider_message_id,direction), UNIQUE(tenant_id,household_id,session_id,sequence)
);
CREATE TABLE pending_financial_actions (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 session_id uuid NOT NULL, user_id uuid NOT NULL, intent text NOT NULL, raw_message text, transcription text, extracted_data jsonb NOT NULL DEFAULT '{}', missing_fields jsonb NOT NULL DEFAULT '[]', ambiguous_fields jsonb NOT NULL DEFAULT '[]', confidence numeric(5,4) CHECK(confidence BETWEEN 0 AND 1), status text NOT NULL CHECK(status IN ('WAITING_INFORMATION','WAITING_CONFIRMATION','CONFIRMED','CANCELLED','EXPIRED')), expires_at timestamptz NOT NULL, confirmation_prompt_message_id uuid, target_transaction_id uuid, target_version int, execution_result jsonb, question text,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,session_id) REFERENCES conversation_sessions(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,target_transaction_id) REFERENCES transactions(tenant_id,household_id,id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX one_active_action ON pending_financial_actions(tenant_id,household_id,session_id) WHERE status IN ('WAITING_INFORMATION','WAITING_CONFIRMATION');
ALTER TABLE conversation_messages ADD FOREIGN KEY(tenant_id,household_id,pending_action_id) REFERENCES pending_financial_actions(tenant_id,household_id,id);
CREATE TABLE outgoing_messages (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 session_id uuid, integration_id uuid NOT NULL, recipient_identity_id uuid NOT NULL, client_message_id uuid NOT NULL UNIQUE, text text, status text NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','SENDING','SENT','FAILED','UNKNOWN')), provider_message_id text, attempts int NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(), sent_at timestamptz,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,session_id) REFERENCES conversation_sessions(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,integration_id) REFERENCES integrations(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,recipient_identity_id) REFERENCES channel_identities(tenant_id,household_id,id) ON DELETE RESTRICT
);
CREATE TABLE webhook_receipts (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 integration_id uuid NOT NULL, provider_event_key text NOT NULL, payload_hash text NOT NULL, message_id uuid, status text NOT NULL, received_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,integration_id) REFERENCES integrations(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,message_id) REFERENCES conversation_messages(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(integration_id,provider_event_key)
);
CREATE TABLE channel_link_tokens (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 integration_id uuid NOT NULL, user_id uuid NOT NULL, token_hash text NOT NULL UNIQUE, expires_at timestamptz NOT NULL, used_at timestamptz, attempts int NOT NULL DEFAULT 0 CHECK(attempts>=0),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,integration_id) REFERENCES integrations(tenant_id,household_id,id) ON DELETE RESTRICT
);
