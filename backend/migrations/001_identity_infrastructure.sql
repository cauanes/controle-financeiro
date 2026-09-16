CREATE TABLE tenants (
 id uuid PRIMARY KEY, slug text NOT NULL UNIQUE, name text NOT NULL,
 status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','SUSPENDED')),
 created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE users (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenants(id), email text NOT NULL,
 display_name text NOT NULL, password_hash text NOT NULL, status text NOT NULL DEFAULT 'ACTIVE',
 created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(tenant_id,id), UNIQUE(tenant_id,email));
CREATE TABLE households (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenants(id), name text NOT NULL,
 currency text NOT NULL DEFAULT 'BRL' CHECK(currency='BRL'), timezone text NOT NULL DEFAULT 'America/Sao_Paulo',
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1, UNIQUE(tenant_id,id));
CREATE TABLE auth_sessions (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, user_id uuid NOT NULL,
 access_hash text NOT NULL UNIQUE, refresh_hash text NOT NULL UNIQUE, csrf_hash text NOT NULL,
 family_id uuid NOT NULL, access_expires_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
 revoked_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
 FOREIGN KEY(tenant_id,user_id) REFERENCES users(tenant_id,id));
CREATE TABLE login_attempts (key text PRIMARY KEY, attempts int NOT NULL, window_start timestamptz NOT NULL);
CREATE TABLE household_members (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 user_id uuid NOT NULL, role text NOT NULL CHECK(role IN ('OWNER','ADMIN','MEMBER','VIEWER')), status text NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','REVOKED')),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,user_id), FOREIGN KEY(tenant_id,user_id) REFERENCES users(tenant_id,id)
);
CREATE TABLE member_invites (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 email text NOT NULL, role text NOT NULL CHECK(role IN ('ADMIN','MEMBER','VIEWER')), token_hash text NOT NULL UNIQUE, expires_at timestamptz NOT NULL, accepted_at timestamptz, invited_by uuid NOT NULL,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,invited_by) REFERENCES users(tenant_id,id)
);
CREATE TABLE audit_logs (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 actor_user_id uuid, action text NOT NULL, entity_type text NOT NULL, entity_id uuid NOT NULL, before jsonb, after jsonb, origin text NOT NULL, correlation_id uuid NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE outbox_events (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 event_type text NOT NULL, aggregate_id uuid NOT NULL, payload jsonb NOT NULL DEFAULT '{}', available_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz, attempts int NOT NULL DEFAULT 0, last_error text,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
);
CREATE TABLE processed_events (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 consumer text NOT NULL, event_id uuid NOT NULL, processed_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, FOREIGN KEY(tenant_id,household_id,event_id) REFERENCES outbox_events(tenant_id,household_id,id) ON DELETE RESTRICT
, UNIQUE(consumer,event_id)
);
CREATE TABLE idempotency_keys (
 id uuid PRIMARY KEY, tenant_id uuid NOT NULL, household_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
 version integer NOT NULL DEFAULT 1 CHECK(version>0),
 user_id uuid NOT NULL, route text NOT NULL, key text NOT NULL, request_hash text NOT NULL, response_body jsonb NOT NULL, expires_at timestamptz NOT NULL,
 UNIQUE(tenant_id,household_id,id),
 FOREIGN KEY(tenant_id,household_id) REFERENCES households(tenant_id,id) ON DELETE RESTRICT
, UNIQUE(tenant_id,household_id,user_id,route,key)
);
CREATE INDEX outbox_pending ON outbox_events(available_at) WHERE completed_at IS NULL;
