# Plantilla de servicio

1. Cada servicio debe tener **su propio directorio**. Copia `service.toml` a `services/<nombre>/service.toml` y completa los valores (o crea el manifiesto en la ruta `code_path` declarada).
2. Sigue `.kiro/steering/creating-a-service.md` (SSOT por capas + checklist por clase/flags).
3. Asegura que el servicio queda registrado en `docker-compose.prod.yml` (SSOT de despliegue).
4. Ejecuta `pwsh ./scripts/validate-services.ps1` desde la raíz del repo.

`service.toml` declara *cómo* se integra el servicio; no sustituye a compose, nginx, CI ni tests de coherencia.
