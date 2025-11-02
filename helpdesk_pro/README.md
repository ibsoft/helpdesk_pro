# Helpdesk Pro

Helpdesk Pro is a modern IT service management platform that combines ticketing, knowledge management, asset tracking, collaboration, and AI assistance. The application is built with Flask, SQLAlchemy, and Bootstrap 5, and ships with a first-party REST API and an embedded Model Context Protocol (MCP) server for structured AI queries.

---

## Feature highlights

- Role-aware navigation, localization (English/Greek), and responsive UI.
- Ticket lifecycle management with attachments, comments, audit logs, and departmental visibility.
- Knowledge base with versioning, search across article bodies and attachment text, and multilingual support.
- Hardware and software inventory tracking, including assignments, warranties, and license keys.
- Network, contract, backup, and address book modules for wider IT operations coverage.
- Collaboration threads and AI assistant with pluggable providers plus MCP tooling.
- REST API with API-key authentication and on-demand OpenAPI document.

For the full documentation set—including setup guides, module reference, and exhaustive API examples—see the [Helpdesk Pro Handbook](docs/handbook.md).

---

## Quick start

### Docker Compose (recommended for production-like setups)

```bash
cp helpdesk_pro/.env.example helpdesk_pro/.env   # configure secrets
docker compose -f helpdesk_pro/docker-compose.yml up -d --build
```

Visit `http://localhost:8080` and complete the `/setup` wizard to create the first admin user. PostgreSQL data, application logs, and uploads are persisted via named Docker volumes.

### Local development

```bash
cd helpdesk_pro/helpdesk_pro
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
flask db upgrade
flask --app app run --debug
```

Populate `.env` with the variables described in the handbook. PostgreSQL is recommended, but SQLite works for lightweight development.

---

## Documentation map

- `docs/handbook.md` – full platform handbook (architecture, configuration, modules, API, MCP, operations).
- `API.md` – standalone REST API reference with request/response payloads and curl examples.
- `docs/tools/` – supplementary guides and scripts.

---

## Key technology stack

- **Backend:** Flask application factory, SQLAlchemy ORM, Alembic migrations, Flask-Login, Flask-Babel.
- **Frontend:** Bootstrap 5, DataTables, FontAwesome, Jinja templates.
- **Async services:** Background email ingestion worker, FastAPI-based MCP server.
- **Authentication:** Session login for UI, API-key auth for programmatic access.
- **Database:** PostgreSQL (production) or SQLite (development).

---

## Repository layout (abridged)

```
helpdesk_pro/
├── app/                # Flask blueprints, models, utilities
├── config.py           # Environment-driven configuration
├── docker-compose.yml  # Production-style stack (Postgres + Gunicorn + MCP + Nginx)
├── Dockerfile          # Builds the application image with Supervisor
├── docs/               # Documentation assets (handbook, tools, screenshots)
├── migrations/         # Alembic migration scripts
├── requirements.txt    # Python dependencies
├── static/             # Compiled JS/CSS/asset bundles
└── templates/          # Jinja templates
```

A deeper walkthrough of each module lives in the handbook.

---

## Contributing & support

1. Fork and clone the repository.
2. Create a virtual environment and install dependencies.
3. Run migrations (`flask db upgrade`) and verify key flows (login, tickets, API calls).
4. Add or update tests where possible (`pytest`).
5. Submit a pull request with a concise description of the change.

Questions, bugs, or feature requests can be opened as issues in the upstream repository.

---

## License

MIT License © 2025 Ioannis A. Bouhras. See [`LICENSE`](../LICENSE) for the full text.
