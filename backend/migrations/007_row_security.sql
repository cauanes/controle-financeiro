DO $$ BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='ff_app') THEN CREATE ROLE ff_app NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO ff_app;
ALTER TABLE household_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE household_members FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON household_members USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON household_members TO ff_app;
ALTER TABLE member_invites ENABLE ROW LEVEL SECURITY;
ALTER TABLE member_invites FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON member_invites USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON member_invites TO ff_app;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON audit_logs USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON audit_logs TO ff_app;
ALTER TABLE outbox_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE outbox_events FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON outbox_events USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON outbox_events TO ff_app;
ALTER TABLE processed_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE processed_events FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON processed_events USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON processed_events TO ff_app;
ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON idempotency_keys USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON idempotency_keys TO ff_app;
ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounts FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON accounts USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON accounts TO ff_app;
ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE categories FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON categories USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON categories TO ff_app;
ALTER TABLE merchants ENABLE ROW LEVEL SECURITY;
ALTER TABLE merchants FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON merchants USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON merchants TO ff_app;
ALTER TABLE credit_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_cards FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON credit_cards USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON credit_cards TO ff_app;
ALTER TABLE credit_card_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_card_invoices FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON credit_card_invoices USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON credit_card_invoices TO ff_app;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON transactions USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON transactions TO ff_app;
ALTER TABLE transaction_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE transaction_sources FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON transaction_sources USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON transaction_sources TO ff_app;
ALTER TABLE invoice_payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_payments FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON invoice_payments USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON invoice_payments TO ff_app;
ALTER TABLE category_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE category_rules FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON category_rules USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON category_rules TO ff_app;
ALTER TABLE merchant_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE merchant_rules FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON merchant_rules USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON merchant_rules TO ff_app;
ALTER TABLE user_financial_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_financial_preferences FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON user_financial_preferences USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON user_financial_preferences TO ff_app;
ALTER TABLE integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE integrations FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON integrations USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON integrations TO ff_app;
ALTER TABLE channel_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_identities FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON channel_identities USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON channel_identities TO ff_app;
ALTER TABLE conversation_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON conversation_sessions USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON conversation_sessions TO ff_app;
ALTER TABLE conversation_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_messages FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON conversation_messages USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON conversation_messages TO ff_app;
ALTER TABLE pending_financial_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_financial_actions FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON pending_financial_actions USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON pending_financial_actions TO ff_app;
ALTER TABLE outgoing_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE outgoing_messages FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON outgoing_messages USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON outgoing_messages TO ff_app;
ALTER TABLE webhook_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhook_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON webhook_receipts USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON webhook_receipts TO ff_app;
ALTER TABLE channel_link_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE channel_link_tokens FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON channel_link_tokens USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON channel_link_tokens TO ff_app;
ALTER TABLE import_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_templates FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON import_templates USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON import_templates TO ff_app;
ALTER TABLE import_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_jobs FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON import_jobs USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON import_jobs TO ff_app;
ALTER TABLE import_rows ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_rows FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON import_rows USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON import_rows TO ff_app;
ALTER TABLE transaction_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE transaction_matches FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON transaction_matches USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON transaction_matches TO ff_app;
ALTER TABLE budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE budgets FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON budgets USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON budgets TO ff_app;
ALTER TABLE budget_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_categories FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON budget_categories USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON budget_categories TO ff_app;
ALTER TABLE recurring_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE recurring_transactions FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON recurring_transactions USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON recurring_transactions TO ff_app;
ALTER TABLE goals ENABLE ROW LEVEL SECURITY;
ALTER TABLE goals FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON goals USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON goals TO ff_app;
ALTER TABLE goal_contributions ENABLE ROW LEVEL SECURITY;
ALTER TABLE goal_contributions FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON goal_contributions USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON goal_contributions TO ff_app;
ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE assets FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON assets USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON assets TO ff_app;
ALTER TABLE liabilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE liabilities FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON liabilities USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON liabilities TO ff_app;
ALTER TABLE financial_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE financial_snapshots FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON financial_snapshots USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON financial_snapshots TO ff_app;
ALTER TABLE alert_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_rules FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON alert_rules USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON alert_rules TO ff_app;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON alerts USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE ON alerts TO ff_app;
REVOKE UPDATE ON audit_logs FROM ff_app;
ALTER TABLE users ENABLE ROW LEVEL SECURITY; ALTER TABLE users FORCE ROW LEVEL SECURITY;
CREATE POLICY identity_scope ON users USING (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid) WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid);
GRANT SELECT,INSERT,UPDATE ON users TO ff_app;
ALTER TABLE households ENABLE ROW LEVEL SECURITY; ALTER TABLE households FORCE ROW LEVEL SECURITY;
CREATE POLICY identity_scope ON households USING (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND id=nullif(current_setting('app.household_id',true),'')::uuid) WITH CHECK (tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT,INSERT,UPDATE ON households TO ff_app;

CREATE FUNCTION login_lookup(slug_arg text,email_arg text) RETURNS TABLE(id uuid,tenant_id uuid,password_hash text)
LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT u.id,u.tenant_id,u.password_hash FROM users u JOIN tenants t ON t.id=u.tenant_id
 WHERE t.slug=slug_arg AND u.email=email_arg AND u.status='ACTIVE' AND t.status='ACTIVE' $$;
CREATE FUNCTION throttle_login(key_arg text) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE n int; BEGIN
 INSERT INTO login_attempts(key,attempts,window_start) VALUES(key_arg,1,now())
 ON CONFLICT(key) DO UPDATE SET attempts=CASE WHEN login_attempts.window_start<now()-interval '15 minutes' THEN 1 ELSE login_attempts.attempts+1 END,
 window_start=CASE WHEN login_attempts.window_start<now()-interval '15 minutes' THEN now() ELSE login_attempts.window_start END RETURNING attempts INTO n;
 RETURN n<=10; END $$;
CREATE FUNCTION new_session(id_arg uuid,t uuid,u uuid,a text,r text,c text,f uuid) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
 INSERT INTO auth_sessions(id,tenant_id,user_id,access_hash,refresh_hash,csrf_hash,family_id,access_expires_at,expires_at)
 VALUES(id_arg,t,u,a,r,c,f,now()+interval '30 minutes',now()+interval '30 days') $$;
CREATE FUNCTION resolve_session(hash_arg text) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT jsonb_build_object('id',s.id,'tenant_id',s.tenant_id,'user_id',s.user_id,'csrf_hash',s.csrf_hash,
 'display_name',u.display_name,'email',u.email,'households',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',h.id,'name',h.name,'timezone',h.timezone,'role',m.role))
 FROM household_members m JOIN households h ON h.id=m.household_id WHERE m.user_id=u.id AND m.tenant_id=u.tenant_id AND m.status='ACTIVE'),'[]'::jsonb))
 FROM auth_sessions s JOIN users u ON u.id=s.user_id JOIN tenants t ON t.id=s.tenant_id
 WHERE s.access_hash=hash_arg AND s.revoked_at IS NULL AND s.access_expires_at>now() AND u.status='ACTIVE' AND t.status='ACTIVE' $$;
CREATE FUNCTION rotate_session(old_hash text,new_id uuid,a text,r text,c text) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS $$
DECLARE s auth_sessions%ROWTYPE; BEGIN
 SELECT * INTO s FROM auth_sessions WHERE refresh_hash=old_hash FOR UPDATE;
 IF NOT FOUND THEN RETURN false; END IF;
 IF s.revoked_at IS NOT NULL THEN UPDATE auth_sessions SET revoked_at=now() WHERE family_id=s.family_id; RETURN false; END IF;
 IF s.expires_at<=now() THEN RETURN false; END IF;
 IF NOT EXISTS(SELECT 1 FROM users u JOIN tenants t ON t.id=u.tenant_id WHERE u.id=s.user_id AND u.status='ACTIVE' AND t.status='ACTIVE') THEN RETURN false; END IF;
 UPDATE auth_sessions SET revoked_at=now() WHERE id=s.id;
 PERFORM new_session(new_id,s.tenant_id,s.user_id,a,r,c,s.family_id); RETURN true; END $$;
CREATE FUNCTION revoke_session(hash_arg text) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
 UPDATE auth_sessions SET revoked_at=now() WHERE family_id IN (SELECT family_id FROM auth_sessions WHERE access_hash=hash_arg) $$;
CREATE FUNCTION integration_lookup(instance_arg text) RETURNS jsonb LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT to_jsonb(i) FROM integrations i WHERE provider='EVOLUTION' AND instance_key=instance_arg AND status='ACTIVE' $$;
CREATE FUNCTION work_scopes() RETURNS TABLE(tenant_id uuid,household_id uuid) LANGUAGE sql SECURITY DEFINER SET search_path=public,pg_temp AS $$
 SELECT h.tenant_id,h.id FROM households h JOIN tenants t ON t.id=h.tenant_id WHERE t.status='ACTIVE' $$;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO ff_app;
