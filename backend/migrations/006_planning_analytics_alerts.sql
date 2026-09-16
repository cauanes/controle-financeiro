CREATE TABLE budgets (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 name text NOT NULL, period_start date NOT NULL, period_end date NOT NULL, currency text NOT NULL DEFAULT 'BRL' CHECK(currency='BRL'),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, CHECK(period_end>=period_start)
);
CREATE TABLE budget_categories (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 budget_id uuid NOT NULL, category_id uuid NOT NULL, amount numeric(18,2) NOT NULL CHECK(amount>=0),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,budget_id) REFERENCES budgets(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,category_id) REFERENCES categories(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,budget_id,category_id)
);
CREATE TABLE recurring_transactions (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 template jsonb NOT NULL, frequency text NOT NULL CHECK(frequency IN ('MONTHLY','WEEKLY','YEARLY')), interval_count int NOT NULL DEFAULT 1 CHECK(interval_count>0), start_date date NOT NULL, end_date date, next_due_date date NOT NULL, enabled boolean NOT NULL DEFAULT true, cost_class text NOT NULL DEFAULT 'UNKNOWN' CHECK(cost_class IN ('FIXED','VARIABLE','UNKNOWN')),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
);
ALTER TABLE transactions ADD FOREIGN KEY(tenant_id,household_id,recurring_transaction_id) REFERENCES recurring_transactions(tenant_id,household_id,id);
CREATE TABLE goals (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 name text NOT NULL, target_amount numeric(18,2) NOT NULL CHECK(target_amount>0), target_date date, status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','COMPLETED','ARCHIVED')),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE goal_contributions (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 goal_id uuid NOT NULL, amount numeric(18,2) NOT NULL CHECK(amount>0), contribution_date date NOT NULL, transaction_id uuid, direction text NOT NULL CHECK(direction IN ('ADD','WITHDRAW')),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,goal_id) REFERENCES goals(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,transaction_id) REFERENCES transactions(tenant_id,household_id,id) ON DELETE RESTRICT
);
CREATE TABLE assets (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 name text NOT NULL, kind text NOT NULL, valuation numeric(18,2) NOT NULL CHECK(valuation>=0), valuation_date date NOT NULL, linked_account_id uuid, archived_at timestamptz,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,linked_account_id) REFERENCES accounts(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,linked_account_id)
);
CREATE TABLE liabilities (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 name text NOT NULL, outstanding_amount numeric(18,2) NOT NULL CHECK(outstanding_amount>=0), valuation_date date NOT NULL, linked_credit_card_id uuid, due_date date, archived_at timestamptz,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,linked_credit_card_id) REFERENCES credit_cards(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,linked_credit_card_id)
);
CREATE TABLE financial_snapshots (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 snapshot_date date NOT NULL, metrics jsonb NOT NULL, calculation_version text NOT NULL, input_watermark timestamptz NOT NULL,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,snapshot_date,calculation_version)
);
CREATE TABLE alert_rules (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 kind text NOT NULL CHECK(kind IN ('BUDGET_THRESHOLD','DUE_SOON','BUDGET_FORECAST_EXCEEDED','LOW_PROJECTED_BALANCE')), config jsonb NOT NULL DEFAULT '{}', channel text NOT NULL CHECK(channel IN ('DASHBOARD','WHATSAPP')), enabled boolean NOT NULL DEFAULT true, quiet_hours jsonb NOT NULL DEFAULT '{"start":22,"end":8}', recipient_user_id uuid NOT NULL, opt_in boolean NOT NULL DEFAULT false,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,recipient_user_id) REFERENCES household_members(tenant_id,household_id,user_id)
);
CREATE TABLE alerts (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 alert_rule_id uuid NOT NULL, dedup_key text NOT NULL, payload jsonb NOT NULL, status text NOT NULL CHECK(status IN ('PENDING','SENT','FAILED','SUPPRESSED')), triggered_at timestamptz NOT NULL DEFAULT now(), sent_at timestamptz, attempts int NOT NULL DEFAULT 0,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,alert_rule_id) REFERENCES alert_rules(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,dedup_key)
);
