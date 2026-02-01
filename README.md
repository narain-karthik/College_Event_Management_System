# College Event Management System

A comprehensive, role-based web application designed for managing college events, bookings, and approvals efficiently. Built for **Cauvery College for Women** using Python and Flask.

![Event Management System Banner](static/images/college_logo.png)

## 🚀 Features

### for Students
- **Browse Events**: View upcoming events with details, posters, and remaining seats.
- **Book Tickets**: Seamless booking process with automated email status updates.
- **My Bookings**: Manage bookings, view status (Confirmed/Pending/Cancelled), and download tickets.
- **Digital Tickets**: Download professional PDF tickets with unique QR codes.
- **Invitations**: Download event invitation documents directly from the event page.

### for Organizers
- **Event Management**: Create, edit, and manage events.
- **Posters & Invitations**: Upload marketing materials and invitation documents (PDF/Image).
- **Event Gallery**: Upload post-event photos to a public gallery.
- **Booking Approvals**: Review and approve student booking requests.
- **Dashboard**: Real-time insights on bookings, seats filled, and pending actions.

### for Faculty
- **Approval Workflow**: Review event bookings that require faculty permission.
- **Dashboard**: Quick view of pending approvals.

### for Admins
- **Master Control**: Manage users, halls, blocks, and system settings.
- **Hall Management**: Add halls, set capacity, and block halls for maintenance.
- **User Management**: Manage user roles and details.

## 🛠️ Technology Stack

- **Backend**: Python 3.12, Flask, Flask-SQLAlchemy, Flask-Login, Flask-Mail.
- **Database**: SQLite (Development) / PostgreSQL (Production ready).
- **Frontend**: HTML5, CSS3, Bootstrap 5, JavaScript.
- **PDF Generation**: ReportLab (Professional Invoice/Ticket generation).
- **QR Codes**: Python QRCode library.
- **Image Processing**: Pillow.

## 📦 Installation & Setup

1.  **Clone the Repository**
    ```bash
    git clone https://github.com/yourusername/event-management-system.git
    cd event-management-system
    ```

2.  **Create a Virtual Environment**
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **Install Dependencies**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configuration**
    - The application uses environment variables or defaults to a local SQLite database.
    - Set `SESSION_SECRET` and `DATABASE_URL` in your environment for production.

5.  **Initialize Database**
    ```bash
    python -c "from app import initdb; initdb()"
    ```
    *This creates the database tables and seeds initial data (admin user, categories, halls).*

6.  **Run the Application**
    ```bash
    python app.py
    ```
    The app will start at `http://127.0.0.1:5000`.

## 🎫 Ticket System

The system generates a professional PDF ticket for every confirmed booking, featuring:
- **College Branding**: Logo and Name.
- **Event Details**: Title, Date, Time, Venue, and Organizer.
- **Security**: Unique Ticket ID and QR Code for entry verification.
- **Delivery**: Automatically emailed to the student and available for download on the portal.

## 📂 Project Structure

```
├── app.py                 # Main Application Logic (Routes, Models, Config)
├── static/
│   ├── css/               # Stylesheets
│   ├── js/                # JavaScript files
│   ├── images/            # Static assets (Logos)
│   └── uploads/           # User uploads (Posters, Tickets, Invitations, Gallery)
├── templates/             # HTML Templates (Jinja2)
├── requirements.txt       # Python Dependencies
└── README.md              # Project Documentation
```

## 👥 Usage Guide

- **Default Admin Login**:
    - Email: `admin@example.com`
    - Password: `admin`
- **Register**: New users can register as Students. Faculty and Organizer roles are assigned by the Admin.

## 📄 License

This project is proprietary software developed for Cauvery College for Women.

---
*Developed with ❤️ by the Advanced Agentic Coding Team.*
