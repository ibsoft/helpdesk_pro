# Helpdesk Pro

Helpdesk Pro is a full‑stack IT service management platform built with Flask, SQLAlchemy, and Bootstrap 5. It provides ticketing, knowledge base, inventory (hardware & software), network maps, collaboration, and an integrated AI assistant. A first‑party REST API with API‑key authentication enables automation and integrations.

---

## Table of Contents

1. Features
2. Architecture
3. Getting Started
   - Prerequisites
   - Installation
   - Configuration
   - Database Setup
4. Running
5. Modules and Capabilities
   - Authentication & Roles
   - Ticketing
   - Knowledge Base
   - Inventory
   - Networks
   - Collaboration
   - AI Assistant
6. REST API (v1)
   - Authentication
   - Endpoints Overview
   - OpenAPI / Swagger
7. Admin Tools
8. Storage & Uploads
9. Project Structure
10. Development
11. Testing
12. Deployment
13. Troubleshooting
14. License

---

## Features

- Role‑based access control (Admin, Manager, Technician, User) with granular menu permissions.
- Ticket lifecycle: create, assign, comment, attach files, audit logs, department scoping, and status/priority flows.
- Knowledge base with versioning, categories/tags, multilingual UI (English/Greek), and attachment text indexing for search.
- Inventory management:
  - Software: licensing, assignment, lifecycle fields.
  - Hardware: asset tags, configuration, status and ownership.
- Fleet monitoring with live telemetry, auto-refreshing dashboards, and remote command/file workflows.
- Network maps: define networks, hosts, generate host lists, and export views.
- Collaboration area for conversation threads and file sharing.
- Integrated AI assistant with pluggable providers and builtin tools.
- REST API for tickets, knowledge, and inventory with API‑key auth and OpenAPI spec.
- Internationalization via Flask‑Babel; light/dark responsive UI.

---

## Architecture

- Framework: Flask (application factory)
- ORM/Migrations: SQLAlchemy + Alembic (Flask‑Migrate)
- DB: PostgreSQL (prod) or SQLite (dev)
- Auth: Flask‑Login (sessions) + API keys (REST)
- UI: Bootstrap 5, FontAwesome 6, jQuery, DataTables
- I18n: Flask‑Babel (en, el)

---

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL 13+ (or SQLite for development)

### Installation

```bash
git clone <repo>
cd helpdesk_pro/helpdesk_pro
python -m venv .venv
# Linux/Mac
source .venv/bin/activate
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

Create `helpdesk_pro/.env` or `helpdesk_pro/instance/.env` and set environment variables. Common settings (see `config.py`):

| Variable | Description | Default |
| --- | --- | --- |
| `SECRET_KEY` | Flask secret | random
| `SQLALCHEMY_DATABASE_URI` | DB connection string | `sqlite:///instance/helpdesk.db`
| `MAIL_*` | SMTP configuration | —
| `LOG_LEVEL` | Logging level | `INFO`
| `DEFAULT_LANGUAGE` | UI locale | `en`
| `KNOWLEDGE_UPLOAD_FOLDER` | Knowledge attachments folder | `instance/knowledge_uploads`
| `TICKETS_UPLOAD_FOLDER` | Ticket attachments folder | `instance/tickets_uploads`

### Database Setup

```bash
flask db upgrade
python -m app.seeds  # optional demo data
```

---

## Running

```bash
flask --app app run --debug              # dev
# or
python wsgi.py                           # production entry (use Gunicorn/Uvicorn + Nginx)
```

---

## Modules and Capabilities

### Authentication & Roles

- Roles: Admin, Manager, Technician, User.
- Managers are scoped to their department for assignment and visibility.
- Session auth (web) and API‑key auth (REST).

### Ticketing

- Create, edit, assign, comment, upload attachments, and delete.
- Department scoping in list and permissions for managers.
- Attachments stored under `instance/tickets_uploads` using unique names and served via a protected route.
- Deleting a ticket removes associated attachment files from disk.

### Knowledge Base

- Articles with versioning, categories/tags, published/draft state.
- Attachment upload with safe naming to `instance/knowledge_uploads`.
- Attachment text extraction for certain MIME types to improve search.
- Deleting an article removes its attachment files from disk.

### Inventory

- Software and Hardware asset registries with CRUD UI and REST API.
- Assign assets to users, track lifecycle fields and timestamps.

### Networks

- Define network maps, add hosts, generate host lists, and export visualizations.

### Fleet Monitoring

- Map-centric dashboard with online/offline telemetry pills, health summaries, and screenshot previews.
- Host detail page refreshes status badges, health cards, and remote action panels via AJAX (send PowerShell scripts, upload files, cancel or view results without reloading).
- Fleet job scheduler queues remote commands or staged uploads across multiple hosts with recurrence support.
- Module structure:
  - `app/fleet/routes.py` – UI views, ingest handlers, remote action endpoints, job scheduler logic.
  - `app/fleet/ingest.py` – agent payload parsing and snapshot persistence.
  - `app/models/fleet.py` – ORM models (hosts, messages, screenshots, alerts, jobs, API keys).
  - `templates/fleet/*.html` – dashboard, host detail, scheduler, shared remote-action partials rendered via AJAX.
- Optional Nginx rate-limiting/RBAC guidance is available in `docs/nginx-rate-limiting.conf` to protect ingest endpoints.
- Optional Nginx rate-limiting/RBAC guidance is available in `docs/nginx-rate-limiting.conf` to protect ingest endpoints.

### Collaboration

- Team conversation space with simple file sharing (scoped by permissions).

### AI Assistant

- Configurable assistant with provider settings via the Admin UI.
- Endpoints to create sessions, upload documents, and exchange messages.

---

## REST API (v1)

Base path: `/api/v1`

### Authentication

Provide an API key in every request using one of:

```
X-API-Key: hp_<prefix>_<secret>
```

or

```
Authorization: Bearer hp_<prefix>_<secret>
```

Manage API keys in the Admin UI. Keys are hashed and cannot be recovered.

### Endpoints Overview

- Health
  - `GET /api/v1/status` – service status

- Tickets
  - `GET /api/v1/tickets` – list (filters: status, department, assigned_to)
  - `POST /api/v1/tickets` – create
  - `GET /api/v1/tickets/<id>` – retrieve
  - `PUT|PATCH /api/v1/tickets/<id>` – update
  - `DELETE /api/v1/tickets/<id>` – delete

- Knowledge Base
  - `GET /api/v1/knowledge` – list/search articles
  - `POST /api/v1/knowledge` – create article (basic fields)

- Inventory – Software
  - `GET /api/v1/inventory/software` – list (filters supported)
  - `POST /api/v1/inventory/software` – create
  - `GET /api/v1/inventory/software/<id>` – retrieve
  - `PUT|PATCH /api/v1/inventory/software/<id>` – update
  - `DELETE /api/v1/inventory/software/<id>` – delete

- Inventory – Hardware
  - `GET /api/v1/inventory/hardware` – list (filters supported)
  - `POST /api/v1/inventory/hardware` – create
  - `GET /api/v1/inventory/hardware/<id>` – retrieve
  - `PUT|PATCH /api/v1/inventory/hardware/<id>` – update
  - `DELETE /api/v1/inventory/hardware/<id>` – delete

See `helpdesk_pro/API.md` for detailed request/response bodies and curl examples.

### OpenAPI / Swagger

- Spec: `GET /api/v1/openapi.json` (no auth)
- Admin UI: Manage → API Docs renders Swagger UI.

---

## Admin Tools

- User management, role assignment, and department metadata.
- API key lifecycle: create, rotate/revoke, default user context.
- Email‑to‑Ticket configuration: IMAP/POP settings, polling interval, defaults.
- General configuration: base URL, i18n, integrations.

---

## Storage & Uploads

- Knowledge attachments: `instance/knowledge_uploads` (configurable via `KNOWLEDGE_UPLOAD_FOLDER`).
- Ticket attachments: `instance/tickets_uploads` (configurable via `TICKETS_UPLOAD_FOLDER`).
- Files are stored with UUID‑prefixed safe names; download uses protected routes with permission checks.
- Deleting an article/ticket removes its attachment files from disk.

Legacy compatibility: older ticket attachments under `static/uploads` are served and cleaned on ticket delete when possible.

---

## Project Structure

```
helpdesk_pro/
  app/
    api/          # Public REST API blueprint
    assistant/    # AI assistant routes
    auth/         # Login/session flows
    inventory/    # Hardware & software modules
    knowledge/    # Knowledge base
    networks/     # Network maps and hosts
    tickets/      # Ticketing UI and actions
    users/        # User management
    manage/       # Admin settings, API keys, docs
    utils/        # Helpers (files, mail, etc.)
    models/       # SQLAlchemy models
  instance/       # Local config and uploads
  migrations/     # Alembic migrations
  config.py       # Settings
  API.md          # Detailed API guide
  README.md
```

---

## Development

```bash
pip install -r requirements.txt
flask db upgrade

# optional tooling
pip install black isort flake8
black app
flake8 app
```

---

## Testing

```bash
pytest
```

Manual checks:
- Compile bytecode: `python -m compileall app`
- Exercise REST endpoints via Swagger (Manage → API Docs) or the OpenAPI spec.

---

## Deployment

- Set `SECRET_KEY` and DB credentials via environment.
- Configure mail for notifications.
- Serve with a WSGI server behind Nginx; enable HTTPS.
- Apply rate limiting/TLS hardening on Fleet ingest endpoints (see `docs/nginx-rate-limiting.conf` for a ready-to-use Nginx snippet).
- Run migrations (`flask db upgrade`) during deploy.
- Ensure `instance/` is writable for uploads and config.

---

## Troubleshooting

| Issue | Resolution |
|---|---|
| Missing tables | Run migrations: `flask db upgrade` |
| 401 on API calls | Provide `X-API-Key` or Bearer token |
| File upload fails | Ensure instance upload folders are writable |
| Emails not sent | Verify SMTP credentials and TLS settings |

---

## License

Copyright (c) 2025 Ioannis A. Bouhras.
Licensed under the MIT License. See `LICENSE`.

---

If you build additional modules or integrations, please contribute back with pull requests or open issues for feature requests.
