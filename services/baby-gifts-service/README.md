# Baby Gifts Service

Baby gift registry service for the Cuchi Casa platform.

## Overview

This service manages a baby gift registry where:
- Admins can add/edit/delete gifts organized by categories
- Authenticated family users can view and reserve gifts
- External guests can access via invitation links to view and reserve

## Authentication Model

Authentication is handled by **nginx auth_request** at the reverse proxy layer,
not by this service directly. The flow:

1. nginx intercepts requests to protected endpoints
2. nginx makes a subrequest to the dashboard's `/api/verify` endpoint
3. If authenticated, nginx sets `X-Auth-User` header and proxies to this service
4. This service reads `X-Auth-User` as defense-in-depth (verifies header is present)

**Important**: This service does NOT verify SUPER profile membership directly.
Admin-only endpoints (gift CRUD, invitation management) rely on nginx routing
rules that only proxy to admin paths if the user has the SUPER profile. The
`require_auth_user` dependency in code is a secondary check ensuring the header
exists, not the primary authorization gate.

FAMILIA users (egnal, virchu) have additional privileges (see hidden gifts,
toggle visibility) checked in code via `is_familia_user()`.

## Port

- **Internal**: 8004
- **External**: Via nginx at `/api/baby-gifts/*`

## API Endpoints

All endpoints are proxied through the dashboard at `/api/baby-gifts/*`.

### Admin Endpoints (protected by nginx, requires SUPER profile)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/baby-gifts` | Get all gifts and categories |
| POST | `/api/baby-gifts` | Create a new gift |
| PUT | `/api/baby-gifts/{id}` | Update a gift |
| DELETE | `/api/baby-gifts/{id}` | Delete a gift |
| POST | `/api/baby-gifts/{id}/unreserve` | Release a reservation (admin) |

### User Endpoints (authenticated users)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/baby-gifts/user` | Get gifts for authenticated user |
| POST | `/api/baby-gifts/user/reserve/{id}` | Reserve a gift |
| POST | `/api/baby-gifts/user/unreserve/{id}` | Unreserve own reservation |

### Guest Endpoints (via invitation token)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/baby-gifts/guest/{token}` | Get gifts for guest |
| POST | `/api/baby-gifts/guest/{token}/reserve/{id}` | Reserve as guest |
| POST | `/api/baby-gifts/guest/{token}/unreserve/{id}` | Unreserve as guest |

### Invitation Management
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/baby-gifts/invitations` | List all invitations |
| POST | `/api/baby-gifts/invitations` | Create invitation |
| POST | `/api/baby-gifts/invitations/{token}/revoke` | Revoke invitation |
| DELETE | `/api/baby-gifts/invitations/{token}` | Delete invitation |

### Health
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/baby-gifts/health` | Health check |

## Data Model

```json
{
  "categories": [
    {"id": 1, "name": "Ropa", "emoji": "👶"}
  ],
  "gifts": [
    {
      "id": 1,
      "name": "Body pack",
      "category_id": 1,
      "url": "https://example.com/product",
      "price": 25.99,
      "priority": "alta",
      "notes": "Size 0-3 months",
      "reserved_by": null,
      "reserved_at": null
    }
  ],
  "invitations": [
    {
      "token": "abc123",
      "name": "Guest Name",
      "created_at": "2026-01-01T00:00:00",
      "revoked": false
    }
  ]
}
```

## Tech Stack

- Python 3.12
- FastAPI + Uvicorn
- JSON file storage (`/app/data/gifts.json`)

## Development

```bash
cd services/baby-gifts-service
pip install -r requirements.txt
cd src && uvicorn main:app --reload --port 8004
```

## Docker

```bash
docker build -t egnal/smart-home-baby-gifts:latest .
docker run -p 8004:8004 -v baby-gifts-data:/app/data egnal/smart-home-baby-gifts:latest
```

## Related Files

- Frontend: `services/baby-gifts-service/src/static/baby-gifts.html`
- Proxy routes: `dashboard/src/api/routes.py` (Baby Gifts section)
- Controller: `services/baby-gifts-service/src/gifts_controller.py`
