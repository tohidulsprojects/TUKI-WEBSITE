from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(40), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(20), unique=True, nullable=False, index=True)
    avatar = db.Column(db.String(100), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="customer", index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class SellerProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    shop_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    commission_percent = db.Column(db.Numeric(5, 2), nullable=False, default=10)
    payout_method = db.Column(db.String(20), nullable=False, default="")
    payout_number = db.Column(db.String(30), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    user = db.relationship("User", backref=db.backref("seller_profile", uselist=False))


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("seller_profile.id"), nullable=True, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False, index=True)
    name = db.Column(db.String(140), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    price = db.Column(db.Integer, nullable=False)
    old_price = db.Column(db.Integer, nullable=False, default=0)
    stock = db.Column(db.Integer, nullable=False, default=0)
    image = db.Column(db.String(100), nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    category = db.relationship("Category")
    seller = db.relationship("SellerProfile")


class Address(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    label = db.Column(db.String(40), nullable=False, default="Home")
    recipient = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    district = db.Column(db.String(60), nullable=False)
    upazila = db.Column(db.String(80), nullable=False)
    address = db.Column(db.String(300), nullable=False)
    is_default = db.Column(db.Boolean, nullable=False, default=False)


class Coupon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False, default="percent")
    value = db.Column(db.Integer, nullable=False)
    minimum = db.Column(db.Integer, nullable=False, default=0)
    max_discount = db.Column(db.Integer, nullable=False, default=0)
    usage_limit = db.Column(db.Integer, nullable=False, default=0)
    used_count = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)
    starts_at = db.Column(db.DateTime(timezone=True))
    ends_at = db.Column(db.DateTime(timezone=True))


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    district = db.Column(db.String(60), nullable=False)
    upazila = db.Column(db.String(80), nullable=False)
    address = db.Column(db.String(300), nullable=False)
    subtotal = db.Column(db.Integer, nullable=False)
    discount = db.Column(db.Integer, nullable=False, default=0)
    shipping = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    coupon_code = db.Column(db.String(40), nullable=False, default="")
    payment_method = db.Column(db.String(20), nullable=False)
    payment_status = db.Column(db.String(20), nullable=False, default="unpaid", index=True)
    status = db.Column(db.String(20), nullable=False, default="placed", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    customer = db.relationship("User")
    seller_orders = db.relationship("SellerOrder", backref="order", cascade="all, delete-orphan")


class SellerOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False, index=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("seller_profile.id"), nullable=True, index=True)
    subtotal = db.Column(db.Integer, nullable=False)
    shipping = db.Column(db.Integer, nullable=False)
    commission = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="placed", index=True)
    payout_status = db.Column(db.String(20), nullable=False, default="unsettled")
    seller = db.relationship("SellerProfile")
    items = db.relationship("OrderItem", backref="seller_order", cascade="all, delete-orphan")


class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_order_id = db.Column(db.Integer, db.ForeignKey("seller_order.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=True)
    product_name = db.Column(db.String(140), nullable=False)
    unit_price = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, nullable=False)


class PaymentMethod(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(20), unique=True, nullable=False)
    title = db.Column(db.String(40), nullable=False)
    account_number = db.Column(db.String(30), nullable=False, default="")
    account_type = db.Column(db.String(20), nullable=False, default="personal")
    instructions = db.Column(db.String(500), nullable=False, default="")
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)


class PaymentSubmission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("order.id"), nullable=False, index=True)
    method = db.Column(db.String(20), nullable=False)
    sender_number = db.Column(db.String(20), nullable=False)
    transaction_id = db.Column(db.String(80), unique=True, nullable=False, index=True)
    receipt_image = db.Column(db.String(100), nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    note = db.Column(db.String(300), nullable=False, default="")
    reviewed_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    reviewed_at = db.Column(db.DateTime(timezone=True))
    order = db.relationship("Order")


class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    stars = db.Column(db.Integer, nullable=False)
    text = db.Column(db.String(1000), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    customer = db.relationship("User")
    product = db.relationship("Product")
    __table_args__ = (db.UniqueConstraint("product_id", "customer_id"),)


class WishlistItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False, index=True)
    __table_args__ = (db.UniqueConstraint("user_id", "product_id"),)


class Banner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    subtitle = db.Column(db.String(200), nullable=False, default="")
    image = db.Column(db.String(100), nullable=False, default="")
    active = db.Column(db.Boolean, nullable=False, default=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)


class SiteSetting(db.Model):
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")


class SupportMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    message = db.Column(db.String(1000), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.String(500), nullable=False, default="")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class SellerPayout(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey("seller_profile.id"), nullable=False, index=True)
    amount = db.Column(db.Integer, nullable=False)
    method = db.Column(db.String(20), nullable=False)
    reference = db.Column(db.String(100), nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    seller = db.relationship("SellerProfile")
