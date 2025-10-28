# Helpdesk Pro

Helpdesk Pro is a full-stack IT service management platform built with Flask, PostgreSQL, SQLAlchemy, and Bootstrap 5. The application covers ticketing, knowledge base, collaboration, inventory (hardware & software), network management, and an integrated AI assistant. It includes a first‑party REST API with API-key authentication plus an admin UI for managing the platform.

---

## Table of Contents

1. [Features](#features)
2. [Architecture Overview](#architecture-overview)
3. [Getting Started](#getting-started)
   - [Prerequisites](#prerequisites)
   - [Installation](#installation)
   - [Configuration](#configuration)
   - [Database Setup](#database-setup)
4. [Running the Application](#running-the-application)
5. [Key Modules](#key-modules)
   - [Authentication & Roles](#authentication--roles)
   - [Ticketing](#ticketing)
   - [Knowledge Base](#knowledge-base)
   - [Inventory](#inventory)
   - [Networks](#networks)
   - [AI Assistant](#ai-assistant)
   - [Collaboration](#collaboration)
6. [REST API](#rest-api)
   - [Authentication](#authentication)
   - [Swagger / OpenAPI](#swagger--openapi)
   - [Endpoints Summary](#endpoints-summary)
7. [Admin Tools](#admin-tools)
   - [Access Control](#access-control)
   - [API Key Management](#api-key-management)
   - [Localization](#localization)
8. [Project Structure](#project-structure)
9. [Development Workflow](#development-workflow)
10. [Testing](#testing)
11. [Deployment Notes](#deployment-notes)
12. [Troubleshooting](#troubleshooting)
13. [License](#license)

---

## Features

- **Role-based access control** (Admin, Manager, Technician, User) with granular menu permissions.
- **Ticket lifecycle management** with comments, attachments, audit logging, SLA-friendly metadata, and DataTable exports.
- **Knowledge base** with versioning, multilingual support (English/Greek), attachment indexing, and advanced search with tagging.
- **Asset inventory** for software (licenses, keys, assignment tracking) and hardware (asset tags, configuration, lifecycle).
- **Network module** for subnet tracking, host assignment, and IP availability lookups.
- **Real-time collaboration** area with conversations, message read states, and file sharing.
- **Integrated AI assistant** configurable per tenant; supports OpenAI, webhook, or builtin data-tooling modes.
- **REST API** for tickets, knowledge, hardware, and software with API key management, Swagger documentation, and JSON output.
- **Internationalization** with Flask-Babel and dynamic locale switching.
- **Responsive UI** built on Bootstrap 5, FontAwesome 6, light/dark mode, and a card-driven dashboard.

---

## Architecture Overview

| Layer            | Technology                                       |
|------------------|--------------------------------------------------|
| Framework        | Flask 3.x (factory pattern)                      |
| ORM              | SQLAlchemy + Flask-Migrate                       |
| Database         | PostgreSQL (production) / SQLite (development)   |
| Authentication   | Flask-Login                                       |
| Frontend         | Bootstrap 5, FontAwesome 6, jQuery, DataTables   |
| Background tasks | (Handled synchronously; integrate Celery easily) |
| API Auth         | API keys stored hashed with bcrypt               |
| AI Assistant     | Configurable provider, builtin tooling, webhooks |
| Localization     | Flask-Babel 3.x (English / Greek)                |

---

## Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL 14+ (or compatible)
- Node tooling optional (assets already bundled)
- Git, virtualenv

### Installation

```bash
git clone https://github.com/your-org/helpdesk_pro.git
cd helpdesk_pro/helpdesk_pro

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Configuration

Copy `.env.example` (if provided) or create `instance/.env`. The application reads configuration via `python-dotenv`.

Important environment variables (`config.py`):

| Variable                    | Description                                                   | Default              |
|-----------------------------|---------------------------------------------------------------|----------------------|
| `SECRET_KEY`                | Flask secret key / JWT secret                                 | `changeme`           |
| `SQLALCHEMY_DATABASE_URI`   | Database connection string                                    | `sqlite:///...`      |
| `MAIL_*`                    | SMTP settings (server, port, TLS, username, password)         | None                 |
| `LOG_LEVEL`                 | Logging level                                                 | `INFO`               |
| `APP_VERSION`               | Displayed in footer / API logs                               | `1.0.5`              |
| `DEFAULT_LANGUAGE`          | Default UI locale                                             | `en`                 |
| `SQLALCHEMY_ECHO`           | Enable SQL logging                                            | `False`              |

Uploads are stored under `uploads/` (tickets) and `instance/knowledge_uploads` / `instance/chat_uploads`. Ensure these directories are writable.

### Database Setup

```bash
flask db upgrade          # applies migrations
```

The first boot seeds an admin user (`admin` / `admin123`). Change the password immediately in production.

If you change models (e.g., after introducing API keys), create migrations:

```bash
flask db migrate -m "describe change"
flask db upgrade
```

---

## Running the Application

Development run (auto reload):

```bash
flask run
```

Configurable via `FLASK_APP=run.py` or using the provided `run.py` script. Production deployments typically run via Gunicorn behind Nginx:

```bash
gunicorn --bind 0.0.0.0:8000 "run:create_app()"
```

---

## Key Modules

### Authentication & Roles

- User accounts live in `app/models/user.py`.
- Roles: `admin`, `manager`, `technician`, `user`.
- Menu-level overrides stored in `menu_permission` and configurable under Manage → Access.
- Login via `/auth/login`; password hashing uses bcrypt.

### Ticketing

- CRUD routes in `app/tickets/routes.py`.
- Tickets support comments, attachments, audit logs, and assignment.
- Dashboard charts summarise counts per status/department.

### Knowledge Base

- Routes in `app/knowledge/routes.py`.
- Articles support versioning, attachments, and full-text (SQL `ILIKE`) search across titles, summaries, tags, content, and attachment text/names.
- The UI includes a “search hero” with advanced filters and pagination (100 items per page).

### Inventory

- Software assets (`software_asset`) track license metadata, keys, renewal, assignment.
- Hardware assets (`hardware_asset`) track configuration, lifecycle, location, assignment.
- Both modules expose search, filters, and AI assistant integration.

### Networks

- Subnet definitions with hosts for IP management.
- Assistant builtin tools surface IP availability queries.

### AI Assistant

- Blueprint `app/assistant/routes.py`.
- Providers: builtin database tooling, OpenAI, hybrid (tools + LLM), webhook.
- Extensive routing for tickets, knowledge, hardware, software, and network prompts.
- Configuration from Manage → AI Assistant (system prompts, OpenAI keys, webhooks).

### Collaboration

- Chats, unread counts, membership, attachments.
- Integrates with dashboard notifications.

---

## REST API

All endpoints live under `/api/v1` and require an API key (except for `openapi.json`).

### Authentication

- Generate keys via Manage → API Keys.
- Keys are shown only once on creation/rotation.
- Include in requests as header:

  ```http
  X-API-Key: hp_<prefix>_<secret>
  ```

  or `Authorization: Bearer hp_<prefix>_<secret>`.

### Swagger / OpenAPI

- REST schema: `/api/v1/openapi.json`
- Admin UI: Manage → API Docs (embedded Swagger UI). The UI reads from the above JSON. Store an API key in `localStorage` with key `helpdeskApiKey` to auto-fill requests.

### Endpoints Summary

| Method | Path                                | Description                                 |
|--------|-------------------------------------|---------------------------------------------|
| GET    | `/api/v1/status`                    | Returns API status and client metadata      |
| GET    | `/api/v1/tickets`                   | List tickets (filters: `status`, `department`, `assigned_to`) |
| POST   | `/api/v1/tickets`                   | Create ticket                               |
| GET    | `/api/v1/tickets/<id>`              | Fetch single ticket                         |
| PATCH  | `/api/v1/tickets/<id>`              | Update ticket fields                        |
| DELETE | `/api/v1/tickets/<id>`              | Delete ticket                               |
| GET    | `/api/v1/knowledge?q=...`           | Search published articles and attachments   |
| POST   | `/api/v1/knowledge`                 | Create article (with optional tags/category)|
| GET    | `/api/v1/inventory/software`        | List software assets                        |
| POST   | `/api/v1/inventory/software`        | Create software asset                       |
| GET    | `/api/v1/inventory/software/<id>`   | Retrieve software asset                     |
| PATCH  | `/api/v1/inventory/software/<id>`   | Update software asset                       |
| DELETE | `/api/v1/inventory/software/<id>`   | Delete software asset                       |
| GET    | `/api/v1/inventory/hardware`        | List hardware assets                        |
| POST   | `/api/v1/inventory/hardware`        | Create hardware asset                       |
| GET    | `/api/v1/inventory/hardware/<id>`   | Retrieve hardware asset                     |
| PATCH  | `/api/v1/inventory/hardware/<id>`   | Update hardware asset                       |
| DELETE | `/api/v1/inventory/hardware/<id>`   | Delete hardware asset                       |

All payloads and responses are documented in the OpenAPI schema.

---

## Admin Tools

### Access Control

Navigate to Manage → Access to override default menu permissions per role. Changes persist in `menu_permission`.

### API Key Management

Manage → API Keys provides:
- Create new API client (with optional default acting user).
- Rotate/ revoke keys.
- Track last used timestamps.
- Delete clients entirely.

Keys are hashed using bcrypt and cannot be recovered once generated.

### Email to Ticket

Manage → Email to Ticket lets admins configure an IMAP/POP3 mailbox that will be polled and converted into new tickets. Required steps:

1. Enable the service and provide host, port, protocol, credentials, and optional folder (IMAP).
2. Choose the Helpdesk user that will be recorded as the ticket creator (and optionally an assignee).
3. Set the poll interval (minimum 30 seconds) and defaults for priority/department.
4. Save settings; the background worker starts automatically. Use “Run now” to trigger an immediate fetch after configuration.

Each processed message becomes a ticket with the email subject/body. HTML bodies are cleaned into text; attachments are stored alongside the ticket. Successfully ingested emails are deleted from the mailbox.

### Localization

App supports English and Greek. Locale is stored in session and can be toggled via query param `?lang=en|el`.

---

## Project Structure

```
helpdesk_pro/
├── app/
│   ├── __init__.py          # Flask factory & extension setup
│   ├── api/                 # Public REST API blueprint
│   ├── assistant/           # AI assistant routes
│   ├── auth/                # Authentication flows
│   ├── collab/              # Collaboration/chat
│   ├── dashboard/           # Dashboard & analytics
│   ├── inventory/           # Hardware & software modules
│   ├── knowledge/           # Knowledge base
│   ├── manage/              # Admin UI
│   ├── networks/            # Network module
│   ├── tickets/             # Ticketing
│   ├── users/               # User management
│   └── models/              # SQLAlchemy models (users, tickets, assets, api clients, etc.)
├── migrations/              # Alembic migrations
├── config.py                # Base config settings
├── requirements.txt
├── run.py                   # Entry point for production
├── README.md
└── instance/                # Instance-specific configs, uploads
```

---

## Development Workflow

1. Create feature branch.
2. Update models/controllers/templates/tests.
3. Run lint/test suite.
4. Generate migrations when models change.
5. Verify no sensitive data in repo (license keys are for demo only).
6. Submit pull request with summary and testing steps.

Recommended tools:

```bash
pip install black isort flake8
black app tests
flake8 app
```

---

## Testing

Tests (if present) stored under `tests/`. Run with:

```bash
pytest
```

For manual checks:
- `python3 -m compileall app` ensures bytecode compilation.
- Use the Swagger UI to exercise REST endpoints.
- Test AI assistant flows (OpenAI requires valid API key).

---

## Deployment Notes

- Set `SECRET_KEY` and database credentials via environment variables.
- Configure mail server if password reset / notifications are required.
- Use a WSGI server (Gunicorn/Uvicorn) behind Nginx; enable HTTPS.
- Run `flask db upgrade` as part of deployment pipeline.
- Configure cron or background tasks as needed for reports.
- Monitor logs in `logs/helpdesk.log`; tune rotation in `app/__init__.py`.

---

## Troubleshooting

| Issue | Resolution |
|-------|------------|
| `sqlalchemy.exc.ProgrammingError: relation "api_client" does not exist` | Run migrations (`flask db migrate && flask db upgrade`). |
| Swagger UI shows `UNAUTHORIZED` when loading spec | Ensure `/api/v1/openapi.json` is reachable (already unauthenticated). Browser caching may require hard refresh. |
| AI assistant refuses to answer license queries | Provide builtin tool configuration and ensure relevant assets exist; check logs for fallback info. |
| File upload errors | Confirm `UPLOAD_FOLDER` and instance directories exist and are writable. |
| Emails not sent | Verify SMTP credentials and enable TLS (`MAIL_USE_TLS`). |

---

## License

© 2025 Ioannis A. Bouhras. Licensed under the MIT License. See `LICENSE` (if provided) or include attribution when distributing.

---

Happy troubleshooting! 🛠️ If you build additional modules or integrations, contribute back via pull requests or open issues for feature requests.
