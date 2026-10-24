-- The catalogue of laboratories (feature electron, DEC-058): applied by cloud/tools/migrate.py as the owner role.
-- Every table has row-level security; the service connects as the non-privileged role app_api and sets app.account_id per
-- connection (cloud_account()). Cross-table checks are SECURITY DEFINER functions owned by the migration role, so that a policy
-- never consults another policy. The owner role is used by migrations and the live tests' cleanup only.

CREATE TABLE IF NOT EXISTS lab (
    id             uuid PRIMARY KEY,
    owner_id       text NOT NULL,
    origin_lab_id  uuid NOT NULL UNIQUE,
    name           text NOT NULL,
    author         text NOT NULL,
    description    text,
    url            text,
    visibility     text NOT NULL CHECK (visibility IN ('public', 'private')),
    created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS lab_owner ON lab(owner_id);

CREATE TABLE IF NOT EXISTS release (
    id                   uuid PRIMARY KEY,
    lab_id               uuid NOT NULL REFERENCES lab(id),
    number               integer NOT NULL CHECK (number >= 1),
    content_sha256       text NOT NULL,
    file_sha256          text NOT NULL,
    manifest             jsonb NOT NULL,
    lab_record           jsonb NOT NULL,
    byte_size            bigint NOT NULL,
    chunk_count          integer NOT NULL,
    chunk_bytes          integer NOT NULL,
    counts               jsonb NOT NULL,
    terms                text NOT NULL,
    previous_release_id  uuid REFERENCES release(id),
    published_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (lab_id, number)
);

CREATE TABLE IF NOT EXISTS chunk (
    release_id  uuid NOT NULL REFERENCES release(id),
    n           integer NOT NULL CHECK (n >= 0),
    bytes       bytea NOT NULL,
    PRIMARY KEY (release_id, n)
);

CREATE TABLE IF NOT EXISTS publication (
    id                            uuid PRIMARY KEY,
    lab_id                        uuid NOT NULL REFERENCES lab(id),
    owner_id                      text NOT NULL,
    idempotency_key               text NOT NULL,
    release_id                    uuid NOT NULL UNIQUE,
    release_number                integer NOT NULL,
    expected_previous_release_id  uuid,
    file_sha256                   text,                 -- declared at finalize, once the file exists
    byte_size                     bigint,
    chunk_count                   integer,
    chunk_bytes                   integer NOT NULL,
    state                        text NOT NULL CHECK (state IN ('uploading', 'finalized', 'failed', 'expired')),
    failure                       text,
    created_at                    timestamptz NOT NULL DEFAULT now(),
    expires_at                    timestamptz NOT NULL,
    UNIQUE (owner_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS publication_chunk (
    publication_id  uuid NOT NULL REFERENCES publication(id) ON DELETE CASCADE,
    n               integer NOT NULL CHECK (n >= 0),
    bytes           bytea NOT NULL,
    PRIMARY KEY (publication_id, n)
);

CREATE TABLE IF NOT EXISTS release_withdrawal (
    id                      bigserial PRIMARY KEY,
    release_id              uuid NOT NULL REFERENCES release(id),
    target_kind             text NOT NULL,
    target_id               text NOT NULL,
    reason                  text NOT NULL,
    replacement_release_id  uuid,
    created_at              timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS release_withdrawal_release ON release_withdrawal(release_id);

CREATE TABLE IF NOT EXISTS invitation (
    id           uuid PRIMARY KEY,
    lab_id       uuid NOT NULL REFERENCES lab(id),
    token_hash   text NOT NULL UNIQUE,
    created_by   text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    accepted_by  text,
    accepted_at  timestamptz,
    revoked_at   timestamptz
);

CREATE TABLE IF NOT EXISTS membership (
    lab_id          uuid NOT NULL REFERENCES lab(id),
    account_id      text NOT NULL,
    via_invitation  uuid REFERENCES invitation(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (lab_id, account_id)
);

CREATE TABLE IF NOT EXISTS idempotency (
    account_id  text NOT NULL,
    key         text NOT NULL,
    operation   text NOT NULL,
    status      integer NOT NULL,
    response    jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, key, operation)
);

-- the account of the request, '' when none
CREATE OR REPLACE FUNCTION cloud_account() RETURNS text LANGUAGE sql STABLE AS
$$ SELECT COALESCE(NULLIF(current_setting('app.account_id', true), ''), '') $$;

CREATE OR REPLACE FUNCTION cloud_owns_lab(the_lab uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT EXISTS (SELECT 1 FROM lab WHERE id = the_lab AND owner_id = cloud_account() AND cloud_account() <> '') $$;

CREATE OR REPLACE FUNCTION cloud_is_member(the_lab uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT EXISTS (SELECT 1 FROM membership WHERE lab_id = the_lab AND account_id = cloud_account() AND cloud_account() <> '') $$;

CREATE OR REPLACE FUNCTION cloud_can_read_lab(the_lab uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT EXISTS (SELECT 1 FROM lab WHERE id = the_lab AND (visibility = 'public' OR owner_id = cloud_account() AND cloud_account() <> ''))
          OR cloud_is_member(the_lab) $$;

CREATE OR REPLACE FUNCTION cloud_lab_of_release(the_release uuid) RETURNS uuid LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT lab_id FROM release WHERE id = the_release $$;

CREATE OR REPLACE FUNCTION cloud_owns_publication(the_publication uuid) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT EXISTS (SELECT 1 FROM publication WHERE id = the_publication AND owner_id = cloud_account() AND cloud_account() <> '') $$;

-- Accepting an invitation is the one write a non-owner makes on a laboratory it cannot see yet: one function with the one-time rules.
CREATE OR REPLACE FUNCTION cloud_accept_invitation(the_hash text, the_account text)
RETURNS TABLE (lab_id uuid, account_id text, via_invitation uuid, created_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE inv invitation%ROWTYPE;
BEGIN
    IF the_account IS NULL OR the_account = '' THEN RAISE EXCEPTION 'unauthorized: sign in to accept an invitation'; END IF;
    SELECT * INTO inv FROM invitation WHERE token_hash = the_hash FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'not_found: there is no such invitation'; END IF;
    IF inv.revoked_at IS NOT NULL THEN RAISE EXCEPTION 'revoked: the invitation was revoked'; END IF;
    IF inv.expires_at < now() THEN RAISE EXCEPTION 'expired: the invitation expired'; END IF;
    IF inv.accepted_by IS NOT NULL AND inv.accepted_by <> the_account THEN RAISE EXCEPTION 'used: the invitation was used by someone else'; END IF;
    UPDATE invitation SET accepted_by = the_account, accepted_at = COALESCE(accepted_at, now()) WHERE id = inv.id;
    INSERT INTO membership(lab_id, account_id, via_invitation) VALUES (inv.lab_id, the_account, inv.id) ON CONFLICT DO NOTHING;
    RETURN QUERY SELECT m.lab_id, m.account_id, m.via_invitation, m.created_at FROM membership m WHERE m.lab_id = inv.lab_id AND m.account_id = the_account;
END $$;

-- policies -------------------------------------------------------------------------------------------------------------------
ALTER TABLE lab ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS lab_read ON lab;
-- on the row itself, not through cloud_can_read_lab: INSERT … RETURNING applies the SELECT policy to the new row, which a STABLE
-- function (snapshot of the statement's start) would not see yet
CREATE POLICY lab_read ON lab FOR SELECT
    USING (visibility = 'public' OR (owner_id = cloud_account() AND cloud_account() <> '') OR cloud_is_member(id));
DROP POLICY IF EXISTS lab_create ON lab;
CREATE POLICY lab_create ON lab FOR INSERT WITH CHECK (owner_id = cloud_account() AND cloud_account() <> '');
DROP POLICY IF EXISTS lab_change ON lab;
CREATE POLICY lab_change ON lab FOR UPDATE USING (owner_id = cloud_account() AND cloud_account() <> '');

ALTER TABLE release ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS release_read ON release;
CREATE POLICY release_read ON release FOR SELECT USING (cloud_can_read_lab(lab_id));
DROP POLICY IF EXISTS release_create ON release;
CREATE POLICY release_create ON release FOR INSERT WITH CHECK (cloud_owns_lab(lab_id));

ALTER TABLE chunk ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS chunk_read ON chunk;
CREATE POLICY chunk_read ON chunk FOR SELECT USING (cloud_can_read_lab(cloud_lab_of_release(release_id)));
DROP POLICY IF EXISTS chunk_create ON chunk;
CREATE POLICY chunk_create ON chunk FOR INSERT WITH CHECK (cloud_owns_lab(cloud_lab_of_release(release_id)));

ALTER TABLE release_withdrawal ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS withdrawal_read ON release_withdrawal;
CREATE POLICY withdrawal_read ON release_withdrawal FOR SELECT USING (cloud_can_read_lab(cloud_lab_of_release(release_id)));
DROP POLICY IF EXISTS withdrawal_create ON release_withdrawal;
CREATE POLICY withdrawal_create ON release_withdrawal FOR INSERT WITH CHECK (cloud_owns_lab(cloud_lab_of_release(release_id)));

ALTER TABLE publication ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS publication_owner ON publication;
CREATE POLICY publication_owner ON publication USING (owner_id = cloud_account() AND cloud_account() <> '')
    WITH CHECK (owner_id = cloud_account() AND cloud_account() <> '' AND cloud_owns_lab(lab_id));

ALTER TABLE publication_chunk ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS publication_chunk_owner ON publication_chunk;
CREATE POLICY publication_chunk_owner ON publication_chunk USING (cloud_owns_publication(publication_id)) WITH CHECK (cloud_owns_publication(publication_id));

ALTER TABLE invitation ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS invitation_owner ON invitation;
CREATE POLICY invitation_owner ON invitation USING (cloud_owns_lab(lab_id)) WITH CHECK (cloud_owns_lab(lab_id));

ALTER TABLE membership ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS membership_read ON membership;
CREATE POLICY membership_read ON membership FOR SELECT USING ((account_id = cloud_account() AND cloud_account() <> '') OR cloud_owns_lab(lab_id));
DROP POLICY IF EXISTS membership_remove ON membership;
CREATE POLICY membership_remove ON membership FOR DELETE USING (cloud_owns_lab(lab_id));

ALTER TABLE idempotency ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS idempotency_owner ON idempotency;
CREATE POLICY idempotency_owner ON idempotency USING (account_id = cloud_account() AND cloud_account() <> '')
    WITH CHECK (account_id = cloud_account() AND cloud_account() <> '');

-- the service's role: no password here (cloud/tools/app_api_password.py sets one), only the grants the routes need ----------------
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_api') THEN CREATE ROLE app_api LOGIN NOINHERIT; END IF;
END $$;
GRANT USAGE ON SCHEMA public TO app_api;
GRANT SELECT, INSERT, UPDATE ON lab TO app_api;
GRANT SELECT, INSERT ON release, chunk, release_withdrawal TO app_api;
GRANT SELECT, INSERT, UPDATE ON publication TO app_api;
GRANT SELECT, INSERT, UPDATE, DELETE ON publication_chunk TO app_api;
GRANT SELECT, INSERT, UPDATE ON invitation TO app_api;
GRANT SELECT, DELETE ON membership TO app_api;
GRANT SELECT, INSERT ON idempotency TO app_api;
GRANT USAGE ON SEQUENCE release_withdrawal_id_seq TO app_api;
GRANT EXECUTE ON FUNCTION cloud_account(), cloud_owns_lab(uuid), cloud_is_member(uuid), cloud_can_read_lab(uuid), cloud_lab_of_release(uuid),
    cloud_owns_publication(uuid), cloud_accept_invitation(text, text) TO app_api;
