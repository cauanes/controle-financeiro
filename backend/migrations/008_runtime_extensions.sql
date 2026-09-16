ALTER TABLE recurring_transactions ADD COLUMN created_by uuid;
ALTER TABLE recurring_transactions ADD FOREIGN KEY(tenant_id,created_by) REFERENCES users(tenant_id,id);
GRANT DELETE ON budget_categories TO ff_app;
CREATE INDEX ON audit_logs(tenant_id,household_id,entity_id,occurred_at);
CREATE INDEX ON conversation_messages(tenant_id,household_id,session_id,sequence);
CREATE INDEX ON pending_financial_actions(tenant_id,household_id,status,expires_at);
