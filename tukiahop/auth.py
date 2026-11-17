import re
from urllib.parse import urlparse

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from sqlalchemy import or_

from .extensions import db, limiter
from .helpers import audit, clean, normalize_phone
from .models import SellerProfile, User

bp = Blueprint("auth", __name__)


def safe_next(value):
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
        return None
    return value


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("marketplace.home"))
    if request.method == "POST":
        name = clean(request.form.get("name"), 100)
        username = clean(request.form.get("username"), 40).lower()
        phone = normalize_phone(request.form.get("phone"))
        password = request.form.get("password", "")
        if not name or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,39}", username) or not phone:
            flash("Enter a name, valid username, and Bangladesh mobile number.", "error")
        elif len(password) < 10 or len(password) > 200:
            flash("Password must be at least 10 characters.", "error")
        elif User.query.filter(or_(User.username == username, User.phone == phone)).first():
            flash("That username or phone number is already registered.", "error")
        else:
            user = User(name=name, username=username, phone=phone, role="customer")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            login_user(user, remember=request.form.get("remember") == "1")
            flash("Welcome to TUKISHOP. Your account is ready.", "success")
            return redirect(url_for("marketplace.home"))
    return render_template("auth/register.html")


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per 15 minutes", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("marketplace.home"))
    if request.method == "POST":
        identifier = clean(request.form.get("identifier"), 80).lower()
        user = User.query.filter(or_(User.username == identifier, User.phone == identifier)).first()
        password = request.form.get("password", "")
        if not user or not user.check_password(password) or not user.active:
            flash("Username/phone or password is incorrect.", "error")
        else:
            login_user(user, remember=request.form.get("remember") == "1")
            return redirect(safe_next(request.args.get("next")) or
                            (url_for("admin.dashboard") if user.role == "admin" else url_for("marketplace.home")))
    return render_template("auth/login.html")


@bp.post("/logout")
def logout():
    logout_user()
    flash("You are logged out.", "info")
    return redirect(url_for("marketplace.home"))


@bp.route("/seller/register", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def seller_register():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login", next=url_for("auth.seller_register")))
    if current_user.role == "seller":
        return redirect(url_for("seller.dashboard"))
    if current_user.role == "admin":
        abort(403)
    if request.method == "POST":
        shop_name = clean(request.form.get("shop_name"), 100)
        description = clean(request.form.get("description"), 1000)
        if len(shop_name) < 2:
            flash("Shop name must be at least 2 characters.", "error")
        elif SellerProfile.query.filter_by(shop_name=shop_name).first():
            flash("That shop name is already in use.", "error")
        else:
            profile = SellerProfile(user_id=current_user.id, shop_name=shop_name, description=description)
            current_user.role = "seller"
            db.session.add(profile)
            audit("seller_application", shop_name)
            db.session.commit()
            flash("Seller application submitted. Admin approval is required before listing products.", "success")
            return redirect(url_for("seller.dashboard"))
    return render_template("auth/seller_register.html")
