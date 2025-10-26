# Helpdesk Pro Installation Guide

These instructions walk you through deploying **Helpdesk Pro** on a fresh server. They assume a Unix-like environment, but the steps are similar on Windows (swap `source .venv/bin/activate` with `.venv\Scripts\activate` and adjust paths).

---

## 1. System Requirements

| Component        | Version / Notes                                          |
|------------------|----------------------------------------------------------|
| Python           | 3.12+ (virtual environment strongly recommended)         |
| PostgreSQL       | 13+                                                      |
| Node toolchain   | Optional – assets are precompiled                        |
| SMTP account     | Required for password reset emails (Office365 example)   |

Ensure the server has `git`, `gcc`/build tools, and PostgreSQL client libraries (`libpq-dev` on Debian/Ubuntu, `postgresql-devel` on RHEL/CentOS).

---

## 2. Clone the Repository

```bash
git clone https://github.com/ibsoft/helpdesk_pro.git
cd helpdesk_pro
```

The Flask application source resides in the nested `helpdesk_pro/` directory. All commands below assume you are inside that folder:

```bash
cd helpdesk_pro
```

---

## 3. Create Virtual Environment & Install Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt
```

Dependencies include Flask, SQLAlchemy, Alembic, Flask-Mail, pdfminer, and python-docx.

---

## 4. Configure Environment (.env)

Create (or edit) a `.env` file in the project root (same directory as `requirements.txt`). Example production-ready values:

```env
FLASK_ENV=production
SECRET_KEY=supersecretkey
SQLALCHEMY_DATABASE_URI=postgresql+psycopg2://postgres:superpass@192.168.1.123:5432/helpdesk_pro

MAIL_SERVER=smtp.office365.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=support@company.com
MAIL_PASSWORD="Encrypted: <generated>"
MAIL_DEFAULT_SENDER=support@company.com

DEFAULT_LANGUAGE=en
LOG_LEVEL=INFO
ASSISTANT_TOOL_CALL_DEPTH_LIMIT=100
```

> **Tip:** If you change the database credentials, remember to adjust firewall rules and create the target database beforehand.

---

## 5. Initialize the Database

Make sure PostgreSQL is running and the database specified in `SQLALCHEMY_DATABASE_URI` exists. Then run:

```bash
flask db upgrade
```

Alembic migrations will create all tables (tickets, inventory, assistant, auth configuration, etc.).

---

## 6. Create the Initial Administrator

Start the app temporarily (see the next section) and visit `http://<host>:5000/auth/setup`. Supply an admin username, email, and password. After the first user is created, the setup route becomes unavailable.

---

## 7. Run the Application

### Development / Evaluation

```bash
flask --app app:create_app run --host=0.0.0.0 --port=5000
```

Navigate to `http://<host>:5000`. Log in using the admin credentials created above to configure roles, access, and authentication settings.

### Production (Gunicorn + systemd Example)

```bash
gunicorn --workers 4 --bind 0.0.0.0:8000 "app:create_app()"
```

Reverse-proxy with Nginx/Apache as desired. Ensure the environment variables defined in `.env` are exported in the service unit (`EnvironmentFile=/path/to/.env`).

---

## 8. Post-Installation Steps

1. **Configure Authentication:** Log in as admin → *Manage → Authentication* to decide whether self-registration and password resets are allowed. Set the default role for new users (usually `user`).
2. **Mail Verification:** With SMTP configured, click “Forgot password?” on the login page to verify reset emails are delivered.
3. **Assistant Settings:** *Manage → AI Assistant* to enable the assistant widget and choose the provider (OpenAI, Webhook, Built-in, OpenWebUI).
4. **Access Control:** *Manage → Access* lets you fine-tune menu visibility per role.
5. **Static Assets & Upload Paths:** Ensure `uploads/`, `instance/knowledge_uploads/`, `instance/chat_uploads/`, and `instance/assistant_uploads/` are writable by the web process.

---

## 9. Updating the Application

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt
flask db upgrade
systemctl restart helpdesk_pro      # or restart your WSGI process
```

Always review `CHANGELOG`/commit notes for schema or configuration changes.

---

## 10. Troubleshooting

- **Database connectivity errors:** Verify `SQLALCHEMY_DATABASE_URI` and ensure PostgreSQL trusts the connecting host.
- **Email not sending:** Confirm `MAIL_*` variables, credentials, and network access to the SMTP server.
- **Assistant document uploads:** Make sure `instance/assistant_uploads` exists and is writable.
- **Token expiration:** Password reset tokens expire after 1 hour; generate a new email if needed.

For additional help, check `logs/helpdesk.log`, or run with `LOG_LEVEL=DEBUG` during troubleshooting (not recommended in production).

---

Installation is complete! Continue with tenant-specific configuration and begin onboarding your IT team. If you require clustering, containerization, or background task integration, the existing Flask factory pattern makes it straightforward to extend. Happy supporting!
