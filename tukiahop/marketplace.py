from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_, update

from .extensions import db, limiter
from .helpers import DISTRICTS, clean, normalize_phone, parse_whole_number, save_image, setting
from .models import (
    Address, Banner, Category, Coupon, Order, OrderItem, PaymentMethod,
    PaymentSubmission, Product, Review, SellerOrder, SellerProfile, User,
    SupportMessage, WishlistItem,
)

bp = Blueprint("marketplace", __name__)

PAYMENT_TITLES = {"bkash": "bKash", "nagad": "Nagad", "upay": "Upay", "rocket": "Rocket"}
ORDER_STATUSES = {
    "placed": "Order placed",
    "confirmed": "Confirmed",
    "processing": "Preparing",
    "shipped": "Shipped",
    "delivered": "Delivered",
    "cancel_requested": "Cancellation requested",
    "cancelled": "Cancelled",
}


@bp.app_context_processor
def inject_globals():
    return {
        "site_name": setting("site_name", "TUKISHOP"),
        "site_tagline": setting("site_tagline", "Everything you love, all in one hop."),
    }


@bp.get("/")
def home():
    query = clean(request.args.get("q"), 100)
    category_id = parse_whole_number(request.args.get("category"), 1, 1000000)
    sort = request.args.get("sort", "popular")
    page_number = parse_whole_number(request.args.get("page"), 1, 1000000) or 1
    minimum_price = parse_whole_number(request.args.get("min_price"), 0, 10000000)
    maximum_price = parse_whole_number(request.args.get("max_price"), 0, 10000000)
    products_query = Product.query.join(Category).filter(
        Product.status == "approved", Product.active.is_(True),
        Category.active.is_(True),
    )
    if query:
        term = f"%{query}%"
        products_query = products_query.filter(or_(Product.name.ilike(term), Product.description.ilike(term)))
    if category_id:
        products_query = products_query.filter(Product.category_id == category_id)
    if minimum_price is not None:
        products_query = products_query.filter(Product.price >= minimum_price)
    if maximum_price is not None:
        products_query = products_query.filter(Product.price <= maximum_price)
    if request.args.get("in_stock") == "1":
        products_query = products_query.filter(Product.stock > 0)
    if sort == "price_asc":
        products_query = products_query.order_by(Product.price.asc(), Product.id.desc())
    elif sort == "price_desc":
        products_query = products_query.order_by(Product.price.desc(), Product.id.desc())
    else:
        products_query = products_query.order_by(Product.id.desc())
    pagination = products_query.paginate(page=page_number, per_page=24, error_out=False)
    products = pagination.items
    categories = Category.query.filter_by(active=True).order_by(Category.name).all()
    banners = Banner.query.filter_by(active=True).order_by(Banner.sort_order, Banner.id).all()
    return render_template("marketplace/home.html", products=products, categories=categories,
                           banners=banners, query=query, selected_category=category_id,
                           sort=sort, pagination=pagination, minimum_price=minimum_price,
                           maximum_price=maximum_price, in_stock=request.args.get("in_stock") == "1")


@bp.get("/product/<int:product_id>")
def product_detail(product_id):
    product = Product.query.filter_by(id=product_id, status="approved", active=True).first_or_404()
    reviews = Review.query.filter_by(product_id=product.id, active=True).order_by(Review.created_at.desc()).limit(30).all()
    seller = product.seller
    avg = round(sum(review.stars for review in reviews) / len(reviews), 1) if reviews else None
    return render_template("marketplace/product.html", product=product, reviews=reviews, average=avg, seller=seller)


@bp.post("/wishlist/<int:product_id>")
@login_required
def toggle_wishlist(product_id):
    product = Product.query.filter_by(id=product_id, status="approved", active=True).first_or_404()
    saved = WishlistItem.query.filter_by(user_id=current_user.id, product_id=product.id).first()
    if saved:
        db.session.delete(saved)
        flash("Removed from your wishlist.", "info")
    else:
        db.session.add(WishlistItem(user_id=current_user.id, product_id=product.id))
        flash("Added to your wishlist.", "success")
    db.session.commit()
    return redirect(request.referrer or url_for("marketplace.product_detail", product_id=product.id))


@bp.get("/wishlist")
@login_required
def wishlist():
    rows = WishlistItem.query.filter_by(user_id=current_user.id).order_by(WishlistItem.id.desc()).all()
    products = [db.session.get(Product, row.product_id) for row in rows]
    return render_template("marketplace/wishlist.html", products=[p for p in products if p and p.active])


@bp.route("/cart", methods=["GET", "POST"])
def cart():
    if request.method == "POST":
        cart_data = {}
        for key, value in request.form.items():
            if not key.startswith("qty_"):
                continue
            product_id = parse_whole_number(key[4:], 1, 100000000)
            quantity = parse_whole_number(value, 0, 20)
            if product_id is not None and quantity is not None:
                if quantity:
                    cart_data[str(product_id)] = quantity
        session["cart"] = cart_data
        session.modified = True
        flash("Cart updated.", "success")
        return redirect(url_for("marketplace.cart"))
    products = _cart_products()
    subtotal = sum(product.price * quantity for product, quantity in products)
    return render_template("marketplace/cart.html", products=products, subtotal=subtotal)


@bp.post("/cart/add/<int:product_id>")
def cart_add(product_id):
    product = Product.query.filter_by(id=product_id, status="approved", active=True).first_or_404()
    if product.stock <= 0:
        flash("This product is out of stock.", "error")
    else:
        cart_data = dict(session.get("cart", {}))
        current = parse_whole_number(cart_data.get(str(product_id), 0), 0, 20) or 0
        cart_data[str(product_id)] = min(current + 1, product.stock, 20)
        session["cart"] = cart_data
        flash("Added to cart.", "success")
    return redirect(request.referrer or url_for("marketplace.home"))


@bp.get("/checkout")
@login_required
def checkout():
    products = _cart_products()
    if not products:
        flash("Your cart is empty.", "error")
        return redirect(url_for("marketplace.cart"))
    subtotal = sum(product.price * quantity for product, quantity in products)
    methods = PaymentMethod.query.filter_by(enabled=True).order_by(PaymentMethod.sort_order).all()
    addresses = Address.query.filter_by(user_id=current_user.id).order_by(Address.is_default.desc(), Address.id.desc()).all()
    return render_template("marketplace/checkout.html", products=products, subtotal=subtotal,
                           methods=methods, addresses=addresses, districts=DISTRICTS)


@bp.post("/checkout")
@login_required
def place_order():
    products = _cart_products()
    if not products:
        flash("Your cart is empty.", "error")
        return redirect(url_for("marketplace.cart"))
    saved_address_id = parse_whole_number(request.form.get("address_id"), 1, 100000000)
    saved_address = Address.query.filter_by(id=saved_address_id, user_id=current_user.id).first() if saved_address_id else None
    name = clean(saved_address.recipient if saved_address else request.form.get("name"), 100)
    phone = normalize_phone(saved_address.phone if saved_address else request.form.get("phone"))
    district = clean(saved_address.district if saved_address else request.form.get("district"), 60)
    upazila = clean(saved_address.upazila if saved_address else request.form.get("upazila"), 80)
    address = clean(saved_address.address if saved_address else request.form.get("address"), 300)
    method = clean(request.form.get("payment_method"), 20)
    enabled_methods = {row.slug for row in PaymentMethod.query.filter_by(enabled=True).all()}
    if method not in enabled_methods | {"cod"}:
        flash("Choose an available payment method.", "error")
        return redirect(url_for("marketplace.checkout"))
    if not name or not phone or district not in DISTRICTS or len(upazila) < 2 or len(address) < 5:
        flash("Check your name, Bangladesh phone number, district, area, and full address.", "error")
        return redirect(url_for("marketplace.checkout"))

    refreshed = []
    for product, quantity in products:
        current = Product.query.filter_by(id=product.id, status="approved", active=True).with_for_update().first()
        if not current or current.stock < quantity:
            flash(f"Not enough stock for {product.name}. Please update your cart.", "error")
            return redirect(url_for("marketplace.cart"))
        refreshed.append((current, quantity))
    subtotal = sum(product.price * quantity for product, quantity in refreshed)
    coupon_code = clean(request.form.get("coupon_code"), 40).upper()
    coupon, discount = _coupon_discount(coupon_code, subtotal)
    if coupon_code and coupon is None:
        flash("That coupon is invalid, expired, or does not meet its minimum order.", "error")
        return redirect(url_for("marketplace.checkout"))
    grouped = defaultdict(list)
    for product, quantity in refreshed:
        grouped[product.seller_id].append((product, quantity))
    inside = district == "Dhaka"
    shipping_rate = parse_whole_number(
        setting("shipping_inside_dhaka" if inside else "shipping_outside_dhaka", "60" if inside else "120"),
        0, 5000,
    ) or 0
    free_minimum = parse_whole_number(setting("free_shipping_minimum", "5000"), 0, 1000000) or 0
    total_shipping = 0 if free_minimum and subtotal >= free_minimum else shipping_rate * len(grouped)
    total = subtotal - discount + total_shipping
    order = Order(
        customer_id=current_user.id, name=name, phone=phone, district=district,
        upazila=upazila, address=address, subtotal=subtotal, discount=discount,
        shipping=total_shipping, total=total, coupon_code=coupon.code if coupon else "",
        payment_method=method, payment_status="unpaid" if method == "cod" else "pending",
    )
    for seller_id, lines in grouped.items():
        seller_subtotal = sum(product.price * quantity for product, quantity in lines)
        if total_shipping == 0:
            seller_shipping = 0
        else:
            seller_shipping = shipping_rate
        seller = db.session.get(SellerProfile, seller_id) if seller_id else None
        commission_rate = float(seller.commission_percent) if seller else float(setting("commission_percent", "10"))
        commission = round(seller_subtotal * commission_rate / 100)
        seller_order = SellerOrder(
            order=order, seller_id=seller_id, subtotal=seller_subtotal,
            shipping=seller_shipping, commission=commission,
        )
        db.session.add(seller_order)
        for product, quantity in lines:
            affected = db.session.execute(
                update(Product).where(Product.id == product.id, Product.stock >= quantity)
                .values(stock=Product.stock - quantity)
            ).rowcount
            if affected != 1:
                db.session.rollback()
                flash(f"Stock changed for {product.name}. Please try again.", "error")
                return redirect(url_for("marketplace.cart"))
            db.session.add(OrderItem(
                seller_order=seller_order, product_id=product.id, product_name=product.name,
                unit_price=product.price, quantity=quantity,
            ))
    if coupon:
        coupon.used_count += 1
    db.session.add(order)
    db.session.flush()
    db.session.commit()
    session["cart"] = {}
    flash(f"Order #{order.id} placed. Complete payment submission if you chose mobile banking.", "success")
    return redirect(url_for("marketplace.order_detail", order_id=order.id))


@bp.get("/account/orders")
@login_required
def my_orders():
    orders = Order.query.filter_by(customer_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template("marketplace/orders.html", orders=orders, statuses=ORDER_STATUSES)


@bp.get("/account/avatar")
@login_required
def profile_avatar():
    if not current_user.avatar:
        abort(404)
    return send_from_directory(current_app.config["PRIVATE_UPLOAD_FOLDER"], current_user.avatar)


@bp.route("/account/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        name = clean(request.form.get("name"), 100)
        phone = normalize_phone(request.form.get("phone"))
        phone_in_use = User.query.filter(
            User.phone == phone, User.id != current_user.id,
        ).first() if phone else None
        if not name or not phone:
            flash("Enter your name and a valid Bangladesh mobile number.", "error")
        elif phone_in_use:
            flash("That phone number is already registered to another account.", "error")
        else:
            try:
                avatar_filename = save_image(request.files.get("avatar"), "avatar")
            except ValueError as exc:
                flash(str(exc), "error")
            else:
                old_avatar = current_user.avatar
                current_user.name = name
                current_user.phone = phone
                if avatar_filename:
                    current_user.avatar = avatar_filename
                db.session.commit()
                if (
                    avatar_filename and old_avatar
                    and Path(old_avatar).name == old_avatar
                    and old_avatar.startswith("avatar-")
                ):
                    old_path = Path(current_app.config["PRIVATE_UPLOAD_FOLDER"]) / old_avatar
                    try:
                        old_path.unlink(missing_ok=True)
                    except OSError:
                        current_app.logger.exception("Unable to remove previous user avatar")
                flash("Your profile details were updated.", "success")
                return redirect(url_for("marketplace.profile"))

    addresses = Address.query.filter_by(user_id=current_user.id).order_by(
        Address.is_default.desc(), Address.id.desc(),
    ).all()
    return render_template(
        "marketplace/profile.html",
        addresses=addresses,
        order_count=Order.query.filter_by(customer_id=current_user.id).count(),
        wishlist_count=WishlistItem.query.filter_by(user_id=current_user.id).count(),
    )


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        if not current_user.check_password(current):
            flash("Current password is incorrect.", "error")
        elif len(new) < 10 or len(new) > 200 or new == current:
            flash("Choose a different password with at least 10 characters.", "error")
        else:
            current_user.set_password(new)
            db.session.commit()
            flash("Password changed successfully.", "success")
            return redirect(url_for("marketplace.change_password"))
    return render_template("marketplace/password.html")


@bp.route("/account/addresses", methods=["GET", "POST"])
@login_required
def addresses():
    if request.method == "POST":
        label = clean(request.form.get("label") or "Home", 40)
        recipient = clean(request.form.get("recipient"), 100)
        phone = normalize_phone(request.form.get("phone"))
        district = clean(request.form.get("district"), 60)
        upazila = clean(request.form.get("upazila"), 80)
        address = clean(request.form.get("address"), 300)
        if not recipient or not phone or district not in DISTRICTS or len(upazila) < 2 or len(address) < 5:
            flash("Check the recipient, phone, district, area, and full address.", "error")
        else:
            is_default = request.form.get("is_default") == "1"
            if is_default:
                Address.query.filter_by(user_id=current_user.id).update({"is_default": False})
            saved = Address(
                user_id=current_user.id, label=label, recipient=recipient, phone=phone,
                district=district, upazila=upazila, address=address,
                is_default=is_default,
            )
            db.session.add(saved)
            db.session.commit()
            flash("Delivery address saved.", "success")
            return redirect(url_for("marketplace.addresses"))
    saved_addresses = Address.query.filter_by(user_id=current_user.id).order_by(
        Address.is_default.desc(), Address.id.desc(),
    ).all()
    return render_template("marketplace/addresses.html", addresses=saved_addresses, districts=DISTRICTS)


@bp.post("/account/addresses/<int:address_id>/delete")
@login_required
def delete_address(address_id):
    saved = Address.query.filter_by(id=address_id, user_id=current_user.id).first_or_404()
    db.session.delete(saved)
    db.session.commit()
    flash("Address deleted.", "info")
    return redirect(url_for("marketplace.addresses"))


@bp.post("/account/addresses/<int:address_id>/default")
@login_required
def default_address(address_id):
    saved = Address.query.filter_by(id=address_id, user_id=current_user.id).first_or_404()
    Address.query.filter_by(user_id=current_user.id).update({"is_default": False})
    saved.is_default = True
    db.session.commit()
    flash("Default address updated.", "success")
    return redirect(url_for("marketplace.addresses"))


@bp.route("/contact", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def contact():
    if request.method == "POST":
        name = clean(request.form.get("name"), 100)
        phone = normalize_phone(request.form.get("phone"))
        message = clean(request.form.get("message"), 1000)
        if not name or not phone or len(message) < 5:
            flash("Enter your name, a Bangladesh mobile number, and a message.", "error")
        else:
            db.session.add(SupportMessage(
                user_id=current_user.id if current_user.is_authenticated else None,
                name=name, phone=phone, message=message,
            ))
            db.session.commit()
            flash("Your message was sent to TUKISHOP support.", "success")
            return redirect(url_for("marketplace.contact"))
    return render_template("marketplace/contact.html")


@bp.get("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = Order.query.filter_by(id=order_id, customer_id=current_user.id).first_or_404()
    methods = {method.slug: method for method in PaymentMethod.query.all()}
    submissions = PaymentSubmission.query.filter_by(order_id=order.id).order_by(PaymentSubmission.created_at.desc()).all()
    return render_template("marketplace/order_detail.html", order=order, methods=methods,
                           submissions=submissions, statuses=ORDER_STATUSES)


@bp.post("/orders/<int:order_id>/payment")
@login_required
def submit_payment(order_id):
    order = Order.query.filter_by(id=order_id, customer_id=current_user.id).first_or_404()
    if order.payment_method == "cod" or order.payment_status in {"paid", "refund_pending", "refunded"}:
        abort(400)
    if PaymentSubmission.query.filter_by(order_id=order.id, status="pending").first():
        flash("A payment submission is already waiting for verification.", "info")
        return redirect(url_for("marketplace.order_detail", order_id=order.id))
    method = PaymentMethod.query.filter_by(slug=order.payment_method, enabled=True).first()
    if not method:
        flash("That payment method is currently unavailable. Contact support.", "error")
        return redirect(url_for("marketplace.order_detail", order_id=order.id))
    sender = normalize_phone(request.form.get("sender_number"))
    transaction_id = clean(request.form.get("transaction_id"), 80).upper()
    if not sender or not 4 <= len(transaction_id) <= 80:
        flash("Enter a valid sender number and transaction ID.", "error")
        return redirect(url_for("marketplace.order_detail", order_id=order.id))
    if PaymentSubmission.query.filter_by(transaction_id=transaction_id).first():
        flash("That transaction ID has already been submitted.", "error")
        return redirect(url_for("marketplace.order_detail", order_id=order.id))
    try:
        receipt = save_image(request.files.get("receipt"), "receipt")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("marketplace.order_detail", order_id=order.id))
    submission = PaymentSubmission(
        order_id=order.id, method=method.slug, sender_number=sender,
        transaction_id=transaction_id, receipt_image=receipt,
    )
    db.session.add(submission)
    order.payment_status = "pending"
    db.session.commit()
    flash("Payment details submitted for admin verification.", "success")
    return redirect(url_for("marketplace.order_detail", order_id=order.id))


@bp.post("/orders/<int:order_id>/cancel")
@login_required
def request_cancel(order_id):
    order = Order.query.filter_by(id=order_id, customer_id=current_user.id).first_or_404()
    if order.status != "placed":
        flash("Cancellation is only available before the seller confirms the order.", "error")
    else:
        order.status = "cancel_requested"
        for seller_order in order.seller_orders:
            seller_order.status = "cancel_requested"
        db.session.commit()
        flash("Cancellation request sent to TUKISHOP support.", "success")
    return redirect(url_for("marketplace.order_detail", order_id=order.id))


@bp.post("/product/<int:product_id>/review")
@login_required
def add_review(product_id):
    product = Product.query.filter_by(id=product_id, status="approved", active=True).first_or_404()
    delivered = db.session.query(OrderItem.id).join(SellerOrder).join(Order).filter(
        Order.customer_id == current_user.id, Order.status == "delivered",
        OrderItem.product_id == product.id,
    ).first()
    if not delivered:
        abort(403)
    stars = parse_whole_number(request.form.get("stars"), 1, 5)
    text = clean(request.form.get("text"), 1000)
    if stars is None or len(text) < 3:
        flash("Select a rating and write at least a few words.", "error")
    else:
        review = Review.query.filter_by(product_id=product.id, customer_id=current_user.id).first()
        if review is None:
            review = Review(product_id=product.id, customer_id=current_user.id)
            db.session.add(review)
        review.stars, review.text = stars, text
        db.session.commit()
        flash("Verified review submitted.", "success")
    return redirect(url_for("marketplace.product_detail", product_id=product.id))


@bp.get("/seller/<int:seller_id>")
def seller_store(seller_id):
    seller = SellerProfile.query.filter_by(id=seller_id, status="approved").first_or_404()
    products = Product.query.filter_by(seller_id=seller.id, status="approved", active=True).order_by(Product.id.desc()).all()
    return render_template("marketplace/store.html", seller=seller, products=products)


@bp.get("/privacy")
def privacy():
    return render_template("marketplace/legal.html", title="Privacy policy", kind="privacy")


@bp.get("/terms")
def terms():
    return render_template("marketplace/legal.html", title="Terms & conditions", kind="terms")


def _cart_products():
    cart_data = session.get("cart", {})
    if not isinstance(cart_data, dict):
        session["cart"] = {}
        return []
    products = []
    for key, value in cart_data.items():
        product_id = parse_whole_number(key, 1, 100000000)
        quantity = parse_whole_number(value, 1, 20)
        if product_id is None or quantity is None:
            continue
        product = Product.query.filter_by(id=product_id, status="approved", active=True).first()
        if product and product.stock:
            products.append((product, min(quantity, product.stock)))
    return products


def _coupon_discount(code, subtotal):
    if not code:
        return None, 0
    coupon = Coupon.query.filter_by(code=code, active=True).first()
    if not coupon or subtotal < coupon.minimum:
        return None, 0
    now = datetime.now(timezone.utc)
    if coupon.starts_at and coupon.starts_at > now:
        return None, 0
    if coupon.ends_at and coupon.ends_at < now:
        return None, 0
    if coupon.usage_limit and coupon.used_count >= coupon.usage_limit:
        return None, 0
    discount = round(subtotal * coupon.value / 100) if coupon.kind == "percent" else coupon.value
    if coupon.max_discount:
        discount = min(discount, coupon.max_discount)
    return coupon, min(max(discount, 0), subtotal)
