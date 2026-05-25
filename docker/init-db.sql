-- Runs as postgres superuser during container initialisation.
-- The Alembic migration also contains CREATE EXTENSION IF NOT EXISTS vector,
-- but that runs as the app user which may lack superuser privileges.
CREATE EXTENSION IF NOT EXISTS vector;
