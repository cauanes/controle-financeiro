CREATE TABLE import_templates (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 name text NOT NULL, format text NOT NULL, mapping jsonb NOT NULL, user_id uuid,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,name,version)
);
CREATE TABLE import_jobs (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 integration_id uuid, template_id uuid, file_hash text NOT NULL, file_ref text, format text NOT NULL, status text NOT NULL CHECK(status IN ('UPLOADED','PARSING','PREVIEW','PROCESSING','COMPLETED','PARTIAL','FAILED','CANCELLED')), target_account_id uuid, target_credit_card_id uuid, mapping jsonb NOT NULL DEFAULT '{}', counts jsonb NOT NULL DEFAULT '{}', errors jsonb NOT NULL DEFAULT '[]', confirmed_by uuid, confirmed_at timestamptz,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,integration_id) REFERENCES integrations(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,template_id) REFERENCES import_templates(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,target_account_id) REFERENCES accounts(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,target_credit_card_id) REFERENCES credit_cards(tenant_id,household_id,id) ON DELETE RESTRICT
);
CREATE TABLE import_rows (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 import_job_id uuid NOT NULL, row_number int NOT NULL, external_id text, fingerprint text NOT NULL, source_key text NOT NULL, normalized_data jsonb NOT NULL, validation_errors jsonb NOT NULL DEFAULT '[]', status text NOT NULL CHECK(status IN ('READY','INVALID','DUPLICATE','REVIEW','IMPORTED','RECONCILED','SKIPPED')), transaction_id uuid,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,import_job_id) REFERENCES import_jobs(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,transaction_id) REFERENCES transactions(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,import_job_id,row_number)
);
CREATE TABLE transaction_matches (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 transaction_id uuid NOT NULL, import_row_id uuid NOT NULL, score numeric(5,4) NOT NULL CHECK(score BETWEEN 0 AND 1), score_details jsonb NOT NULL, status text NOT NULL CHECK(status IN ('PROPOSED','ACCEPTED','REJECTED','STALE')), decided_by uuid, decided_at timestamptz, transaction_version int NOT NULL,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,transaction_id) REFERENCES transactions(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,import_row_id) REFERENCES import_rows(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,transaction_id,import_row_id)
);
CREATE UNIQUE INDEX accepted_row ON transaction_matches(tenant_id,household_id,import_row_id) WHERE status='ACCEPTED';
CREATE INDEX ON import_rows(tenant_id,household_id,fingerprint);
ALTER TABLE transaction_sources ADD FOREIGN KEY(tenant_id,household_id,import_row_id) REFERENCES import_rows(tenant_id,household_id,id);
ALTER TABLE transaction_sources ADD FOREIGN KEY(tenant_id,household_id,conversation_message_id) REFERENCES conversation_messages(tenant_id,household_id,id);
ALTER TABLE transaction_sources ADD FOREIGN KEY(tenant_id,household_id,integration_id) REFERENCES integrations(tenant_id,household_id,id);
