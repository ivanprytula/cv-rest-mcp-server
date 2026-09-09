-- Local equivalent of what Terraform provisions on Cloud SQL: the role the
-- application connects as.
--
-- Deliberately NOSUPERUSER NOBYPASSRLS. Row-level security is not enforced
-- for either attribute -- not even with FORCE ROW LEVEL SECURITY on the
-- table -- so an app connecting with them would read every tenant's rows
-- while the policy sat there looking correct. Migrations and operator work
-- use the superuser instead; only the application uses this role.
--
-- Runs once, on an empty data directory (docker-entrypoint-initdb.d). Wipe
-- the volume to re-run it: `docker volume rm cv-rest-mcp-server_postgres-data`.

-- Cloud SQL has no initdb hook, and its google_sql_user accounts are granted
-- cloudsqlsuperuser (which carries BYPASSRLS), so the same role arrives there
-- with the bypass already set. Run the equivalent once against the instance,
-- as the postgres user via `just db-proxy`:
--
--     ALTER ROLE cv_app NOSUPERUSER NOBYPASSRLS;
--     REVOKE cloudsqlsuperuser FROM cv_app;
--     -- then the GRANT/ALTER DEFAULT PRIVILEGES statements below
--
--     SELECT rolname, rolsuper, rolbypassrls
--       FROM pg_roles WHERE rolname = 'cv_app';   -- expect: f | f
--
-- api-core refuses to start if this was skipped (verify_rls_enforced), so a
-- missed step is a failed deploy rather than cross-tenant reads.

CREATE ROLE cv_app LOGIN PASSWORD 'cv_app_local_dev' NOSUPERUSER NOBYPASSRLS;

GRANT USAGE ON SCHEMA public TO cv_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cv_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cv_app;

-- Tables the migrations create later would otherwise be unreachable to the
-- app until someone remembered to grant on them.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO cv_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO cv_app;

-- Cross-tenant analytics will eventually need to read past the policy. That
-- is a THIRD role (SELECT + BYPASSRLS, no write), never this one: granting
-- the app BYPASSRLS would remove the backstop from every request-handling
-- query, including the one that forgets its filter. Deferred until the gap
-- and posting tables are themselves tenant-scoped -- today they have no RLS
-- at all, so nothing is blocked.
