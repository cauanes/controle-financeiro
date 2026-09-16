CREATE TABLE category_rules (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 user_id uuid, pattern text NOT NULL, match_type text NOT NULL CHECK(match_type IN ('EXACT','CONTAINS')), category_id uuid NOT NULL, priority int NOT NULL DEFAULT 0, confidence numeric(5,4) CHECK(confidence BETWEEN 0 AND 1), enabled boolean NOT NULL DEFAULT true,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,category_id) REFERENCES categories(tenant_id,household_id,id) ON DELETE RESTRICT
);
CREATE TABLE merchant_rules (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 pattern text NOT NULL, match_type text NOT NULL CHECK(match_type IN ('EXACT','CONTAINS')), merchant_id uuid NOT NULL, priority int NOT NULL DEFAULT 0, enabled boolean NOT NULL DEFAULT true,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,merchant_id) REFERENCES merchants(tenant_id,household_id,id) ON DELETE RESTRICT
);
CREATE TABLE user_financial_preferences (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 user_id uuid NOT NULL, context_key text NOT NULL, suggested_fields jsonb NOT NULL, observations int NOT NULL DEFAULT 0, confidence numeric(5,4) CHECK(confidence BETWEEN 0 AND 1), enabled boolean NOT NULL DEFAULT true, last_confirmed_at timestamptz,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,user_id,context_key)
);
