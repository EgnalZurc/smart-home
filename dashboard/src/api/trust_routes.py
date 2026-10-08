"""Trusted-device management endpoints for the Cuchi Casa platform.

Routes
------
GET  /api/auth/trust/approve  Admin approves a trusted-device request (email link)
GET  /api/auth/trust/reject   Admin rejects a trusted-device request (email link)

These endpoints are reached through single-use signed links emailed to the admin
when a user requests that their device be marked as trusted. The device-token
issuing flow itself lives in ``auth_routes.py`` (the ``POST /api/auth/token``
handler), since it is part of the login path.
"""

import html
import logging

import auth_users
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

# Same prefix/tag as auth_routes so the public API is unchanged.
router = APIRouter(prefix="/api/auth", tags=["Auth"])


# ---------------------------------------------------------------------------
# Trust request management (admin email links)
# ---------------------------------------------------------------------------


@router.get("/trust/approve", include_in_schema=False)
async def trust_approve(token: str, sig: str):
    """Admin approves a trust request via signed email link."""
    if not auth_users.verify_action_sig(token, "approve", sig):
        raise HTTPException(status_code=403, detail="Invalid or tampered signature")

    row = auth_users.resolve_trust_request(token, "approved")
    if row is None:
        return HTMLResponse(
            _result_page(
                "Ya procesado",
                "Esta solicitud ya fue procesada anteriormente.",
                success=False,
            )
        )

    username = row["username"]
    logger.info("Admin approved trusted device request for user %r", username)
    return HTMLResponse(
        _result_page(
            "Solicitud aprobada",
            f"La solicitud de <strong>{html.escape(username)}</strong> ha sido aprobada. "
            "En el próximo inicio de sesión con «Recordar dispositivo» marcado "
            "recibirá su token de dispositivo.",
            success=True,
        )
    )


@router.get("/trust/reject", include_in_schema=False)
async def trust_reject(token: str, sig: str):
    """Admin rejects a trust request via signed email link."""
    if not auth_users.verify_action_sig(token, "reject", sig):
        raise HTTPException(status_code=403, detail="Invalid or tampered signature")

    row = auth_users.resolve_trust_request(token, "rejected")
    if row is None:
        return HTMLResponse(
            _result_page(
                "Ya procesado",
                "Esta solicitud ya fue procesada anteriormente.",
                success=False,
            )
        )

    username = row["username"]
    logger.info("Admin rejected trusted device request for user %r", username)
    return HTMLResponse(
        _result_page(
            "Solicitud rechazada",
            f"La solicitud de confianza de <strong>{html.escape(username)}</strong> ha sido rechazada.",
            success=False,
        )
    )


# ---------------------------------------------------------------------------
# HTML result page (approve/reject confirmation)
# ---------------------------------------------------------------------------


def _result_page(title: str, message: str, success: bool) -> str:
    icon = "✅" if success else "❌"
    color = "#4f46e5" if success else "#dc2626"
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Cuchi Casa — {title}</title>
  <style>
    body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
          background:#0f172a;color:#e2e8f0;display:flex;align-items:center;
          justify-content:center;min-height:100vh;margin:0}}
    .card{{background:rgba(30,41,59,.9);border:1px solid rgba(51,65,85,.5);
           border-radius:12px;padding:40px 32px;max-width:440px;text-align:center}}
    h1{{font-size:1.25rem;margin:12px 0 8px;color:{color}}}
    p{{color:#94a3b8;line-height:1.6}}
    a{{color:#6366f1;text-decoration:none;font-weight:600}}
  </style>
</head>
<body>
  <div class="card">
    <div style="font-size:2.5rem">{icon}</div>
    <h1>{title}</h1>
    <p>{message}</p>
    <p style="margin-top:24px"><a href="/smart-home">← Ir al dashboard</a></p>
  </div>
</body>
</html>"""
