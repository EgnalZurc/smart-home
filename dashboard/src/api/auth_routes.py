"""Authentication endpoints for the Cuchi Casa platform.

Routes
------
GET  /api/auth/login          Serve the login page (public)
POST /api/auth/token          Verify credentials, issue session cookie (+ device cookie if approved)
POST /api/auth/logout         Clear session + device cookies, revoke device token
GET  /api/auth/me             Return current user info (requires valid session)
GET  /api/auth/trust/approve  Admin approves a trusted-device request (email link)
GET  /api/auth/trust/reject   Admin rejects a trusted-device request (email link)

Device-token flow
-----------------
1. User logs in with "Remember device" checked.
2. If user already has an approved trust request in the DB → issue device cookie
   (Jaspan opaque token) AND clear the trust request row.
   If not yet approved → create pending trust request, send email, login succeeds
   with standard 24h session only.
3. On subsequent visits with expired JWT but valid device cookie → AuthMiddleware
   in main.py calls auth_devices.verify_and_rotate(), issues a fresh JWT, and
   sets the rotated device cookie — transparent to the user.
4. On logout → device token is revoked from DB.
"""

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import auth as auth_core
import auth_devices
import auth_users
import user_profiles
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# ---------------------------------------------------------------------------
# Injected configuration (set by main.py lifespan)
# ---------------------------------------------------------------------------
SMTP_HOST: str = "smtp.gmail.com"
SMTP_PORT: int = 587
SMTP_USER: str = ""
SMTP_PASSWORD: str = ""
ADMIN_EMAIL: str = "acmlsn@gmail.com"
BASE_URL: str = "https://raspberrypi.tailaa37cd.ts.net"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _serve_login_html(error: str | None = None) -> HTMLResponse:
    """Read and return login.html, optionally injecting an error message."""
    # __file__ is /app/api/auth_routes.py — static/ is at /app/static/
    login_path = Path(__file__).parent.parent / "static" / "login.html"
    content = login_path.read_text(encoding="utf-8")
    if error:
        # Remove 'hidden' from the error div class (works regardless of other classes)
        import re as _re

        content = _re.sub(
            r'(id="error-msg"[^>]*?)\bhidden\b',
            r"\1",
            content,
            count=1,
        ).replace("__ERROR__", error)
    else:
        content = content.replace("__ERROR__", "")
    return HTMLResponse(
        content=content,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def _set_device_cookie(response: Response, cookie_value: str) -> None:
    """Attach the long-lived device cookie to a response."""
    response.set_cookie(
        key=auth_devices.DEVICE_COOKIE_NAME,
        value=cookie_value,
        max_age=auth_devices.DEVICE_TOKEN_TTL,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
    )


def _clear_device_cookie(response: Response) -> None:
    """Delete the device cookie."""
    response.delete_cookie(
        key=auth_devices.DEVICE_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
    )


def _send_trust_email(username: str, user_agent: str, ip: str, token: str) -> None:
    """Send the admin an approval/rejection email for a trust request."""
    approve_url = auth_users.make_action_url(BASE_URL, token, "approve")
    reject_url = auth_users.make_action_url(BASE_URL, token, "reject")

    subject = f"[Cuchi Casa] Solicitud de dispositivo de confianza — {username}"
    body_html = f"""
    <html><body style="font-family:sans-serif;color:#1e293b;max-width:520px;margin:auto">
      <h2 style="color:#4f46e5">🏠 Cuchi Casa — Dispositivo de confianza</h2>
      <p>El usuario <strong>{username}</strong> ha solicitado que su dispositivo
         sea marcado como <em>de confianza</em> (sesión de 1 año).</p>
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
           style="background:#4f46e5;color:#fff;padding:10px 22px;border-radius:6px;
                  text-decoration:none;font-weight:600;margin-right:12px">
          ✅ Aprobar
        </a>
        <a href="{reject_url}"
           style="background:#dc2626;color:#fff;padding:10px 22px;border-radius:6px;
                  text-decoration:none;font-weight:600">
          ❌ Rechazar
        </a>
      </p>
      <p style="margin-top:24px;font-size:12px;color:#64748b">
        Enlace de un solo uso. Si no reconoces esta solicitud, haz clic en Rechazar.
      </p>
    </body></html>"""

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
        logger.info(
            "Trust request email sent for user %r (token prefix: %s)",
            username,
            token[:8],
        )
    except Exception as exc:
        logger.error("Failed to send trust request email: %s", exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/login", include_in_schema=False, response_class=HTMLResponse)
async def get_login(request: Request):
    """Serve the login page. Redirect to /smart-home if already authenticated."""
    if auth_core.get_current_user(request):
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

    If 'trusted' is checked:
      A) User already has an approved trust request in the DB:
         → Issue device cookie (Jaspan token), clear the trust request row.
         → Also issue a fresh 24h JWT as usual.
      B) No approved request yet:
         → If no active (pending/approved) request exists: create one + send email.
         → If one already exists: skip (dedup).
         → Issue standard 24h JWT only.

    Sanitises the next_url redirect to relative paths only.
    """
    if not auth_users.authenticate_user(username, password):
        logger.warning(
            "Failed login for user %r from %s",
            username,
            request.client.host if request.client else "unknown",
        )
        return _serve_login_html(error="Usuario o contraseña incorrectos")

    # Build response — always issue fresh 24h JWT
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/smart-home"

    response = RedirectResponse(url=next_url, status_code=303)
    session_token = auth_core.create_token(username)
    auth_core.set_session_cookie(response, session_token)

    if trusted:
        # Check for an approved trust request for this user
        approved_row = auth_users.get_approved_trust_request(username)

        if approved_row:
            # Issue the Jaspan device token and clear the (now consumed) trust request
            ip = request.client.host if request.client else "unknown"
            ua = request.headers.get("User-Agent", "unknown")
            device_cookie = auth_devices.create_device_token(username, ua, ip)
            _set_device_cookie(response, device_cookie)
            auth_users.delete_trust_request(approved_row["token"])
            logger.info("Device token issued for approved user %r", username)
        else:
            # No approved request — create pending one (with dedup) and send email
            if not auth_users.has_active_trust_request(username):
                ip = request.client.host if request.client else "unknown"
                ua = request.headers.get("User-Agent", "unknown")
                trust_token = auth_users.create_trust_request(username, ua, ip)
                _send_trust_email(username, ua, ip, trust_token)
                logger.info(
                    "Trust request created for user %r, token prefix: %s",
                    username,
                    trust_token[:8],
                )
            else:
                logger.info(
                    "Trust request skipped for user %r — active request already exists",
                    username,
                )

    return response


@router.post("/logout")
async def post_logout(request: Request):
    """Clear session and device cookies, revoke device token from DB."""
    # Revoke device token if present
    device_cookie = auth_devices.get_device_cookie_from_request(request)
    if device_cookie:
        from auth_devices import _decode_cookie, revoke_device

        parsed = _decode_cookie(device_cookie)
        if parsed:
            series, _ = parsed
            revoked = revoke_device(series)
            if revoked:
                logger.info(
                    "Device token revoked on logout (series prefix: %s)", series[:8]
                )

    response = RedirectResponse(url="/api/auth/login", status_code=303)
    auth_core.clear_session_cookie(response)
    _clear_device_cookie(response)
    return response


@router.get("/me")
async def get_me(request: Request):
    """Return the current authenticated user info, or 401.

    Response includes profile info and the list of apps the user can access,
    so the dashboard can filter its app list without an extra round-trip.
    """
    user = auth_core.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    has_device = bool(auth_devices.get_device_cookie_from_request(request))

    profiles = user_profiles.get_user_profiles(user)
    effective_level = user_profiles.get_effective_level(user)

    return JSONResponse(
        {
            "username": user,
            "trusted_device": has_device,
            "profiles": profiles,
            "effective_level": effective_level,
            "is_admin": effective_level == 0,
            "apps": user_profiles.app_permissions(user),
            "external_services": user_profiles.visible_external_services(user),
        }
    )


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
            f"La solicitud de <strong>{username}</strong> ha sido aprobada. "
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
            f"La solicitud de confianza de <strong>{username}</strong> ha sido rechazada.",
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


# ── nginx auth_request guard ──────────────────────────────────────────────────


@router.get("/verify")
async def verify_session(request: Request):
    """Endpoint for nginx auth_request.

    nginx calls this before forwarding requests to external microservices
    (ac-service, vacaciones-service, etc.).

    Returns:
        200 if the request carries a valid JWT session cookie.
        401 if not authenticated (nginx will redirect to login).
    """
    import auth as auth_core
    from fastapi.responses import Response as FastAPIResponse

    user = auth_core.get_current_user(request)
    if user:
        # Pass username downstream so microservices can log it if needed
        resp = FastAPIResponse(status_code=200)
        resp.headers["X-Auth-User"] = user
        return resp
    return FastAPIResponse(status_code=401)


# ---------------------------------------------------------------------------
# Admin API: Users and Profiles management (SUPER only)
# ---------------------------------------------------------------------------


def _require_super(request: Request) -> str:
    """Check that the current user has level 0 (SUPER). Returns username or raises 403."""
    user = auth_core.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not user_profiles.is_super(user):
        raise HTTPException(status_code=403, detail="Admin access required (level 0)")
    return user


# ── User Management ──────────────────────────────────────────────────────────


@router.get("/admin/users", tags=["Admin"])
async def list_users(request: Request):
    """List all users with their assigned profiles.

    Returns: [{"username": str, "profiles": [str], "effective_level": int}, ...]
    """
    _require_super(request)
    users = auth_users._load_htpasswd(auth_users.HTPASSWD_PATH)
    result = []
    for username in sorted(users.keys()):
        profiles = user_profiles.get_user_profiles(username)
        effective_level = user_profiles.get_effective_level(username)
        result.append(
            {
                "username": username,
                "profiles": profiles,
                "effective_level": effective_level,
            }
        )
    return result


@router.put("/admin/users/{username}/profiles", tags=["Admin"])
async def set_user_profiles_endpoint(username: str, request: Request):
    """Set the profiles for a user (replaces all existing).

    Body: {"profiles": ["PROFILE1", "PROFILE2", ...]}
    """
    _require_super(request)

    if not auth_users.user_exists(username):
        raise HTTPException(status_code=404, detail=f"User not found: {username}")

    body = await request.json()
    profiles = body.get("profiles", [])

    if not profiles:
        raise HTTPException(status_code=400, detail="At least one profile required")

    all_profiles = user_profiles.get_all_profiles()
    for p in profiles:
        if p not in all_profiles:
            raise HTTPException(status_code=400, detail=f"Unknown profile: {p}")

    user_profiles.set_user_profiles(username, profiles)
    logger.info("Profiles %r assigned to user %r by admin", profiles, username)

    return {
        "username": username,
        "profiles": profiles,
        "effective_level": user_profiles.get_effective_level(username),
    }


@router.post("/admin/users/{username}/profiles/{profile}", tags=["Admin"])
async def add_user_profile_endpoint(username: str, profile: str, request: Request):
    """Add a profile to a user (keeps existing profiles)."""
    _require_super(request)

    if not auth_users.user_exists(username):
        raise HTTPException(status_code=404, detail=f"User not found: {username}")

    all_profiles = user_profiles.get_all_profiles()
    if profile not in all_profiles:
        raise HTTPException(status_code=400, detail=f"Unknown profile: {profile}")

    user_profiles.add_user_profile(username, profile)

    return {
        "username": username,
        "profiles": user_profiles.get_user_profiles(username),
        "effective_level": user_profiles.get_effective_level(username),
    }


@router.delete("/admin/users/{username}/profiles/{profile}", tags=["Admin"])
async def remove_user_profile_endpoint(username: str, profile: str, request: Request):
    """Remove a profile from a user."""
    _require_super(request)

    if not auth_users.user_exists(username):
        raise HTTPException(status_code=404, detail=f"User not found: {username}")

    current_profiles = user_profiles.get_user_profiles(username)
    if len(current_profiles) <= 1:
        raise HTTPException(status_code=400, detail="Cannot remove last profile")

    user_profiles.remove_user_profile(username, profile)

    return {
        "username": username,
        "profiles": user_profiles.get_user_profiles(username),
        "effective_level": user_profiles.get_effective_level(username),
    }


# ── Profile Management ───────────────────────────────────────────────────────


@router.get("/admin/profiles", tags=["Admin"])
async def list_profiles(request: Request):
    """List all available profiles with their settings.

    Returns: {"PROFILE_KEY": {level, description, builtin}, ...}
    """
    _require_super(request)
    return user_profiles.get_all_profiles()


@router.post("/admin/profiles", tags=["Admin"])
async def create_profile_endpoint(request: Request):
    """Create a new custom profile.

    Body: {"name": str, "level": int (0-3), "description": str}
    """
    _require_super(request)

    body = await request.json()
    name = body.get("name", "").strip().upper()
    level = body.get("level")
    description = body.get("description", "")

    if not name:
        raise HTTPException(status_code=400, detail="Profile name required")
    if level is None or not isinstance(level, int):
        raise HTTPException(status_code=400, detail="Level required (0-3)")
    if not 0 <= level <= 3:
        raise HTTPException(status_code=400, detail="Level must be 0-3")

    try:
        user_profiles.create_profile(name, level, description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"name": name, "level": level, "description": description, "builtin": False}


@router.put("/admin/profiles/{name}", tags=["Admin"])
async def update_profile_endpoint(name: str, request: Request):
    """Update a custom profile. Cannot modify built-in profiles.

    Body: {"level": int (optional), "description": str (optional)}
    """
    _require_super(request)

    body = await request.json()
    level = body.get("level")
    description = body.get("description")

    if level is not None and not 0 <= level <= 3:
        raise HTTPException(status_code=400, detail="Level must be 0-3")

    try:
        user_profiles.update_profile(name, level, description)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    all_profiles = user_profiles.get_all_profiles()
    return all_profiles.get(name, {})


@router.delete("/admin/profiles/{name}", tags=["Admin"])
async def delete_profile_endpoint(name: str, request: Request):
    """Delete a custom profile. Cannot delete built-in profiles."""
    _require_super(request)

    try:
        user_profiles.delete_profile(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"deleted": name}


# ── Legacy endpoint for backward compatibility ───────────────────────────────


@router.put("/admin/users/{username}/profile", tags=["Admin"])
async def set_user_profile_legacy(username: str, request: Request):
    """Legacy: Assign a single profile to a user (replaces all).

    Body: {"profile": "PROFILE_KEY"}
    """
    _require_super(request)

    if not auth_users.user_exists(username):
        raise HTTPException(status_code=404, detail=f"User not found: {username}")

    body = await request.json()
    profile_key = body.get("profile")
    if not profile_key:
        raise HTTPException(status_code=400, detail="Missing 'profile' field")

    all_profiles = user_profiles.get_all_profiles()
    if profile_key not in all_profiles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid profile: {profile_key}. Valid: {list(user_profiles.PROFILES.keys())}",
        )

    user_profiles.set_profile(username, profile_key)
    logger.info("Profile %r assigned to user %r by admin", profile_key, username)
    return {"username": username, "profile": profile_key}
