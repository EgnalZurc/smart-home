"""
Script de setup único para autorizar el acceso a Gmail via OAuth2.

Soporta dos modos:
  - Con navegador (PC Windows/Mac/Linux desktop):
        python setup_gmail.py
  - Sin navegador (Raspberry Pi, servidor headless):
        python setup_gmail.py --headless

En modo headless el script imprime una URL en la consola.
Ábrela en cualquier navegador (tu PC, el móvil...), autoriza,
y pega el código que te devuelve Google de vuelta en la consola.

REQUISITOS PREVIOS (Google Cloud Console):
  1. Ir a https://console.cloud.google.com/
  2. Crear proyecto → "APIs y servicios" → "Habilitar APIs"
     → buscar "Gmail API" → Habilitar
  3. "Credenciales" → "Crear credenciales" → "ID de cliente OAuth"
     → Tipo de aplicación: "Aplicación de escritorio"
  4. Descargar el JSON resultante
  5. Copiarlo a la Raspberry como: /data/casita-suenos/gmail_credentials.json
     (o la ruta que configure CASITA_DATA_DIR en el .env)

NOTAS:
  - El token generado NO caduca (tiene refresh_token). Solo necesitas
    ejecutar este script una vez. La app lo renueva automáticamente.
  - Si cambias los permisos (scopes) tendrás que repetir el proceso.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent))

SCOPES = ["https://mail.google.com/"]

# Rutas por defecto (relativas al directorio data junto a src/)
_SRC_DIR  = Path(__file__).parent
_DATA_DIR = _SRC_DIR.parent / "data"


def _resolve_paths(data_dir: str | None) -> tuple[Path, Path]:
    base = Path(data_dir) if data_dir else _DATA_DIR
    return base / "gmail_credentials.json", base / "gmail_token.json"


def _check_credentials(credentials_path: Path) -> None:
    if not credentials_path.exists():
        print(f"\n❌  No se encontró: {credentials_path}")
        print("""
Pasos para obtener el fichero de credenciales:

  1. Ve a https://console.cloud.google.com/
  2. Crea (o selecciona) un proyecto
  3. "APIs y servicios" → "Biblioteca" → busca "Gmail API" → Habilitar
  4. "APIs y servicios" → "Credenciales" → "Crear credenciales"
     → "ID de cliente OAuth 2.0"
     → Tipo de aplicación: "Aplicación de escritorio"
     → Nombre: casita-suenos (o el que quieras)
  5. Descarga el JSON
  6. Cópialo a la Raspberry:
       scp credentials.json pi@raspberrypi:/data/casita-suenos/gmail_credentials.json
     O ponlo en la ruta indicada arriba si estás en local.
""")
        sys.exit(1)


def authorize_with_browser(credentials_path: Path, token_path: Path) -> None:
    """Flujo estándar con navegador local (para PC con escritorio)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    print(f"  Credenciales: {credentials_path}")
    print("  Abriendo navegador...")

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds, token_path)


def authorize_headless(credentials_path: Path, token_path: Path) -> None:
    """
    Flujo sin navegador (para Raspberry Pi u otros servidores headless).

    Utiliza el flujo de autorización por código de dispositivo OAuth2:
    el script imprime una URL, la abres en cualquier navegador,
    autorizas, y pegas el código de vuelta en la consola.
    """
    import json
    import urllib.parse
    import urllib.request

    # Leer el client_id y client_secret del fichero de credenciales
    with open(credentials_path, encoding="utf-8") as f:
        creds_data = json.load(f)

    # El JSON de Google puede tener la clave "installed" o "web"
    client_info = creds_data.get("installed") or creds_data.get("web")
    if not client_info:
        print("❌  Formato de credentials.json no reconocido.")
        sys.exit(1)

    client_id     = client_info["client_id"]
    client_secret = client_info["client_secret"]
    token_uri     = client_info.get("token_uri", "https://oauth2.googleapis.com/token")

    # Paso 1 — Construir la URL de autorización (modo OOB → redirect a urn:ietf:wg:oauth:2.0:oob)
    # Google deprecó OOB en 2022 para clientes web, pero para "app de escritorio" sigue soportado.
    # Si da error "disallowed_useragent", usa el flujo de dispositivo más abajo.
    auth_params = {
        "client_id":     client_id,
        "redirect_uri":  "urn:ietf:wg:oauth:2.0:oob",
        "response_type": "code",
        "scope":         " ".join(SCOPES),
        "access_type":   "offline",
        "prompt":        "consent",   # fuerza la emisión del refresh_token
    }
    auth_url = "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(auth_params)

    print("\n" + "─" * 60)
    print("  AUTORIZACIÓN SIN NAVEGADOR")
    print("─" * 60)
    print("\n  1. Abre esta URL en cualquier navegador (PC, móvil...):\n")
    print(f"     {auth_url}\n")
    print("  2. Inicia sesión con tu cuenta de Gmail")
    print("  3. Autoriza el acceso a 'casita-suenos'")
    print("  4. Google te mostrará un código. Cópialo.")
    print("\n" + "─" * 60)

    code = input("\n  Pega el código aquí y pulsa Enter: ").strip()
    if not code:
        print("❌  No introdujiste ningún código.")
        sys.exit(1)

    # Paso 2 — Intercambiar el código por tokens
    token_data = urllib.parse.urlencode({
        "code":          code,
        "client_id":     client_id,
        "client_secret": client_secret,
        "redirect_uri":  "urn:ietf:wg:oauth:2.0:oob",
        "grant_type":    "authorization_code",
    }).encode()

    req = urllib.request.Request(
        token_uri,
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            token_response = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"\n❌  Error al obtener el token: {e.code} {body}")
        sys.exit(1)

    if "error" in token_response:
        print(f"\n❌  Google devolvió un error: {token_response}")
        sys.exit(1)

    # Paso 3 — Construir el JSON del token en el formato que espera google-auth
    import datetime as _dt

    expiry = _dt.datetime.utcnow() + _dt.timedelta(
        seconds=int(token_response.get("expires_in", 3600))
    )

    token_json = {
        "token":         token_response["access_token"],
        "refresh_token": token_response.get("refresh_token"),
        "token_uri":     token_uri,
        "client_id":     client_id,
        "client_secret": client_secret,
        "scopes":        SCOPES,
        "expiry":        expiry.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
    }

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(token_json, indent=2))
    _save_confirmation(token_path)


def _save_token(creds, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    _save_confirmation(token_path)


def _save_confirmation(token_path: Path) -> None:
    print(f"\n✅  Token guardado en: {token_path}")
    print("""
La app ya puede acceder a Gmail sin interacción manual.
El token se renueva automáticamente antes de que caduque.

Si estás en la Raspberry y ejecutaste esto en tu PC, copia el token:
    scp gmail_token.json pi@raspberrypi:/data/casita-suenos/gmail_token.json
""")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autoriza acceso a Gmail para casita-orquestador.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  En tu PC (con navegador):
      python setup_gmail.py

  En la Raspberry (sin navegador):
      python setup_gmail.py --headless

  Con ruta de datos personalizada:
      python setup_gmail.py --headless --data-dir /mnt/data/casita
        """,
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Modo sin navegador: imprime una URL para autorizar desde otro dispositivo.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        metavar="PATH",
        help=f"Directorio donde buscar credentials.json y guardar token.json. "
             f"Por defecto: {_DATA_DIR}",
    )
    args = parser.parse_args()

    credentials_path, token_path = _resolve_paths(args.data_dir)

    print("\n╔══════════════════════════════════════════════╗")
    print("║     casita-orquestador — Setup Gmail OAuth2  ║")
    print("╚══════════════════════════════════════════════╝\n")

    # Si el token ya existe y es válido, no hacer nada
    if token_path.exists():
        print(f"ℹ️   Ya existe un token en: {token_path}")
        overwrite = input("   ¿Sobreescribir? [s/N]: ").strip().lower()
        if overwrite != "s":
            print("   Cancelado. El token existente se mantiene.")
            sys.exit(0)

    _check_credentials(credentials_path)

    print(f"  Modo: {'headless (sin navegador)' if args.headless else 'con navegador'}")

    if args.headless:
        authorize_headless(credentials_path, token_path)
    else:
        authorize_with_browser(credentials_path, token_path)


if __name__ == "__main__":
    main()
