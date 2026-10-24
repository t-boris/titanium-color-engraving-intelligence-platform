-- The sign-in handoff table of migration 0002 is not needed (feature electron, DEC-060): the desktop signs in through Neon Auth's
-- OAuth provider (authorization code with PKCE, a refresh token kept by the desktop), and this service keeps nothing of a sign-in.
-- The table held rows of at most two minutes and was empty whenever no sign-in was in flight.

DROP TABLE IF EXISTS auth_handoff;
