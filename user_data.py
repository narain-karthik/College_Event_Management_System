#!/usr/bin/env python3
"""
Seed test data for College Event System.

Usage:
    python seed_test_data.py
"""
import os
from datetime import datetime, timedelta

# import from your app (assumes app.py defines these names)
from app import app, db, User, Category, Hall, Event, Booking, generate_ticket_qr, ensure_schema

def make_user(email, password, full_name, role):
    u = User.query.filter_by(email=email).first()
    if u:
        return u
    u = User(email=email, full_name=full_name, role=role)
    u.set_password(password)
    db.session.add(u)
    db.session.flush()
    return u

with app.app_context():
    print("Ensuring schema and seeding baseline data...")
    # ensure schema exists and columns added (if your app has ensure_schema)
    try:
        ensure_schema()
    except Exception:
        # fallback to create_all
        db.create_all()

    # Create test users
    admin = make_user("admin@example.com", "adminpass", "Site Admin", "admin")
    organizer = make_user("organizer@example.com", "organizerpass", "Org One", "organizer")
    student = make_user("student@example.com", "studentpass", "Student One", "student")
    faculty = make_user("faculty@example.com", "facultypass", "Faculty One", "faculty")

    # Seed categories
    categories = []
    for cname in ("Tech", "Cultural", "Sports", "Workshops"):
        c = Category.query.filter_by(name=cname).first()
        if not c:
            c = Category(name=cname)
            db.session.add(c)
        categories.append(c)

    # Seed halls
    if Hall.query.count() == 0:
        h1 = Hall(name="A Block Hall", capacity=200, location="A Block")
        h2 = Hall(name="Seminar Hall 1", capacity=120, location="Main")
        h3 = Hall(name="Seminar Hall 2", capacity=100, location="Main")
        db.session.add_all([h1, h2, h3])
        db.session.flush()
    else:
        h1 = Hall.query.filter_by(name="A Block Hall").first()
        h2 = Hall.query.filter_by(name="Seminar Hall 1").first()
        h3 = Hall.query.filter_by(name="Seminar Hall 2").first()

    # Create sample events by organizer
    now = datetime.utcnow()
    ev1 = Event.query.filter_by(title="Tech Talk: AI in 2026").first()
    if not ev1:
        ev1 = Event(
            title="Tech Talk: AI in 2026",
            description="An overview of AI research and applications.",
            category_id=Category.query.filter_by(name="Tech").first().id,
            hall_id=h1.id,
            organizer_id=organizer.id,
            capacity=150,
            start_time=now + timedelta(days=1, hours=2),
            end_time=now + timedelta(days=1, hours=4),
            status="approved"
        )
        db.session.add(ev1)

    ev2 = Event.query.filter_by(title="Cultural Evening").first()
    if not ev2:
        ev2 = Event(
            title="Cultural Evening",
            description="Music and dance performances from clubs.",
            category_id=Category.query.filter_by(name="Cultural").first().id,
            hall_id=h2.id,
            organizer_id=organizer.id,
            capacity=80,
            start_time=now + timedelta(days=2, hours=5),
            end_time=now + timedelta(days=2, hours=8),
            status="pending"
        )
        db.session.add(ev2)

    db.session.commit()

    # Create a booking (student books ev1)
    if ev1 and not Booking.query.filter_by(user_id=student.id, event_id=ev1.id, status="confirmed").first():
        booking = Booking(user_id=student.id, event_id=ev1.id)
        db.session.add(booking)
        db.session.flush()
        # generate QR if qrcode available
        try:
            qr = generate_ticket_qr(booking.ticket_id)
            booking.qr_path = qr
        except Exception:
            pass
        db.session.commit()
        print("Created booking for student:", booking.ticket_id)

    print("Seeding complete. Test users:")
    print("  Admin   - admin@example.com / adminpass")
    print("  Organizer - organizer@example.com / organizerpass")
    print("  Student - student@example.com / studentpass")
    print("  Faculty - faculty@example.com / facultypass")
    print("Open the app and login with the above credentials.")