# Docker Structure Documentation

This document explains the Docker-related files and structure of this project.

## 📁 Docker Files Location

Following industry standards, Docker configuration files are located in the **project root**:

```
smart-home/
├── docker-compose.yml           # Production configuration (Raspberry Pi)
├── docker-compose.override.yml  # Development overrides (local Windows)
├── .dockerignore                # Files to exclude from Docker builds
├── .env                         # Environment variables (not in git)
├── .env.example                 # Environment template
└── src/backend/Dockerfile       # Backend service image definition
```

## 🎯 Why Root Location?

This is the **standard convention** for Docker projects because:

1. **Immediate usage**: `docker-compose up` works from project root
2. **Industry standard**: Used by GitLab, Mastodon, Home Assistant, Nextcloud, and thousands of projects
3. **Docker Compose expects it**: Default behavior looks for `docker-compose.yml` in current directory
4. **Simplicity**: No need for `-f docker/compose/...` flags
5. **CI/CD friendly**: Most CI tools expect configs in root

### When to use `docker/` folder?

Only for **large enterprise monorepos** with:
- 20+ microservices
- Multiple deployment targets (Kubernetes, Swarm, etc.)
- Complex build matrices
- Separate teams per service

**Our project**: 3-4 services = Root location is correct ✅

## 📄 File Purposes

### `docker-compose.yml`

**Purpose**: Base production configuration for Raspberry Pi deployment

**Contains**:
- Service definitions (mosquitto, zigbee2mqtt, backend)
- Network configuration
- Volume mounts (all pointing to `./data/`)
- Port mappings
- Restart policies

**Usage**:
```bash
# On Raspberry Pi (production)
docker-compose up -d
```

### `docker-compose.override.yml`

**Purpose**: Development-specific overrides for local Windows development

**Docker Compose behavior**:
- Automatically merged with `docker-compose.yml` when running `docker-compose up`
- Not committed to production environments
- Allows local customization without modifying base config

**Contains**:
- Source code volume mounts for hot-reload
- Debug logging levels
- Development-only services (if needed)

**Usage**:
```bash
# On local Windows (development)
docker-compose up -d  # Automatically uses both files

# To ignore override file:
docker-compose -f docker-compose.yml up -d
```

### `docker-compose.dev.yml` (DEPRECATED)

**Status**: ⚠️ To be removed

**Reason**: Replaced by `docker-compose.override.yml` which follows Docker Compose official pattern

### `.dockerignore`

**Purpose**: Exclude unnecessary files from Docker build context

**Why important**:
- Faster builds (smaller context)
- Prevents sensitive data from entering images
- Reduces image size
- Security best practice

**What we exclude**:
- Git files (`.git/`, `.github/`)
- Documentation (`*.md`, `docs/`)
- Runtime data (`data/`)
- Python cache (`__pycache__/`, `*.pyc`)
- Environment files (`.env`)
- Development tools (`.vscode/`, `.idea/`)

## 🏗️ Project Structure Philosophy

### Clear Separation

```
smart-home/
├── 📦 Docker configs (root)     # Deployment & orchestration
│   ├── docker-compose.yml
│   ├── docker-compose.override.yml
│   └── .dockerignore
├── 🔧 Infrastructure            # Service configurations (in git)
│   └── infrastructure/
├── 💾 Runtime data              # Generated data (NOT in git)
│   └── data/
└── 💻 Source code               # Application code (in git)
    └── src/
```

### Why Not a `docker/` Folder?

**Evaluated structure**:
```
docker/
├── compose/
│   ├── docker-compose.yml
│   └── docker-compose.override.yml
└── images/
    └── backend/
        └── Dockerfile
```

**Rejected because**:
- ❌ Adds unnecessary nesting for small project
- ❌ Requires `docker-compose -f docker/compose/docker-compose.yml up`
- ❌ Not standard for projects our size
- ❌ Harder for new contributors
- ❌ CI/CD tools expect root location

## 🚀 Deployment Scenarios

### Local Development (Windows)

**Requirements**:
- `serial_bridge.py` running (COM3 → TCP:8282)
- `.env` configured with credentials

**Commands**:
```bash
# Start all services (uses override automatically)
docker-compose up -d

# View logs
docker-compose logs -f

# Rebuild after code changes
docker-compose up -d --build
```

### Production (Raspberry Pi)

**Requirements**:
- USB Zigbee coordinator connected
- `.env` configured

**Commands**:
```bash
# Start services (production only, no override)
docker-compose up -d

# Update services
git pull
docker-compose up -d --build

# Backup data
tar -czf backup.tar.gz data/
```

## 📊 Comparison with Industry Examples

| Project | Docker Location | Complexity | Our Match |
|---------|----------------|------------|-----------|
| **Home Assistant** | Root (`docker-compose.yml`) | 5-10 services | ✅ Yes |
| **GitLab** | Root (`docker-compose.yml`) | 10-15 services | ✅ Yes |
| **Nextcloud** | Root (`docker-compose.yml`) | 3-5 services | ✅ Yes |
| **Mastodon** | Root (`docker-compose.yml`) | 5-8 services | ✅ Yes |
| **Kubernetes projects** | `deploy/` or `k8s/` | 50+ services | ❌ Different scale |
| **Google monorepos** | `docker/` or `build/` | 100+ services | ❌ Different scale |

**Conclusion**: Our structure matches industry standards for projects of similar size and complexity ✅

## 🔄 Migration Notes

### From `docker-compose.dev.yml` to `docker-compose.override.yml`

**Old way**:
```bash
docker-compose -f docker-compose.dev.yml up -d
```

**New way** (automatic):
```bash
docker-compose up -d  # Automatically uses override.yml
```

**Benefits**:
- No need to remember `-f` flag
- Standard Docker Compose behavior
- Clearer separation: production vs development
- Easier for new team members

## 📚 References

- [Docker Compose Override Documentation](https://docs.docker.com/compose/extends/)
- [Docker Compose Best Practices](https://docs.docker.com/compose/production/)
- [The Twelve-Factor App](https://12factor.net/) - Config management principles
- [Docker Build Context Best Practices](https://docs.docker.com/build/building/context/)

## 🎓 Learning Resources

**Understanding our choices**:
1. Why root? → Docker Compose convention
2. Why override.yml? → Official Docker pattern
3. Why .dockerignore? → Build efficiency & security
4. Why data/ separate? → The Twelve-Factor App (VI. Processes)

---

**Last updated**: June 24, 2026  
**Maintained by**: Smart Home Project Team
