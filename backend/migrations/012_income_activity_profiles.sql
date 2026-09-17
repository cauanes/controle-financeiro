CREATE TABLE income_activity_profiles (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 user_id uuid NOT NULL, category_id uuid NOT NULL, keywords text[] NOT NULL DEFAULT '{}',
 UNIQUE(tenant_id,household_id,id), UNIQUE(tenant_id,household_id,user_id,category_id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT,
 FOREIGN KEY(tenant_id,household_id,user_id) REFERENCES household_members(tenant_id,household_id,user_id),
 FOREIGN KEY(tenant_id,household_id,category_id) REFERENCES categories(tenant_id,household_id,id)
);
ALTER TABLE income_activity_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE income_activity_profiles FORCE ROW LEVEL SECURITY;
CREATE POLICY scoped ON income_activity_profiles USING (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid
) WITH CHECK (
 tenant_id=nullif(current_setting('app.tenant_id',true),'')::uuid AND
 household_id=nullif(current_setting('app.household_id',true),'')::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON income_activity_profiles TO ff_app;
