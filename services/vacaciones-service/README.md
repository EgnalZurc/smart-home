# Vacaciones Service

Christmas vacation meal planning service for the Cuchi Casa platform.

## Overview

This service helps plan family Christmas vacation meals, tracking who brings what dish for each day across different family groups (núcleos).

## Port

- **Internal**: 8003
- **External**: Via nginx at `/api/vacaciones/*`

## API Endpoints

All endpoints are proxied through the dashboard at `/api/vacaciones/*`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/vacaciones` | Get all vacation data (years, config, meals) |
| GET | `/api/vacaciones/health` | Health check |
| POST | `/api/vacaciones/year` | Add a new year |
| POST | `/api/vacaciones/year/{year}` | Update year data (meals, notes) |
| DELETE | `/api/vacaciones/year/{year}` | Delete a year |
| POST | `/api/vacaciones/config` | Update config (family groups, people) |

## Data Model

```json
{
  "config": {
    "nucleos": ["Núcleo 1", "Núcleo 2", "Núcleo 3"],
    "personas": [
      {"id": 1, "nombre": "Person 1", "nucleo": 0},
      {"id": 2, "nombre": "Person 2", "nucleo": 1}
    ]
  },
  "years": [
    {
      "year": 2026,
      "comidas": {
        "24-12-cena": {"plato": "Dish", "persona_id": 1},
        "25-12-comida": {"plato": "Dish", "persona_id": 2}
      },
      "notas": "Optional notes"
    }
  ]
}
```

## Tech Stack

- Python 3.12
- FastAPI + Uvicorn
- JSON file storage (`/app/data/vacaciones.json`)

## Development

```bash
cd services/vacaciones-service
pip install -r requirements.txt
cd src && uvicorn main:app --reload --port 8003
```

## Docker

```bash
docker build -t egnal/smart-home-vacaciones:latest .
docker run -p 8003:8003 -v vacaciones-data:/app/data egnal/smart-home-vacaciones:latest
```

## Related Files

- Frontend: `dashboard/src/static/vacaciones.html`
- Proxy routes: `dashboard/src/api/routes.py` (Vacaciones section)
- Controller: `dashboard/src/controllers/vacaciones_controller.py`
