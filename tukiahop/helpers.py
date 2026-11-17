import os
import re
import secrets
from functools import wraps
from io import BytesIO
from pathlib import Path

from flask import abort, current_app, flash, redirect, request, url_for
from flask_login import current_user
from PIL import Image, ImageOps
from werkzeug.utils import secure_filename

from .extensions import db
from .models import AuditLog, SiteSetting

DISTRICTS = (
    "Bagerhat", "Bandarban", "Barguna", "Barishal", "Bhola", "Bogura",
    "Brahmanbaria", "Chandpur", "Chapainawabganj", "Chattogram",
    "Chuadanga", "Cox's Bazar", "Cumilla", "Dhaka", "Dinajpur", "Faridpur",
    "Feni", "Gaibandha", "Gazipur", "Gopalganj", "Habiganj", "Jamalpur",
    "Jashore", "Jhalokathi", "Jhenaidah", "Joypurhat", "Khagrachhari",
    "Khulna", "Kishoreganj", "Kurigram", "Kushtia", "Lakshmipur",
    "Lalmonirhat", "Madaripur", "Magura", "Manikganj", "Meherpur",
    "Moulvibazar", "Munshiganj", "Mymensingh", "Naogaon", "Narail",
    "Narayanganj", "Narsingdi", "Natore", "Netrokona", "Nilphamari",
    "Noakhali", "Pabna", "Panchagarh", "Patuakhali", "Pirojpur", "Rajbari",
    "Rajshahi", "Rangamati", "Rangpur", "Satkhira", "Shariatpur",
    "Sherpur", "Sirajganj", "Sunamganj", "Sylhet", "Tangail", "Thakurgaon",
)


def setting(key, default=""):
    row = db.session.get(SiteSetting, key)
    return row.value if row else default


def save_settings(values):
    for key, value in values.items():
        row = db.session.get(SiteSetting, key)
        if row is None:
            row = SiteSetting(key=key, value=str(value))
            db.session.add(row)
        else:
            row.value = str(value)


def audit(action, details=""):
    db.session.add(AuditLog(
        actor_id=current_user.id if current_user.is_authenticated else None,
        action=action[:100],
        details=details[:500],
    ))


def role_required(*roles):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login", next=request.path))
            if not current_user.active or current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorate


def clean(value, limit):
    return " ".join(str(value or "").split())[:limit]


def normalize_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("880") and len(digits) == 13:
        digits = "0" + digits[3:]
    return digits if re.fullmatch(r"01[3-9]\d{8}", digits) else None


def save_image(file, prefix="product"):
    if not file or not file.filename:
        return ""
    filename = secure_filename(file.filename)
    if not filename or len(file.read(1)) == 0:
        file.seek(0)
        return ""
    file.seek(0)
    data = file.read(4 * 1024 * 1024 + 1)
    if len(data) > 4 * 1024 * 1024:
        raise ValueError("Image must be 4 MB or smaller.")
    try:
        image = Image.open(BytesIO(data))
        if image.format not in {"JPEG", "PNG", "WEBP"}:
            raise ValueError("Use a JPG, PNG, or WEBP image.")
        image.verify()
        image = ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB")
        image.thumbnail((1200, 1200))
        name = f"{prefix}-{secrets.token_hex(16)}.jpg"
        folder = current_app.config["PRIVATE_UPLOAD_FOLDER"] if prefix in {"receipt", "avatar"} else current_app.config["UPLOAD_FOLDER"]
        image.save(Path(folder) / name, "JPEG", quality=84, optimize=True)
        return name
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("That image could not be processed.") from exc


def image_url(filename):
    return os.path.join("uploads", filename) if filename else ""


def parse_whole_number(value, minimum=0, maximum=1000000):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if minimum <= number <= maximum else None


def flash_error(message):
    flash(message, "error")
