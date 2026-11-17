import os
import secrets
from pathlib import Path

from flask import Flask, request
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash

from .extensions import db, limiter
from .models import Category, PaymentMethod, SiteSetting, User

csrf = CSRFProtect()
login_manager = LoginManager()
migrate = Migrate()


def create_app(test_config=None):
    app = Flask(
        __name__, instance_relative_config=True,
        template_folder="../templates", static_folder="../static",
    )
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    default_db = "sqlite:///" + str(Path(app.instance_path) / "tukiahop.db")
    database_url = os.environ.get("DATABASE_URL", default_db)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("TUKI_SECRET_KEY") or _local_secret(app.instance_path),
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
        UPLOAD_FOLDER=os.path.join(app.root_path, "..", "static", "uploads"),
        PRIVATE_UPLOAD_FOLDER=os.path.join(app.instance_path, "private_uploads"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("TUKI_HTTPS") == "1",
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
        REMEMBER_COOKIE_SECURE=os.environ.get("TUKI_HTTPS") == "1",
        FREE_SHIPPING_MINIMUM=5000,
        DEFAULT_COMMISSION_PERCENT=10,
        RATELIMIT_STORAGE_URI=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
    )
    if test_config:
        app.config.update(test_config)
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["PRIVATE_UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    limiter.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to continue."
    login_manager.login_message_category = "info"
    if os.environ.get("TUKI_PROXY") == "1":
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    from . import admin, auth, marketplace, seller

    @login_manager.user_loader
    def load_user(user_id):
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    app.register_blueprint(auth.bp)
    app.register_blueprint(marketplace.bp)
    app.register_blueprint(seller.bp)
    app.register_blueprint(admin.bp)

    @app.context_processor
    def common_template_data():
        from .helpers import setting
        categories = Category.query.filter_by(active=True).order_by(Category.name).limit(8).all()
        return {
            "nav_categories": categories,
            "owner_name": setting("owner_name", "Nayeem"),
            "developer_name": setting("developer_name", "TOHIDUL"),
            "support_phone": setting("support_phone", ""),
        }

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.path.startswith(("/admin", "/account", "/seller", "/orders", "/checkout", "/wishlist", "/addresses")):
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @app.cli.command("init-db")
    def init_db_command():
        """Create tables and seed marketplace defaults for a new installation."""
        with app.app_context():
            db.create_all()
            _seed_defaults(app)
        print("TUKISHOP database initialized.")

    @app.cli.command("create-admin")
    def create_admin_command():
        """Create or promote an administrator without a hard-coded password."""
        import getpass

        username = input("Admin username: ").strip().lower()
        phone = input("Admin phone: ").strip()
        password = getpass.getpass("Admin password (12+ characters): ")
        if not username or not phone or len(password) < 12:
            raise SystemExit("Username and phone are required; password must be 12+ characters.")
        with app.app_context():
            db.create_all()
            user = User.query.filter_by(username=username).first()
            if user is None:
                user = User(username=username, phone=phone, name="TUKISHOP Admin", role="admin")
                db.session.add(user)
            user.role = "admin"
            user.phone = phone
            user.password_hash = generate_password_hash(password)
            db.session.commit()
        print("Administrator saved.")

    return app


def _local_secret(instance_path):
    path = Path(instance_path) / ".secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_text(encoding="utf-8").strip()


def _seed_defaults(app):
    if not Category.query.first():
        db.session.add_all(
            Category(name=name)
            for name in (
                "Fashion", "Beauty & Health", "Phones & Accessories",
                "Home & Living", "Electronics", "Groceries", "Sports",
            )
        )
    for slug, title in (
        ("bkash", "bKash"), ("nagad", "Nagad"),
        ("upay", "Upay"), ("rocket", "Rocket"),
    ):
        if not PaymentMethod.query.filter_by(slug=slug).first():
            db.session.add(PaymentMethod(slug=slug, title=title, enabled=False))
    for key, value in {
        "site_name": "TUKISHOP",
        "site_tagline": "Everything you love, all in one hop.",
        "owner_name": "Nayeem",
        "developer_name": "TOHIDUL",
        "support_phone": "",
        "support_email": "",
        "shipping_inside_dhaka": "60",
        "shipping_outside_dhaka": "120",
        "free_shipping_minimum": str(app.config["FREE_SHIPPING_MINIMUM"]),
        "commission_percent": str(app.config["DEFAULT_COMMISSION_PERCENT"]),
    }.items():
        existing = SiteSetting.query.filter_by(key=key).first()
        if existing is None:
            db.session.add(SiteSetting(key=key, value=value))
        elif key == "site_name" and existing.value == "TUKIAHOP":
            existing.value = value
    db.session.commit()
