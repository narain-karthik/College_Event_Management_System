#!/usr/bin/env python3
"""
College Event Booking & Management System - single-file Flask app.

This variant fixes compatibility with SQLAlchemy 2.x by using connection
objects instead of Engine.execute(). It also contains an `ensure_schema`
helper that creates missing tables and adds missing columns (development use).

Run:
    pip install -r requirements.txt
    pip install "qrcode[pil]" pillow reportlab  # optional QR/PDF/email helpers
    python app.py

Notes:
- For production, use Alembic migrations and backups instead of this ad-hoc schema updater.
- This file contains added role-based functionality:
  - Admin: manage email settings, manage users (roles/active), manage events
  - Student: view/book events, receive PDF ticket and notifications on event creation
  - Faculty: view bookings and mark faculty approval
  - Organizer: create/manage events, view bookings and give organizer approval
"""
import os
import uuid
from datetime import datetime
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template, redirect, url_for, flash,
    send_from_directory, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user, current_user, login_required
)
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text

# Optional libs
try:
    import qrcode
except Exception:
    qrcode = None

try:
    from flask_mail import Mail, Message
except Exception:
    Mail = None
    Message = None

# PDF/Imaging optional
have_reportlab = True
have_pillow = True
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm
except Exception:
    have_reportlab = False
try:
    from PIL import Image
except Exception:
    have_pillow = False

# -----------------------
# Config
# -----------------------
from werkzeug.middleware.proxy_fix import ProxyFix

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
POSTER_FOLDER = os.path.join(UPLOAD_FOLDER, "posters")
TICKET_FOLDER = os.path.join(UPLOAD_FOLDER, "tickets")
INVITATION_FOLDER = os.path.join(UPLOAD_FOLDER, "invitations")
GALLERY_FOLDER = os.path.join(UPLOAD_FOLDER, "gallery")
os.makedirs(POSTER_FOLDER, exist_ok=True)
os.makedirs(TICKET_FOLDER, exist_ok=True)
os.makedirs(INVITATION_FOLDER, exist_ok=True)
os.makedirs(GALLERY_FOLDER, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SESSION_SECRET") or "dev-secret-key"
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL") or "sqlite:///college_events.db"
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # 64MB

# Default mail config (overridden by DB settings when set)
app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER", "")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 0) or 0)
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD", "")
app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "").lower() in ("1", "true", "yes")
app.config["MAIL_USE_SSL"] = os.environ.get("MAIL_USE_SSL", "").lower() in ("1", "true", "yes")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER", "noreply@example.com")

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# Mail instance (initialized/overridden by load_email_settings)
mail = None

# -----------------------
# Models
# -----------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, unique=True, nullable=True)
    student_id = db.Column(db.String, unique=True, nullable=True)
    password_hash = db.Column(db.String, nullable=False)
    full_name = db.Column(db.String)
    role = db.Column(db.String, nullable=False, default="student")  # student, faculty, organizer, admin
    phone = db.Column(db.String, nullable=True)
    department = db.Column(db.String, nullable=True)
    year = db.Column(db.String, nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, nullable=False)

class Hall(db.Model):
    __tablename__ = "halls"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, nullable=False)
    capacity = db.Column(db.Integer, default=0)
    status = db.Column(db.String, default="free")  # free, blocked
    location = db.Column(db.String, nullable=True)

class Event(db.Model):
    __tablename__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String, nullable=False)
    description = db.Column(db.Text)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    hall_id = db.Column(db.Integer, db.ForeignKey("halls.id"), nullable=False)
    organizer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    capacity = db.Column(db.Integer, default=0)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    poster_path = db.Column(db.String, nullable=True)
    invitation_path = db.Column(db.String, nullable=True)
    status = db.Column(db.String, default="pending")  # pending, approved, rejected
    requires_faculty_approval = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    club_id = db.Column(db.Integer, nullable=True)

    category = db.relationship("Category", lazy="joined")
    hall = db.relationship("Hall", lazy="joined")
    organizer = db.relationship("User", lazy="joined")
    # images relationship defined via backref in EventImage

class EventImage(db.Model):
    __tablename__ = "event_images"
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    image_path = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    event = db.relationship("Event", backref=db.backref("images", lazy=True, cascade="all, delete-orphan"))


class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.String, unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False)
    status = db.Column(db.String, default="pending")  # pending, confirmed, cancelled
    faculty_approved = db.Column(db.Boolean, default=False)
    organizer_approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    qr_path = db.Column(db.String, nullable=True)
    pdf_path = db.Column(db.String, nullable=True)

    user = db.relationship("User", lazy="joined")
    event = db.relationship("Event", lazy="joined")

class Setting(db.Model):
    __tablename__ = "settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String, unique=True, nullable=False)
    value = db.Column(db.Text, nullable=True)

# -----------------------
# Settings helpers & mail loader
# -----------------------
def get_setting(key, default=None):
    try:
        s = Setting.query.filter_by(key=key).first()
        return s.value if s else default
    except Exception:
        return default

def set_setting(key, value):
    s = Setting.query.filter_by(key=key).first()
    if s:
        s.value = value
    else:
        s = Setting(key=key, value=value)
        db.session.add(s)
    db.session.commit()
    return s

def load_email_settings():
    global mail
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        if 'settings' not in inspector.get_table_names():
            return

        mail_server = get_setting("MAIL_SERVER", app.config.get("MAIL_SERVER", ""))
        mail_port = get_setting("MAIL_PORT", str(app.config.get("MAIL_PORT", 0)))
        mail_username = get_setting("MAIL_USERNAME", app.config.get("MAIL_USERNAME", ""))
        mail_password = get_setting("MAIL_PASSWORD", app.config.get("MAIL_PASSWORD", ""))
        mail_use_tls = get_setting("MAIL_USE_TLS", str(int(app.config.get("MAIL_USE_TLS", False))))
        mail_use_ssl = get_setting("MAIL_USE_SSL", str(int(app.config.get("MAIL_USE_SSL", False))))
        mail_default_sender = get_setting("MAIL_DEFAULT_SENDER", app.config.get("MAIL_DEFAULT_SENDER", "noreply@example.com"))

        try:
            mail_port_val = int(mail_port or 0)
        except Exception:
            mail_port_val = 0
        mail_use_tls_val = str(mail_use_tls).lower() in ("1", "true", "yes")
        mail_use_ssl_val = str(mail_use_ssl).lower() in ("1", "true", "yes")

        app.config["MAIL_SERVER"] = mail_server or ""
        app.config["MAIL_PORT"] = mail_port_val
        app.config["MAIL_USERNAME"] = mail_username or ""
        app.config["MAIL_PASSWORD"] = mail_password or ""
        app.config["MAIL_USE_TLS"] = mail_use_tls_val
        app.config["MAIL_USE_SSL"] = mail_use_ssl_val
        app.config["MAIL_DEFAULT_SENDER"] = mail_default_sender or "noreply@example.com"

        if Mail and app.config["MAIL_SERVER"]:
            try:
                mail = Mail(app)
                app.logger.info("Flask-Mail initialized with server %s:%s", app.config["MAIL_SERVER"], app.config["MAIL_PORT"])
            except Exception:
                mail = None
                app.logger.exception("Failed to initialize Flask-Mail")
        else:
            mail = None
            app.logger.debug("Flask-Mail not configured or package missing.")
    except Exception:
        app.logger.exception("Error loading email settings from DB")

# -----------------------
# Schema helper
# -----------------------
def ensure_schema():
    app.logger.info("Running db.create_all() to create missing tables.")
    db.create_all()

    try:
        if db.session.query(Category).count() == 0:
            default = ["Tech", "Cultural", "Sports", "Workshops"]
            for n in default:
                if not Category.query.filter_by(name=n).first():
                    db.session.add(Category(name=n))
            db.session.commit()
            app.logger.info("Seeded default categories.")
            
        # Migrate: Add invitation_path to events if missing
        inspector = db.inspect(db.engine)
        columns = [c["name"] for c in inspector.get_columns("events")]
        if "invitation_path" not in columns:
            app.logger.info("Migrating: Adding invitation_path to events table")
            with db.engine.connect() as conn:
                conn.execute(text("ALTER TABLE events ADD COLUMN invitation_path VARCHAR"))
                conn.commit()

        # Migrate: Create event_images if missing (handled by create_all, but double check if we need manual table creation in future)
        # db.create_all() at start should handle it for new tables.

    except Exception:
        db.session.rollback()

    try:
        load_email_settings()
    except Exception:
        app.logger.exception("Failed to load email settings after ensure_schema()")

# -----------------------
# Utilities & helpers
# -----------------------
@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except Exception:
        return None

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login"))
            if current_user.role not in roles:
                flash("Access denied: insufficient permissions", "danger")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return wrapped
    return decorator

def allowed_file(filename):
    ALLOWED = {"png", "jpg", "jpeg", "gif", "pdf"}
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED

def save_uploaded_file(file_storage, dest_folder, prefix="file"):
    if not file_storage:
        return None
    filename = secure_filename(file_storage.filename)
    if filename == "":
        return None
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    unique = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}.{ext}"
    path = os.path.join(dest_folder, unique)
    file_storage.save(path)
    return os.path.relpath(path, BASE_DIR).replace(os.path.sep, '/')

def generate_ticket_qr(ticket_id):
    if qrcode is None:
        app.logger.debug("qrcode module not available")
        return None

    fname = f"ticket_{ticket_id}.png"
    path = os.path.join(TICKET_FOLDER, fname)

    try:
        QRCode = getattr(qrcode, "QRCode", None)
        if QRCode:
            qr = QRCode(box_size=6, border=2)
            qr.add_data(ticket_id)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            img.save(path)
            return os.path.relpath(path, BASE_DIR).replace(os.path.sep, '/')
    except Exception:
        app.logger.exception("qrcode.QRCode approach failed")

    try:
        make = getattr(qrcode, "make", None)
        if make:
            img = make(ticket_id)
            try:
                img.save(path)
                return os.path.relpath(path, BASE_DIR).replace(os.path.sep, '/')
            except Exception:
                app.logger.exception("qrcode.make returned object couldn't be saved")
    except Exception:
        app.logger.exception("qrcode.make approach failed")

    try:
        import segno
        segno.make(ticket_id).save(path)
        return os.path.relpath(path, BASE_DIR).replace(os.path.sep, '/')
    except Exception:
        app.logger.debug("segno not available or failed")

    app.logger.error("Failed to generate QR for ticket %s: no suitable library/method available", ticket_id)
    return None

def generate_ticket_pdf(ticket_id, event, booking):
    if not have_reportlab:
        app.logger.debug("reportlab not available; skipping PDF generation")
        return None
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.utils import ImageReader
        
        fname = f"ticket_{ticket_id}.pdf"
        out_path = os.path.join(TICKET_FOLDER, fname)

        c = canvas.Canvas(out_path, pagesize=A4)
        width, height = A4
        
        sky_blue = HexColor('#0284c7')
        light_sky = HexColor('#e0f2fe')
        dark_text = HexColor('#1e293b')
        gray_text = HexColor('#64748b')
        
        c.setFillColor(sky_blue)
        c.rect(0, height - 50*mm, width, 50*mm, fill=True, stroke=False)
        
        logo_path = os.path.join(BASE_DIR, "static", "images", "college_logo.png")
        if os.path.exists(logo_path):
            try:
                c.drawImage(logo_path, 15*mm, height - 42*mm, width=30*mm, height=30*mm, preserveAspectRatio=True, mask='auto')
            except Exception:
                app.logger.debug("Could not add logo to PDF")
        
        c.setFillColor(HexColor('#ffffff'))
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50*mm, height - 22*mm, "CAUVERY COLLEGE FOR WOMEN")
        c.setFont("Helvetica", 10)
        c.drawString(50*mm, height - 30*mm, "(Autonomous) | NAAC Accreditation 'A+' Grade")
        c.setFont("Helvetica-Bold", 12)
        c.drawString(50*mm, height - 40*mm, "EVENT ENTRY TICKET")
        
        c.setFillColor(light_sky)
        c.roundRect(15*mm, height - 130*mm, width - 30*mm, 70*mm, 5*mm, fill=True, stroke=False)
        
        c.setFillColor(dark_text)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(20*mm, height - 65*mm, event.title)
        
        c.setFont("Helvetica", 11)
        c.setFillColor(gray_text)
        y = height - 78*mm
        
        c.setFillColor(dark_text)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20*mm, y, "Date & Time:")
        c.setFont("Helvetica", 10)
        c.setFillColor(gray_text)
        c.drawString(55*mm, y, event.start_time.strftime('%B %d, %Y | %I:%M %p'))
        
        y -= 8*mm
        c.setFillColor(dark_text)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20*mm, y, "Venue:")
        c.setFont("Helvetica", 10)
        c.setFillColor(gray_text)
        c.drawString(55*mm, y, f"{event.hall.name}" + (f" - {event.hall.location}" if event.hall.location else ""))
        
        y -= 8*mm
        c.setFillColor(dark_text)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20*mm, y, "Organized By:")
        c.setFont("Helvetica", 10)
        c.setFillColor(gray_text)
        c.drawString(55*mm, y, event.organizer.full_name or event.organizer.email)
        
        y -= 8*mm
        c.setFillColor(dark_text)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20*mm, y, "Attendee:")
        c.setFont("Helvetica", 10)
        c.setFillColor(gray_text)
        attendee_name = booking.user.full_name or booking.user.email if booking and booking.user else "N/A"
        c.drawString(55*mm, y, attendee_name)
        
        c.setFillColor(HexColor('#ffffff'))
        c.roundRect(width - 75*mm, height - 125*mm, 55*mm, 55*mm, 3*mm, fill=True, stroke=False)
        
        if booking and getattr(booking, "qr_path", None) and have_pillow:
            qr_rel = booking.qr_path
            qr_abs = os.path.join(BASE_DIR, qr_rel)
            if os.path.exists(qr_abs):
                try:
                    c.drawImage(qr_abs, width - 72*mm, height - 122*mm, width=49*mm, height=49*mm, preserveAspectRatio=True, mask='auto')
                except Exception:
                    app.logger.exception("Failed to add QR to PDF")
        
        c.setStrokeColor(light_sky)
        c.setLineWidth(2)
        c.line(15*mm, height - 145*mm, width - 15*mm, height - 145*mm)
        
        c.setFillColor(dark_text)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(20*mm, height - 158*mm, "Ticket ID:")
        c.setFont("Courier-Bold", 11)
        c.setFillColor(sky_blue)
        c.drawString(50*mm, height - 158*mm, ticket_id[:36] if len(ticket_id) > 36 else ticket_id)
        
        c.setFillColor(gray_text)
        c.setFont("Helvetica", 9)
        c.drawString(20*mm, height - 170*mm, "Please present this ticket (printed or digital) at the venue entrance.")
        c.drawString(20*mm, height - 178*mm, "This ticket is valid for one person only and is non-transferable.")
        
        c.setFillColor(sky_blue)
        c.rect(0, 0, width, 15*mm, fill=True, stroke=False)
        c.setFillColor(HexColor('#ffffff'))
        c.setFont("Helvetica", 8)
        c.drawCentredString(width/2, 5*mm, f"Issued on {datetime.utcnow().strftime('%B %d, %Y at %I:%M %p UTC')} | Cauvery College for Women Event Management System")
        
        c.showPage()
        c.save()

        return os.path.relpath(out_path, BASE_DIR).replace(os.path.sep, '/')
    except Exception:
        app.logger.exception("Failed to generate PDF ticket")
        return None

def finalize_booking_if_ready(booking):
    """
    If booking has faculty approval AND organizer approval (if required), finalize: set status confirmed,
    generate QR/PDF, send email to student.
    """
    ev = booking.event
    faculty_ok = booking.faculty_approved
    # By default, assume organizer approval is needed unless implemented otherwise.
    # Logic in book_event auto-approves if organizer creates it.
    organizer_ok = booking.organizer_approved
    
    if faculty_ok and organizer_ok and booking.status != "confirmed":
        booking.status = "confirmed"
        # generate qr/pdf
        try:
            if qrcode:
                qr = generate_ticket_qr(booking.ticket_id)
                booking.qr_path = qr
        except Exception:
            app.logger.exception("QR generation failed during finalization")
        try:
            pdf = generate_ticket_pdf(booking.ticket_id, ev, booking)
            if pdf:
                booking.pdf_path = pdf
        except Exception:
            app.logger.exception("PDF generation failed during finalization")
        db.session.commit()
        # send email
        if mail and booking.user and booking.user.email:
            try:
                send_ticket_email(booking.user.email, ev, booking)
            except Exception:
                app.logger.exception("Failed sending final ticket email")

def seats_taken(event_id):
    return Booking.query.filter_by(event_id=event_id, status="confirmed").count()

def seats_available(event):
    event_cap = event.capacity if event.capacity and event.capacity > 0 else None
    hall_cap = event.hall.capacity if event.hall and event.hall.capacity and event.hall.capacity > 0 else None
    effective = event_cap if event_cap is not None else (hall_cap if hall_cap is not None else None)
    if effective is None:
        return None
    return max(0, effective - seats_taken(event.id))

def send_ticket_email(recipient, event, booking):
    if mail is None or not app.config.get("MAIL_SERVER"):
        app.logger.debug("Mail not configured; skipping email send.")
        return False
    try:
        msg = Message(subject=f"Ticket for {event.title}", recipients=[recipient])
        msg.body = f"Your ticket id: {booking.ticket_id}\nEvent: {event.title}\nStart: {event.start_time}\n"
        if booking.qr_path:
            try:
                qr_abs = os.path.join(BASE_DIR, booking.qr_path)
                if os.path.exists(qr_abs):
                    with open(qr_abs, "rb") as fp:
                        msg.attach(os.path.basename(qr_abs), "image/png", fp.read())
            except Exception:
                app.logger.exception("Failed to attach QR image to email")
        if booking.pdf_path:
            try:
                pdf_abs = os.path.join(BASE_DIR, booking.pdf_path)
                if os.path.exists(pdf_abs):
                    with open(pdf_abs, "rb") as pf:
                        msg.attach(os.path.basename(pdf_abs), "application/pdf", pf.read())
            except Exception:
                app.logger.exception("Failed to attach PDF to email")
        mail.send(msg)
        return True
    except Exception:
        app.logger.exception("Failed to send email")
        return False

def send_notification_email(subject, body, recipients):
    """Simple helper to send notifications to a list of emails (best-effort)."""
    if mail is None or not app.config.get("MAIL_SERVER"):
        app.logger.debug("Mail not configured; skipping notifications.")
        return False
    try:
        # send individually to avoid exposing lists and to handle failures per recipient
        for r in recipients:
            try:
                msg = Message(subject=subject, recipients=[r])
                msg.body = body
                mail.send(msg)
            except Exception:
                app.logger.exception("Failed to send notification to %s", r)
        return True
    except Exception:
        app.logger.exception("Bulk notification failure")
        return False

# -----------------------
# Views - Auth & User
# -----------------------
@app.route("/health")
def health():
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        return jsonify({"ok": True, "tables": tables})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/")
def index():
    upcoming = Event.query.filter(Event.status == "approved", Event.start_time >= datetime.utcnow()).order_by(Event.start_time).limit(6).all()
    return render_template("index.html", upcoming=upcoming, current_user=current_user)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        role = request.form.get("role", "student")
        email = request.form.get("email")
        password = request.form.get("password")
        full_name = request.form.get("full_name")
        if not email or not password:
            flash("Email and password required", "danger")
            return redirect(url_for("register"))
        if User.query.filter_by(email=email).first():
            flash("Email already registered", "warning")
            return redirect(url_for("register"))
        user = User(email=email, full_name=full_name, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("Registration successful. Please login.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identifier = request.form.get("identifier")
        password = request.form.get("password")
        user = None
        if "@" in (identifier or ""):
            user = User.query.filter_by(email=identifier).first()
        else:
            user = User.query.filter_by(student_id=identifier).first()
        if not user or not user.check_password(password) or not user.active:
            flash("Invalid credentials or inactive account", "danger")
            return redirect(url_for("login"))
        login_user(user)
        flash("Logged in", "success")
        return redirect(url_for("index"))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out", "info")
    return redirect(url_for("index"))

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        current_user.full_name = request.form.get("full_name")
        current_user.phone = request.form.get("phone")
        current_user.department = request.form.get("department")
        current_user.year = request.form.get("year")
        db.session.commit()
        flash("Profile updated", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", user=current_user)

# -----------------------
# Event & Hall Management
# -----------------------
@app.route("/events")
def event_list():
    q = Event.query.filter(Event.status.in_(["approved", "pending"]) ).order_by(Event.start_time)
    category = request.args.get("category")
    if category:
        q = q.join(Category).filter(Category.name == category)
    events = q.all()
    categories = Category.query.order_by(Category.name).all()
    return render_template("event_list.html", events=events, categories=categories)

@app.route("/events/<int:event_id>")
def event_detail(event_id):
    ev = Event.query.get_or_404(event_id)
    available = seats_available(ev)
    
    user_booking = None
    if current_user.is_authenticated:
        user_booking = Booking.query.filter_by(user_id=current_user.id, event_id=ev.id).filter(Booking.status != 'cancelled').first()

    return render_template("event_detail.html", event=ev, available=available, available_percent=(available/ev.hall.capacity)*100 if ev.hall and ev.hall.capacity else 100, user_booking=user_booking)

@app.route("/organizer/events/new", methods=["GET", "POST"])
@login_required
@role_required("organizer", "admin")
def create_event():
    categories = Category.query.order_by(Category.name).all()
    halls = Hall.query.order_by(Hall.name).all()
    if request.method == "POST":
        try:
            title = request.form.get("title")
            description = request.form.get("description")
            category_id = request.form.get("category_id") or None
            hall_id_raw = request.form.get("hall_id")
            capacity_raw = request.form.get("capacity") or 0
            start_time = request.form.get("start_time")
            end_time = request.form.get("end_time")
            poster = request.files.get("poster")
            invitation = request.files.get("invitation")
            requires_faculty = bool(request.form.get("requires_faculty"))

            if not title or not hall_id_raw or not start_time or not end_time:
                flash("Missing required fields", "danger")
                return redirect(url_for("create_event"))

            try:
                hall_id = int(hall_id_raw)
            except Exception:
                flash("Invalid hall selection", "danger")
                return redirect(url_for("create_event"))

            try:
                capacity = int(capacity_raw or 0)
            except Exception:
                capacity = 0

            try:
                st = datetime.fromisoformat(start_time)
                et = datetime.fromisoformat(end_time)
            except Exception:
                flash("Invalid date format. Use ISO: YYYY-MM-DDTHH:MM", "danger")
                return redirect(url_for("create_event"))
            if st >= et:
                flash("Start must be before end", "danger")
                return redirect(url_for("create_event"))

            hall = Hall.query.get(hall_id)
            if not hall:
                flash("Invalid hall", "danger")
                return redirect(url_for("create_event"))
            if hall.status == "blocked":
                flash("Hall is currently blocked", "danger")
                return redirect(url_for("create_event"))

            conflicts = Event.query.filter(
                Event.hall_id == hall_id,
                Event.status == "approved",
                Event.start_time < et,
                Event.end_time > st
            ).all()
            if conflicts:
                flash("Time conflict with another approved event", "danger")
                return redirect(url_for("create_event"))

            poster_path = None
            if poster and allowed_file(poster.filename):
                poster_path = save_uploaded_file(poster, POSTER_FOLDER, prefix="poster")

            invitation_path = None
            if invitation and allowed_file(invitation.filename):
                invitation_path = save_uploaded_file(invitation, INVITATION_FOLDER, prefix="invitation")

            try:
                club_id_val = int(request.form.get("club_id", 0))
            except Exception:
                club_id_val = 0

            ev = Event(
                title=title, description=description, category_id=category_id,
                hall_id=hall_id, organizer_id=current_user.id,
                capacity=capacity, start_time=st, end_time=et,
                poster_path=poster_path, invitation_path=invitation_path, status="approved",
                club_id=club_id_val, requires_faculty_approval=True
            )
            db.session.add(ev)
            db.session.commit()
            app.logger.info("Created event id=%s title=%s organizer=%s club_id=%s", ev.id, ev.title, current_user.id, club_id_val)

            # Notify students about new event creation (best-effort)
            try:
                students = [u.email for u in User.query.filter_by(role="student", active=True).all() if u.email]
                if students:
                    subject = f"New Event Created: {ev.title}"
                    body = f"A new event '{ev.title}' is now available for booking. Start: {ev.start_time}\nVisit the site to book your seat!"
                    send_notification_email(subject, body, students)
            except Exception:
                app.logger.exception("Failed to send event creation notifications")

            flash("Event created successfully! Students can now book.", "success")
            return redirect(url_for("event_detail", event_id=ev.id))

        except Exception as exc:
            app.logger.exception("Error while creating event")
            flash(f"Failed to create event: {exc}", "danger")
            return redirect(url_for("create_event"))

    return render_template("create_event.html", categories=categories, halls=halls)

@app.route("/organizer/events/<int:event_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("organizer", "admin")
def edit_event(event_id):
    ev = Event.query.get_or_404(event_id)
    if current_user.id != ev.organizer_id and current_user.role != "admin":
        flash("Not allowed", "danger")
        return redirect(url_for("event_detail", event_id=event_id))
    categories = Category.query.order_by(Category.name).all()
    halls = Hall.query.order_by(Hall.name).all()
    if request.method == "POST":
        ev.title = request.form.get("title")
        ev.description = request.form.get("description")
        ev.category_id = request.form.get("category_id") or None
        ev.capacity = int(request.form.get("capacity") or 0)
        ev.requires_faculty_approval = bool(request.form.get("requires_faculty"))
        
        poster = request.files.get("poster")
        if poster and allowed_file(poster.filename):
            ev.poster_path = save_uploaded_file(poster, POSTER_FOLDER, prefix="poster")

        invitation = request.files.get("invitation")
        if invitation and allowed_file(invitation.filename):
            ev.invitation_path = save_uploaded_file(invitation, INVITATION_FOLDER, prefix="invitation")

        db.session.commit()
        flash("Event updated", "success")
        return redirect(url_for("event_detail", event_id=ev.id))
    return render_template("create_event.html", categories=categories, halls=halls, edit=True, event=ev)

@app.route("/organizer/events/<int:event_id>/gallery/upload", methods=["POST"])
@login_required
@role_required("organizer", "admin")
def upload_event_gallery(event_id):
    ev = Event.query.get_or_404(event_id)
    if current_user.id != ev.organizer_id and current_user.role != "admin":
        flash("Not allowed", "danger")
        return redirect(url_for("event_detail", event_id=event_id))
    
    files = request.files.getlist("images")
    count = 0
    for f in files:
        if f and allowed_file(f.filename):
            path = save_uploaded_file(f, GALLERY_FOLDER, prefix=f"gallery_{event_id}")
            if path:
                img = EventImage(event_id=ev.id, image_path=path)
                db.session.add(img)
                count += 1
    
    if count > 0:
        db.session.commit()
        flash(f"Uploaded {count} images to gallery", "success")
    else:
        flash("No valid images uploaded", "warning")
    
    return redirect(url_for("event_detail", event_id=event_id))

@app.route("/admin/events/<int:event_id>/approve", methods=["POST"])
@login_required
@role_required("admin")
def admin_approve_event(event_id):
    ev = Event.query.get_or_404(event_id)
    if ev.hall.status == "blocked":
        flash("Hall is blocked, cannot approve", "danger")
        return redirect(url_for("event_detail", event_id=event_id))
    conflicts = Event.query.filter(
        Event.hall_id == ev.hall_id,
        Event.status == "approved",
        Event.start_time < ev.end_time,
        Event.end_time > ev.start_time,
        Event.id != ev.id
    ).all()
    if conflicts:
        flash("Conflict detected; cannot approve", "danger")
        return redirect(url_for("event_detail", event_id=event_id))
    ev.status = "approved"
    db.session.commit()
    flash("Event approved", "success")
    return redirect(url_for("event_detail", event_id=event_id))

@app.route("/admin/halls", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_halls():
    if request.method == "POST":
        name = request.form.get("name")
        cap = int(request.form.get("capacity") or 0)
        location = request.form.get("location")
        if not name:
            flash("Name required", "danger")
            return redirect(url_for("admin_halls"))
        h = Hall(name=name, capacity=cap, location=location)
        db.session.add(h)
        db.session.commit()
        flash("Hall created", "success")
        return redirect(url_for("admin_halls"))
    halls = Hall.query.order_by(Hall.name).all()
    return render_template("admin_halls.html", halls=halls)

@app.route("/admin/halls/<int:hall_id>/block", methods=["POST"])
@login_required
@role_required("admin")
def admin_block_hall(hall_id):
    h = Hall.query.get_or_404(hall_id)
    action = request.form.get("action")
    if action == "block":
        h.status = "blocked"
    else:
        h.status = "free"
    db.session.commit()
    flash("Hall status updated", "success")
    return redirect(url_for("admin_halls"))

# -----------------------
# Booking & Tickets
# -----------------------
@app.route("/events/<int:event_id>/book", methods=["POST"])
@login_required
def book_event(event_id):
    ev = Event.query.get_or_404(event_id)
    if current_user.role not in ("student", "faculty", "organizer", "admin"):
        return jsonify({"error": "role not allowed to book"}), 403
    if ev.status != "approved" and current_user.role != "admin":
        return jsonify({"error": "event not open for booking"}), 400
    avail = seats_available(ev)
    if avail is not None and avail <= 0:
        return jsonify({"error": "sold_out"}), 409
    existing = Booking.query.filter_by(user_id=current_user.id, event_id=ev.id).filter(Booking.status != 'cancelled').first()
    if existing:
        return jsonify({"message": "already_booked", "booking_id": existing.id}), 200

    booking = Booking(user_id=current_user.id, event_id=ev.id, status="pending", faculty_approved=False, organizer_approved=False)
    db.session.add(booking)
    db.session.flush()

    # If event does not require faculty approval and organizer is the current_user (organizer booking),
    # auto-approve organizer_approved; otherwise organizer must approve later.
    if not ev.requires_faculty_approval and (current_user.role in ("organizer", "admin")):
        booking.organizer_approved = True

    # If organizer_approved is already true and faculty approval not required, finalize immediately
    db.session.commit()

    # Notify organizer and optionally faculty that a new booking is pending
    try:
        recipients = []
        if ev.organizer and ev.organizer.email:
            recipients.append(ev.organizer.email)
        # notify all faculty (simpler): in real deployments, filter by department or event assignment
        faculty_emails = [u.email for u in User.query.filter_by(role="faculty", active=True).all() if u.email]
        recipients.extend(faculty_emails)
        # notify student with "pending" info
        if current_user.email:
            send_notification_email(f"Booking received for {ev.title}", f"Your booking for {ev.title} is pending approval.", [current_user.email])
        if recipients:
            send_notification_email(f"Booking pending: {ev.title}", f"A new booking by {current_user.full_name or current_user.email} is pending for event '{ev.title}'.", list(set(recipients)))
    except Exception:
        app.logger.exception("Failed to send booking notifications")

    # Attempt to finalize (this will finalize only if approvals are satisfied)
    try:
        finalize_booking_if_ready(booking)
    except Exception:
        app.logger.exception("Error during booking finalization")

    return jsonify({
        "message": "booked",
        "booking_id": booking.id,
        "ticket_id": booking.ticket_id,
        "qr_url": url_for("serve_upload", filename=os.path.basename(booking.qr_path)) if booking.qr_path else None
    }), 201

@app.route("/bookings/<int:booking_id>/ticket")
@login_required
def view_ticket(booking_id):
    b = Booking.query.get_or_404(booking_id)
    if b.user_id != current_user.id and current_user.role not in ("admin", "organizer"):
        abort(403)
    if b.pdf_path:
        pdf_abs = os.path.join(BASE_DIR, b.pdf_path)
        if os.path.exists(pdf_abs):
            return send_from_directory(os.path.dirname(pdf_abs), os.path.basename(pdf_abs))
    if b.qr_path:
        qr_abs = os.path.join(BASE_DIR, b.qr_path)
        if os.path.exists(qr_abs):
            return send_from_directory(os.path.dirname(qr_abs), os.path.basename(qr_abs))
    flash("No ticket available", "warning")
    return redirect(url_for("event_detail", event_id=b.event_id))

@app.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    b = Booking.query.get_or_404(booking_id)
    if b.user_id != current_user.id and current_user.role not in ("admin",):
        abort(403)
    b.status = "cancelled"
    db.session.commit()
    flash("Booking cancelled", "info")
    return redirect(url_for("event_detail", event_id=b.event_id))

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    for folder in (POSTER_FOLDER, TICKET_FOLDER, INVITATION_FOLDER, GALLERY_FOLDER):
        candidate = os.path.join(folder, filename)
        if os.path.exists(candidate):
            return send_from_directory(folder, filename)
    abort(404)

# -----------------------
# Organizer Dashboard
# -----------------------
@app.route("/organizer")
@login_required
@role_required("organizer", "admin")
def organizer_dashboard():
    my_events = Event.query.filter_by(organizer_id=current_user.id).order_by(Event.start_time.desc()).all()
    for e in my_events:
        e.booking_count = Booking.query.filter_by(event_id=e.id).count()
    
    event_ids = [e.id for e in my_events]
    pending_bookings = Booking.query.filter(
        Booking.event_id.in_(event_ids),
        Booking.organizer_approved == False
    ).order_by(Booking.created_at.desc()).all()
    
    total_bookings = Booking.query.filter(Booking.event_id.in_(event_ids)).count()
    upcoming_events = [e for e in my_events if e.start_time >= datetime.utcnow()]
    
    return render_template("organizer_dashboard.html",
                           my_events=my_events,
                           pending_bookings=pending_bookings,
                           total_bookings=total_bookings,
                           upcoming_events=upcoming_events)

# -----------------------
# Faculty & Organizer approvals
# -----------------------
@app.route("/organizer/bookings")
@login_required
@role_required("organizer", "admin")
def organizer_bookings():
    # Organizer should see bookings for their events
    events_ids = [e.id for e in Event.query.filter_by(organizer_id=current_user.id).all()]
    bookings = Booking.query.filter(Booking.event_id.in_(events_ids)).order_by(Booking.created_at.desc()).all()
    return render_template("organizer_bookings.html", bookings=bookings)

@app.route("/organizer/bookings/<int:booking_id>/approve", methods=["POST"])
@login_required
@role_required("organizer", "admin")
def organizer_approve_booking(booking_id):
    b = Booking.query.get_or_404(booking_id)
    # ensure current_user is organizer for the event or admin
    if current_user.role != "admin" and current_user.id != b.event.organizer_id:
        abort(403)
    b.organizer_approved = True
    db.session.commit()
    try:
        finalize_booking_if_ready(b)
    except Exception:
        app.logger.exception("Error finalizing after organizer approval")
    flash("Booking approved by organizer", "success")
    return redirect(url_for("organizer_bookings"))

# -----------------------
# Admin: Users & Email Settings
# -----------------------
@app.route("/admin/users", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_users():
    if request.method == "POST":
        # create new user from admin panel
        email = request.form.get("email")
        full_name = request.form.get("full_name")
        role = request.form.get("role", "student")
        password = request.form.get("password", "changeme")
        if not email:
            flash("Email required", "danger")
            return redirect(url_for("admin_users"))
        if User.query.filter_by(email=email).first():
            flash("Email already exists", "warning")
            return redirect(url_for("admin_users"))
        u = User(email=email, full_name=full_name, role=role)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        flash("User created", "success")
        return redirect(url_for("admin_users"))

    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin_users.html", users=users)

@app.route("/admin/users/<int:user_id>/update", methods=["POST"])
@login_required
@role_required("admin")
def admin_update_user(user_id):
    u = User.query.get_or_404(user_id)
    role = request.form.get("role")
    active = bool(request.form.get("active"))
    if role:
        u.role = role
    u.active = active
    db.session.commit()
    flash("User updated", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/email-settings", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_email_settings():
    if request.method == "POST":
        server = request.form.get("mail_server", "").strip()
        port = request.form.get("mail_port", "").strip()
        username = request.form.get("mail_username", "").strip()
        password = request.form.get("mail_password", "").strip()
        use_tls = "1" if request.form.get("mail_use_tls") else "0"
        use_ssl = "1" if request.form.get("mail_use_ssl") else "0"
        default_sender = request.form.get("mail_default_sender", "").strip()

        try:
            existing_pw = get_setting("MAIL_PASSWORD", "")
            pw_to_store = existing_pw if password == "" else password

            set_setting("MAIL_SERVER", server)
            set_setting("MAIL_PORT", port)
            set_setting("MAIL_USERNAME", username)
            set_setting("MAIL_PASSWORD", pw_to_store)
            set_setting("MAIL_USE_TLS", use_tls)
            set_setting("MAIL_USE_SSL", use_ssl)
            set_setting("MAIL_DEFAULT_SENDER", default_sender)
            load_email_settings()
            flash("Email settings updated.", "success")
        except Exception:
            app.logger.exception("Failed to save email settings")
            flash("Failed to save email settings. See server logs.", "danger")
        return redirect(url_for("admin_email_settings"))

    current = {
        "MAIL_SERVER": get_setting("MAIL_SERVER", app.config.get("MAIL_SERVER", "")),
        "MAIL_PORT": get_setting("MAIL_PORT", str(app.config.get("MAIL_PORT", 0))),
        "MAIL_USERNAME": get_setting("MAIL_USERNAME", app.config.get("MAIL_USERNAME", "")),
        "MAIL_PASSWORD": get_setting("MAIL_PASSWORD", app.config.get("MAIL_PASSWORD", "")),
        "MAIL_USE_TLS": get_setting("MAIL_USE_TLS", str(int(app.config.get("MAIL_USE_TLS", False)))),
        "MAIL_USE_SSL": get_setting("MAIL_USE_SSL", str(int(app.config.get("MAIL_USE_SSL", False)))),
        "MAIL_DEFAULT_SENDER": get_setting("MAIL_DEFAULT_SENDER", app.config.get("MAIL_DEFAULT_SENDER", "noreply@example.com")),
    }
    masked = current["MAIL_PASSWORD"]
    if masked:
        masked = "********"
    return render_template("admin_email_settings.html", current=current, masked_password=masked)

# -----------------------
# Admin Dashboard & Simple Views
# -----------------------
@app.route("/admin")
@login_required
@role_required("admin")
def admin_dashboard():
    pending_events = Event.query.filter_by(status="pending").order_by(Event.created_at.desc()).all()
    users = User.query.order_by(User.created_at.desc()).limit(20).all()
    total_users = User.query.count()
    total_events = Event.query.count()
    total_bookings = Booking.query.count()
    return render_template("admin_dashboard.html", 
                           pending_events=pending_events, 
                           users=users,
                           total_users=total_users,
                           total_events=total_events,
                           total_bookings=total_bookings)

@app.route("/my/bookings")
@login_required
def my_bookings():
    bookings = Booking.query.filter_by(user_id=current_user.id).order_by(Booking.created_at.desc()).all()
    return render_template("my_bookings.html", bookings=bookings)

# -----------------------
# CLI: initdb
# -----------------------
@app.cli.command("initdb")
def initdb():
    ensure_schema()
    if not User.query.filter_by(role="admin").first():
        admin = User(email="admin@example.com", full_name="Administrator", role="admin")
        admin.set_password("adminpass")
        db.session.add(admin)
    for name in ("Tech", "Cultural", "Sports", "Workshops"):
        if not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name))
    if Hall.query.count() == 0:
        db.session.add(Hall(name="A Block Hall", capacity=200, location="A Block"))
        db.session.add(Hall(name="Seminar Hall 1", capacity=120, location="Main"))
        db.session.add(Hall(name="Seminar Hall 2", capacity=100, location="Main"))
    db.session.commit()
    print("Initialized database with admin@example.com / adminpass and sample data.")

# Faculty dashboard and approval routes
@app.route("/faculty")
@login_required
@role_required("faculty")
def faculty_dashboard():
    """
    Simple faculty dashboard: shows pending bookings that require faculty approval
    and a short list of recent events for context.
    """
    try:
        pending_bookings = (
            db.session.query(Booking)
            .join(Event)
            .filter(Booking.faculty_approved == False, Event.requires_faculty_approval == True)
            .order_by(Booking.created_at.desc())
            .all()
        )
        pending_count = len(pending_bookings)
        recent_events = Event.query.order_by(Event.start_time.desc()).limit(8).all()
    except Exception:
        app.logger.exception("Error loading faculty dashboard")
        pending_bookings = []
        pending_count = 0
        recent_events = []
    approved_count = Booking.query.filter_by(faculty_approved=True).count()
    return render_template("faculty_dashboard.html",
                           pending_count=pending_count,
                           pending_bookings=pending_bookings,
                           recent_events=recent_events,
                           approved_count=approved_count)

@app.route("/faculty/bookings")
@login_required
@role_required("faculty")
def faculty_bookings():
    """
    Show bookings that require faculty approval:
    - booking.faculty_approved == False
    - booking.event.requires_faculty_approval == True
    """
    try:
        bookings = (
            db.session.query(Booking)
            .join(Event)
            .filter(Booking.faculty_approved == False, Event.requires_faculty_approval == True)
            .order_by(Booking.created_at.desc())
            .all()
        )
        app.logger.info("Faculty %s saw %d pending bookings", current_user.email, len(bookings))
    except Exception:
        app.logger.exception("Error fetching faculty bookings")
        bookings = []
    return render_template("faculty_bookings.html", bookings=bookings)

@app.route("/faculty/bookings/<int:booking_id>/approve", methods=["POST"])
@login_required
@role_required("faculty")
def faculty_approve_booking(booking_id):
    """
    Mark a booking as faculty_approved and attempt finalization.
    """
    b = Booking.query.get_or_404(booking_id)
    # Optional: ensure the booking's event actually requires faculty approval
    if not b.event.requires_faculty_approval:
        flash("This booking does not require faculty approval.", "warning")
        return redirect(url_for("faculty_bookings"))

    b.faculty_approved = True
    db.session.commit()

    # Attempt to finalize (this will confirm and send ticket)
    try:
        finalize_booking_if_ready(b)
    except Exception:
        app.logger.exception("Error finalizing after faculty approval")

    flash("Booking approved! Student ticket is now confirmed.", "success")
    return redirect(url_for("faculty_bookings"))


# -----------------------
# Run
# -----------------------
if __name__ == "__main__":
    with app.app_context():
        ensure_schema()
        if not User.query.filter_by(role="admin").first():
            admin = User(email="admin@example.com", full_name="Administrator", role="admin")
            admin.set_password("adminpass")
            db.session.add(admin)
            db.session.commit()
            app.logger.info("Created admin@example.com / adminpass")
        load_email_settings()
    app.run(debug=True, host="0.0.0.0", port=5000)