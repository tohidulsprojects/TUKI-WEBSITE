# Tuki Beauty Shop (HTML, CSS, JavaScript, Python)

Buyer shop at `/`, protected admin at `/admin` (you can move it to a secret address, see below).

## Run on your computer
1. Install Python 3.10+.
2. `python -m venv venv`, then activate it (Windows: `venv\Scripts\activate`, Mac/Linux: `source venv/bin/activate`)
3. `pip install -r requirements.txt`
4. `python app.py create-admin` (choose a username and a password of 12+ characters)
5. `python app.py`, then open http://127.0.0.1:5000 (admin: http://127.0.0.1:5000/admin/login)

## Customer accounts
Customers sign up with name, phone number and a password (8+ characters), then log in to order. Under **Account** they automatically see **My orders** (items, delivery details, total, status, updated when you change the status in admin), and can change their password. Passwords are stored hashed; wrong logins are rate limited.
- There is no SMS or email, so a customer who forgets the password asks you, and you set a new one in the admin under **Customers** (then tell them privately).
- To also allow orders without an account, start the server with `TUKI_REQUIRE_LOGIN=0`.

### Staying logged in
Customers stay logged in on their phone for 30 days (the **Keep me logged in** box is ticked by default; untick it on a shared phone). The login forms are built so the phone or browser offers to save the phone number and password and fill them in next time. The shop never stores a customer's password itself, only a hash. Admin logins always expire after 2 hours.

## Change or reset the admin password
Change it any time in the admin panel (Change password section). If you forget it, run `python app.py create-admin` again and choose a new one.

## Secret admin address
The shop never shows a link to the admin. To hide it further, set `TUKI_ADMIN_PATH` before starting, e.g. `TUKI_ADMIN_PATH=my-secret-door`, and the login moves to `/my-secret-door/login`.
This only hides the door. The real lock is your strong password.

## Putting it online
See `HOSTING.md` for step by step PythonAnywhere instructions. On any host with a proxy in front, set `TUKI_PROXY=1` (and `TUKI_HTTPS=1`) so visitor limits and secure cookies work.

## Opening the admin login
- **Secret address:** set `TUKI_ADMIN_PATH` (for example `tuki-owner-7391`) and the login lives at `yourshop/tuki-owner-7391/login`. The shop shows no admin link. Bookmark it, or use Chrome menu > Add to Home screen.
- **Logo tap:** tapping the shop name 3 times quickly opens the login page. Set `TUKI_LOGO_DOOR=0` to switch this off. Note: anyone who learns the trick can reach the login page, so the real protection is your strong password (wrong guesses are rate limited).

## What you can manage in the admin
- **Products**: add, edit, hide, photos. **Orders**: see items and change status. **Customers**: reset a forgotten password.
- **Reviews**: customers can review a product after their order with it is delivered. Hide or delete any review.
- **Reports**: sales, orders, average order, top products, new customers and ratings for 24 hours, 7 days, 30 days or all time, plus a CSV download.
- **Settings**: shop name, main colour, headline, footer, phone / WhatsApp / Facebook (these create the Chat button), delivery charges and free-delivery amount, and categories.
- **Security**: backup download and admin password.

## Backup and restore
In the admin, press **Download backup**. You get a zip with `tuki.db` (products, orders, customers) and an `uploads` folder (photos). Keep it private, it holds customer phone numbers and password hashes.
To restore on a new server: unzip, copy `tuki.db` next to `app.py`, and copy the files inside `uploads` into `static/uploads/`.

## Product photos
In the admin, choose a JPG, PNG or WEBP photo (max 4 MB) when adding or editing a product. Photos are checked, resized and re-saved as clean JPEG files. Back up `static/uploads/` together with `tuki.db`.

## Before going live
- Use HTTPS (hosting with a free certificate) and set `TUKI_HTTPS=1`.
- Run with `gunicorn app:app`, not `python app.py`.
- Set `TUKI_SECRET_KEY` to a long random value on the server.
- Edit delivery charges in `app.py` (`SHIPPING`). Payment is cash on delivery only.
- Back up `tuki.db` regularly (it holds products and orders). Never share `.secret_key` or `tuki.db`.
- Behind a proxy (nginx), make sure the real visitor IP reaches the app, or login rate limiting will not work properly.
- Keep Flask and Python updated (`pip install -U -r requirements.txt`).

## What protects it
Admin password is hashed; login is rate limited; every form and the order API use CSRF tokens;
prices are always taken from the database, never from the browser; all database queries are parameterised;
output is escaped; uploaded photos are verified and re-encoded; security headers (CSP, no framing) are set; admin pages are not cached.
No website can be promised 100% secure, so keep it updated and use a strong, unique admin password.
