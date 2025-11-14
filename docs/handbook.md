# Helpdesk Pro Handbook

Comprehensive documentation for developers, operators, and administrators running the Helpdesk Pro platform. This handbook replaces the legacy scattered notes and consolidates setup guides, module descriptions, API references, and operational procedures in a single place.

---

## Table of contents

- [1. Platform Overview](#1-platform-overview)
- [2. System Architecture](#2-system-architecture)
- [3. Getting Started](#3-getting-started)
  - [3.1 Quick start with Docker Compose](#31-quick-start-with-docker-compose)
  - [3.2 Source installation for local development](#32-source-installation-for-local-development)
- [4. Configuration Reference](#4-configuration-reference)
- [5. Operations & Maintenance](#5-operations--maintenance)
- [6. Module Guide](#6-module-guide)
- [7. Data Model Overview](#7-data-model-overview)
- [8. REST API Reference](#8-rest-api-reference)
- [9. AI Assistant & MCP Services](#9-ai-assistant--mcp-services)
- [10. Background Jobs & Integrations](#10-background-jobs--integrations)
- [11. Logging, Monitoring, and Auditing](#11-logging-monitoring-and-auditing)
- [12. Directory Layout](#12-directory-layout)
- [13. Testing & Quality](#13-testing--quality)
- [14. Troubleshooting](#14-troubleshooting)
- [15. Release & Deployment Checklist](#15-release--deployment-checklist)

---

## 1. Platform Overview

Helpdesk Pro is a full-stack IT service management (ITSM) application built with Flask, SQLAlchemy, and Bootstrap 5. It combines ticketing, knowledge management, inventory tracking, network visibility, contract governance, collaboration, and an AI assistant that can query structured data through the Model Context Protocol (MCP).

Key capabilities:

- Role-aware navigation, localization (English/Greek), and responsive UI.
- Ticket lifecycle management with attachments, comments, audit logs, and departmental scoping.
- Knowledge base with version history, file uploads, and search across article bodies and extracted attachment text.
- Hardware and software inventory, including assignment, license tracking, and lifecycle metadata.
- Network recording of sites, CIDR blocks, hosts, and exports.
- Contract management, address book, and tape backup custody tracking for compliance.
- Integrated collaboration (chat-style threads) and AI assistant with pluggable providers and tools.
- REST API with API-key authentication plus OpenAPI documentation.
- Embedded MCP FastAPI service to power structured AI queries against the production database.

Helpdesk Pro can be deployed with Docker Compose (PostgreSQL + Flask + Nginx) or installed natively on Linux/Windows.

---

## 2. System Architecture

Component highlights:

- **Flask application (WSGI)** – renders the primary UI, exposes REST endpoints, and orchestrates all modules.
- **PostgreSQL** – canonical datastore for relational entities (tickets, assets, knowledge, chat, etc). The MCP service connects to the same database via an async driver.
- **Nginx reverse proxy** – terminates TLS (in production) and proxies traffic to Gunicorn (port 5000) and the MCP HTTP service (port 8081).
- **Gunicorn** – runs the Flask app. The Docker image provisions Supervisor to spawn both Gunicorn and MCP processes.
- **MCP service** – FastAPI + Uvicorn server that exposes the Model Context Protocol endpoints (`/healthz`, `/mcp/tools`, `/mcp/invoke`).
- **Email ingestion worker** – background thread polling IMAP/POP3 mailboxes to transform messages into tickets.
- **Static assets** – Bootstrap-based templates with DataTables, FontAwesome, and custom Jinja macros.
- **Logging** – Rotating file handler at `logs/helpdesk.log` plus supervisor-managed stdout/stderr files (`/app/logs/*` in containers).

Supporting scripts:

- `build.sh` – convenience wrapper that runs `docker compose up -d --build`.
- `start.sh` – helper for launching the Flask dev server.
- `run.py` – single-process entry point (mostly historical; prefer `flask --app app run` or Gunicorn).

---

## 3. Getting Started

### 3.1 Quick start with Docker Compose

The repository includes a production-style stack (`docker-compose.yml`) with PostgreSQL, the Flask application, and Nginx.

```bash
cp helpdesk_pro/.env.example helpdesk_pro/.env   # populate secrets (see Section 4)
docker compose -f helpdesk_pro/docker-compose.yml up -d --build
```

The application becomes available at `http://localhost:8080` (map differs if you set `BASE_URL`). The initial admin user is created on first run via `/setup`.

Useful commands:

- `docker compose logs -f app` – follow application logs (Gunicorn + MCP).
- `docker compose exec app flask db upgrade` – run migrations inside the container.
- `docker compose exec app flask shell` – open an interactive shell with application context.
- `docker compose down -v` – stop containers and remove volumes (wipes DB and uploaded files).

### 3.2 Source installation for local development

1. **Clone** the repository and create a virtual environment:

   ```bash
   git clone https://github.com/<org>/helpdesk_pro.git
   cd helpdesk_pro/helpdesk_pro
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure** a `.env` file (see Section 4 for details). For local dev you can point `SQLALCHEMY_DATABASE_URI` to SQLite, but PostgreSQL is recommended.

3. **Initialize** the database:

   ```bash
   flask db upgrade
   python -m app.seeds  # optional sample data
   ```

4. **Run** the development server:

   ```bash
   flask --app app run --debug
   ```

5. **Enable** the embedded MCP server (optional in dev):

   ```bash
   export MCP_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/helpdesk
   python -m app.mcp.main
   ```

---

## 4. Configuration Reference

Helpdesk Pro loads configuration from environment variables (preferred) or `.env`. Admins can edit most settings from **Manage → Configuration**, which persists values to `.env`.

### Core settings

| Variable | Purpose | Default |
| --- | --- | --- |
| `SECRET_KEY` | Flask & JWT signing secret | auto-generated placeholder |
| `SQLALCHEMY_DATABASE_URI` | Primary database connection | `sqlite:///instance/helpdesk.db` (dev) |
| `DEFAULT_LANGUAGE` | Default UI language (`en`, `el`) | `en` |
| `LOG_LEVEL` | Application log level | `INFO` |
| `SQLALCHEMY_ECHO` | Enable SQL query echo (debug) | `false` |
| `BASE_URL` | External canonical URL | unset |

### Email (SMTP)

| Variable | Description |
| --- | --- |
| `MAIL_SERVER`, `MAIL_PORT` | SMTP host/port |
| `MAIL_USE_TLS` | Toggle STARTTLS |
| `MAIL_USERNAME`, `MAIL_PASSWORD` | Credentials (optional if server supports unauthenticated mail) |
| `MAIL_FALLBACK_TO_NO_AUTH` | Retry without SMTP AUTH if advertised features fail |

### Upload & UI tuning

| Variable | Description | Default |
| --- | --- | --- |
| `KNOWLEDGE_UPLOAD_FOLDER` | Knowledge article attachments | `instance/knowledge_uploads` |
| `TICKETS_UPLOAD_FOLDER` | Ticket attachments | `instance/tickets_uploads` |
| `ASSISTANT_UPLOAD_FOLDER` | Assistant document uploads | `instance/assistant_uploads` |
| `UI_FONT_SCALE`, `UI_NAVBAR_HEIGHT`, `UI_FOOTER_HEIGHT` | Layout scaling factors | various |

### AI assistant & MCP

| Variable | Purpose | Default |
| --- | --- | --- |
| `ASSISTANT_ENABLE_LLM_OVERRIDE` | Allow providers to override system prompt | `true` |
| `ASSISTANT_TOOL_CALL_DEPTH_LIMIT` | Recursive tool call limit (`-1` unlimited) | `-1` |
| `MCP_ENABLED` | Start the embedded MCP server | `true` |
| `MCP_CMD` | Override supervisor command for MCP | `python -m app.mcp.main` (set in Dockerfile) |
| `MCP_DATABASE_URL` | Async connection used by MCP | required for MCP |
| `MCP_HOST`, `MCP_PORT` | MCP bind address/port | `0.0.0.0`, `8081` |
| `MCP_ALLOWED_ORIGINS` | CORS whitelist for MCP | empty list |
| `MCP_MAX_ROWS` | Row limit for MCP SQL tools | `1000` |
| `MCP_REQUEST_TIMEOUT` | Tool execution timeout (seconds) | `10` |

### Email-to-ticket ingestion

Configure via **Manage → Email to Ticket**; persisted settings map to `EmailIngestConfig` (host, protocol, poll interval, subject filters, default ticket fields).

---

## 5. Operations & Maintenance

- **Database migrations** – run `flask db upgrade` during deployments. Alembic revision files live under `migrations/`.
- **Seeding** – `python -m app.seeds` populates demo departments, statuses, and sample data.
- **Backups** – schedule PostgreSQL dumps and ensure `instance/` (uploads, config) is backed up.
- **MCP lifecycle** – use **Manage → MCP** to start, stop, or reload configuration. Supervisor restarts the process on failure.
- **Logs** – rotate automatically; monitor `logs/helpdesk.log` and container-level `/app/logs/*`.
- **Email ingestion** – toggle auto-start via config. Admin UI exposes “Run now” to force an immediate poll.
- **Translations** – maintain `.po` files under `translations/`. Regenerate with Babel, then compile.

---

## 6. Module Guide

Each module corresponds to a Flask blueprint or service housed under `app/`.

### 6.1 Authentication (`app/auth`)

- Handles login, logout, registration (optional), password reset, and first-run admin setup.
- Integrates with `AuthConfig` to control self-registration, password policies, and SMTP usage.
- Uses Flask-Login for session management; `validate_password_strength` enforces complexity.
- Templates: `templates/auth/*`.

### 6.2 Dashboard (`app/dashboard`)

- Default landing page after login with widgets for ticket counts, SLA breaches, inventory summaries, and assistant status.
- Roles determine which panels appear (leverages `navigation.py`).

### 6.3 Users & Roles (`app/users`, `app/navigation`, `app/permissions`)

- CRUD for user accounts, roles, departments, and avatar uploads.
- Module and menu permissions enforce role-based module access (`ModulePermission`, `MenuPermission`).
- Exposes CSV export for user lists and audit logs for changes.

### 6.4 Ticketing (`app/tickets`)

- Routes under `/tickets` cover listing, creation, edit, assignment, comments, status transitions, and attachment management.
- Attachments persist under `instance/tickets_uploads` with secure filenames via `app.utils.files`.
- Ticket comments support inline images and notify participants via email (using queued mail helpers).
- Models: `Ticket`, `TicketComment`, `Attachment`, `AuditLog`.

### 6.5 Knowledge Base (`app/knowledge`)

- Article authoring with Markdown (rendered to HTML), version history (`KnowledgeArticleVersion`), categories, tags, and visibility controls.
- Attachments saved to `instance/knowledge_uploads` and indexed for search.
- Includes bulk publish/unpublish, language localization, and per-article audit trail.

### 6.6 Inventory (`app/inventory`)

- Two submodules: software (`SoftwareAsset`) and hardware (`HardwareAsset`).
- Features include asset assignment, license tracking, warranty dates, custom fields, and CSV import/export.
- UI provides filters, quick bulk actions, and timeline view for hardware custody.

### 6.7 Networks (`app/networks`)

- Manage network sites, CIDR blocks, hosts, and relationships to tickets or assets.
- Supports CSV import/export, IP address validation, and visual widgets rendered via templates.
- Hosts can be tagged, assigned to departments, and linked to inventory items.

### 6.8 Contracts (`app/contracts`)

- Tracks vendor contracts, renewal dates, SLA details, and attachments.
- Provides reminders for upcoming renewals and integration with assistant queries.

### 6.9 Address Book (`app/address_book`)

- Centralized contact directory with categories (Vendor, Partner, Customer, etc).
- AJAX endpoints for pagination and detail retrieval (`/address-book/api/list`).
- Supports bulk import/export (CSV) and tag-based filtering.

### 6.10 Collaboration (`app/collab`)

- Internal conversation threads (chat-style) scoped to participants with read receipts (`ChatMessageRead`).
- Integrates with ticketing and assistant modules for contextual discussions.
- Supports file uploads into `instance/chat_uploads`.

### 6.11 Assistant (`app/assistant`)

- Web assistant widget plus REST endpoints for sessions, message exchange, document uploads, and provider management.
- Supports OpenAI-compatible providers, custom webhooks, OpenWebUI, and embedded MCP tooling.
- Handles advanced query parsing (ticket references, asset tags, IPs) to route requests to structured queries.
- Related models: `AssistantConfig`, `AssistantSession`, `AssistantMessage`, `AssistantDocument`.

### 6.12 Manage (`app/manage`)

- Administrative console for configuration, navigation customization, module permissions, API key management, and system diagnostics.
- Allows editing `.env` values securely (hiding sensitive fields).
- Provides MCP lifecycle controls, translation export, and maintenance utilities.

### 6.13 Backup Monitor (`app/backup`)

- Tracks tape cartridges, storage locations, custody events, and lifecycle statuses.
- Generates LTO barcodes and enforces access control via module permissions.
- Offers audit logging (`BackupAuditLog`) and analytics dashboards (counts by status/site).

### 6.14 Email-to-Ticket (`app/email2ticket`)

- Background worker polls configured mailboxes (IMAP/POP3) on a schedule.
- Subject filtering and regex allow scoping ingestion to specific requests.
- Stores attachments, maps sender to existing users, and records ingestion audit entries.
- Admin UI (Manage → Email to Ticket) controls enable/disable, interval, and default ticket values.

### 6.15 Tools (`app/tools`)

- Utility endpoints (password/passphrase generators) gated by login.

### 6.16 API Blueprint (`app/api`)

- Exposes `/api/v1` REST endpoints (tickets, knowledge, inventory, status).
- Handles API-key authentication, default user mapping, and schema generation for the OpenAPI document.
- See Section 8 for a full reference.

### 6.17 AI MCP Service (`app/mcp`)

- FastAPI application (`server.py`) exported through `app.mcp.main`.
- Tool registry lives under `app/mcp/tools`. Out-of-the-box tools include `list_tables`, `describe_table`, and SQL query helpers leveraging async SQLAlchemy.
- Configuration loaded from environment with Pydantic (`config.py`); `db.py` manages async engines.

### 6.18 Utilities (`app/utils`, `app/mail_utils.py`)

- Shared helpers for file handling, validation, mail queuing, and security utilities (password strength, CSRF bypass for API).
- `mail_utils` transparently retries SMTP sends without AUTH if the server does not advertise it.
- `background.py` wraps `submit_background_task`, the lightweight executor used by email notifications and ingestion.

### 6.19 Task Scheduler (`app/task_scheduler`)

- **Purpose** – Coordinate maintenance windows, onsite visits, and long-running chores without double-booking the engineering team. Managers publish internal calendars, accept self-service bookings, and convert confirmed slots into Helpdesk tickets.
- **Data model** – `TaskSchedulerTask` (core definition), `TaskSchedulerSlot` (individual reservations), `TaskSchedulerShareToken` (public/restricted share links), and `TaskSchedulerAuditLog` (immutable record of slot creation, ticket conversions, share link activity, and outbound email).
- **Access control** – Technicians can read shared tasks; managers/admins create and manage them. Administrators and managers only see the tasks they personally created to avoid cross-team edits.
- **List view (`templates/task_scheduler/list.html`)** – Provides summary metrics plus per-task actions:
  - CRUD operations via modal forms (title, status, estimated duration, rich descriptions).
  - Slot management (add/remove with conflict detection and auto-suggested alternatives).
  - Share link creation (`/task-scheduler/<id>/share`) with copy-to-clipboard helpers.
  - **Email Task** button that opens a modal, lets managers select “All active users” or multi-select recipients, add an optional note, and sends the active share link through the configured SMTP account.
  - Ticket creation from slots (enforces that managers belong to a department so tickets inherit the proper scope).
- **Public share page (`templates/task_scheduler/public_share.html`)** – Minimal landing page for external recipients. Highlights:
  - Displays task metadata, description, share visibility, and status.
  - Booking form validates start times through `/task-scheduler/share/<token>/check`, showing friendly availability messages.
  - “Upcoming slots” section now shows each attendee plus the exact date/time they selected, helping others pick open windows.
- **Email workflow** – `/task-scheduler/<id>/email` verifies that a valid share link exists, gathers recipients from `/task-scheduler/email/recipients`, and queues the message through `queue_mail_with_optional_auth`. The endpoint refuses to send when no sender address is configured (requires `MAIL_DEFAULT_SENDER` or `MAIL_USERNAME`) and emits localized error messages for the UI.
- **Auditing & logs** – Every significant action (task create/update/delete, slot creation/removal, ticket conversion, share creation/revoke, email sends) writes to `TaskSchedulerAuditLog`. This makes it easy to review who invited whom or removed a slot.
- **Localization** – Strings live in the translation catalogs. After tweaking the module, regenerate/compile translations:

  ```bash
  pybabel extract -F babel.cfg -o messages.pot .
  pybabel update -i messages.pot -d translations
  pybabel compile -d translations
  ```

- **Operational reminders** – Task Scheduler is part of the main Flask app; no extra services needed. Ensure SMTP credentials are valid if you plan to use the email action. Share links follow the task status—closing a task renders public booking forms read-only.

### 6.20 Fleet Monitoring (`app/fleet`)

- **Mission** – Provide a first-class experience for endpoint telemetry, marrying device snapshots, map geography, health summaries, screenshots, alerts, and remote tooling into the Helpdesk Pro shell. The ingestion service will eventually listen on port `8449` (`/ingest`) with API-key authentication and NDJSON payloads.
- **Milestone 1 deliverables**:
  - Data layer: `FleetHost`, `FleetMessage`, `FleetLatestState`, `FleetScreenshot`, `FleetApiKey`, and `FleetModuleSettings`.
  - Blueprint scaffolding (`fleet_bp`) with `/fleet`, `/fleet/hosts/<id>`, and `/fleet/settings` routes.
  - Navigation + RBAC using the existing module permission framework (`module_key = "fleet_monitoring"`).
  - Stylish dashboard, host detail, and settings templates that match the rest of the UI.
  - Handbook documentation to orient developers/operators before ingestion comes online.
- **Dashboard** (`templates/fleet/dashboard.html`):
  - Hero card summarizing module purpose plus quick access to settings for write-capable users.
  - Split layout with an OpenStreetMap placeholder (configurable zoom/icon pulled from `FleetModuleSettings`) and quick stats.
  - Responsive host tiles highlighting OS, mock CPU/RAM/Disk micro-graphs, location badges, and state tags. Clicking a tile opens the host detail page.
- **Host detail** (`templates/fleet/host_detail.html`):
  - System health block rendering the latest snapshot JSON (UTC stored data; UI renders via Babel in Europe/Athens).
  - Screenshot panel showing the freshest agent capture (base64 rendered).
  - Message feed with timestamp/category/subtype/level/payload columns, full filtering (time range, category, subtype, level, text search), pagination, and JSON export.
  - Alert panel listing active rule hits (CPU/Disk/AV/Updates/Events) created automatically during ingestion; alerts resolve when telemetry returns to normal.
  - Remote actions: SSH/RDP/VNC deep links, command queue, and file uploads. Agents poll `/ingest/commands` and `/ingest/files` (headers: `X-API-Key`, `X-Agent-ID`) to receive tasks, acknowledge them (`/ingest/commands/<id>/result`), and download pending uploads (`/ingest/files/<id>/download`). These operations are logged via `FleetRemoteCommand` and `FleetFileTransfer`.
- **Settings** (`templates/fleet/settings.html`) now allow editing:
  - API keys (create/disable/revoke/expiry) backed by `FleetApiKey`.
  - Map defaults (zoom, custom pin icon) and screenshot toggle for the dashboard.
  - Retention windows for messages/screenshots and default alert rule thresholds.
- **Operations** – Tables auto-create during startup (similar to Task Scheduler). All timestamps are stored in UTC, while the UI honors Europe/Athens formatting just like the rest of the platform. Future milestones will expand the ingest listener contract (agent ACKs/polling) and notification hooks.

---

## 7. Data Model Overview

Primary SQLAlchemy models (`app/models/*`):

- **User** – login credentials, role, department, password hash, profile metadata.
- **Ticket** – core ticket info plus relationships to comments (`TicketComment`), attachments, and audit logs.
- **KnowledgeArticle** – article body, summary, tags, versions (`KnowledgeArticleVersion`), attachments.
- **SoftwareAsset / HardwareAsset** – asset catalogs with lifecycle timestamps (purchase, warranty, retirement).
- **Network / NetworkHost** – network definitions and individual hosts.
- **Contract** – vendor agreements, renewal metrics, financial values.
- **AddressBookEntry** – contact directory records.
- **Assistant*** – configuration, sessions, messages, documents.
- **Chat*** – collaboration threads (`ChatConversation`, `ChatMessage`, `ChatMessageRead`).
- **TapeCartridge / TapeLocation / TapeCustodyEvent** – backup tape tracking.
- **ApiClient** – API key metadata, hashed secrets, default user context.
- **EmailIngestConfig** – persisted mailbox settings.
- **ModulePermission / MenuPermission** – role-based access control caches.

Refer to `app/models/__init__.py` for full exports and relationships.

---

## 8. REST API Reference

Base URL: `/api/v1`. All endpoints require an API key unless noted. Keys are managed via **Manage → API Keys** and are shown only once at creation time.

### 8.1 Authentication

Provide your key using either header:

```
X-API-Key: hp_prefix_secret
```

or

```
Authorization: Bearer hp_prefix_secret
```

If authentication fails, the API returns `401 {"error": "Valid API key required."}`.

### 8.2 Conventions

- **Content type** – `application/json`.
- **Dates** – ISO 8601 (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`).
- **User references** – numeric ID or username string (case-insensitive).
- **Errors** – JSON envelope `{ "error": "message" }` with appropriate HTTP status.

### 8.3 Endpoints

#### GET `/api/v1/status`

Health, timestamp, and API client metadata.

```bash
curl -sS https://helpdesk.example.com/api/v1/status \
  -H "X-API-Key: hp_demo_abc123"
```

Response:

```json
{
  "status": "ok",
  "timestamp": "2025-03-01T09:12:24.532184",
  "client": {
    "id": 4,
    "name": "Automation Bot",
    "default_user": "integration-user"
  }
}
```

#### Tickets

##### GET `/api/v1/tickets`

Query parameters: `status`, `department`, `assigned_to`.

```bash
curl -sS "https://helpdesk.example.com/api/v1/tickets?status=Open&department=Network" \
  -H "X-API-Key: hp_demo_abc123"
```

Response:

```json
{
  "tickets": [
    {
      "id": 42,
      "subject": "VPN outage",
      "description": "Users cannot connect",
      "priority": "High",
      "status": "Open",
      "department": "Network",
      "created_by": 5,
      "assigned_to": 2,
      "assignee": "alex",
      "created_at": "2025-02-23T08:15:00",
      "updated_at": "2025-02-23T10:04:11",
      "closed_at": null
    }
  ]
}
```

##### POST `/api/v1/tickets`

```bash
curl -sS https://helpdesk.example.com/api/v1/tickets \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hp_demo_abc123" \
  -d '{
        "subject": "Printer jam",
        "description": "3rd floor printer keeps jamming",
        "priority": "Medium",
        "department": "Facilities",
        "created_by": "maria",
        "assigned_to": "tech01"
      }'
```

Returns `201` with the created ticket payload. `subject` and `description` are required. `created_by` defaults to the API client’s default user when omitted.

##### GET `/api/v1/tickets/<id>`

Retrieve a single ticket.

```bash
curl -sS https://helpdesk.example.com/api/v1/tickets/42 \
  -H "X-API-Key: hp_demo_abc123"
```

##### PATCH `/api/v1/tickets/<id>`

Partial updates. Supported fields: `subject`, `description`, `priority`, `status`, `department`, `assigned_to`, `closed_at`.

```bash
curl -sS -X PATCH https://helpdesk.example.com/api/v1/tickets/42 \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hp_demo_abc123" \
  -d '{ "status": "Resolved", "assigned_to": null, "closed_at": "2025-02-24T15:00:00" }'
```

##### DELETE `/api/v1/tickets/<id>`

Deletes the ticket and related attachments/comments.

```bash
curl -sS -X DELETE https://helpdesk.example.com/api/v1/tickets/42 \
  -H "X-API-Key: hp_demo_abc123"
```

#### Knowledge Base

##### GET `/api/v1/knowledge`

Search published articles with `q` query parameter.

```bash
curl -sS "https://helpdesk.example.com/api/v1/knowledge?q=vpn" \
  -H "X-API-Key: hp_demo_abc123"
```

Response includes the matching articles with metadata and attachment outlines.

##### POST `/api/v1/knowledge`

```bash
curl -sS https://helpdesk.example.com/api/v1/knowledge \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hp_demo_abc123" \
  -d '{
        "title": "Reset VPN profile",
        "summary": "Steps to fix VPN client issues",
        "content": "1. Open VPN client...",
        "tags": ["vpn", "network"],
        "category": "Networking",
        "is_published": true,
        "created_by": "alex"
      }'
```

Returns `201` with article payload (including `attachments` array).

#### Software Inventory

##### GET `/api/v1/inventory/software`

Filters: `vendor`, `name`.

```bash
curl -sS "https://helpdesk.example.com/api/v1/inventory/software?vendor=Microsoft" \
  -H "X-API-Key: hp_demo_abc123"
```

##### POST `/api/v1/inventory/software`

```bash
curl -sS https://helpdesk.example.com/api/v1/inventory/software \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hp_demo_abc123" \
  -d '{
        "name": "Visio Professional",
        "version": "2019",
        "vendor": "Microsoft",
        "license_type": "OEM",
        "license_key": "XXXX-XXXX-XXXX-XXXX",
        "assigned_to": "geozac"
      }'
```

Supports full/partial updates via `PATCH /inventory/software/<id>` and retrieval/deletion via `GET`/`DELETE`.

#### Hardware Inventory

##### GET `/api/v1/inventory/hardware`

Filters: `manufacturer`, `category`.

##### POST `/api/v1/inventory/hardware`

```bash
curl -sS https://helpdesk.example.com/api/v1/inventory/hardware \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hp_demo_abc123" \
  -d '{
        "asset_tag": "DL-PRD-005",
        "manufacturer": "Dell",
        "model": "PowerEdge R750",
        "category": "Server",
        "hostname": "app-node-5",
        "assigned_to": "infra-team"
      }'
```

`GET`, `PATCH`, and `DELETE` on `/inventory/hardware/<id>` manage individual assets.

#### OpenAPI Document

- `GET /api/v1/openapi.json` – publicly accessible OpenAPI 3.0 document generated at runtime.
- Import into Postman, Insomnia, or other tools for exploration.

---

## 9. AI Assistant & MCP Services

- **Assistant configuration** – Managed from **Manage → Assistant**. Set provider (OpenAI, webhook, OpenWebUI), API credentials, default prompt, and tool usage.
- **Sessions & messaging** – `/assistant/api/sessions` (create/end), `/assistant/api/messages` (send/receive). The web UI uses these endpoints for real-time chat.
- **Document uploads** – Users can upload PDFs, DOCX, and text files stored under `instance/assistant_uploads`. Documents are chunked and indexed for retrieval-augmented responses.
- **Embedded MCP** – Runs at `http://<host>:8081` by default.
  - `GET /healthz`
  - `GET /mcp/tools` – list available tools.
  - `POST /mcp/invoke` – execute a tool with JSON arguments.
- **Example MCP call**:

  ```bash
  curl -sS http://localhost:8081/mcp/invoke \
    -H "Content-Type: application/json" \
    -d '{"tool": "list_tables", "arguments": {"schema": "public"}}'
  ```

- Assistant routes tools based on user prompts (regex detection for ticket IDs, asset tags, IP addresses). MCP tools execute read-only SQL against the PostgreSQL replica using async SQLAlchemy.

---

## 10. Background Jobs & Integrations

- **Email ingestion** – See Section 6.14. The worker honours poll intervals, SSL/TLS settings, and subject filters. Errors surface in the admin UI and application logs.
- **Outgoing mail** – `app/mail_utils.py` queues emails and optionally retries without SMTP AUTH when allowed. Notifications include new ticket alerts, password resets, and assistant digests.
- **Scheduled tasks** – External cronjobs can invoke management commands (`flask` CLI) for housekeeping (e.g., daily `flask tickets purge-closed --days=90`). Custom commands can be added under `app/manage/commands`.
- **Integrations** – REST API provides automation surface; additional modules (e.g., backup exports) expose CSV/JSON downloads.

---

## 11. Logging, Monitoring, and Auditing

- **Application logs** – `logs/helpdesk.log` (rotating) plus console handler. Log level configured via `LOG_LEVEL`.
- **Supervisor logs (Docker)** – `/app/logs/web_stdout.log`, `/app/logs/web_stderr.log`, `/app/logs/mcp_stdout.log`, `/app/logs/mcp_stderr.log`.
- **Audit logs** – `AuditLog` model captures sensitive actions (ticket updates, permission changes). Viewable under **Manage → Audit Logs**.
- **Metrics** – Not bundled; integrate with external agents (e.g., Prometheus node exporter) if required. SQLAlchemy pool metrics available through MCP logs when debug enabled.

---

## 12. Directory Layout

```
helpdesk_pro/
├── app/
│   ├── address_book/        # Contact directory blueprint
│   ├── api/                 # Public REST API
│   ├── assistant/           # AI assistant backend
│   ├── auth/                # Authentication flows
│   ├── backup/              # Tape custody tracking
│   ├── collab/              # Team conversations
│   ├── contracts/           # Vendor contract management
│   ├── dashboard/           # Landing page widgets
│   ├── email2ticket/        # Mail ingestion worker
│   ├── inventory/           # Hardware/software inventory
│   ├── knowledge/           # Knowledge base
│   ├── manage/              # Admin console
│   ├── mcp/                 # FastAPI MCP service
│   ├── networks/            # Network mapping
│   ├── tickets/             # Ticketing UI
│   ├── tools/               # Utility generators
│   ├── users/               # User management
│   └── utils/               # Shared helpers
├── config.py                # Environment configuration loader
├── docker-compose.yml       # Production-style stack
├── Dockerfile               # Multi-service container (Gunicorn + MCP)
├── requirements*.txt        # Python dependencies
├── migrations/              # Alembic revision scripts
├── static/                  # JS/CSS assets
├── templates/               # Jinja templates
└── docs/                    # Documentation (this handbook, tools)
```

---

## 13. Testing & Quality

- Automated tests (pytest) can be added under `tests/`. Run `pytest` from the project root.
- Manual smoke checks:
  - `flask --app app routes` to inspect route map.
  - `python -m compileall app` to catch syntax errors.
  - Exercise critical workflows (login, ticket create/update, knowledge search, inventory edit).
- Linting recommendations: `flake8`, `black`, `isort` (not pinned in requirements).

---

## 14. Troubleshooting

| Symptom | Diagnostic steps | Resolution |
| --- | --- | --- |
| Cannot log in (first run) | No users in DB | Visit `/setup` to create the first admin |
| MCP fails to start | `mcp_stderr.log` mentions sync driver | Set `MCP_DATABASE_URL=postgresql+asyncpg://...` |
| Ticket attachments fail | Permission denied writing to `instance/` | Ensure folder exists and is writable |
| Email ingestion idle | Check `EmailIngestConfig.last_error`, view logs | Verify mailbox credentials, enable less-secure apps if required |
| API returns 401 | Missing/invalid key | Re-issue key or include `X-API-Key` header |
| Static assets 404 behind Nginx | Misconfigured `BASE_URL` or proxy headers | Set `BASE_URL` and ensure `X-Forwarded-*` headers reach Gunicorn |

---

## 15. Release & Deployment Checklist

- [ ] Update version (`APP_VERSION`) and changelog.
- [ ] Run migrations (`flask db upgrade`) and backup database.
- [ ] Build Docker image (`docker compose build app`) or wheel package.
- [ ] Verify `.env` contains required secrets (DB, SMTP, assistant providers, MCP).
- [ ] Collect static translations (`pybabel compile`).
- [ ] Smoke-test key flows post-deploy (login, ticket create/update, API call, assistant prompt, MCP tool).
- [ ] Confirm background worker running (Email → status OK).
- [ ] Rotate API keys if necessary and inform integrators.


Translations

pybabel extract -F babel.cfg -k _ -k _l -o messages.pot .

pybabel update -i messages.pot -d translations

pybabel compile -d translations

---

This handbook should be kept up-to-date whenever modules evolve or new endpoints are introduced. Contributions are welcome—open a pull request with documentation updates alongside feature branches.
