# TUKISHOP

TUKISHOP is a Bangladesh-focused multi-vendor e-commerce marketplace. The owner is Nayeem; developer credit is TOHIDUL.

## Marketplace features

- Buyer accounts with editable name, phone, and private profile photo; saved delivery addresses; wishlists; search, price filters, categories, pagination, cart, order history, and verified product reviews.
- Seller applications, admin approval, seller shops, product moderation, stock management, seller-specific order packages, commission tracking, and manual payout requests.
- Admin control for products, categories, seller accounts, orders, wallet payment numbers, payment verification, refunds, COD receipts, coupons, campaigns, support messages, shipping rules, and marketplace settings.
- Manual bKash, Nagad, Upay, and Rocket payment submissions, plus cash on delivery. Wallet numbers and instructions are edited in Admin → Wallet numbers. Buyers submit sender number and transaction ID; admins verify the payment.
- Responsive original TUKISHOP theme, reduced-motion support, CSRF protection, secure password hashes, role-based access, upload validation, audit events, and rate limits.

## Local setup

Python 3.10+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
flask --app app init-db
flask --app app create-admin
flask --app app run
```

Open `http://127.0.0.1:5000`. Create the first admin using the CLI prompt; there is no default admin password. The default local database is SQLite under the ignored `instance/` folder.

## PostgreSQL

Use PostgreSQL for a production marketplace. Set `DATABASE_URL` before starting the application, for example:

```text
postgresql+psycopg://USER:PASSWORD@HOST:5432/tukiahop
```

The app also accepts the common `postgres://` and `postgresql://` URL prefixes and converts them to the psycopg 3 dialect. Do not put database credentials in source files or commit them.

For a new database, `init-db` creates the initial tables and marketplace defaults. For later model changes, create and review a migration before deploying:

```bash
flask --app app db init
flask --app app db migrate -m "describe the schema change"
flask --app app db upgrade
```

Keep migration files in version control. Test migrations against a backup/staging database first.

## Admin and seller workflows

1. Sign in at `/login` with the admin account created by the CLI.
2. In Admin → Wallet numbers, set the receiving number, account type, instructions, and enabled state for each wallet.
3. Configure shipping, default commission, categories, banners, and coupons in Admin.
4. Sellers register from “Sell on TUKISHOP”. Admin approves the shop and can set its commission.
5. Sellers submit products for moderation. Approved products appear in the storefront.
6. Buyers place an order. Mobile-wallet orders remain pending until an administrator checks the transaction and verifies it.
7. Sellers fulfill their own packages; administrators can manage all order statuses, COD receipt, cancellation, refunds, and seller payouts.

Never ask buyers or sellers for wallet PINs or OTPs. A transaction ID or receipt image is not proof by itself; verify it against the wallet statement before marking an order paid.

## Configuration

- `DATABASE_URL`: PostgreSQL for production; omitted means local SQLite.
- `TUKI_SECRET_KEY`: long, random secret for signed sessions. The local app creates `instance/.secret_key` if omitted.
- `TUKI_HTTPS=1`: enables secure session cookies when HTTPS is active.
- `RATELIMIT_STORAGE_URI`: use a shared Redis URL in multi-worker or multi-instance production. The default in-memory limiter is for local/single-process use only.
- `FREE_SHIPPING_MINIMUM` and `DEFAULT_COMMISSION_PERCENT`: first-install defaults; update ongoing settings in Admin.

## Backups and deployment

Back up PostgreSQL and uploaded files regularly, encrypt backups, restrict access, and periodically test a restore. In production, use HTTPS, a managed PostgreSQL provider, persistent or object storage for product photos and private profile photos/receipts, Redis for shared rate limits, and a production WSGI server such as Gunicorn. See [HOSTING.md](./HOSTING.md).

## Integrations to add before operating at large scale

Wallet transfers in this release are intentionally manual: there is no bKash/Nagad/Upay/Rocket API settlement. Courier booking/tracking, SMS/OTP, email receipts, live chat, seller identity verification, advanced product variants, and a native mobile app require external providers, accounts, policies, and additional implementation. Do not advertise those as live until connected and tested.
