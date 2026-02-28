# Auth migration: add columns for signup/signin (username + password + email verification)

If your `users` table was created before the new auth (sign up / sign in with email verification), add these columns.

**PostgreSQL:**
```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token VARCHAR;
ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token_expires TIMESTAMP;
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_verification_token ON users(verification_token);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users(username);
```

**SQLite** (no `IF NOT EXISTS` for columns; run once):
```sql
ALTER TABLE users ADD COLUMN username VARCHAR;
ALTER TABLE users ADD COLUMN password_hash VARCHAR;
ALTER TABLE users ADD COLUMN email_verified INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN verification_token VARCHAR;
ALTER TABLE users ADD COLUMN verification_token_expires DATETIME;
CREATE UNIQUE INDEX ix_users_username ON users(username);
CREATE UNIQUE INDEX ix_users_verification_token ON users(verification_token);
```

Then restart the app.
