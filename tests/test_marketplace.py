import unittest
from io import BytesIO
from tempfile import TemporaryDirectory

from PIL import Image

from tukiahop import create_app
from tukiahop.extensions import db
from tukiahop.models import (
    Category, Order, PaymentMethod, PaymentSubmission, Product,
    SellerProfile, User,
)


class MarketplaceFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "UPLOAD_FOLDER": self.temp.name + "/public",
            "PRIVATE_UPLOAD_FOLDER": self.temp.name + "/private",
            "RATELIMIT_ENABLED": False,
        })
        result = self.app.test_cli_runner().invoke(args=["init-db"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.client = self.app.test_client()
        with self.app.app_context():
            category = Category.query.filter_by(name="Fashion").first()
            seller = User(name="Seller One", username="sellerone", phone="01711111111", role="seller")
            seller.set_password("seller-password-123")
            db.session.add(seller)
            db.session.flush()
            profile = SellerProfile(user_id=seller.id, shop_name="One Shop", status="approved", commission_percent=10)
            db.session.add(profile)
            db.session.flush()
            db.session.add(Product(
                seller_id=profile.id, category_id=category.id, name="Test shirt",
                description="Cotton shirt", price=1000, stock=5, status="approved",
            ))
            admin = User(name="Admin", username="adminuser", phone="01722222222", role="admin")
            admin.set_password("admin-password-123")
            db.session.add(admin)
            wallet = PaymentMethod.query.filter_by(slug="bkash").first()
            wallet.account_number = "01700000000"
            wallet.account_type = "merchant"
            wallet.enabled = True
            db.session.commit()
        self.customer = self.client
        response = self.customer.post("/register", data={
            "name": "Buyer One", "username": "buyerone", "phone": "01733333333",
            "password": "buyer-password-123",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn(b"TUKISHOP", self.customer.get("/").data)
        self.assertEqual(self.customer.get("/product/1").status_code, 200)
        self.assertEqual(self.customer.get("/account/addresses").status_code, 200)
        self.assertEqual(self.customer.get("/account/password").status_code, 200)

    def tearDown(self):
        with self.app.app_context():
            db.engine.dispose()
        self.temp.cleanup()

    def test_account_actions_are_inside_profile_menu(self):
        body = self.customer.get("/").data
        menu_start = body.index(b'<details class="profile-menu">')
        menu_end = body.index(b"</details>", menu_start)
        profile_menu = body[menu_start:menu_end]
        for detail in (b"Buyer One", b"@buyerone", b"01733333333"):
            self.assertIn(detail, profile_menu)
        for action in (b"My profile", b"My orders", b"Change password", b"Log out"):
            self.assertIn(action, profile_menu)
            self.assertNotIn(action, body[:menu_start])

    def test_supplied_logo_is_rendered_and_served_as_favicon(self):
        body = self.customer.get("/").data
        self.assertIn(b'<img class="brand-logo" src="/static/logo.png"', body)
        self.assertIn(b'rel="icon" type="image/png" href="/static/logo.png"', body)
        logo = self.customer.get("/static/logo.png")
        self.assertEqual(logo.status_code, 200)
        self.assertEqual(logo.mimetype, "image/png")
        logo.close()

    def test_profile_updates_personal_details_and_displays_addresses(self):
        response = self.customer.post("/account/profile", data={
            "name": "Updated Buyer", "phone": "01733333334",
        })
        self.assertEqual(response.status_code, 302)
        response = self.customer.post("/account/addresses", data={
            "label": "Home", "recipient": "Updated Buyer", "phone": "01733333334",
            "district": "Dhaka", "upazila": "Dhanmondi",
            "address": "House 1, Road 2", "is_default": "1",
        })
        self.assertEqual(response.status_code, 302)
        body = self.customer.get("/account/profile").data
        self.assertIn(b"Updated Buyer", body)
        self.assertIn(b"01733333334", body)
        self.assertIn(b"House 1, Road 2", body)
        self.assertIn(b"Dhanmondi, Dhaka", body)

    def test_customer_can_upload_profile_photo(self):
        image = BytesIO()
        Image.new("RGB", (8, 8), (65, 75, 210)).save(image, format="PNG")
        image.seek(0)
        response = self.customer.post("/account/profile", data={
            "name": "Buyer One", "phone": "01733333333",
            "avatar": (image, "profile.png"),
        })
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            avatar = User.query.filter_by(username="buyerone").one().avatar
            self.assertTrue(avatar.startswith("avatar-"))
        image_response = self.customer.get("/account/avatar")
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.mimetype, "image/jpeg")
        image_response.close()
        self.assertEqual(self.customer.get(f"/static/uploads/{avatar}").status_code, 404)
        self.assertIn(b"profile-avatar-image", self.customer.get("/").data)

    def test_multi_seller_checkout_and_manual_payment_verification(self):
        with self.app.app_context():
            category = Category.query.filter_by(name="Fashion").first()
            seller = User(name="Seller Two", username="sellertwo", phone="01744444444", role="seller")
            seller.set_password("seller-password-123")
            db.session.add(seller)
            db.session.flush()
            profile = SellerProfile(user_id=seller.id, shop_name="Two Shop", status="approved")
            db.session.add(profile)
            db.session.flush()
            db.session.add(Product(
                seller_id=profile.id, category_id=category.id, name="Test shoes",
                description="Everyday shoes", price=2000, stock=3, status="approved",
            ))
            db.session.commit()

        self.customer.post("/cart/add/1")
        self.customer.post("/cart/add/2")
        self.assertEqual(self.customer.get("/checkout").status_code, 200)
        response = self.customer.post("/checkout", data={
            "name": "Buyer One", "phone": "01733333333",
            "district": "Dhaka", "upazila": "Dhanmondi",
            "address": "House 1, Road 2, Dhaka", "payment_method": "bkash",
        })
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            order = Order.query.one()
            self.assertEqual(order.payment_method, "bkash")
            self.assertEqual(order.total, 3120)
            self.assertEqual(len(order.seller_orders), 2)
            self.assertEqual(order.payment_status, "pending")
            order_id = order.id

        response = self.customer.post(f"/orders/{order_id}/payment", data={
            "sender_number": "01755555555", "transaction_id": "TXN-TEST-1",
        })
        self.assertEqual(response.status_code, 302)

        admin = self.app.test_client()
        response = admin.post("/login", data={
            "identifier": "adminuser", "password": "admin-password-123",
        })
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(b">Admin</a>", admin.get("/").data)
        for path in (
            "/admin/", "/admin/sellers", "/admin/products", "/admin/reviews",
            "/admin/orders", "/admin/payments", "/admin/catalog",
            "/admin/promotions", "/admin/settings",
        ):
            self.assertEqual(admin.get(path).status_code, 200, path)
        with self.app.app_context():
            submission = PaymentSubmission.query.one()
            submission_id = submission.id
        response = admin.post(f"/admin/payments/{submission_id}", data={
            "decision": "verified", "note": "Checked against wallet statement",
        })
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(db.session.get(Order, order_id).payment_status, "paid")
            self.assertEqual(PaymentSubmission.query.one().reviewed_by, User.query.filter_by(role="admin").one().id)

    def test_unapproved_seller_cannot_list_products_and_admin_is_protected(self):
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/seller/register", data={
            "shop_name": "Pending Store", "description": "A new seller",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/seller/").status_code, 200)
        self.assertEqual(self.client.get("/seller/products").status_code, 200)
        with self.app.app_context():
            profile = SellerProfile.query.filter_by(shop_name="Pending Store").one()
            self.assertEqual(profile.status, "pending")
            self.assertFalse(Product.query.filter_by(seller_id=profile.id).first())


if __name__ == "__main__":
    unittest.main()
