from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .extensions import db
from .helpers import audit, clean, parse_whole_number, role_required, save_image
from .models import (
    Category, Order, Product, SellerOrder, SellerPayout, SellerProfile, SiteSetting,
)

bp = Blueprint("seller", __name__, url_prefix="/seller")


def _profile():
    return SellerProfile.query.filter_by(user_id=current_user.id).first_or_404()


@bp.get("/")
@login_required
@role_required("seller")
def dashboard():
    profile = _profile()
    product_count = Product.query.filter_by(seller_id=profile.id).count()
    orders = SellerOrder.query.filter_by(seller_id=profile.id).order_by(SellerOrder.id.desc()).limit(12).all()
    payouts = SellerPayout.query.filter_by(seller_id=profile.id).order_by(SellerPayout.id.desc()).limit(20).all()
    earned = db.session.query(db.func.coalesce(db.func.sum(SellerOrder.subtotal - SellerOrder.commission), 0)).filter(
        SellerOrder.seller_id == profile.id, SellerOrder.status == "delivered",
        SellerOrder.payout_status == "unsettled",
    ).scalar()
    reserved = db.session.query(db.func.coalesce(db.func.sum(SellerPayout.amount), 0)).filter(
        SellerPayout.seller_id == profile.id,
        SellerPayout.status.in_(("pending", "paid")),
    ).scalar()
    earned = max(int(earned or 0) - int(reserved or 0), 0)
    return render_template("seller/dashboard.html", profile=profile, product_count=product_count,
                           orders=orders, payouts=payouts, earned=earned)


@bp.get("/products")
@login_required
@role_required("seller")
def products():
    profile = _profile()
    items = Product.query.filter_by(seller_id=profile.id).order_by(Product.id.desc()).all()
    categories = Category.query.filter_by(active=True).order_by(Category.name).all()
    return render_template("seller/products.html", products=items, categories=categories)


@bp.post("/products")
@login_required
@role_required("seller")
def add_product():
    profile = _profile()
    if profile.status != "approved":
        abort(403)
    name = clean(request.form.get("name"), 140)
    description = clean(request.form.get("description"), 3000)
    category_id = parse_whole_number(request.form.get("category_id"), 1, 1000000)
    price = parse_whole_number(request.form.get("price"), 1, 1000000)
    old_price = parse_whole_number(request.form.get("old_price") or "0", 0, 1000000)
    stock = parse_whole_number(request.form.get("stock"), 0, 100000)
    category = db.session.get(Category, category_id) if category_id else None
    if not name or not category or not category.active or price is None or old_price is None or stock is None:
        flash("Check the product name, category, price, old price, and stock.", "error")
        return redirect(url_for("seller.products"))
    try:
        image = save_image(request.files.get("image"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("seller.products"))
    product = Product(
        seller_id=profile.id, category_id=category.id, name=name,
        description=description, price=price, old_price=old_price if old_price > price else 0,
        stock=stock, image=image, status="pending",
    )
    db.session.add(product)
    audit("seller_product_created", f"seller={profile.id}, product={name}")
    db.session.commit()
    flash("Product submitted. Admin approval is required before it appears in the shop.", "success")
    return redirect(url_for("seller.products"))


@bp.post("/products/<int:product_id>")
@login_required
@role_required("seller")
def edit_product(product_id):
    profile = _profile()
    product = Product.query.filter_by(id=product_id, seller_id=profile.id).first_or_404()
    if profile.status != "approved":
        abort(403)
    name = clean(request.form.get("name"), 140)
    description = clean(request.form.get("description"), 3000)
    category_id = parse_whole_number(request.form.get("category_id"), 1, 1000000)
    price = parse_whole_number(request.form.get("price"), 1, 1000000)
    old_price = parse_whole_number(request.form.get("old_price") or "0", 0, 1000000)
    stock = parse_whole_number(request.form.get("stock"), 0, 100000)
    category = db.session.get(Category, category_id) if category_id else None
    if not name or not category or not category.active or price is None or old_price is None or stock is None:
        flash("Check the product details.", "error")
        return redirect(url_for("seller.products"))
    try:
        image = save_image(request.files.get("image"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("seller.products"))
    product.name, product.description, product.category_id = name, description, category.id
    product.price, product.old_price, product.stock = price, old_price if old_price > price else 0, stock
    product.status = "pending"
    if image:
        product.image = image
    audit("seller_product_updated", f"seller={profile.id}, product={product.id}")
    db.session.commit()
    flash("Changes submitted for admin review.", "success")
    return redirect(url_for("seller.products"))


@bp.get("/orders")
@login_required
@role_required("seller")
def orders():
    profile = _profile()
    items = SellerOrder.query.filter_by(seller_id=profile.id).order_by(SellerOrder.id.desc()).limit(200).all()
    return render_template("seller/orders.html", orders=items)


@bp.post("/orders/<int:seller_order_id>")
@login_required
@role_required("seller")
def update_order(seller_order_id):
    profile = _profile()
    item = SellerOrder.query.filter_by(id=seller_order_id, seller_id=profile.id).first_or_404()
    status = request.form.get("status")
    transitions = {
        "placed": "confirmed",
        "confirmed": "processing",
        "processing": "shipped",
        "shipped": "delivered",
    }
    if transitions.get(item.status) != status:
        flash("That order status change is not allowed.", "error")
        return redirect(url_for("seller.orders"))
    if status in {"processing", "shipped", "delivered"} and item.order.payment_method != "cod" and item.order.payment_status != "paid":
        flash("Verify the buyer's wallet payment before fulfillment.", "error")
        return redirect(url_for("seller.orders"))
    item.status = status
    if item.order.seller_orders and all(o.status == "delivered" for o in item.order.seller_orders):
        item.order.status = "delivered"
    elif status in {"confirmed", "processing", "shipped"}:
        item.order.status = status
    audit("seller_order_status", f"seller={profile.id}, seller_order={item.id}, status={status}")
    db.session.commit()
    flash("Order status updated.", "success")
    return redirect(url_for("seller.orders"))


@bp.route("/payout-settings", methods=["GET", "POST"])
@login_required
@role_required("seller")
def payout_settings():
    profile = _profile()
    if request.method == "POST":
        method = request.form.get("method", "")
        number = clean(request.form.get("number"), 30)
        if method not in {"bkash", "nagad", "upay", "rocket"} or len(number) < 8:
            flash("Choose a payout wallet and enter a valid payout number.", "error")
        else:
            profile.payout_method, profile.payout_number = method, number
            db.session.commit()
            flash("Payout details saved.", "success")
    return render_template("seller/payout_settings.html", profile=profile)


@bp.post("/payouts/request")
@login_required
@role_required("seller")
def request_payout():
    profile = _profile()
    if profile.status != "approved" or not profile.payout_method or not profile.payout_number:
        flash("Save your payout details and make sure your seller account is approved first.", "error")
        return redirect(url_for("seller.dashboard"))
    payable = db.session.query(
        db.func.coalesce(db.func.sum(SellerOrder.subtotal - SellerOrder.commission), 0)
    ).filter(
        SellerOrder.seller_id == profile.id,
        SellerOrder.status == "delivered",
        SellerOrder.payout_status == "unsettled",
    ).scalar()
    reserved = db.session.query(db.func.coalesce(db.func.sum(SellerPayout.amount), 0)).filter(
        SellerPayout.seller_id == profile.id,
        SellerPayout.status.in_(("pending", "paid")),
    ).scalar()
    payable = max(int(payable or 0) - int(reserved or 0), 0)
    amount = parse_whole_number(request.form.get("amount"), 1, 100000000)
    if amount is None or amount > payable:
        flash(f"Enter an amount up to ৳{payable}.", "error")
        return redirect(url_for("seller.dashboard"))
    db.session.add(SellerPayout(
        seller_id=profile.id, amount=amount, method=profile.payout_method,
        reference=profile.payout_number,
    ))
    db.session.commit()
    flash("Payout request sent to TUKISHOP admin.", "success")
    return redirect(url_for("seller.dashboard"))
