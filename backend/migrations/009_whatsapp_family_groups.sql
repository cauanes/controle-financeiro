CREATE TABLE whatsapp_groups (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 integration_id uuid NOT NULL, group_jid text NOT NULL, subject text NOT NULL,
 status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','DISCONNECTED')),
 created_by uuid NOT NULL, invite_url text,
 UNIQUE(tenant_id,household_id,id), UNIQUE(integration_id,group_jid),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id),
 FOREIGN KEY(tenant_id,household_id,integration_id) REFERENCES integrations(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,created_by) REFERENCES users(tenant_id,id)
);
DO $$
DECLARE constraint_name text;
BEGIN
 SELECT conname INTO constraint_name FROM pg_constraint
 WHERE conrelid = 'conversation_sessions'::regclass AND contype = 'u'
 AND pg_get_constraintdef(oid) LIKE '%channel_identity_id%' LIMIT 1;
 IF constraint_name IS NULL THEN RAISE EXCEPTION 'conversation identity unique constraint missing'; END IF;
 EXECUTE format('ALTER TABLE conversation_sessions DROP CONSTRAINT %I', constraint_name);
END $$;
ALTER TABLE conversation_sessions ADD COLUMN whatsapp_group_id uuid;
ALTER TABLE conversation_sessions ADD FOREIGN KEY(tenant_id,household_id,whatsapp_group_id) REFERENCES whatsapp_groups(tenant_id,household_id,id);
CREATE UNIQUE INDEX conversation_private_identity ON conversation_sessions(tenant_id,household_id,channel_identity_id) WHERE whatsapp_group_id IS NULL;
CREATE UNIQUE INDEX conversation_group_identity ON conversation_sessions(tenant_id,household_id,channel_identity_id,whatsapp_group_id) WHERE whatsapp_group_id IS NOT NULL;
ALTER TABLE whatsapp_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_groups FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON whatsapp_groups USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND household_id=nullif(current_setting('app.household_id',true),'')::uuid
);
GRANT SELECT,INSERT,UPDATE ON whatsapp_groups TO ff_app;
