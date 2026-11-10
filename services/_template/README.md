# Service template

1. Each service must have **its own directory**. Copy `service.toml` to `services/<name>/service.toml` and fill in the values (or create the manifest at the declared `code_path`).
2. Follow `.kiro/steering/creating-a-service.md` (SSOT layers + checklist by class/flags).
3. Ensure the service is registered in `docker-compose.prod.yml` (deployment SSOT).
4. Run `pwsh ./scripts/validate-services.ps1` from the repo root.

`service.toml` declares *how* the service is integrated; it does not replace compose, nginx, CI, or coherence tests.