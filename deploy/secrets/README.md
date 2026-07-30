# Production secret files

Create these files locally before starting the production Compose project:

- `database_password`: the PostgreSQL role password;
- `database_url`: the complete SQLAlchemy URL, for example `postgresql+psycopg://bibmgr:PASSWORD@postgres:5432/bibmgr`;
- `auth_secret`: at least 32 random bytes used to protect login codes and sessions;
- `smtp_password`: the SMTP relay password, or an empty file when the relay does not use SMTP authentication.

Do not commit the secret values. Files in this directory other than this README are ignored by Git.
