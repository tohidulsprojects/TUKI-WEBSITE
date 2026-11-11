"""Tuki Beauty Shop: Flask + SQLite. Buyer shop and a protected admin panel."""
import csv
import getpass
import io
import os
import tempfile
import zipfile
from datetime import datetime
import re
import secrets
import sqlite3
import sys
import time
from functools import wraps

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, send_file, session, url_for)
from PIL import Image, ImageOps
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "tuki.db")
KEY_PATH = os.path.join(BASE, ".secret_key")

# Secret admin address. Set TUKI_ADMIN_PATH (letters, digits, - and _) to something only you know.
_ap = os.environ.get("TUKI_ADMIN_PATH") or "admin"
if not re.fullmatch(r"[A-Za-z0-9_-]{3,40}", _ap):
    sys.exit("TUKI_ADMIN_PATH may only use letters, digits, - and _ (3-40 characters).")
ADMIN = "/" + _ap
UPLOAD_DIR = os.path.join(BASE, "static", "uploads")
MAX_IMAGE_BYTES = 4 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 30_000_000
# Customers must log in to order. Set TUKI_REQUIRE_LOGIN=0 to also allow guest orders.
REQUIRE_LOGIN = os.environ.get("TUKI_REQUIRE_LOGIN", "1") != "0"
# Starting values for everything the owner can change in Admin > Settings (saved in the database).
DEFAULTS = {"name": "Tuki", "color": "", "hl": "Beauty you can trust, at your door.",
            "sub": "Skin care, makeup, hair and body care. Pick what you like and order in a minute.",
            "foot": "Dhaka · Delivery across Bangladesh", "phone": "", "wa": "", "fb": "",
            "inside": 60, "outside": 120, "free": 0}
ADMIN_TABS = ["Products", "Orders", "Customers", "Messages", "Reviews", "Reports", "Banners", "Settings", "Security"]
PAYMENTS = {"cod": "Cash on delivery"}
STATUSES = ["new", "confirmed", "shipped", "delivered", "cancelled"]


def load_secret():
    env = os.environ.get("TUKI_SECRET_KEY")
    if env:
        return env
    if not os.path.exists(KEY_PATH):
        fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32))
    with open(KEY_PATH) as f:
        return f.read().strip()


app = Flask(__name__)
app.config.update(
    SECRET_KEY=load_secret(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("TUKI_HTTPS") == "1",
    PERMANENT_SESSION_LIFETIME=30 * 24 * 3600,
    MAX_CONTENT_LENGTH=MAX_IMAGE_BYTES + 64 * 1024,
)

if os.environ.get("TUKI_PROXY") == "1":
    # Hosting that puts a proxy in front of the app (most hosts): use the real visitor IP, so the
    # rate limits (logins, orders, sign-ups) are counted per visitor and not for everyone together.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
  price INTEGER NOT NULL, color TEXT NOT NULL DEFAULT '#f2b8cc',
  note TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
  image TEXT NOT NULL DEFAULT '', old_price INTEGER NOT NULL DEFAULT 0,
  stock INTEGER NOT NULL DEFAULT 10);
CREATE TABLE IF NOT EXISTS banners(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, text TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',
  c1 TEXT NOT NULL DEFAULT '#f06aa4', c2 TEXT NOT NULL DEFAULT '#a31d5b',
  active INTEGER NOT NULL DEFAULT 1, pos INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new', created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY, name TEXT, phone TEXT, address TEXT, zone TEXT, district TEXT, upazila TEXT,
  shipping INTEGER, pay TEXT, trx TEXT, total INTEGER,
  status TEXT NOT NULL DEFAULT 'new', created TEXT DEFAULT CURRENT_TIMESTAMP,
  customer_id INTEGER);
CREATE TABLE IF NOT EXISTS customers(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT UNIQUE NOT NULL,
  pw_hash TEXT NOT NULL, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS order_items(
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
  product_id INTEGER, name TEXT, price INTEGER, qty INTEGER);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL, customer_id INTEGER NOT NULL,
  stars INTEGER NOT NULL, text TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  created TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(product_id, customer_id));
"""
SAMPLE = [
    ("Rose Hydrating Serum", "Skin care", 1450, "#f2b8cc", "30 ml"),
    ("Daily Sunscreen SPF 50", "Skin care", 980, "#f7d9a8", "50 g"),
    ("Velvet Matte Lipstick", "Makeup", 650, "#b3274f", "Shade: Berry"),
    ("Black Kajal Pencil", "Makeup", 320, "#3b2a3d", "Smudge-proof"),
    ("Argan Hair Oil", "Hair", 760, "#e3b45c", "100 ml"),
    ("Shea Body Butter", "Body", 830, "#f5e1c8", "200 g"),
]


def init_db():
    con = sqlite3.connect(DB_PATH)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    con.executescript(SCHEMA)
    cols = [r[1] for r in con.execute("PRAGMA table_info(products)")]
    if "image" not in cols:
        con.execute("ALTER TABLE products ADD COLUMN image TEXT NOT NULL DEFAULT ''")
    if "old_price" not in cols:
        con.execute("ALTER TABLE products ADD COLUMN old_price INTEGER NOT NULL DEFAULT 0")
    if "stock" not in [r[1] for r in con.execute("PRAGMA table_info(products)")]:
        con.execute("ALTER TABLE products ADD COLUMN stock INTEGER NOT NULL DEFAULT 100")  # existing products: set the real quantity in admin
    if "customer_id" not in [r[1] for r in con.execute("PRAGMA table_info(orders)")]:
        con.execute("ALTER TABLE orders ADD COLUMN customer_id INTEGER")
    ocols = [r[1] for r in con.execute("PRAGMA table_info(orders)")]
    for col in ("district", "upazila"):
        if col not in ocols:
            con.execute("ALTER TABLE orders ADD COLUMN " + col + " TEXT")
    if con.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO products(name,category,price,color,note) VALUES(?,?,?,?,?)", SAMPLE)
        con.execute("UPDATE products SET old_price=CAST(ROUND(price*1.25) AS INTEGER) WHERE id IN (1,3,5)")
    con.execute("INSERT OR IGNORE INTO categories(name) SELECT category FROM products GROUP BY category ORDER BY MIN(id)")
    if con.execute("SELECT COUNT(*) FROM banners").fetchone()[0] == 0:
        con.executemany("INSERT INTO banners(title,text,category,c1,c2,pos) VALUES(?,?,?,?,?,?)", [
            ("Up to 40% off", "Skin care this week", "Skin care", "#f06aa4", "#a31d5b", 1),
            ("Makeup sale", "Lipsticks and more", "Makeup", "#b3274f", "#3b2a3d", 2),
            ("Free delivery", "On bigger orders", "", "#7a5c3e", "#c9a27a", 3)])
    con.commit()
    con.close()


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


# ---------- security helpers ----------
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


def check_csrf():
    sent = request.form.get("csrf") or request.headers.get("X-CSRF-Token", "")
    if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
        abort(400)


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("admin") or time.time() - session.get("admin_at", 0) > 7200:
            session.pop("admin", None)
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


@app.after_request
def headers(resp):
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.path.startswith(ADMIN):
        resp.headers["Cache-Control"] = "no-store"
    return resp


HITS = {}  # ip -> list of timestamps (simple in-memory rate limiter)


def limited(bucket, ip, limit, window):
    now = time.time()
    key = (bucket, ip)
    HITS[key] = [t for t in HITS.get(key, []) if now - t < window]
    return len(HITS[key]) >= limit


def hit(bucket, ip):
    HITS.setdefault((bucket, ip), []).append(time.time())


def clean(value, n):
    return " ".join(str(value or "").split())[:n]


def parse_product(form):
    name, cat = clean(form.get("name"), 80), clean(form.get("category"), 40)
    note, color = clean(form.get("note"), 60), form.get("color", "")
    try:
        price = int(form.get("price", ""))
    except ValueError:
        return None
    if not name or not cat or not 1 <= price <= 1000000 or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return None
    if not db().execute("SELECT 1 FROM categories WHERE name=?", (cat,)).fetchone():
        return None
    try:
        old_price = int(form.get("old_price", "") or 0)
    except ValueError:
        return None
    if old_price <= price or old_price > 1000000:
        old_price = 0  # no discount shown unless the old price is higher
    raw = form.get("stock")
    try:
        stock = 10 if raw is None else int(raw or 0)
    except ValueError:
        return None
    if not 0 <= stock <= 100000:
        return None
    return name, cat, price, color, note, old_price, stock


def save_image(file):
    """Returns (filename, error). Re-encodes the upload so only a clean JPEG is stored."""
    if not file or not file.filename:
        return "", None
    data = file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        return "", "Image is too big (max 4 MB)."
    try:
        probe = Image.open(io.BytesIO(data))
        if probe.format not in ("JPEG", "PNG", "WEBP"):
            return "", "Use a JPG, PNG or WEBP image."
        probe.verify()
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[3])
            img = bg
        else:
            img = img.convert("RGB")
        img.thumbnail((900, 900))
        name = secrets.token_hex(12) + ".jpg"
        img.save(os.path.join(UPLOAD_DIR, name), "JPEG", quality=82, optimize=True)
        return name, None
    except Exception:
        return "", "That file is not a valid image."


def remove_image(name):
    if name and re.fullmatch(r"[0-9a-f]{24}\.jpg", name):
        try:
            os.remove(os.path.join(UPLOAD_DIR, name))
        except OSError:
            pass


# ---------- settings helpers ----------
def get_settings():
    out = dict(DEFAULTS)
    for r in db().execute("SELECT key,value FROM settings"):
        k = r["key"]
        if k in out:
            try:
                out[k] = int(r["value"]) if isinstance(DEFAULTS[k], int) else r["value"]
            except ValueError:
                pass
    return out


def set_settings(**kw):
    for k, v in kw.items():
        if k in DEFAULTS:
            db().execute("INSERT INTO settings(key,value) VALUES(?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
    db().commit()


DISTRICTS = ["Bagerhat", "Bandarban", "Barguna", "Barishal", "Bhola", "Bogura", "Brahmanbaria", "Chandpur", "Chapainawabganj", "Chattogram", "Chuadanga", "Cox's Bazar", "Cumilla", "Dhaka", "Dinajpur", "Faridpur", "Feni", "Gaibandha", "Gazipur", "Gopalganj", "Habiganj", "Jamalpur", "Jashore", "Jhalokathi", "Jhenaidah", "Joypurhat", "Khagrachhari", "Khulna", "Kishoreganj", "Kurigram", "Kushtia", "Lakshmipur", "Lalmonirhat", "Madaripur", "Magura", "Manikganj", "Meherpur", "Moulvibazar", "Munshiganj", "Mymensingh", "Naogaon", "Narail", "Narayanganj", "Narsingdi", "Natore", "Netrokona", "Nilphamari", "Noakhali", "Pabna", "Panchagarh", "Patuakhali", "Pirojpur", "Rajbari", "Rajshahi", "Rangamati", "Rangpur", "Satkhira", "Shariatpur", "Sherpur", "Sirajganj", "Sunamganj", "Sylhet", "Tangail", "Thakurgaon"]


def ship_for(st, zone, subtotal):
    if zone not in ("inside", "outside"):
        return None
    if st["free"] > 0 and subtotal >= st["free"]:
        return 0
    return st[zone]


FB_RE = re.compile(r"https://(?:www\.|m\.)?(?:facebook\.com|fb\.com|fb\.me|m\.me|messenger\.com)/[^\s]{1,150}")


def msgr_link(fb):
    m = re.match(r"https://(?:www\.|m\.)?(?:facebook|fb)\.com/(?:profile\.php\?id=)?([A-Za-z0-9._-]+)", fb or "")
    return "https://m.me/" + m.group(1) if m else fb


@app.context_processor
def inject_settings():
    return {"S": get_settings(), "msgr_link": msgr_link}


def back():
    tab = request.form.get("tab", "")
    return redirect(url_for("admin") + ("#" + tab if tab in ADMIN_TABS else ""))


def ink_on(h):
    r, g_, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return "#2a0f1c" if 0.299 * r + 0.587 * g_ + 0.114 * b > 150 else "#ffffff"


@app.get("/theme.css")
def theme_css():
    """The owner's main colour as a stylesheet (inline styles are blocked by our security policy)."""
    c = get_settings()["color"]
    css = ":root{--berry:%s;--berry-ink:%s}" % (c, ink_on(c)) if re.fullmatch(r"#[0-9a-fA-F]{6}", c or "") else ""
    resp = app.response_class(css, mimetype="text/css")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


LOGO_DOOR = os.environ.get("TUKI_LOGO_DOOR", "1") != "0"  # set TUKI_LOGO_DOOR=0 to switch the logo-tap shortcut off


@app.get("/door")
def logo_door():
    """Shortcut used by tapping the shop name 3 times. Leads to the login page, nothing more."""
    if not LOGO_DOOR:
        abort(404)
    resp = redirect(url_for("login"))
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------- public shop ----------
@app.get("/")
def shop():
    conn, st = db(), get_settings()
    rows = conn.execute(
        "SELECT p.id,p.name,p.category,p.price,p.old_price AS old,p.stock,p.color,p.note,p.image,"
        " (SELECT COUNT(*) FROM reviews r WHERE r.product_id=p.id AND r.active=1) AS rn,"
        " (SELECT AVG(r.stars) FROM reviews r WHERE r.product_id=p.id AND r.active=1) AS ra"
        " FROM products p WHERE p.active=1 AND p.category NOT IN (SELECT name FROM categories WHERE active=0)"
        " ORDER BY p.id").fetchall()
    products = []
    for r in rows:
        d = dict(r)
        d["ra"] = round(d["ra"], 1) if d["ra"] else 0
        products.append(d)
    cats = [r["name"] for r in conn.execute("SELECT name FROM categories WHERE active=1 ORDER BY id")]
    shipping = {"inside": st["inside"], "outside": st["outside"], "free": st["free"]}
    pub = {"color": st["color"], "name": st["name"], "wa": st["wa"]}
    banners = [dict(r) for r in conn.execute("SELECT title,text,category,c1,c2 FROM banners WHERE active=1 ORDER BY pos,id")]
    return render_template("shop.html", products=products, shipping=shipping, cats=cats, pub=pub, districts=DISTRICTS, banners=banners)


@app.post("/api/order")
def api_order():
    check_csrf()
    cust = cust_row()
    if REQUIRE_LOGIN and not cust:
        return jsonify(ok=False, login=True, error="Please log in or sign up to place your order."), 401
    ip = request.remote_addr or "?"
    if limited("order", ip, 10, 3600):
        return jsonify(ok=False, error="Too many orders. Please try again later."), 429
    d = request.get_json(silent=True) or {}
    name, address = clean(d.get("name"), 80), clean(d.get("address"), 300)
    phone = re.sub(r"[\s-]", "", str(d.get("phone", "")))[:20]
    district, upazila = d.get("district"), clean(d.get("upazila"), 60)
    zone = ("inside" if district == "Dhaka" else "outside") if district in DISTRICTS else None
    pay, trx = d.get("pay"), clean(d.get("trx"), 40)
    items = d.get("items")
    bad = (not name or len(address) < 5 or not re.fullmatch(r"\+?\d{10,15}", phone)
           or zone is None or len(upazila) < 2 or pay not in PAYMENTS
           or not isinstance(items, list) or not 0 < len(items) <= 30)
    if bad:
        return jsonify(ok=False, error="Please check your details and try again."), 400
    wanted = {}
    for it in items:
        try:
            pid, qty = int(it.get("id")), int(it.get("qty"))
        except (TypeError, ValueError, AttributeError):
            return jsonify(ok=False, error="Invalid cart."), 400
        if not 1 <= qty <= 20:
            return jsonify(ok=False, error="Invalid quantity."), 400
        wanted[pid] = wanted.get(pid, 0) + qty
    conn = db()
    lines, total = [], 0
    for pid, qty in wanted.items():  # price always comes from the database
        p = conn.execute("SELECT id,name,price,stock FROM products WHERE id=? AND active=1 AND category NOT IN (SELECT name FROM categories WHERE active=0)", (pid,)).fetchone()
        if not p:
            return jsonify(ok=False, error="A product is no longer available."), 400
        if p["stock"] < qty:
            msg = ('"%s" is out of stock.' % p["name"]) if p["stock"] <= 0 else ('Only %d left of "%s".' % (p["stock"], p["name"]))
            return jsonify(ok=False, error=msg, stock=True), 409
        lines.append((p["id"], p["name"], p["price"], qty))
        total += p["price"] * qty
    ship = ship_for(get_settings(), zone, total)
    for pid, _n, _p, qty in lines:  # take the stock; the condition stops two buyers taking the last item
        if conn.execute("UPDATE products SET stock=stock-? WHERE id=? AND stock>=?", (qty, pid, qty)).rowcount != 1:
            conn.rollback()
            return jsonify(ok=False, error="Sorry, someone just bought the last items. Please refresh and try again.", stock=True), 409
    cur = conn.execute(
        "INSERT INTO orders(name,phone,address,zone,district,upazila,shipping,pay,trx,total,customer_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (name, phone, address, zone, district, upazila, ship, pay, "", total + ship, cust["id"] if cust else None))
    conn.executemany(
        "INSERT INTO order_items(order_id,product_id,name,price,qty) VALUES(?,?,?,?,?)",
        [(cur.lastrowid, *line) for line in lines])
    conn.commit()
    hit("order", ip)
    return jsonify(ok=True, order=cur.lastrowid, total=total + ship)


# ---------- customer accounts ----------
DUMMY_CUSTOMER_HASH = generate_password_hash("not-a-real-customer-password")


def norm_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("880") and len(digits) == 13:
        digits = "0" + digits[3:]
    return digits if re.fullmatch(r"\d{10,15}", digits) else None


def cust_row():
    cid = session.get("cust")
    if not cid:
        return None
    return db().execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone()


def login_customer(row, remember=True):
    session["cust"] = row["id"]
    session.permanent = bool(remember)  # True: stay logged in for 30 days on this phone


@app.get("/api/me")
def api_me():
    c = cust_row()
    return jsonify(ok=True, require_login=REQUIRE_LOGIN,
                   user={"name": c["name"], "phone": c["phone"]} if c else None)


@app.post("/api/register")
def api_register():
    check_csrf()
    ip = request.remote_addr or "?"
    if limited("reg", ip, 10, 3600):
        return jsonify(ok=False, error="Too many tries. Please wait a while."), 429
    d = request.get_json(silent=True) or {}
    name, phone, pw = clean(d.get("name"), 80), norm_phone(d.get("phone")), str(d.get("password", ""))
    if not name or not phone or not 8 <= len(pw) <= 200:
        return jsonify(ok=False, error="Enter your name, a valid phone number, and a password of at least 8 characters."), 400
    hit("reg", ip)
    if db().execute("SELECT 1 FROM customers WHERE phone=?", (phone,)).fetchone():
        return jsonify(ok=False, error="This phone number already has an account. Please log in."), 400
    cur = db().execute("INSERT INTO customers(name,phone,pw_hash) VALUES(?,?,?)",
                       (name, phone, generate_password_hash(pw)))
    db().commit()
    login_customer({"id": cur.lastrowid}, d.get("remember", True))
    return jsonify(ok=True, user={"name": name, "phone": phone})


@app.post("/api/login")
def api_login():
    check_csrf()
    ip = request.remote_addr or "?"
    if limited("clogin", ip, 10, 900):
        return jsonify(ok=False, error="Too many wrong tries. Please wait 15 minutes."), 429
    d = request.get_json(silent=True) or {}
    phone, pw = norm_phone(d.get("phone")), str(d.get("password", ""))
    row = db().execute("SELECT * FROM customers WHERE phone=?", (phone,)).fetchone() if phone else None
    ok = check_password_hash(row["pw_hash"] if row else DUMMY_CUSTOMER_HASH, pw)
    if row and ok:
        login_customer(row, d.get("remember", True))
        return jsonify(ok=True, user={"name": row["name"], "phone": row["phone"]})
    hit("clogin", ip)
    return jsonify(ok=False, error="Wrong phone number or password."), 401


@app.post("/api/logout")
def api_logout():
    check_csrf()
    session.pop("cust", None)
    return jsonify(ok=True)


@app.post("/api/password")
def api_password():
    check_csrf()
    c = cust_row()
    if not c:
        return jsonify(ok=False, error="Please log in first."), 401
    ip = request.remote_addr or "?"
    if limited("cpw", ip, 5, 900):
        return jsonify(ok=False, error="Too many tries. Please wait 15 minutes."), 429
    d = request.get_json(silent=True) or {}
    cur_pw, new_pw = str(d.get("current", "")), str(d.get("new", ""))
    if not check_password_hash(c["pw_hash"], cur_pw):
        hit("cpw", ip)
        return jsonify(ok=False, error="Current password is wrong."), 400
    if not 8 <= len(new_pw) <= 200 or new_pw == cur_pw:
        return jsonify(ok=False, error="New password must be 8+ characters and different from the current one."), 400
    db().execute("UPDATE customers SET pw_hash=? WHERE id=?", (generate_password_hash(new_pw), c["id"]))
    db().commit()
    return jsonify(ok=True)


@app.get("/api/my-orders")
def api_my_orders():
    c = cust_row()
    if not c:
        return jsonify(ok=False, error="Please log in."), 401
    out = []
    for o in db().execute("SELECT * FROM orders WHERE customer_id=? ORDER BY id DESC LIMIT 50", (c["id"],)):
        items = db().execute("SELECT name,price,qty FROM order_items WHERE order_id=?", (o["id"],)).fetchall()
        out.append({"id": o["id"], "status": o["status"], "name": o["name"], "address": o["address"],
                    "area": (o["upazila"] + ", " + o["district"]) if o["district"] else ("Inside Dhaka" if o["zone"] == "inside" else "Outside Dhaka"),
                    "shipping": o["shipping"], "total": o["total"], "placed": o["created"],
                    "items": [dict(i) for i in items]})
    return jsonify(ok=True, orders=out)

# ---------- product reviews ----------
def can_review(cid, pid):
    if not cid:
        return False
    return db().execute(
        "SELECT 1 FROM orders o JOIN order_items i ON i.order_id=o.id "
        "WHERE o.customer_id=? AND o.status='delivered' AND i.product_id=? LIMIT 1", (cid, pid)).fetchone() is not None


@app.get("/api/reviews/<int:pid>")
def api_reviews(pid):
    conn, c = db(), cust_row()
    if not conn.execute("SELECT 1 FROM products WHERE id=? AND active=1", (pid,)).fetchone():
        return jsonify(ok=False), 404
    rows = conn.execute(
        "SELECT r.stars,r.text,r.created,c.name FROM reviews r JOIN customers c ON c.id=r.customer_id "
        "WHERE r.product_id=? AND r.active=1 ORDER BY r.id DESC LIMIT 100", (pid,)).fetchall()
    mine = None
    if c:
        m = conn.execute("SELECT stars,text FROM reviews WHERE product_id=? AND customer_id=?", (pid, c["id"])).fetchone()
        mine = dict(m) if m else None
    resp = jsonify(ok=True, logged_in=bool(c), can_review=can_review(c["id"] if c else None, pid), mine=mine,
                   reviews=[{"stars": r["stars"], "text": r["text"], "name": r["name"].split(" ")[0],
                             "created": (r["created"] or "")[:10]} for r in rows])
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.post("/api/reviews/<int:pid>")
def api_review_save(pid):
    check_csrf()
    c = cust_row()
    if not c:
        return jsonify(ok=False, error="Please log in to write a review."), 401
    ip = request.remote_addr or "?"
    if limited("review", ip, 10, 3600):
        return jsonify(ok=False, error="Too many reviews. Try again later."), 429
    if not can_review(c["id"], pid):
        return jsonify(ok=False, error="Only customers whose order with this product was delivered can write a review."), 403
    d = request.get_json(silent=True) or {}
    try:
        stars = int(d.get("stars"))
    except (TypeError, ValueError):
        stars = 0
    text = clean(d.get("text"), 500)
    if not 1 <= stars <= 5 or len(text) < 3:
        return jsonify(ok=False, error="Choose a rating and write at least a few words."), 400
    db().execute("INSERT INTO reviews(product_id,customer_id,stars,text) VALUES(?,?,?,?) "
                 "ON CONFLICT(product_id,customer_id) DO UPDATE SET stars=excluded.stars,text=excluded.text,created=CURRENT_TIMESTAMP",
                 (pid, c["id"], stars, text))
    db().commit()
    hit("review", ip)
    return jsonify(ok=True)


# ---------- admin ----------
DUMMY_HASH = generate_password_hash("not-a-real-password")


@app.route(ADMIN + "/login", methods=["GET", "POST"])
def login():
    ip = request.remote_addr or "?"
    if request.method == "POST":
        check_csrf()
        if limited("login", ip, 5, 900):
            flash("Too many failed attempts. Wait 15 minutes.")
            return render_template("admin_login.html"), 429
        row = db().execute("SELECT * FROM admin WHERE username=?",
                           (clean(request.form.get("username"), 60),)).fetchone()
        ok = check_password_hash(row["pw_hash"] if row else DUMMY_HASH, request.form.get("password", ""))
        if row and ok:
            session.clear()
            session["admin"] = True
            session["admin_at"] = time.time()
            session.permanent = True
            return back()
        hit("login", ip)
        flash("Wrong username or password.")
    return render_template("admin_login.html")


@app.post(ADMIN + "/logout")
@admin_required
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("login"))


REPORT_DAYS = {0: "All time", 1: "Last 24 hours", 7: "Last 7 days", 30: "Last 30 days"}


def build_report(days):
    conn = db()
    o_where = "WHERE o.created >= datetime('now', ?)" if days else "WHERE 1=1"
    o_args = ("-%d days" % days,) if days else ()
    base = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(CASE WHEN o.status!='cancelled' THEN o.total END),0) rev, "
                        "COALESCE(SUM(CASE WHEN o.status!='cancelled' THEN o.shipping END),0) ship, "
                        "SUM(CASE WHEN o.status!='cancelled' THEN 1 ELSE 0 END) ok FROM orders o " + o_where, o_args).fetchone()
    units = conn.execute("SELECT COALESCE(SUM(i.qty),0) FROM order_items i JOIN orders o ON o.id=i.order_id "
                         + o_where + " AND o.status!='cancelled'", o_args).fetchone()[0]
    by_status = conn.execute("SELECT o.status s, COUNT(*) n FROM orders o " + o_where + " GROUP BY o.status", o_args).fetchall()
    top = conn.execute("SELECT i.name, SUM(i.qty) q, SUM(i.qty*i.price) r FROM order_items i JOIN orders o ON o.id=i.order_id "
                       + o_where + " AND o.status!='cancelled' GROUP BY i.name ORDER BY q DESC LIMIT 5", o_args).fetchall()
    c_where = "WHERE created >= datetime('now', ?)" if days else "WHERE 1=1"
    new_c = conn.execute("SELECT COUNT(*) FROM customers " + c_where, o_args).fetchone()[0]
    rv = conn.execute("SELECT COUNT(*) n, AVG(stars) a FROM reviews " + c_where + " AND active=1", o_args).fetchone()
    ok = base["ok"] or 0
    return {"orders": base["n"], "sales": base["rev"], "avg": round(base["rev"] / ok) if ok else 0,
            "units": units, "ship": base["ship"], "new_customers": new_c, "reviews": rv["n"],
            "rating": round(rv["a"], 1) if rv["a"] else None,
            "by_status": [dict(r) for r in by_status], "top": [dict(r) for r in top]}


@app.get(ADMIN)
@admin_required
def admin():
    conn = db()
    products = conn.execute("SELECT * FROM products ORDER BY id DESC").fetchall()
    orders = []
    for o in conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 100").fetchall():
        its = conn.execute("SELECT name,price,qty FROM order_items WHERE order_id=?", (o["id"],)).fetchall()
        orders.append((o, its))
    customers = conn.execute(
        "SELECT c.id,c.name,c.phone,c.created,(SELECT COUNT(*) FROM orders o WHERE o.customer_id=c.id) AS n "
        "FROM customers c ORDER BY c.id DESC LIMIT 200").fetchall()
    categories = conn.execute(
        "SELECT c.id,c.name,c.active,(SELECT COUNT(*) FROM products p WHERE p.category=c.name) AS n "
        "FROM categories c ORDER BY c.id").fetchall()
    reviews = conn.execute(
        "SELECT r.id,r.stars,r.text,r.active,r.created,c.name AS cname,p.name AS pname FROM reviews r "
        "JOIN customers c ON c.id=r.customer_id JOIN products p ON p.id=r.product_id ORDER BY r.id DESC LIMIT 200").fetchall()
    try:
        days = int(request.args.get("days", 0))
    except ValueError:
        days = 0
    days = days if days in REPORT_DAYS else 0
    messages = conn.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 200").fetchall()
    banners = conn.execute("SELECT * FROM banners ORDER BY pos,id").fetchall()
    return render_template("admin.html", products=products, orders=orders, customers=customers, messages=messages, banners=banners,
                           categories=categories, reviews=reviews, report=build_report(days), days=days,
                           report_days=REPORT_DAYS, statuses=STATUSES, payments=PAYMENTS)


@app.post(ADMIN + "/products")
@admin_required
def add_product():
    check_csrf()
    p = parse_product(request.form)
    if p:
        image, err = save_image(request.files.get("image"))
        if err:
            flash(err)
            return back()
        db().execute("INSERT INTO products(name,category,price,color,note,old_price,stock,image) VALUES(?,?,?,?,?,?,?,?)", (*p, image))
        db().commit()
        flash("Product added.")
    else:
        flash("Check the product details. Price must be a whole number.")
    return back()


@app.post(ADMIN + "/products/<int:pid>")
@admin_required
def edit_product(pid):
    check_csrf()
    p = parse_product(request.form)
    if p:
        active = 1 if request.form.get("active") == "1" else 0
        image, err = save_image(request.files.get("image"))
        if err:
            flash(err)
            return back()
        old = db().execute("SELECT image FROM products WHERE id=?", (pid,)).fetchone()
        db().execute("UPDATE products SET name=?,category=?,price=?,color=?,note=?,old_price=?,stock=?,active=? WHERE id=?",
                     (*p, active, pid))
        if image:
            db().execute("UPDATE products SET image=? WHERE id=?", (image, pid))
            if old:
                remove_image(old["image"])
        db().commit()
        flash("Product saved.")
    else:
        flash("Check the product details. Price must be a whole number.")
    return back()


@app.post(ADMIN + "/products/<int:pid>/delete")
@admin_required
def delete_product(pid):
    check_csrf()
    db().execute("UPDATE products SET active=0 WHERE id=?", (pid,))  # hidden, old orders keep working
    db().commit()
    flash("Product hidden from the shop.")
    return back()


@app.post(ADMIN + "/orders/<int:oid>")
@admin_required
def order_status(oid):
    check_csrf()
    status = request.form.get("status")
    conn = db()
    o = conn.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()
    if status in STATUSES and o and o["status"] != status:
        items = conn.execute("SELECT product_id,qty FROM order_items WHERE order_id=?", (oid,)).fetchall()
        if status == "cancelled":  # cancelled order: the items go back on the shelf
            for i in items:
                conn.execute("UPDATE products SET stock=stock+? WHERE id=?", (i["qty"], i["product_id"]))
        elif o["status"] == "cancelled":  # reopening: take the stock again
            for i in items:
                if conn.execute("UPDATE products SET stock=stock-? WHERE id=? AND stock>=?", (i["qty"], i["product_id"], i["qty"])).rowcount != 1:
                    conn.rollback()
                    flash("Not enough stock to reopen this order. Add stock to the products first.")
                    return back()
        conn.execute("UPDATE orders SET status=? WHERE id=?", (status, oid))
        conn.commit()
    return back()


@app.post(ADMIN + "/password")
@admin_required
def change_password():
    check_csrf()
    ip = request.remote_addr or "?"
    if limited("pw", ip, 5, 900):
        flash("Too many attempts. Wait 15 minutes.")
        return back()
    cur, new, again = (request.form.get(k, "") for k in ("current", "new", "again"))
    row = db().execute("SELECT * FROM admin WHERE id=1").fetchone()
    if not row or not check_password_hash(row["pw_hash"], cur):
        hit("pw", ip)
        flash("Current password is wrong.")
    elif len(new) < 12:
        flash("New password must be at least 12 characters.")
    elif new != again:
        flash("New passwords do not match.")
    elif new == cur:
        flash("Choose a different password from the current one.")
    else:
        db().execute("UPDATE admin SET pw_hash=? WHERE id=1", (generate_password_hash(new),))
        db().commit()
        session.clear()
        flash("Password changed. Please log in again with the new password.")
        return redirect(url_for("login"))
    return back()


@app.post(ADMIN + "/customers/<int:cid>/password")
@admin_required
def reset_customer_password(cid):
    check_csrf()
    new = request.form.get("new", "")
    if 8 <= len(new) <= 200 and db().execute("SELECT 1 FROM customers WHERE id=?", (cid,)).fetchone():
        db().execute("UPDATE customers SET pw_hash=? WHERE id=?", (generate_password_hash(new), cid))
        db().commit()
        flash("Customer password reset. Tell the customer the new password privately.")
    else:
        flash("New password must be at least 8 characters.")
    return back()


@app.post(ADMIN + "/backup")
@admin_required
def backup():
    """One zip with the database (products, orders, customers) and all product photos."""
    check_csrf()
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "tuki.db")
        src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(snap)
        src.backup(dst)  # consistent copy even while the shop is running
        src.close()
        dst.close()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "tuki.db")
            if os.path.isdir(UPLOAD_DIR):
                for name in sorted(os.listdir(UPLOAD_DIR)):
                    path = os.path.join(UPLOAD_DIR, name)
                    if os.path.isfile(path) and re.fullmatch(r"[0-9a-f]{24}\.jpg", name):
                        z.write(path, "uploads/" + name)
    buf.seek(0)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name="tuki-backup-" + stamp + ".zip")


@app.get(ADMIN + "/orders.csv")
@admin_required
def orders_csv():
    try:
        days = int(request.args.get("days", 0))
    except ValueError:
        days = 0
    days = days if days in REPORT_DAYS else 0
    where, args = ("WHERE created >= datetime('now', ?)", ("-%d days" % days,)) if days else ("", ())
    conn = db()

    def safe(v):  # stop spreadsheet formulas from running
        v = str(v if v is not None else "")
        return "'" + v if v[:1] in ("=", "+", "-", "@") else v
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Order", "Date (UTC)", "Name", "Phone", "Address", "District", "Upazila", "Delivery", "Total", "Status", "Items"])
    for o in conn.execute("SELECT * FROM orders " + where + " ORDER BY id", args):
        its = conn.execute("SELECT name,qty FROM order_items WHERE order_id=?", (o["id"],)).fetchall()
        w.writerow([o["id"], o["created"], safe(o["name"]), safe(o["phone"]), safe(o["address"]), safe(o["district"] or o["zone"]), safe(o["upazila"] or ""),
                    o["shipping"], o["total"], o["status"], safe("; ".join("%d x %s" % (i["qty"], i["name"]) for i in its))])
    resp = app.response_class("\ufeff" + buf.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = "attachment; filename=tuki-orders-" + datetime.now().strftime("%Y%m%d") + ".csv"
    return resp


@app.post(ADMIN + "/reviews/<int:rid>")
@admin_required
def review_toggle(rid):
    check_csrf()
    db().execute("UPDATE reviews SET active=1-active WHERE id=?", (rid,))
    db().commit()
    flash("Review updated.")
    return back()


@app.post(ADMIN + "/reviews/<int:rid>/delete")
@admin_required
def review_delete(rid):
    check_csrf()
    db().execute("DELETE FROM reviews WHERE id=?", (rid,))
    db().commit()
    flash("Review deleted.")
    return back()


@app.post(ADMIN + "/settings/look")
@admin_required
def settings_look():
    check_csrf()
    f = request.form
    name, hl, sub, foot = clean(f.get("name"), 30), clean(f.get("hl"), 90), clean(f.get("sub"), 140), clean(f.get("foot"), 140)
    color = "" if f.get("reset_color") == "1" else f.get("color", "")
    if not name or not hl or (color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color)):
        flash("Shop name and headline cannot be empty.")
    else:
        set_settings(name=name, hl=hl, sub=sub, foot=foot, color=color)
        flash("Shop look saved.")
    return back()


@app.post(ADMIN + "/settings/contact")
@admin_required
def settings_contact():
    check_csrf()
    f = request.form
    phone, wa, fb = clean(f.get("phone"), 20), re.sub(r"[\s+-]", "", f.get("wa", "")), clean(f.get("fb"), 200)
    if phone and not re.fullmatch(r"[0-9+\s-]{8,20}", phone):
        flash("Phone number looks wrong.")
    elif wa and not re.fullmatch(r"\d{8,15}", wa):
        flash("WhatsApp number: digits only, with country code, like 8801XXXXXXXXX.")
    elif fb and not FB_RE.fullmatch(fb):
        flash("Facebook link must start with https:// and be a Facebook or Messenger link.")
    else:
        set_settings(phone=phone, wa=wa, fb=fb)
        flash("Contact saved. The Chat button shows in the shop when at least one is filled.")
    return back()


@app.post(ADMIN + "/settings/delivery")
@admin_required
def settings_delivery():
    check_csrf()
    try:
        a, b, c = (int(request.form.get(k, "")) for k in ("inside", "outside", "free"))
    except ValueError:
        a = b = c = -1
    if not (0 <= a <= 5000 and 0 <= b <= 5000 and 0 <= c <= 100000):
        flash("Use whole numbers: charges 0 to 5000, free-delivery amount 0 to 100000.")
    else:
        set_settings(inside=a, outside=b, free=c)
        flash("Delivery saved.")
    return back()


@app.post(ADMIN + "/categories")
@admin_required
def add_category():
    check_csrf()
    name = clean(request.form.get("name"), 30)
    if not name:
        flash("Type a category name.")
    elif db().execute("SELECT 1 FROM categories WHERE lower(name)=lower(?)", (name,)).fetchone():
        flash("That category already exists.")
    else:
        db().execute("INSERT INTO categories(name) VALUES(?)", (name,))
        db().commit()
        flash("Category added.")
    return back()


@app.post(ADMIN + "/categories/<int:cid>")
@admin_required
def edit_category(cid):
    check_csrf()
    name, active = clean(request.form.get("name"), 30), 1 if request.form.get("active") == "1" else 0
    old = db().execute("SELECT name FROM categories WHERE id=?", (cid,)).fetchone()
    if not old or not name:
        flash("Category name cannot be empty.")
    elif db().execute("SELECT 1 FROM categories WHERE lower(name)=lower(?) AND id!=?", (name, cid)).fetchone():
        flash("That category already exists.")
    else:
        db().execute("UPDATE categories SET name=?, active=? WHERE id=?", (name, active, cid))
        db().execute("UPDATE products SET category=? WHERE category=?", (name, old["name"]))
        db().commit()
        flash("Category saved." + ("" if active else " It is hidden, so its products are hidden too."))
    return back()


@app.post(ADMIN + "/categories/<int:cid>/delete")
@admin_required
def delete_category(cid):
    check_csrf()
    row = db().execute("SELECT name FROM categories WHERE id=?", (cid,)).fetchone()
    if row and not db().execute("SELECT 1 FROM products WHERE category=?", (row["name"],)).fetchone():
        db().execute("DELETE FROM categories WHERE id=?", (cid,))
        db().commit()
        flash("Category deleted.")
    else:
        flash("Only an empty category can be deleted. Hide it instead.")
    return back()


# ---------- customer support messages ----------
@app.post("/api/message")
def api_message():
    check_csrf()
    ip = request.remote_addr or "?"
    if limited("msg", ip, 5, 3600):
        return jsonify(ok=False, error="Too many messages. Please try again later."), 429
    d = request.get_json(silent=True) or {}
    name, body = clean(d.get("name"), 80), clean(d.get("message"), 500)
    phone = re.sub(r"[\s-]", "", str(d.get("phone", "")))[:20]
    if not name or len(body) < 3 or not re.fullmatch(r"\+?\d{10,15}", phone):
        return jsonify(ok=False, error="Enter your name, a message and a phone number with at least 10 digits."), 400
    db().execute("INSERT INTO messages(name,phone,body) VALUES(?,?,?)", (name, phone, body))
    db().commit()
    hit("msg", ip)
    return jsonify(ok=True)


@app.post(ADMIN + "/messages/<int:mid>")
@admin_required
def message_status(mid):
    check_csrf()
    st = "done" if request.form.get("status") == "done" else "new"
    db().execute("UPDATE messages SET status=? WHERE id=?", (st, mid))
    db().commit()
    return back()


@app.post(ADMIN + "/messages/<int:mid>/delete")
@admin_required
def message_delete(mid):
    check_csrf()
    db().execute("DELETE FROM messages WHERE id=?", (mid,))
    db().commit()
    flash("Message deleted.")
    return back()


# ---------- home page banners ----------
def parse_banner(form):
    title, text = clean(form.get("title"), 40), clean(form.get("text"), 80)
    cat, c1, c2 = clean(form.get("category"), 40), form.get("c1", ""), form.get("c2", "")
    if not title or not re.fullmatch(r"#[0-9a-fA-F]{6}", c1) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c2):
        return None
    if cat and not db().execute("SELECT 1 FROM categories WHERE name=?", (cat,)).fetchone():
        return None
    return title, text, cat, c1, c2


@app.post(ADMIN + "/banners")
@admin_required
def add_banner():
    check_csrf()
    b = parse_banner(request.form)
    if b:
        pos = db().execute("SELECT COALESCE(MAX(pos),0)+1 FROM banners").fetchone()[0]
        db().execute("INSERT INTO banners(title,text,category,c1,c2,pos) VALUES(?,?,?,?,?,?)", (*b, pos))
        db().commit()
        flash("Banner added.")
    else:
        flash("Check the banner: it needs a title and two colours.")
    return back()


@app.post(ADMIN + "/banners/<int:bid>")
@admin_required
def edit_banner(bid):
    check_csrf()
    b = parse_banner(request.form)
    if b:
        db().execute("UPDATE banners SET title=?,text=?,category=?,c1=?,c2=?,active=? WHERE id=?",
                     (*b, 1 if request.form.get("active") == "1" else 0, bid))
        db().commit()
        flash("Banner saved.")
    else:
        flash("Check the banner: it needs a title and two colours.")
    return back()


@app.post(ADMIN + "/banners/<int:bid>/delete")
@admin_required
def delete_banner(bid):
    check_csrf()
    db().execute("DELETE FROM banners WHERE id=?", (bid,))
    db().commit()
    flash("Banner deleted.")
    return back()


def create_admin():
    init_db()
    user = input("Admin username: ").strip()
    pw = getpass.getpass("Admin password (12+ characters): ")
    if not user or len(pw) < 12 or pw != getpass.getpass("Repeat password: "):
        sys.exit("Username missing, password too short, or passwords differ.")
    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT OR REPLACE INTO admin(id,username,pw_hash) VALUES(1,?,?)",
                (user, generate_password_hash(pw)))
    con.commit()
    con.close()
    print("Admin saved. Log in at " + ADMIN + "/login")


init_db()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "create-admin":
        create_admin()
    else:
        app.run(host="127.0.0.1", port=5000, debug=False)
