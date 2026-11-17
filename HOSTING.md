# TUKISHOP production deployment

## Recommended services

- Python 3.10+ application runtime with Gunicorn.
- Managed PostgreSQL database with automated point-in-time backups.
- Redis for rate limiting when using multiple Gunicorn workers or app instances.
- Persistent/object storage for product photos and private profile photos/payment receipts.
- HTTPS domain and server-side environment variables.

The repository does not include credentials. Configure secrets in the hosting provider's environment settings.

## Environment

Set at minimum:

```text
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/tukiahop
TUKI_SECRET_KEY=<long-random-secret>
TUKI_HTTPS=1
RATELIMIT_STORAGE_URI=redis://<redis-host>:6379/0
```

Use the hosting provider's exact database and Redis URLs. Do not commit credentials or paste them into public issues.

## Deploy steps

1. Create the PostgreSQL database and Redis instance.
2. Build the Python environment and install `requirements.txt`.
3. Set the environment variables above and ensure the upload volume is persistent. Store private profile photos and payment receipts outside the public static directory.
4. Run `flask --app app init-db` for the first deployment. For subsequent releases, run reviewed database migrations with `flask --app app db upgrade`.
5. Create the initial admin using `flask --app app create-admin` in a secure console.
6. Start the web process with `gunicorn --workers 2 --bind 0.0.0.0:$PORT app:app` (adapt the port syntax for your platform).
7. Confirm HTTPS, buyer checkout, seller approval, admin login, manual payment verification, image uploads, database backup, and restore on staging before launch.

## Operational safety

- Keep the database private; restrict it to the application network.
- Keep uploaded payment receipts private. The application serves them only to administrators.
- Use a shared Redis rate-limit store in multi-worker production; in-memory limits are not shared across workers.
- Back up PostgreSQL and uploaded files on independent schedules; encrypt them and test restoration.
- Never store payment PINs or OTPs. Verify manual wallet payments in the provider's merchant/personal wallet records.
- Monitor errors and disk usage. Configure log retention so customer phone numbers and payment identifiers are not unnecessarily exposed.
