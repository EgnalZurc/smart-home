# Baby Gifts Service

Baby gift registry service for the Cuchi Casa platform.

## Overview

This service manages a baby gift registry where:
- Admins can add/edit/delete gifts organized by categories
- Authenticated family users can view and reserve gifts
- External guests can access via invitation links to view and reserve

## Port

- **Internal**: 8004
- **External**: Via nginx at `/api/baby-gifts/*`

## API Endpoints

All endpoints are proxied through the dashboard at `/api/baby-gifts/*`.

### Admin Endpoints (requires SUPER profile)
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
