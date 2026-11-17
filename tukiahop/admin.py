import csv
import io
from datetime import datetime, timezone

from flask import Blueprint, abort, current_app, flash, make_response, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from .extensions import db
from .helpers import audit, clean, parse_whole_number, role_required, save_settings
from .models import (
    AuditLog, Banner, Category, Coupon, Order, OrderItem, PaymentMethod,
    PaymentSubmission, Product, Review, SellerOrder, SellerPayout, SellerProfile,
    SiteSetting, SupportMessage, User,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.get("/")
@login_required
@role_required("admin")
def dashboard():
    stats = {
        "orders": Order.query.count(),
        "pending_payments": PaymentSubmission.query.filter_by(status="pending").count(),
        "pending_sellers": SellerProfile.query.filter_by(status="pending").count(),
        "pending_products": Product.query.filter_by(status="pending").count(),
        "customers": User.query.filter_by(role="customer").count(),
        "sellers": SellerProfile.query.filter_by(status="approved").count(),
        "sales": db.session.query(func.coalesce(func.sum(Order.total), 0)).filter(
            Order.status != "cancelled",
        ).scalar(),
    }
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(12).all()
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(15).all()
    return render_template("admin/dashboard.html", stats=stats, orders=recent_orders, logs=logs)


@bp.get("/sellers")
@login_required
@role_required("admin")
def sellers():
    rows = SellerProfile.query.order_by(
        (SellerProfile.status == "pending").desc(), SellerProfile.created_at.desc(),
    ).limit(300).all()
    return render_template("admin/sellers.html", sellers=rows)


@bp.post("/sellers/<int:seller_id>")
@login_required
@role_required("admin")
def update_seller(seller_id):
    profile = db.get_or_404(SellerProfile, seller_id)
    status = request.form.get("status")
    commission = request.form.get("commission")
    try:
        rate = float(commission)
    except (TypeError, ValueError):
        rate = -1
    if status not in {"pending", "approved", "rejected", "suspended"} or not 0 <= rate <= 50:
        flash("Choose a valid seller status and commission from 0% to 50%.", "error")
    else:
        profile.status = status
        profile.commission_percent = rate
        audit("seller_updated", f"seller={profile.id}, status={status}, commission={rate}")
        db.session.commit()
        flash("Seller account updated.", "success")
    return redirect(url_for("admin.sellers"))


@bp.get("/products")
@login_required
@role_required("admin")
def products():
    rows = Product.query.order_by((Product.status == "pending").desc(), Product.id.desc()).limit(500).all()
    return render_template("admin/products.html", products=rows, categories=Category.query.filter_by(active=True).all())


@bp.get("/reviews")
@login_required
@role_required("admin")
def reviews():
    rows = Review.query.order_by(Review.created_at.desc()).limit(500).all()
    return render_template("admin/reviews.html", reviews=rows)


@bp.post("/reviews/<int:review_id>")
@login_required
@role_required("admin")
def toggle_review(review_id):
    review = db.get_or_404(Review, review_id)
    review.active = not review.active
    audit("review_moderated", f"review={review.id}, active={review.active}")
    db.session.commit()
    return redirect(url_for("admin.reviews"))


@bp.post("/products/create")
@login_required
@role_required("admin")
def create_product():
    name = clean(request.form.get("name"), 140)
    description = clean(request.form.get("description"), 3000)
    category_id = parse_whole_number(request.form.get("category_id"), 1, 1000000)
    price = parse_whole_number(request.form.get("price"), 1, 1000000)
    stock = parse_whole_number(request.form.get("stock"), 0, 100000)
    category = db.session.get(Category, category_id) if category_id else None
    try:
        image = save_image(request.files.get("image"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.products"))
    if not name or not category or price is None or stock is None:
        flash("Check the product name, category, price, and stock.", "error")
    else:
        product = Product(
            category_id=category.id, name=name, description=description,
            price=price, stock=stock, image=image, status="approved",
        )
        db.session.add(product)
        audit("admin_product_created", name)
        db.session.commit()
        flash("Admin product published.", "success")
    return redirect(url_for("admin.products"))


@bp.post("/products/<int:product_id>")
@login_required
@role_required("admin")
def update_product(product_id):
    product = db.get_or_404(Product, product_id)
    status = request.form.get("status")
    active = request.form.get("active") == "1"
    if status not in {"pending", "approved", "rejected"}:
        abort(400)
    product.status, product.active = status, active
    audit("product_moderated", f"product={product.id}, status={status}, active={active}")
    db.session.commit()
    flash("Product moderation saved.", "success")
    return redirect(url_for("admin.products"))


@bp.get("/orders")
@login_required
@role_required("admin")
def orders():
    rows = Order.query.order_by(Order.created_at.desc()).limit(500).all()
    submissions = PaymentSubmission.query.order_by(
        (PaymentSubmission.status == "pending").desc(), PaymentSubmission.created_at.desc(),
    ).limit(300).all()
    return render_template("admin/orders.html", orders=rows, submissions=submissions)


@bp.post("/orders/<int:order_id>")
@login_required
@role_required("admin")
def update_order(order_id):
    order = db.get_or_404(Order, order_id)
    status = request.form.get("status")
    if status not in {"placed", "confirmed", "processing", "shipped", "delivered", "cancelled"}:
        abort(400)
    if order.status == "cancelled" and status != "cancelled":
        flash("Cancelled orders cannot be reopened; create a replacement order instead.", "error")
        return redirect(url_for("admin.orders"))
    if status in {"confirmed", "processing", "shipped", "delivered"} and order.payment_method != "cod" and order.payment_status != "paid":
        flash("Verify the wallet payment before advancing this order.", "error")
        return redirect(url_for("admin.orders"))
    if status == "cancelled" and order.status != "cancelled":
        _restore_stock(order)
        if order.payment_status == "paid":
            order.payment_status = "refund_pending"
    order.status = status
    for seller_order in order.seller_orders:
        seller_order.status = status
    audit("order_status", f"order={order.id}, status={status}")
    db.session.commit()
    flash("Order status updated.", "success")
    return redirect(url_for("admin.orders"))


@bp.post("/payments/<int:submission_id>")
@login_required
@role_required("admin")
def review_payment(submission_id):
    submission = db.get_or_404(PaymentSubmission, submission_id)
    decision = request.form.get("decision")
    if submission.status != "pending" or decision not in {"verified", "rejected"}:
        flash("This payment submission has already been reviewed or the action is invalid.", "error")
        return redirect(url_for("admin.orders"))
    submission.status = decision
    submission.note = clean(request.form.get("note"), 300)
    submission.reviewed_by = current_user.id
    submission.reviewed_at = datetime.now(timezone.utc)
    submission.order.payment_status = "paid" if decision == "verified" else "rejected"
    if submission.order.status == "cancelled" and decision == "verified":
        submission.order.payment_status = "refund_pending"
    audit("payment_review", f"submission={submission.id}, decision={decision}, order={submission.order_id}")
    db.session.commit()
    flash(f"Payment marked {decision}.", "success")
    return redirect(url_for("admin.orders"))


@bp.get("/payments/<int:submission_id>/receipt")
@login_required
@role_required("admin")
def payment_receipt(submission_id):
    submission = db.get_or_404(PaymentSubmission, submission_id)
    if not submission.receipt_image:
        abort(404)
    return send_from_directory(
        current_app.config["PRIVATE_UPLOAD_FOLDER"],
        submission.receipt_image,
        mimetype="image/jpeg",
        as_attachment=False,
        download_name="payment-receipt.jpg",
    )


@bp.post("/orders/<int:order_id>/refund")
@login_required
@role_required("admin")
def update_refund(order_id):
    order = db.get_or_404(Order, order_id)
    status = request.form.get("payment_status")
    if order.payment_status != "refund_pending" or status not in {"refunded", "refund_rejected"}:
        flash("This order does not have a pending refund.", "error")
    else:
        order.payment_status = status
        audit("refund_status", f"order={order.id}, status={status}")
        db.session.commit()
        flash("Refund status updated. Complete the wallet transfer manually before marking it refunded.", "success")
    return redirect(url_for("admin.orders"))


@bp.post("/orders/<int:order_id>/cod-payment")
@login_required
@role_required("admin")
def settle_cod(order_id):
    order = db.get_or_404(Order, order_id)
    if order.payment_method != "cod" or order.status != "delivered" or order.payment_status == "paid":
        flash("Cash-on-delivery payment can be marked received only after delivery.", "error")
    else:
        order.payment_status = "paid"
        audit("cod_payment_received", f"order={order.id}")
        db.session.commit()
        flash("Cash-on-delivery receipt recorded.", "success")
    return redirect(url_for("admin.orders"))


@bp.route("/payments", methods=["GET", "POST"])
@login_required
@role_required("admin")
def payments():
    methods = PaymentMethod.query.order_by(PaymentMethod.sort_order, PaymentMethod.id).all()
    if request.method == "POST":
        method_id = parse_whole_number(request.form.get("method_id"), 1, 1000000)
        method = db.session.get(PaymentMethod, method_id) if method_id else None
        if not method:
            abort(404)
        number = clean(request.form.get("account_number"), 30)
        account_type = request.form.get("account_type")
        if account_type not in {"personal", "merchant"} or (request.form.get("enabled") == "1" and len(number) < 8):
            flash("Enabled wallet methods need a valid account number and account type.", "error")
        else:
            method.account_number = number
            method.account_type = account_type
            method.instructions = clean(request.form.get("instructions"), 500)
            method.enabled = request.form.get("enabled") == "1"
            audit("payment_method_updated", f"method={method.slug}, enabled={method.enabled}")
            db.session.commit()
            flash(f"{method.title} settings saved.", "success")
        return redirect(url_for("admin.payments"))
    return render_template("admin/payments.html", methods=methods)


@bp.get("/catalog")
@login_required
@role_required("admin")
def catalog():
    categories = Category.query.order_by(Category.name).all()
    return render_template("admin/catalog.html", categories=categories)


@bp.post("/categories")
@login_required
@role_required("admin")
def add_category():
    name = clean(request.form.get("name"), 60)
    if len(name) < 2:
        flash("Category must be at least 2 characters.", "error")
    elif Category.query.filter(func.lower(Category.name) == name.lower()).first():
        flash("That category already exists.", "error")
    else:
        db.session.add(Category(name=name))
        audit("category_created", name)
        db.session.commit()
        flash("Category created.", "success")
    return redirect(url_for("admin.catalog"))


@bp.post("/categories/<int:category_id>")
@login_required
@role_required("admin")
def update_category(category_id):
    category = db.get_or_404(Category, category_id)
    name = clean(request.form.get("name"), 60)
    if len(name) < 2 or Category.query.filter(
        func.lower(Category.name) == name.lower(), Category.id != category.id,
    ).first():
        flash("Choose a unique category name.", "error")
    else:
        category.name = name
        category.active = request.form.get("active") == "1"
        audit("category_updated", f"category={category.id}, name={name}")
        db.session.commit()
        flash("Category saved.", "success")
    return redirect(url_for("admin.catalog"))


@bp.post("/coupons")
@login_required
@role_required("admin")
def add_coupon():
    code = clean(request.form.get("code"), 40).upper()
    kind = request.form.get("kind")
    value = parse_whole_number(request.form.get("value"), 1, 1000000)
    minimum = parse_whole_number(request.form.get("minimum") or "0", 0, 10000000)
    max_discount = parse_whole_number(request.form.get("max_discount") or "0", 0, 10000000)
    usage_limit = parse_whole_number(request.form.get("usage_limit") or "0", 0, 10000000)
    if (len(code) < 3 or kind not in {"percent", "fixed"} or value is None
            or minimum is None or max_discount is None or usage_limit is None
            or (kind == "percent" and value > 100)
            or Coupon.query.filter_by(code=code).first()):
        flash("Check the coupon code and values; percentage cannot exceed 100.", "error")
    else:
        db.session.add(Coupon(code=code, kind=kind, value=value, minimum=minimum,
                              max_discount=max_discount, usage_limit=usage_limit))
        audit("coupon_created", code)
        db.session.commit()
        flash("Coupon created.", "success")
    return redirect(url_for("admin.promotions"))


@bp.post("/coupons/<int:coupon_id>")
@login_required
@role_required("admin")
def toggle_coupon(coupon_id):
    coupon = db.get_or_404(Coupon, coupon_id)
    coupon.active = not coupon.active
    audit("coupon_toggled", f"coupon={coupon.code}, active={coupon.active}")
    db.session.commit()
    return redirect(url_for("admin.promotions"))


@bp.get("/promotions")
@login_required
@role_required("admin")
def promotions():
    return render_template(
        "admin/promotions.html",
        coupons=Coupon.query.order_by(Coupon.id.desc()).all(),
        banners=Banner.query.order_by(Banner.sort_order, Banner.id).all(),
    )


@bp.post("/banners")
@login_required
@role_required("admin")
def add_banner():
    title = clean(request.form.get("title"), 100)
    subtitle = clean(request.form.get("subtitle"), 200)
    try:
        image = save_image(request.files.get("image"), "banner")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.promotions"))
    if not title:
        flash("Banner title is required.", "error")
    else:
        db.session.add(Banner(title=title, subtitle=subtitle, image=image))
        audit("banner_created", title)
        db.session.commit()
        flash("Banner added.", "success")
    return redirect(url_for("admin.promotions"))


@bp.post("/banners/<int:banner_id>")
@login_required
@role_required("admin")
def toggle_banner(banner_id):
    banner = db.get_or_404(Banner, banner_id)
    banner.active = not banner.active
    db.session.commit()
    return redirect(url_for("admin.promotions"))


@bp.post("/settings")
@login_required
@role_required("admin")
def settings():
    values = {}
    for key, limit in {
        "site_name": 40, "site_tagline": 180, "owner_name": 80,
        "developer_name": 80, "support_phone": 20, "support_email": 120,
    }.items():
        values[key] = clean(request.form.get(key), limit)
    inside = parse_whole_number(request.form.get("shipping_inside_dhaka"), 0, 5000)
    outside = parse_whole_number(request.form.get("shipping_outside_dhaka"), 0, 5000)
    free = parse_whole_number(request.form.get("free_shipping_minimum"), 0, 1000000)
    commission = request.form.get("commission_percent", "")
    try:
        commission = float(commission)
    except (TypeError, ValueError):
        commission = -1
    if not values["site_name"] or inside is None or outside is None or free is None or not 0 <= commission <= 50:
        flash("Check site name, delivery charges, free shipping threshold, and commission.", "error")
    else:
        values.update(
            shipping_inside_dhaka=inside, shipping_outside_dhaka=outside,
            free_shipping_minimum=free, commission_percent=commission,
        )
        save_settings(values)
        audit("site_settings_updated")
        db.session.commit()
        flash("Marketplace settings saved.", "success")
    return redirect(url_for("admin.settings_page"))


@bp.get("/settings")
@login_required
@role_required("admin")
def settings_page():
    keys = (
        "site_name", "site_tagline", "owner_name", "developer_name", "support_phone",
        "support_email", "shipping_inside_dhaka", "shipping_outside_dhaka",
        "free_shipping_minimum", "commission_percent",
    )
    from .helpers import setting
    values = {key: setting(key) for key in keys}
    users = User.query.order_by(User.id.desc()).limit(200).all()
    messages = SupportMessage.query.order_by(SupportMessage.created_at.desc()).limit(100).all()
    payouts = SellerPayout.query.order_by(
        (SellerPayout.status == "pending").desc(), SellerPayout.created_at.desc(),
    ).limit(200).all()
    return render_template("admin/settings.html", values=values, users=users, messages=messages, payouts=payouts)


@bp.post("/users/<int:user_id>")
@login_required
@role_required("admin")
def toggle_user(user_id):
    user = db.get_or_404(User, user_id)
    if user.role == "admin":
        abort(403)
    user.active = not user.active
    audit("user_access_toggled", f"user={user.id}, active={user.active}")
    db.session.commit()
    flash("Account access updated.", "success")
    return redirect(url_for("admin.settings_page"))


@bp.post("/payouts/<int:payout_id>")
@login_required
@role_required("admin")
def update_payout(payout_id):
    payout = db.get_or_404(SellerPayout, payout_id)
    status = request.form.get("status")
    if payout.status != "pending" or status not in {"paid", "rejected"}:
        flash("Only pending payout requests can be paid or rejected.", "error")
    else:
        payout.status = status
        payout.reference = clean(request.form.get("reference") or payout.reference, 100)
        audit("seller_payout_review", f"payout={payout.id}, status={status}")
        db.session.commit()
        flash("Payout request updated.", "success")
    return redirect(url_for("admin.settings_page"))


@bp.post("/messages/<int:message_id>")
@login_required
@role_required("admin")
def update_message(message_id):
    message = db.get_or_404(SupportMessage, message_id)
    message.status = "closed" if message.status == "open" else "open"
    db.session.commit()
    return redirect(url_for("admin.settings_page"))


@bp.get("/reports.csv")
@login_required
@role_required("admin")
def reports_csv():
    rows = Order.query.order_by(Order.created_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Order", "Date", "Customer", "Phone", "Status", "Payment",
                     "Payment status", "Subtotal", "Discount", "Shipping", "Total"])

    def safe(value):
        value = str(value if value is not None else "")
        return "'" + value if value[:1] in {"=", "+", "-", "@"} else value

    for order in rows:
        writer.writerow([
            order.id, order.created_at.isoformat(), safe(order.name), safe(order.phone),
            safe(order.status), safe(order.payment_method), safe(order.payment_status),
            order.subtotal, order.discount, order.shipping, order.total,
        ])
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=tukiahop-orders.csv"
    return response


def _restore_stock(order):
    for item in OrderItem.query.join(SellerOrder).filter(SellerOrder.order_id == order.id).all():
        if item.product_id:
            product = db.session.get(Product, item.product_id)
            if product:
                product.stock += item.quantity
