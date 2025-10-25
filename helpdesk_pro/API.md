# Helpdesk Pro REST API

The Helpdesk Pro API allows external systems to integrate with the platform for ticketing, knowledge base, and inventory operations. All endpoints are JSON-based and live under `/api/v1`.

## Table of Contents

1. [Getting Access](#getting-access)
2. [Authentication](#authentication)
3. [Error Handling](#error-handling)
4. [Tickets](#tickets)
   - [List Tickets](#list-tickets)
   - [Create Ticket](#create-ticket)
   - [Retrieve Ticket](#retrieve-ticket)
   - [Update Ticket](#update-ticket)
   - [Delete Ticket](#delete-ticket)
5. [Knowledge Base](#knowledge-base)
   - [Search Articles](#search-articles)
   - [Create Article](#create-article)
6. [Software Inventory](#software-inventory)
   - [List Software Assets](#list-software-assets)
   - [Create Software Asset](#create-software-asset)
   - [Retrieve Software Asset](#retrieve-software-asset)
   - [Update Software Asset](#update-software-asset)
   - [Delete Software Asset](#delete-software-asset)
7. [Hardware Inventory](#hardware-inventory)
   - [List Hardware Assets](#list-hardware-assets)
   - [Create Hardware Asset](#create-hardware-asset)
   - [Retrieve Hardware Asset](#retrieve-hardware-asset)
   - [Update Hardware Asset](#update-hardware-asset)
   - [Delete Hardware Asset](#delete-hardware-asset)
8. [Swagger / OpenAPI](#swagger--openapi)

---

## Getting Access

1. Log in as an admin.
2. Navigate to **Manage → API Keys**.
3. Create an API client and copy the generated key (shown once).
4. Optionally assign a default user context for audit fields.

Keys are hashed server-side and cannot be retrieved after creation. Rotate as needed.

---

## Authentication

Include your key in every request using either header:

```
X-API-Key: hp_<prefix>_<secret>
```

or

```
Authorization: Bearer hp_<prefix>_<secret>
```

If authentication fails, the API responds with HTTP `401` and `{"error": "Valid API key required."}`.

---

## Error Handling

Errors follow a simple JSON envelope:

```json
{
  "error": "Description of the issue."
}
```

Common status codes:

| Code | Meaning                     |
|------|-----------------------------|
| 400  | Validation error            |
| 401  | Missing/invalid API key     |
| 404  | Resource not found          |
| 500  | Unexpected server error     |

---

## Tickets

### List Tickets

`GET /api/v1/tickets`

Optional query parameters:
- `status`
- `department`
- `assigned_to` (username or user id)

```bash
curl -sS https://helpdesk.example.com/api/v1/tickets \
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
      "created_at": "2025-10-24T09:15:00",
      "updated_at": "2025-10-24T10:00:00",
      "closed_at": null
    }
  ]
}
```

### Create Ticket

`POST /api/v1/tickets`

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

Required fields: `subject`, `description`, `created_by` (directly or via default user).

### Retrieve Ticket

`GET /api/v1/tickets/<id>`

```bash
curl -sS https://helpdesk.example.com/api/v1/tickets/42 \
  -H "X-API-Key: hp_demo_abc123"
```

### Update Ticket

`PATCH /api/v1/tickets/<id>`

```bash
curl -sS -X PATCH https://helpdesk.example.com/api/v1/tickets/42 \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hp_demo_abc123" \
  -d '{
        "status": "Resolved",
        "assigned_to": null,
        "closed_at": "2025-10-25T11:30:00"
      }'
```

### Delete Ticket

`DELETE /api/v1/tickets/<id>`

```bash
curl -sS -X DELETE https://helpdesk.example.com/api/v1/tickets/42 \
  -H "X-API-Key: hp_demo_abc123"
```

---

## Knowledge Base

### Search Articles

`GET /api/v1/knowledge?q=<query>`

```bash
curl -sS "https://helpdesk.example.com/api/v1/knowledge?q=vpn" \
  -H "X-API-Key: hp_demo_abc123"
```

Response includes top 50 published articles matching title/summary/content/tags/attachments.

### Create Article

`POST /api/v1/knowledge`

```bash
curl -sS https://helpdesk.example.com/api/v1/knowledge \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hp_demo_abc123" \
  -d '{
        "title": "Reset VPN profile",
        "summary": "Steps to fix VPN client issues",
        "content": "1. Open VPN client ...",
        "tags": ["vpn", "network"],
        "category": "Networking",
        "is_published": true,
        "created_by": "alex"
      }'
```

Tags may be passed as an array or comma-separated string.

---

## Software Inventory

### List Software Assets

`GET /api/v1/inventory/software`

Filters: `vendor`, `name`

```bash
curl -sS "https://helpdesk.example.com/api/v1/inventory/software?vendor=Microsoft" \
  -H "X-API-Key: hp_demo_abc123"
```

### Create Software Asset

`POST /api/v1/inventory/software`

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

### Retrieve Software Asset

`GET /api/v1/inventory/software/<id>`

```bash
curl -sS https://helpdesk.example.com/api/v1/inventory/software/15 \
  -H "X-API-Key: hp_demo_abc123"
```

### Update Software Asset

`PATCH /api/v1/inventory/software/<id>`

```bash
curl -sS -X PATCH https://helpdesk.example.com/api/v1/inventory/software/15 \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hp_demo_abc123" \
  -d '{ "expiration_date": "2026-06-30", "assigned_to": null }'
```

### Delete Software Asset

`DELETE /api/v1/inventory/software/<id>`

```bash
curl -sS -X DELETE https://helpdesk.example.com/api/v1/inventory/software/15 \
  -H "X-API-Key: hp_demo_abc123"
```

---

## Hardware Inventory

### List Hardware Assets

`GET /api/v1/inventory/hardware`

Filters: `manufacturer`, `category`

```bash
curl -sS "https://helpdesk.example.com/api/v1/inventory/hardware?manufacturer=Dell" \
  -H "X-API-Key: hp_demo_abc123"
```

### Create Hardware Asset

`POST /api/v1/inventory/hardware`

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

### Retrieve Hardware Asset

`GET /api/v1/inventory/hardware/<id>`

### Update Hardware Asset

`PATCH /api/v1/inventory/hardware/<id>`

```bash
curl -sS -X PATCH https://helpdesk.example.com/api/v1/inventory/hardware/21 \
  -H "Content-Type: application/json" \
  -H "X-API-Key: hp_demo_abc123" \
  -d '{ "status": "In Repair", "assigned_to": "workshop" }'
```

### Delete Hardware Asset

`DELETE /api/v1/inventory/hardware/<id>`

---

## Swagger / OpenAPI

- OpenAPI spec: `GET /api/v1/openapi.json` (no authentication required).
- Embedded documentation: **Manage → API Docs** (Swagger UI).

Example download:

```bash
curl -sS https://helpdesk.example.com/api/v1/openapi.json > openapi.json
```

Import this file into Postman, Insomnia, or other tooling to explore the API interactively.

---

## Notes

- All date/time fields use ISO 8601 format (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`).
- User references accept either numeric IDs or usernames (case-insensitive).
- When omitting `created_by` or `assigned_to`, the API uses the default user configured for the API key (if any).
- Rate limiting is not enforced by default; consider adding a reverse proxy for production environments.

For assistance or to request additional endpoints, contact the Helpdesk Pro maintainers.

