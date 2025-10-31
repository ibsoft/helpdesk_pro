# Helpdesk Pro MCP Server

This service exposes a minimal set of database-aware tools over the Model
Context Protocol (MCP) so AI agents can query production data through a
controlled interface. The server now runs embedded inside Helpdesk Pro.

## Features

- FastAPI-based HTTP service with MCP-compatible endpoints.
- Pluggable tool architecture (see `app/mcp/tools`).
- Initial schema introspection tools: `list_tables`, `describe_table`.
- Centralised configuration via environment variables (`MCP_*`).
- Async SQLAlchemy engine with connection pooling.

## Local Development

### 1. Create a virtualenv

```bash
python -m venv .venv-mcp
source .venv-mcp/bin/activate
pip install -r app/mcp/requirements.txt
```

### 2. Configure environment

Create a `.env` file at repository root (or export variables manually):

```
MCP_DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/helpdesk_pro
MCP_HOST=0.0.0.0
MCP_PORT=8081
MCP_MAX_ROWS=1000
MCP_ALLOWED_ORIGINS=["http://localhost:3000"]
MCP_ENV=development
```

### 3. Run the server

```bash
python -m app.mcp.main
```

The API will be available at `http://localhost:8081`. Check
`http://localhost:8081/healthz` for a quick status response.

### 4. Tool catalogue

```bash
curl http://localhost:8081/mcp/tools | jq
```

### 5. Invoke a tool

```bash
curl -X POST http://localhost:8081/mcp/invoke \
  -H 'Content-Type: application/json' \
  -d '{"tool": "list_tables", "arguments": {"schema": "public"}}'
```

## Next Steps

- Add contract, inventory, and backup domain tools.
- Implement authentication middleware (e.g. JWT or API tokens).
- Introduce request/response logging and metrics exporters.
- Wire the assistant to call these MCP endpoints instead of free-form SQL.
