-- The sign-in handoff (feature electron, DEC-058; titanium_cloud/handoff.py): the browser page signed in with Neon Auth leaves the
-- session token here under a one-time code for two minutes; the desktop exchanges the code with its PKCE verifier once, and the row
-- is deleted. The rows belong to no account (the sign-in is not finished yet), so the policy is the service's own; expired rows are
-- deleted whenever a handoff is made or taken.

CREATE TABLE IF NOT EXISTS auth_handoff (
    code_hash      text PRIMARY KEY,                  -- sha256 of the code the page received; the code itself is never stored
    state          text NOT NULL,                     -- the desktop's state, checked again at the exchange
    challenge      text NOT NULL,                     -- S256 of the desktop's verifier
    session_token  text NOT NULL,                     -- Neon Auth's session token, given to the desktop once
    created_at     timestamptz NOT NULL DEFAULT now(),
    expires_at     timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS auth_handoff_expiry ON auth_handoff(expires_at);

ALTER TABLE auth_handoff ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS auth_handoff_service ON auth_handoff;
CREATE POLICY auth_handoff_service ON auth_handoff TO app_api USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, DELETE ON auth_handoff TO app_api;
