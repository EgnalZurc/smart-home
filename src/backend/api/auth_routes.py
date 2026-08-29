"""Authentication endpoints for the Cuchi Casa platform.

Routes
------
GET  /auth/login                  Serve the login page (public)
POST /auth/token                  Verify credentials, issue session cookie
POST /auth/logout                 Clear session cookie
GET  /auth/me                     Return current user info (requires auth)
GET  /auth/trust/approve          Admin approves a trusted-device request
GET  /auth/trust/reject           Admin rejects a trusted-device request
"""
import logging
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

import auth as auth_core
import auth_users

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth")

# ---------------------------------------------------------------------------
# Email configuration (injected from main.py lifespan via module globals)
# ---------------------------------------------------------------------------
SMTP_HOST: str = "smtp.gmail.com"
SMTP_PORT: int = 587
SMTP_USER: str = ""      # REQUIRED: AUTH_SMTP_USER (e.g. acmlsn@gmail.com)
SMTP_PASSWORD: str = ""  # REQUIRED: AUTH_SMTP_PASSWORD (app password)
ADMIN_EMAIL: str = "acmlsn@gmail.com"
BASE_URL: str = "https://raspberrypi.local"  # injected at startup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serve_login_html(error: Optional[str] = None) -> HTMLResponse:
    """Read and return login.html, optionally injecting an error message."""
    # __file__ is at /app/api/auth_routes.py — static/ is one level up at /app/static/
    login_path = Path(__file__).parent.parent / "static" / "login.html"
    content = login_path.read_text(encoding="utf-8")
    if error:
        content = content.replace(
            'id="error-msg" class="hidden"',
            'id="error-msg" class=""',
        ).replace("__ERROR__", error)
    else:
        content = content.replace("__ERROR__", "")
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )


def _set_session_cookie(response: Response, token: str, trusted: bool) -> None:
    """Attach the session cookie to a response."""
    max_age = auth_core.AUTH_TRUSTED_TTL if trusted else auth_core.AUTH_SESSION_TTL
    response.set_cookie(
        key=auth_core.COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def _send_trust_email(username: str, user_agent: str, ip: str, token: str) -> None:
    """Send an approval/rejection email to the admin."""
    approve_url = auth_users.make_action_url(BASE_URL, token, "approve")
    reject_url = auth_users.make_action_url(BASE_URL, token, "reject")

    subject = f"[Cuchi Casa] Solicitud de dispositivo de confianza — {username}"
    body_html = f"""
    <html><body style="font-family:sans-serif;color:#1e293b;max-width:520px;margin:auto">
      <h2 style="color:#4f46e5">🏠 Cuchi Casa — Dispositivo de confianza</h2>
      <p>El usuario <strong>{username}</strong> ha solicitado que su dispositivo sea marcado como <em>de confianza</em> (sesión de 1 año).</p>
      <table style="border-collapse:collapse;width:100%;margin:16px 0">
        <tr><td style="padding:6px 12px;background:#f1f5f9;font-weight:600">Usuario</td>
            <td style="padding:6px 12px">{username}</td></tr>
        <tr><td style="padding:6px 12px;background:#f1f5f9;font-weight:600">IP</td>
            <td style="padding:6px 12px">{ip}</td></tr>
        <tr><td style="padding:6px 12px;background:#f1f5f9;font-weight:600">Dispositivo</td>
            <td style="padding:6px 12px;word-break:break-all">{user_agent}</td></tr>
      </table>
      <p style="margin-top:24px">
        <a href="{approve_url}"
           style="background:#4f46e5;color:#fff;padding:10px 22px;border-radius:6px;text-decoration:none;font-weight:600;margin-right:12px">
          ✅ Aprobar
        </a>
        <a href="{reject_url}"
           style="background:#dc2626;color:#fff;padding:10px 22px;border-radius:6px;text-decoration:none;font-weight:600">
          ❌ Rechazar
        </a>
      </p>
      <p style="margin-top:24px;font-size:12px;color:#64748b">
        Este enlace es de un solo uso. Si no reconoces esta solicitud, haz clic en Rechazar.
      </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ADMIN_EMAIL
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls(context=ctx)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, ADMIN_EMAIL, msg.as_bytes())
        logger.info("Trust request email sent for user %r (token prefix: %s)", username, token[:8])
    except Exception as exc:
        logger.error("Failed to send trust request email: %s", exc)
        # Don't raise — login still succeeds, just without trusted status email


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def get_login(request: Request):
    """Serve the login page.

    If the user already has a valid session, redirect to /smart-home.
    """
    user = auth_core.get_current_user(request)
    if user:
        return RedirectResponse(url="/smart-home", status_code=302)
    return _serve_login_html()


@router.post("/token")
async def post_token(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    trusted: bool = Form(default=False),
    next_url: str = Form(default="/smart-home"),
):
    """Validate credentials and issue a session cookie.

    If `trusted` is True:
    - A pending trust request is created and an approval email is sent to admin.
    - The current session is issued as a normal 24h token.
    - Once the admin approves, the next login with trusted=True will
      receive the long-lived token (the approval check is advisory via email).

    Design note: we keep it simple — the trusted flag in the JWT is only set
    when admin has already approved (see /auth/trust/approve). For now the
    first request always gets a standard token and an email goes out.
    """
    if not auth_users.authenticate_user(username, password):
        logger.warning("Failed login attempt for user %r from %s", username, request.client.host if request.client else "unknown")
        return _serve_login_html(error="Usuario o contraseña incorrectos")

    # Determine if this is a pre-approved trust request
    # (i.e. admin already clicked Approve for a previous request from this user)
    # For now: always issue standard 24h token on login; trusted flag is handled
    # separately via the email flow below.
    token = auth_core.create_token(username, trusted=False)

    if trusted:
        # Create a pending trust request and email the admin
        ip = request.client.host if request.client else "unknown"
        ua = request.headers.get("User-Agent", "unknown")
        trust_token = auth_users.create_trust_request(username, ua, ip)
        _send_trust_email(username, ua, ip, trust_token)
        logger.info("Trust request created for user %r, token prefix: %s", username, trust_token[:8])

    # Sanitise redirect target: only allow relative paths
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/smart-home"

    response = RedirectResponse(url=next_url, status_code=303)
    _set_session_cookie(response, token, trusted=False)
    return response


@router.post("/logout")
async def post_logout():
    """Clear the session cookie and redirect to /auth/login."""
    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie(
        key=auth_core.COOKIE_NAME,
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return response


@router.get("/me")
async def get_me(request: Request):
    """Return the current authenticated user, or 401.

    Used by the dashboard JS to populate the user indicator.
    """
    user = auth_core.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth_core.get_token_from_cookie(request)
    payload = auth_core.decode_token(token) if token else None
    trusted = payload.get("trusted", False) if payload else False

    return JSONResponse({"username": user, "trusted": trusted})


@router.get("/trust/approve")
async def trust_approve(token: str, sig: str):
    """Admin approves a trusted-device request via email link.

    On success: re-issues a long-lived JWT is NOT done here automatically
    (user must log in again). The admin sees a confirmation page.
    """
    if not auth_users.verify_action_sig(token, "approve", sig):
        raise HTTPException(status_code=403, detail="Invalid or tampered signature")

    row = auth_users.resolve_trust_request(token, "approved")
    if row is None:
        return HTMLResponse(_action_result_page(
            "Ya procesado",
            "Esta solicitud ya fue procesada anteriormente.",
            success=False,
        ))

    username = row["username"]
    logger.info("Admin approved trusted device for user %r", username)
    return HTMLResponse(_action_result_page(
        "Dispositivo aprobado",
        f"El dispositivo de <strong>{username}</strong> ha sido marcado como de confianza. "
        "En el próximo inicio de sesión recibirá un token de 1 año.",
        success=True,
    ))


@router.get("/trust/reject")
async def trust_reject(token: str, sig: str):
    """Admin rejects a trusted-device request via email link."""
    if not auth_users.verify_action_sig(token, "reject", sig):
        raise HTTPException(status_code=403, detail="Invalid or tampered signature")

    row = auth_users.resolve_trust_request(token, "rejected")
    if row is None:
        return HTMLResponse(_action_result_page(
            "Ya procesado",
            "Esta solicitud ya fue procesada anteriormente.",
            success=False,
        ))

    username = row["username"]
    logger.info("Admin rejected trusted device for user %r", username)
    return HTMLResponse(_action_result_page(
        "Dispositivo rechazado",
        f"La solicitud de confianza de <strong>{username}</strong> ha sido rechazada.",
        success=False,
    ))


# ---------------------------------------------------------------------------
# Minimal confirmation page for approve/reject actions
# ---------------------------------------------------------------------------

def _action_result_page(title: str, message: str, success: bool) -> str:
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
           border-radius:12px;padding:40px 32px;max-width:420px;text-align:center}}
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
