#!/usr/bin/env python3
"""Test API endpoints with authentication.

Usage:
    python scripts/test_api.py [--username USER] [--password PASS]

Environment variables (alternative to args):
    SMART_HOME_USER
    SMART_HOME_PASS

This script:
1. Authenticates via POST /auth/token
2. Tests various endpoints with the session cookie
3. Reports results
"""
import argparse
import os
import sys
from urllib.parse import urljoin

import httpx

BASE_URL = os.environ.get("SMART_HOME_URL", "https://raspberrypi.tailaa37cd.ts.net")


def authenticate(client: httpx.Client, username: str, password: str) -> bool:
    """Authenticate and store session cookie in client."""
    resp = client.post(
        urljoin(BASE_URL, "/auth/token"),
        data={"username": username, "password": password, "next_url": "/smart-home"},
        follow_redirects=False,
    )
    # Successful login redirects with 303 and sets session cookie
    if resp.status_code in (302, 303):
        print(f"✅ Authenticated as {username}")
        return True
    print(f"❌ Authentication failed: {resp.status_code}")
    return False


def test_endpoint(client: httpx.Client, method: str, path: str, expected_status: int = 200) -> dict:
    """Test an endpoint and return result."""
    url = urljoin(BASE_URL, path)
    try:
        if method.upper() == "GET":
            resp = client.get(url)
        elif method.upper() == "POST":
            resp = client.post(url)
        else:
            return {"path": path, "status": "error", "message": f"Unknown method: {method}"}
        
        success = resp.status_code == expected_status
        result = {
            "path": path,
            "status": "ok" if success else "fail",
            "code": resp.status_code,
            "expected": expected_status,
        }
        
        # Try to parse JSON response
        try:
            result["data"] = resp.json()
        except Exception:
            result["data"] = resp.text[:200] if len(resp.text) > 200 else resp.text
        
        return result
    except Exception as e:
        return {"path": path, "status": "error", "message": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Test Smart Home API endpoints")
    parser.add_argument("--username", "-u", default=os.environ.get("SMART_HOME_USER", ""))
    parser.add_argument("--password", "-p", default=os.environ.get("SMART_HOME_PASS", ""))
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if not args.username or not args.password:
        print("Error: Username and password required")
        print("Use --username/--password or set SMART_HOME_USER/SMART_HOME_PASS")
        sys.exit(1)

    # Endpoints to test (no auth required)
    public_endpoints = [
        ("GET", "/health", 200),
        ("GET", "/api/health/backend", 200),
        ("GET", "/api/health/ac", 200),
        ("GET", "/api/health/zigbee", 200),
        ("GET", "/api/health/casita", 200),
        ("GET", "/api/health/vacaciones", 200),
        ("GET", "/api/health/immich", 200),
        ("GET", "/api/health/passwords", 200),
    ]

    # Endpoints requiring auth
    protected_endpoints = [
        ("GET", "/auth/me", 200),
        ("GET", "/api/containers", 200),
        ("GET", "/api/casita/status", 200),
        ("GET", "/api/casita/radar", 200),
        ("GET", "/api/system/stats", 200),
    ]

    print(f"\n{'='*60}")
    print(f"Smart Home API Test - {BASE_URL}")
    print(f"{'='*60}\n")

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        # Test public endpoints first (no auth)
        print("📡 Testing PUBLIC endpoints (no auth):\n")
        for method, path, expected in public_endpoints:
            result = test_endpoint(client, method, path, expected)
            icon = "✅" if result["status"] == "ok" else "❌"
            print(f"  {icon} {method} {path} → {result.get('code', 'error')}")
            if args.verbose and "data" in result:
                print(f"      {result['data']}")

        # Authenticate
        print(f"\n{'─'*60}")
        print("🔐 Authenticating...\n")
        if not authenticate(client, args.username, args.password):
            sys.exit(1)

        # Test protected endpoints
        print(f"\n📡 Testing PROTECTED endpoints (with auth):\n")
        for method, path, expected in protected_endpoints:
            result = test_endpoint(client, method, path, expected)
            icon = "✅" if result["status"] == "ok" else "❌"
            print(f"  {icon} {method} {path} → {result.get('code', 'error')}")
            if args.verbose and "data" in result:
                data = result["data"]
                if isinstance(data, dict):
                    # Truncate large responses
                    preview = str(data)[:200]
                    print(f"      {preview}...")
                else:
                    print(f"      {data}")

        print(f"\n{'='*60}")
        print("Done!")


if __name__ == "__main__":
    main()
