#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_helpdesk_pro.py
Creates a full production-ready Flask + PostgreSQL Helpdesk system (multilingual, secure, responsive)
Part 1/3
"""

import os
import sys
import shutil
import zipfile
import textwrap
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
APP_NAME = "helpdesk_pro"


def create_dir_structure():
    print("[+] Creating directory structure...")
    dirs = [
        f"{APP_NAME}",
        f"{APP_NAME}/app",
        f"{APP_NAME}/app/models",
        f"{APP_NAME}/app/auth",
        f"{APP_NAME}/app/tickets",
        f"{APP_NAME}/app/users",
        f"{APP_NAME}/app/dashboard",
        f"{APP_NAME}/app/api",
        f"{APP_NAME}/app/i18n",
        f"{APP_NAME}/app/utils",
        f"{APP_NAME}/templates",
        f"{APP_NAME}/templates/includes",
        f"{APP_NAME}/static/css",
        f"{APP_NAME}/static/js",
        f"{APP_NAME}/static/img",
        f"{APP_NAME}/migrations",
        f"{APP_NAME}/logs",
        f"{APP_NAME}/templates/auth",
        f"{APP_NAME}/templates/users",
        f"{APP_NAME}/templates/tickets",
        f"{APP_NAME}/templates/dashboard"

    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)


def write_file(path: str, content: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(content).strip() + "\n")


def create_core_files():
    print("[+] Writing core files...")

    # requirements.txt
    write_file(f"{APP_NAME}/requirements.txt", """
        Flask==3.0.3
        Flask-Login==0.6.3
        Flask-WTF==1.2.1
        Flask-Mail==0.10.0
        Flask-Migrate==4.0.5
        Flask-Babel==4.0.0
        Flask-JWT-Extended==4.6.0
        SQLAlchemy==2.0.30
        psycopg2-binary==2.9.9
        itsdangerous==2.1.2
        bcrypt==4.1.3
        python-dotenv==1.0.1
        email-validator==2.2.0
        WTForms==3.1.2
        gunicorn==21.2.0
        cryptography==42.0.7
    """)

    # .env.example
    write_file(f"{APP_NAME}/.env.example", """
        FLASK_ENV=production
        SECRET_KEY=supersecretkey
        SQLALCHEMY_DATABASE_URI=postgresql+psycopg2://itdesk:superpass@192.168.7.10:5432/itdesk
        MAIL_SERVER=smtp.office365.com
        MAIL_PORT=587
        MAIL_USE_TLS=True
        MAIL_USERNAME=support@company.com
        MAIL_PASSWORD=Encrypted: <generated>
        DEFAULT_LANGUAGE=en
        LOG_LEVEL=INFO
    """)

    # config.py
    write_file(f"{APP_NAME}/config.py", """
        import os
        from datetime import timedelta
        from dotenv import load_dotenv
        load_dotenv()

        class Config:
            SECRET_KEY = os.getenv('SECRET_KEY', 'changeme')
            SQLALCHEMY_DATABASE_URI = os.getenv('SQLALCHEMY_DATABASE_URI')
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            MAIL_SERVER = os.getenv('MAIL_SERVER')
            MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
            MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
            MAIL_USERNAME = os.getenv('MAIL_USERNAME')
            MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
            LANGUAGES = ['en', 'el']
            BABEL_DEFAULT_LOCALE = os.getenv('DEFAULT_LANGUAGE', 'en')
            PERMANENT_SESSION_LIFETIME = timedelta(minutes=45)
            LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
            JWT_SECRET_KEY = os.getenv('SECRET_KEY', 'changeme')
            UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
            MAX_CONTENT_LENGTH = 16 * 1024 * 1024
            SECURITY_HEADERS = {
                "Content-Security-Policy": "default-src 'self'; img-src 'self' data:;",
                "X-Frame-Options": "DENY",
                "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload"
            }
    """)

    # wsgi.py
    write_file(f"{APP_NAME}/wsgi.py", """
        from app import create_app
        app = create_app()
        if __name__ == "__main__":
            app.run(host="0.0.0.0", port=5000)
    """)

    # run.py
    write_file(f"{APP_NAME}/run.py", """
        from app import create_app
        app = create_app()
        if __name__ == '__main__':
            app.run(debug=False)
    """)


def create_app_init():
    print("[+] Creating Flask app initializer...")

    write_file(f"{APP_NAME}/app/__init__.py", """
        import os
        import logging
        from flask import Flask, render_template, request, g
        from flask_sqlalchemy import SQLAlchemy
        from flask_migrate import Migrate
        from flask_login import LoginManager
        from flask_mail import Mail
        from flask_wtf import CSRFProtect
        from flask_babel import Babel, _
        from flask_jwt_extended import JWTManager
        from logging.handlers import RotatingFileHandler
        from config import Config

        db = SQLAlchemy()
        migrate = Migrate()
        login_manager = LoginManager()
        mail = Mail()
        csrf = CSRFProtect()
        jwt = JWTManager()
        babel = Babel()

        def create_app():
            app = Flask(__name__)
            app.config.from_object(Config)

            db.init_app(app)
            migrate.init_app(app, db)
            mail.init_app(app)
            csrf.init_app(app)
            login_manager.init_app(app)
            jwt.init_app(app)
            babel.init_app(app)

            from app.auth.routes import auth_bp
            from app.tickets.routes import tickets_bp
            from app.users.routes import users_bp
            from app.dashboard.routes import dashboard_bp
            from app.api.routes import api_bp

            app.register_blueprint(auth_bp)
            app.register_blueprint(tickets_bp)
            app.register_blueprint(users_bp)
            app.register_blueprint(dashboard_bp)
            app.register_blueprint(api_bp, url_prefix='/api/v1')

            if not os.path.exists('logs'):
                os.mkdir('logs')
            handler = RotatingFileHandler('logs/helpdesk.log', maxBytes=10240, backupCount=10)
            handler.setLevel(app.config['LOG_LEVEL'])
            app.logger.addHandler(handler)

            @app.before_request
            def before_request():
                g.locale = str(get_locale())

            @babel.localeselector
            def get_locale():
                return request.accept_languages.best_match(app.config['LANGUAGES'])

            @app.route('/')
            def index():
                return render_template('index.html')

            return app
    """)


# run section 1
if __name__ == "__main__":
    print("=== Building Helpdesk Pro Project (Part 1/3) ===")
    create_dir_structure()
    create_core_files()
    create_app_init()
    print("=== Part 1 completed. Continue with Part 2 ===")
# ───────────────────────────────
# Part 2/3 — Models, Blueprints, Templates
# ───────────────────────────────


def create_models():
    print("[+] Creating models...")

    write_file(f"{APP_NAME}/app/models/__init__.py",
               "from .user import *\nfrom .ticket import *\nfrom .audit import *\n")

    write_file(f"{APP_NAME}/app/models/user.py", """
        from app import db
        from flask_login import UserMixin
        from datetime import datetime
        import bcrypt

        class User(UserMixin, db.Model):
            id = db.Column(db.Integer, primary_key=True)
            username = db.Column(db.String(64), unique=True, nullable=False)
            email = db.Column(db.String(120), unique=True, nullable=False)
            password_hash = db.Column(db.String(128), nullable=False)
            role = db.Column(db.String(20), default='user')
            department = db.Column(db.String(100))
            active = db.Column(db.Boolean, default=True)
            created_at = db.Column(db.DateTime, default=datetime.utcnow)

            def set_password(self, password):
                self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            def check_password(self, password):
                return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))
    """)

    write_file(f"{APP_NAME}/app/models/ticket.py", """
        from app import db
        from datetime import datetime

        class Ticket(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            subject = db.Column(db.String(255), nullable=False)
            description = db.Column(db.Text, nullable=False)
            priority = db.Column(db.String(50))
            status = db.Column(db.String(50), default='Open')
            department = db.Column(db.String(100))
            assigned_to = db.Column(db.String(100))
            created_by = db.Column(db.String(100))
            created_at = db.Column(db.DateTime, default=datetime.utcnow)
            updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    """)

    write_file(f"{APP_NAME}/app/models/audit.py", """
        from app import db
        from datetime import datetime

        class AuditLog(db.Model):
            id = db.Column(db.Integer, primary_key=True)
            user = db.Column(db.String(64))
            action = db.Column(db.String(256))
            ip = db.Column(db.String(64))
            created_at = db.Column(db.DateTime, default=datetime.utcnow)
    """)


def create_blueprints():
    print("[+] Creating blueprints...")

    # ── AUTH ──
    write_file(f"{APP_NAME}/app/auth/routes.py", """
        from flask import Blueprint, render_template, redirect, url_for, request, flash
        from flask_login import login_user, logout_user, login_required
        from app import db, login_manager
        from app.models.user import User

        auth_bp = Blueprint('auth', __name__)

        @auth_bp.route('/login', methods=['GET', 'POST'])
        def login():
            if request.method == 'POST':
                username = request.form['username']
                password = request.form['password']
                user = User.query.filter_by(username=username).first()
                if user and user.check_password(password):
                    login_user(user)
                    return redirect(url_for('dashboard.index'))
                flash('Invalid credentials', 'danger')
            return render_template('auth/login.html')

        @auth_bp.route('/logout')
        @login_required
        def logout():
            logout_user()
            flash('Logged out', 'info')
            return redirect(url_for('auth.login'))
    """)

    # ── DASHBOARD ──
    write_file(f"{APP_NAME}/app/dashboard/routes.py", """
        from flask import Blueprint, render_template
        from flask_login import login_required
        from app.models.ticket import Ticket
        from app.models.user import User

        dashboard_bp = Blueprint('dashboard', __name__)

        @dashboard_bp.route('/dashboard')
        @login_required
        def index():
            tickets = Ticket.query.all()
            users = User.query.count()
            open_tickets = Ticket.query.filter_by(status='Open').count()
            closed_tickets = Ticket.query.filter_by(status='Closed').count()
            return render_template('dashboard/index.html', tickets=tickets, users=users,
                                   open_tickets=open_tickets, closed_tickets=closed_tickets)
    """)

    # ── TICKETS ──
    write_file(f"{APP_NAME}/app/tickets/routes.py", """
        from flask import Blueprint, render_template, request, redirect, url_for, flash
        from flask_login import login_required, current_user
        from app import db
        from app.models.ticket import Ticket

        tickets_bp = Blueprint('tickets', __name__)

        @tickets_bp.route('/tickets')
        @login_required
        def list_tickets():
            q = request.args.get('q', '')
            if q:
                tickets = Ticket.query.filter(Ticket.subject.ilike(f"%{q}%")).all()
            else:
                tickets = Ticket.query.all()
            return render_template('tickets/list.html', tickets=tickets, q=q)

        @tickets_bp.route('/tickets/create', methods=['GET', 'POST'])
        @login_required
        def create_ticket():
            if request.method == 'POST':
                t = Ticket(
                    subject=request.form['subject'],
                    description=request.form['description'],
                    priority=request.form['priority'],
                    department=request.form['department'],
                    created_by=current_user.username
                )
                db.session.add(t)
                db.session.commit()
                flash('Ticket created successfully', 'success')
                return redirect(url_for('tickets.list_tickets'))
            return render_template('tickets/create.html')
    """)

    # ── USERS ──
    write_file(f"{APP_NAME}/app/users/routes.py", """
        from flask import Blueprint, render_template
        from flask_login import login_required
        from app.models.user import User

        users_bp = Blueprint('users', __name__)

        @users_bp.route('/users')
        @login_required
        def list_users():
            users = User.query.all()
            return render_template('users/list.html', users=users)
    """)

    # ── API ──
    write_file(f"{APP_NAME}/app/api/routes.py", """
        from flask import Blueprint, jsonify, request
        from flask_jwt_extended import jwt_required, create_access_token
        from app.models.ticket import Ticket
        from app.models.user import User
        from app import db

        api_bp = Blueprint('api', __name__)

        @api_bp.route('/login', methods=['POST'])
        def api_login():
            data = request.get_json()
            user = User.query.filter_by(username=data.get('username')).first()
            if user and user.check_password(data.get('password')):
                token = create_access_token(identity=user.username)
                return jsonify({'token': token})
            return jsonify({'error': 'Invalid credentials'}), 401

        @api_bp.route('/tickets', methods=['GET'])
        @jwt_required()
        def api_get_tickets():
            tickets = Ticket.query.all()
            return jsonify([{'id': t.id, 'subject': t.subject, 'status': t.status} for t in tickets])
    """)


def create_templates():
    print("[+] Creating templates (Bootstrap 5, Light/Dark)...")

    base_html = """
    <!doctype html>
    <html lang="{{ g.locale }}">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{{ _('Helpdesk Pro') }}</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css" rel="stylesheet">
        <script>
          document.addEventListener('DOMContentLoaded', () => {
            const toggle = document.getElementById('theme-toggle');
            const theme = localStorage.getItem('theme') || 'light';
            document.body.dataset.bsTheme = theme;
            toggle.checked = theme === 'dark';
            toggle.addEventListener('change', e => {
              const mode = e.target.checked ? 'dark' : 'light';
              document.body.dataset.bsTheme = mode;
              localStorage.setItem('theme', mode);
            });
          });
        </script>
      </head>
      <body data-bs-theme="light">
        <nav class="navbar navbar-expand-lg bg-body-tertiary shadow-sm">
          <div class="container-fluid">
            <a class="navbar-brand" href="/">Helpdesk Pro</a>
            <div class="form-check form-switch ms-auto">
              <input class="form-check-input" type="checkbox" id="theme-toggle">
              <label class="form-check-label" for="theme-toggle"><i class="fa fa-moon"></i></label>
            </div>
          </div>
        </nav>
        <div class="container mt-4">
          {% block content %}{% endblock %}
        </div>
      </body>
    </html>
    """

    index_html = """
    {% extends 'base.html' %}
    {% block content %}
    <div class="text-center">
      <h1>{{ _('Welcome to Helpdesk Pro') }}</h1>
      <p><a href="{{ url_for('auth.login') }}" class="btn btn-primary">{{ _('Login') }}</a></p>
    </div>
    {% endblock %}
    """

    login_html = """
    {% extends 'base.html' %}
    {% block content %}
    <div class="row justify-content-center">
      <div class="col-md-4">
        <h3 class="text-center">{{ _('Login') }}</h3>
        <form method="post">
          <div class="mb-3">
            <label class="form-label">{{ _('Username') }}</label>
            <input type="text" class="form-control" name="username">
          </div>
          <div class="mb-3">
            <label class="form-label">{{ _('Password') }}</label>
            <input type="password" class="form-control" name="password">
          </div>
          <button type="submit" class="btn btn-primary w-100">{{ _('Sign in') }}</button>
        </form>
      </div>
    </div>
    {% endblock %}
    """

    dashboard_html = """
    {% extends 'base.html' %}
    {% block content %}
    <h3>{{ _('Dashboard Overview') }}</h3>
    <div class="row mt-3">
      <div class="col-md-3"><div class="alert alert-info">{{ _('Users') }}: {{ users }}</div></div>
      <div class="col-md-3"><div class="alert alert-success">{{ _('Open Tickets') }}: {{ open_tickets }}</div></div>
      <div class="col-md-3"><div class="alert alert-secondary">{{ _('Closed Tickets') }}: {{ closed_tickets }}</div></div>
    </div>
    {% endblock %}
    """

    create_html = """
    {% extends 'base.html' %}
    {% block content %}
    <h3>{{ _('Create Ticket') }}</h3>
    <form method="post">
      <div class="mb-3"><label>{{ _('Subject') }}</label><input name="subject" class="form-control"></div>
      <div class="mb-3"><label>{{ _('Description') }}</label><textarea name="description" class="form-control"></textarea></div>
      <div class="mb-3"><label>{{ _('Priority') }}</label><select name="priority" class="form-select">
        <option>Low</option><option>Medium</option><option>High</option></select></div>
      <div class="mb-3"><label>{{ _('Department') }}</label><input name="department" class="form-control"></div>
      <button class="btn btn-success">{{ _('Submit') }}</button>
    </form>
    {% endblock %}
    """

    list_html = """
    {% extends 'base.html' %}
    {% block content %}
    <h3>{{ _('Tickets') }}</h3>
    <form class="mb-3" method="get"><input name="q" placeholder="{{ _('Search') }}" value="{{ q }}" class="form-control"></form>
    <table class="table table-striped">
      <thead><tr><th>ID</th><th>{{ _('Subject') }}</th><th>{{ _('Status') }}</th><th>{{ _('Priority') }}</th><th>{{ _('Created') }}</th></tr></thead>
      <tbody>{% for t in tickets %}
        <tr><td>{{ t.id }}</td><td>{{ t.subject }}</td><td>{{ t.status }}</td><td>{{ t.priority }}</td><td>{{ t.created_at.strftime('%Y-%m-%d') }}</td></tr>
      {% endfor %}</tbody>
    </table>
    {% endblock %}
    """

    write_file(f"{APP_NAME}/templates/base.html", base_html)
    write_file(f"{APP_NAME}/templates/index.html", index_html)
    write_file(f"{APP_NAME}/templates/auth/login.html", login_html)
    write_file(f"{APP_NAME}/templates/dashboard/index.html", dashboard_html)
    write_file(f"{APP_NAME}/templates/tickets/create.html", create_html)
    write_file(f"{APP_NAME}/templates/tickets/list.html", list_html)


# Run part 2 section
if __name__ == "__main__":
    create_models()
    create_blueprints()
    create_templates()
    print("=== Part 2 completed. Continue with Part 3 ===")
# ───────────────────────────────
# Part 3/3 — Demo data, Babel, Zip packaging
# ───────────────────────────────


def create_demo_data():
    print("[+] Creating demo data initializer...")
    write_file(f"{APP_NAME}/app/utils/demo_data.py", """
        from app import db
        from app.models.user import User
        from app.models.ticket import Ticket
        from datetime import datetime

        def init_demo_data():
            if not User.query.filter_by(username='admin').first():
                admin = User(username='admin', email='admin@helpdesk.local', role='admin')
                admin.set_password('change_me')
                db.session.add(admin)
                db.session.commit()

            if not Ticket.query.first():
                demo_tickets = [
                    Ticket(subject='Printer not working', description='Office printer error E05', priority='High', department='IT', created_by='admin'),
                    Ticket(subject='Email not syncing', description='Outlook fails to sync inbox', priority='Medium', department='Support', created_by='admin'),
                    Ticket(subject='VPN connection drops', description='Random disconnections during work', priority='Low', department='Network', created_by='admin')
                ]
                for t in demo_tickets:
                    db.session.add(t)
                db.session.commit()
    """)


def create_utils():
    print("[+] Creating utility helpers...")

    write_file(f"{APP_NAME}/app/utils/security.py", """
        import base64, os, sys
        from cryptography.fernet import Fernet
        if sys.platform.startswith('win'):
            import win32crypt

        def encrypt_secret(secret: str) -> str:
            if sys.platform.startswith('win'):
                data = win32crypt.CryptProtectData(secret.encode(), None, None, None, None, 0)
                return base64.b64encode(data[1]).decode()
            else:
                key = os.environ.get('FERNET_KEY') or Fernet.generate_key()
                f = Fernet(key)
                return 'fernet:' + key.decode() + ':' + f.encrypt(secret.encode()).decode()

        def decrypt_secret(token: str) -> str:
            if token.startswith('fernet:'):
                _, key, enc = token.split(':', 2)
                f = Fernet(key.encode())
                return f.decrypt(enc.encode()).decode()
            if sys.platform.startswith('win'):
                data = base64.b64decode(token)
                return win32crypt.CryptUnprotectData(data, None, None, None, 0)[1].decode()
            return token
    """)


def create_babel_files():
    print("[+] Creating Babel i18n folders...")
    os.makedirs(f"{APP_NAME}/app/i18n/en/LC_MESSAGES", exist_ok=True)
    os.makedirs(f"{APP_NAME}/app/i18n/el/LC_MESSAGES", exist_ok=True)

    write_file(f"{APP_NAME}/app/i18n/en/LC_MESSAGES/messages.po", """
        msgid "Helpdesk Pro"
        msgstr "Helpdesk Pro"

        msgid "Welcome to Helpdesk Pro"
        msgstr "Welcome to Helpdesk Pro"

        msgid "Login"
        msgstr "Login"

        msgid "Sign in"
        msgstr "Sign in"

        msgid "Dashboard Overview"
        msgstr "Dashboard Overview"

        msgid "Users"
        msgstr "Users"

        msgid "Open Tickets"
        msgstr "Open Tickets"

        msgid "Closed Tickets"
        msgstr "Closed Tickets"

        msgid "Tickets"
        msgstr "Tickets"

        msgid "Create Ticket"
        msgstr "Create Ticket"

        msgid "Submit"
        msgstr "Submit"
    """)

    write_file(f"{APP_NAME}/app/i18n/el/LC_MESSAGES/messages.po", """
        msgid "Helpdesk Pro"
        msgstr "Helpdesk Pro"

        msgid "Welcome to Helpdesk Pro"
        msgstr "Καλώς ήρθατε στο Helpdesk Pro"

        msgid "Login"
        msgstr "Σύνδεση"

        msgid "Sign in"
        msgstr "Είσοδος"

        msgid "Dashboard Overview"
        msgstr "Επισκόπηση Πίνακα"

        msgid "Users"
        msgstr "Χρήστες"

        msgid "Open Tickets"
        msgstr "Ανοικτά Αιτήματα"

        msgid "Closed Tickets"
        msgstr "Κλειστά Αιτήματα"

        msgid "Tickets"
        msgstr "Αιτήματα"

        msgid "Create Ticket"
        msgstr "Δημιουργία Αιτήματος"

        msgid "Submit"
        msgstr "Υποβολή"
    """)


def create_readme():
    print("[+] Creating README.md...")
    write_file(f"{APP_NAME}/README.md", f"""
        # Helpdesk Pro — Flask + PostgreSQL Ticketing System

        ## Quick Start

        ```bash
        python -m venv .venv
        source .venv/bin/activate   # ή .venv\\Scripts\\activate στα Windows
        pip install -r requirements.txt
        flask db upgrade
        flask run
        ```

        ## Default admin
        username: admin
        password: change_me

        ## PostgreSQL connection
        postgresql+psycopg2://itdesk:superpass@192.168.7.10:5432/itdesk

        ## Multilingual
        English / Greek (switch via Accept-Language header)

        ## Notes
        - Secure headers (CSP, HSTS, X-Frame-Options)
        - Email notifications (SMTP TLS)
        - JWT REST API
        - Bootstrap 5 + FontAwesome + Light/Dark Mode Switch
        - Logging in logs/helpdesk.log
    """)


def zip_project():
    print("[+] Compressing helpdesk_pro.zip ...")
    zipf = zipfile.ZipFile(f"{APP_NAME}.zip", 'w', zipfile.ZIP_DEFLATED)
    for root, dirs, files in os.walk(APP_NAME):
        for file in files:
            full_path = os.path.join(root, file)
            arcname = os.path.relpath(
                full_path, start=os.path.dirname(APP_NAME))
            zipf.write(full_path, arcname)
    zipf.close()
    print(f"[✓] {APP_NAME}.zip created successfully.")


def finalize():
    create_demo_data()
    create_utils()
    create_babel_files()
    create_readme()
    zip_project()
    print("=== ✅ Helpdesk Pro build complete ===")
    print("Run with:\n  cd helpdesk_pro\n  flask db upgrade\n  flask run")


# ───────────────────────────────
# MAIN ENTRY
# ───────────────────────────────
if __name__ == "__main__":
    print("=== Finalizing Helpdesk Pro Build (Part 3/3) ===")
    finalize()
