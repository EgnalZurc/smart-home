"""Manual deploy trigger endpoint.

Lets a SUPER user kick off the GitHub Actions CI/CD workflow for a single
service straight from the dashboard, instead of running
``gh workflow run ci.yml -f service=<name>`` by hand.

The endpoint shells out to the GitHub CLI (``gh``) which must be installed and
authenticated in the dashboard container. On success it resolves the URL of the
run that was just dispatched so the caller can link straight to the Actions page.

Only the SUPER profile may call these endpoints.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request

from api.auth_helpers import require_super

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/deploy", tags=["Deploy"])

# GitHub repository the workflow lives in.
REPO = "EgnalZurc/smart-home"

# Workflow file to dispatch.
WORKFLOW = "ci.yml"

# Services that map 1:1 to the ``service`` choice input of ci.yml's
# workflow_dispatch. Anything outside this set is rejected with 400 so a bad
# frontend value (or a crafted request) can never reach the shell.
VALID_SERVICES: frozenset[str] = frozenset(
    {
        "dashboard",
        "ac-service",
        "baby-gifts",
        "portfolio-monitor",
        "vacaciones",
        "casita",
        "vaultwarden",
        "valheim-admin",
    }
)

# Seconds to wait for each gh invocation before giving up.
GH_TIMEOUT = 20


async def _run_gh(args: list[str]) -> tuple[int, str, str]:
    """Run ``gh`` with the given args, returning (returncode, stdout, stderr).

    The command is executed via ``asyncio.create_subprocess_exec`` (argument
    list, never a shell string) so service names cannot inject shell syntax.
    """
    proc = await asyncio.create_subprocess_exec(
        "gh",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=GH_TIMEOUT
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(status_code=504, detail="gh command timed out")
    return proc.returncode, stdout_b.decode().strip(), stderr_b.decode().strip()


async def _latest_run_url(service: str) -> str | None:
    """Best-effort lookup of the most recent run URL for the workflow.

    Returns ``None`` if the URL cannot be resolved; dispatching already
    succeeded by this point, so a missing URL must not fail the request.
    """
    try:
        rc, out, _ = await _run_gh(
            [
                "run",
                "list",
                "--repo",
                REPO,
                "--workflow",
                WORKFLOW,
                "--limit",
                "1",
                "--json",
                "url",
            ]
        )
    except HTTPException:
        return None
    if rc != 0 or not out:
        return None
    try:
        runs = json.loads(out)
    except json.JSONDecodeError:
        return None
    if isinstance(runs, list) and runs and isinstance(runs[0], dict):
        return runs[0].get("url")
    return None


@router.post("/{service}")
async def trigger_deploy(service: str, request: Request) -> dict[str, object]:
    """Trigger a GitHub Actions deploy for ``service``.

    Dispatches ``ci.yml`` with ``-f service=<service>``. Returns the dispatched
    service plus, when resolvable, the URL of the resulting workflow run.
    Only accessible to the SUPER profile.
    """
    require_super(request)

    if service not in VALID_SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service}")

    rc, _out, err = await _run_gh(
        [
            "workflow",
            "run",
            WORKFLOW,
            "--repo",
            REPO,
            "-f",
            f"service={service}",
        ]
    )
    if rc != 0:
        logger.error("gh workflow run failed for %r: %s", service, err)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to trigger deploy: {err or 'unknown gh error'}",
        )

    logger.info("Deploy triggered for service %r", service)

    # GitHub needs a moment to register the dispatched run before it appears in
    # `gh run list`; give it a short grace period.
    await asyncio.sleep(2)
    run_url = await _latest_run_url(service)

    return {
        "status": "triggered",
        "service": service,
        "run_url": run_url,
        "actions_url": f"https://github.com/{REPO}/actions/workflows/{WORKFLOW}",
    }
