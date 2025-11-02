# Helpdesk Pro REST API

All public API endpoints live under `/api/v1` and are designed for automation integrations (RPA, ITSM orchestration, chatbots, etc.). This document covers access management, conventions, and endpoint details with concrete curl examples.

---

## 1. Access & Authentication

1. Sign in as an administrator.
2. Navigate to **Manage → API Keys**.
3. Create a new API client, capture the generated key (displayed once), and optionally assign a default user context.

Include the key with every request using one of the headers below:

```
X-API-Key: hp_prefix_secret
```

```
Authorization: Bearer hp_prefix_secret
```

Missing or invalid credentials produce `401 {"error": "Valid API key required."}`.

---

## 2. Request Conventions

- **Content type:** `application/json` (UTF-8).
- **Dates:** ISO 8601 (`YYYY-MM-DD`, `YYYY-MM-DDTHH:MM:SS`).
- **User references:** Accept numeric IDs or usernames (case-insensitive). Omit the field to fall back to the API client’s default user (if configured).
- **Errors:** JSON envelope `{"error": "<message>"}` with appropriate status codes.
- **Pagination:** Ticket and inventory list endpoints return full collections; apply query filters to scope results.

Common status codes:

| Status | Meaning |
| --- | --- |
| 200 | Success |
| 201 | Resource created |
| 400 | Validation error or malformed payload |
| 401 | Authentication failure |
| 404 | Resource not found |
| 500 | Unexpected server error |

---

## 3. Meta

### 3.1 GET `/api/v1/status`

Returns service health, timestamp, and API client metadata.

```bash
curl -sS https://helpdesk.example.com/api/v1/status \
  -H "X-API-Key: hp_demo_abc123"
```

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

---

## 4. Tickets

### 4.1 GET `/api/v1/tickets`

List tickets. Optional query parameters: `status`, `department`, `assigned_to`.

```bash
curl -sS "https://helpdesk.example.com/api/v1/tickets?status=Open&department=Network" \
  -H "X-API-Key: hp_demo_abc123"
```

### 4.2 POST `/api/v1/tickets`

Create a ticket. Required fields: `subject`, `description`. `created_by` defaults to the API client’s default user.

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

201 response:

```json
{
  "ticket": {
    "id": 202,
    "subject": "Printer jam",
    "status": "Open",
    "priority": "Medium",
    "department": "Facilities",
    "created_by": 18,
    "assigned_to": 7,
    "assignee": "tech01",
    "created_at": "2025-02-28T09:45:03.104281",
    "updated_at": "2025-02-28T09:45:03.104281",
    "closed_at": null
  }
}
```

### 4.3 GET `/api/v1/tickets/<id>`

Retrieve a single ticket.

```bash
curl -sS https://helpdesk.example.com/api/v1/tickets/202 \
  -H "X-API-Key: hp_demo_abc123"
```

### 4.4 PATCH `/api/v1/tickets/<id>`

Partial updates. Allowed fields: `subject`, `description`, `priority`, `status`, `department`, `assigned_to`, `closed_at`.

```bash
curl -sS -X PATCH https://helpdesk.example.com/api/v1/tickets/202 \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hp_demo_abc123" \
  -d '{ "status": "Resolved", "assigned_to": null, "closed_at": "2025-02-28T11:30:00" }'
```

### 4.5 DELETE `/api/v1/tickets/<id>`

Removes the ticket, its attachments, and comments.

```bash
curl -sS -X DELETE https://helpdesk.example.com/api/v1/tickets/202 \
  -H "X-API-Key: hp_demo_abc123"
```

---

## 5. Knowledge Base

### 5.1 GET `/api/v1/knowledge`

Search published articles with `q` parameter.

```bash
curl -sS "https://helpdesk.example.com/api/v1/knowledge?q=vpn" \
  -H "X-API-Key: hp_demo_abc123"
```

Response snippet:

```json
{
  "results": [
    {
      "id": 12,
      "title": "Reset VPN profile",
      "summary": "Steps to fix VPN client issues",
      "tags": ["vpn", "network"],
      "category": "Networking",
      "is_published": true,
      "created_by": 5,
      "created_at": "2025-01-04T16:21:00",
      "attachments": [
        {
          "id": 91,
          "filename": "vpn_profile_reset.pdf",
          "uploaded_at": "2025-01-04T16:21:22",
          "size": 145223
        }
      ]
    }
  ]
}
```

### 5.2 POST `/api/v1/knowledge`

Create a knowledge article. Required fields: `title`, `content`.

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

`tags` accepts either an array or comma-separated string.

---

## 6. Software Inventory

### 6.1 GET `/api/v1/inventory/software`

Optional filters: `vendor`, `name`.

```bash
curl -sS "https://helpdesk.example.com/api/v1/inventory/software?vendor=Microsoft" \
  -H "X-API-Key: hp_demo_abc123"
```

### 6.2 POST `/api/v1/inventory/software`

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

### 6.3 GET `/api/v1/inventory/software/<id>`

Fetch a single software asset.

### 6.4 PATCH `/api/v1/inventory/software/<id>`

Partial update. Any field in the creation payload can be changed.

```bash
curl -sS -X PATCH https://helpdesk.example.com/api/v1/inventory/software/15 \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hp_demo_abc123" \
  -d '{ "expiration_date": "2026-06-30", "assigned_to": null }'
```

### 6.5 DELETE `/api/v1/inventory/software/<id>`

Remove the asset.

---

## 7. Hardware Inventory

### 7.1 GET `/api/v1/inventory/hardware`

Optional filters: `manufacturer`, `category`.

```bash
curl -sS "https://helpdesk.example.com/api/v1/inventory/hardware?manufacturer=Dell" \
  -H "X-API-Key: hp_demo_abc123"
```

### 7.2 POST `/api/v1/inventory/hardware`

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

### 7.3 GET `/api/v1/inventory/hardware/<id>`

Retrieve details for a single hardware asset.

### 7.4 PATCH `/api/v1/inventory/hardware/<id>`

```bash
curl -sS -X PATCH https://helpdesk.example.com/api/v1/inventory/hardware/21 \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hp_demo_abc123" \
  -d '{ "status": "In Repair", "assigned_to": "workshop" }'
```

### 7.5 DELETE `/api/v1/inventory/hardware/<id>`

Remove the asset.

---

## 8. OpenAPI Specification

- `GET /api/v1/openapi.json` – on-demand OpenAPI 3.0 document (no authentication required).
- Import the document into Postman, Insomnia, Stoplight, or similar to explore interactively.

```bash
curl -sS https://helpdesk.example.com/api/v1/openapi.json > openapi.json
```

Swagger UI is also embedded in the admin console under **Manage → API Docs**.

---

## 9. Best Practices

- **Environment isolation:** Use separate API clients per environment (dev/test/prod) and rotate keys periodically.
- **Rate control:** Helpdesk Pro does not enforce rate limiting; apply limits at your reverse proxy or automation layer.
- **Idempotency:** For create/update workflows, store the returned `id` and use PATCH to modify existing resources instead of repeated POST calls.
- **Error handling:** Inspect `error` messages and HTTP status codes. Many validation errors include field-specific hints (e.g., invalid usernames).
- **Change tracking:** Ticket and knowledge updates automatically generate audit entries viewable in the UI.

---

For additional endpoints (assistant APIs, MCP service, etc.) consult the [Helpdesk Pro Handbook](docs/handbook.md) or contact the maintainers.
