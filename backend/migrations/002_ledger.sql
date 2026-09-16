CREATE TABLE accounts (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 name text NOT NULL, kind text NOT NULL CHECK(kind IN ('CHECKING','SAVINGS','CASH','INVESTMENT')), currency text NOT NULL DEFAULT 'BRL' CHECK(currency='BRL'), opening_balance numeric(18,2) NOT NULL DEFAULT 0, opening_balance_date date NOT NULL, archived_at timestamptz, is_emergency_reserve boolean NOT NULL DEFAULT false,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX account_name_active ON accounts(tenant_id,household_id,lower(name)) WHERE archived_at IS NULL;
CREATE TABLE categories (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 name text NOT NULL, kind text NOT NULL CHECK(kind IN ('EXPENSE','INCOME')), parent_id uuid, archived_at timestamptz, is_essential boolean,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,parent_id) REFERENCES categories(tenant_id,household_id,id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX category_root_name ON categories(tenant_id,household_id,kind,lower(name)) WHERE parent_id IS NULL AND archived_at IS NULL;
CREATE UNIQUE INDEX category_child_name ON categories(tenant_id,household_id,parent_id,lower(name)) WHERE parent_id IS NOT NULL AND archived_at IS NULL;
CREATE TABLE merchants (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 name text NOT NULL, normalized_name text NOT NULL, archived_at timestamptz,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,normalized_name)
);
CREATE TABLE credit_cards (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 name text NOT NULL, issuer text, limit_amount numeric(18,2) CHECK(limit_amount>=0), closing_day int NOT NULL CHECK(closing_day BETWEEN 1 AND 31), due_day int NOT NULL CHECK(due_day BETWEEN 1 AND 31), default_payment_account_id uuid, archived_at timestamptz,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,default_payment_account_id) REFERENCES accounts(tenant_id,household_id,id) ON DELETE RESTRICT
);
CREATE TABLE credit_card_invoices (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 credit_card_id uuid NOT NULL, period_start date NOT NULL, closing_date date NOT NULL, due_date date NOT NULL, status text NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED','PARTIALLY_PAID','PAID')),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,credit_card_id) REFERENCES credit_cards(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,credit_card_id,closing_date), UNIQUE(tenant_id,household_id,credit_card_id,id), CHECK(period_start<=closing_date AND closing_date<due_date)
);
CREATE TABLE transactions (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 type text NOT NULL CHECK(type IN ('EXPENSE','INCOME','TRANSFER')), subtype text CHECK(subtype='INVOICE_PAYMENT'),
 status text NOT NULL CHECK(status IN ('PLANNED','POSTED','VOIDED')), amount numeric(18,2) NOT NULL CHECK(amount>0),
 currency text NOT NULL DEFAULT 'BRL' CHECK(currency='BRL'), transaction_date date NOT NULL, competence_date date NOT NULL,
 due_date date, description text NOT NULL, account_id uuid, destination_account_id uuid, credit_card_id uuid, invoice_id uuid,
 category_id uuid, merchant_id uuid, responsible_user_id uuid, actor_user_id uuid NOT NULL,
 notes text, tags jsonb NOT NULL DEFAULT '[]', installment_group_id uuid, installment_number int, installment_count int,
 recurring_transaction_id uuid, occurrence_date date, reconciliation_status text NOT NULL DEFAULT 'UNRECONCILED'
 CHECK(reconciliation_status IN ('UNRECONCILED','RECONCILED','NEEDS_REVIEW')), voided_at timestamptz, void_reason text,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,account_id) REFERENCES accounts(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,destination_account_id) REFERENCES accounts(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,credit_card_id) REFERENCES credit_cards(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,invoice_id) REFERENCES credit_card_invoices(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,category_id) REFERENCES categories(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,merchant_id) REFERENCES merchants(tenant_id,household_id,id) ON DELETE RESTRICT
, CHECK((type='EXPENSE' AND subtype IS NULL AND destination_account_id IS NULL AND
 ((account_id IS NOT NULL AND credit_card_id IS NULL AND invoice_id IS NULL) OR
 (account_id IS NULL AND credit_card_id IS NOT NULL AND invoice_id IS NOT NULL))) OR
 (type='INCOME' AND subtype IS NULL AND account_id IS NOT NULL AND destination_account_id IS NULL AND credit_card_id IS NULL AND invoice_id IS NULL) OR
 (type='TRANSFER' AND account_id IS NOT NULL AND credit_card_id IS NULL AND category_id IS NULL AND
 ((subtype='INVOICE_PAYMENT' AND invoice_id IS NOT NULL AND destination_account_id IS NULL) OR
 (subtype IS NULL AND invoice_id IS NULL AND destination_account_id IS NOT NULL AND account_id<>destination_account_id)))),
 CHECK(status<>'VOIDED' OR (voided_at IS NOT NULL AND void_reason IS NOT NULL)),
 CHECK((installment_group_id IS NULL AND installment_number IS NULL AND installment_count IS NULL) OR
 (installment_group_id IS NOT NULL AND installment_number IS NOT NULL AND installment_count IS NOT NULL AND installment_number BETWEEN 1 AND installment_count)),
 UNIQUE(tenant_id,household_id,installment_group_id,installment_number),
 UNIQUE(tenant_id,household_id,recurring_transaction_id,occurrence_date),
 FOREIGN KEY(tenant_id,household_id,credit_card_id,invoice_id) REFERENCES credit_card_invoices(tenant_id,household_id,credit_card_id,id),
 FOREIGN KEY(tenant_id,actor_user_id) REFERENCES users(tenant_id,id),
 FOREIGN KEY(tenant_id,household_id,responsible_user_id) REFERENCES household_members(tenant_id,household_id,user_id)
);
CREATE TABLE transaction_sources (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 transaction_id uuid NOT NULL, source_type text NOT NULL CHECK(source_type IN ('MANUAL','WHATSAPP','OFX','CSV','XLSX','PROVIDER','CONVERSATION')), source_key text NOT NULL, integration_id uuid, external_id text, import_row_id uuid, conversation_message_id uuid, evidence jsonb NOT NULL DEFAULT '{}', observed_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,transaction_id) REFERENCES transactions(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,source_type,source_key)
);
CREATE TABLE invoice_payments (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 invoice_id uuid NOT NULL, transaction_id uuid NOT NULL, amount numeric(18,2) NOT NULL CHECK(amount>0),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,invoice_id) REFERENCES credit_card_invoices(tenant_id,household_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,transaction_id) REFERENCES transactions(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,transaction_id)
);
CREATE INDEX ON transactions(tenant_id,household_id,transaction_date DESC,id);
CREATE INDEX ON transactions(tenant_id,household_id,competence_date,type,status);
CREATE INDEX ON transactions(tenant_id,household_id,account_id,transaction_date);
CREATE INDEX ON transactions(tenant_id,household_id,credit_card_id,invoice_id);
CREATE INDEX ON transactions(tenant_id,household_id,category_id,competence_date);
