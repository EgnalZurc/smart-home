# Scripts Directory

This directory contains auxiliary scripts for development, setup, and utilities.

## 📁 Purpose

**Scripts** are helper programs that support development and deployment but are **not part of the main application**. They are typically:
- Run manually by developers
- Used during setup or maintenance
- Development/testing utilities
- One-off automation tasks

## 📜 Available Scripts

### `serial_bridge.py`

**Purpose**: TCP/IP bridge for Zigbee USB dongle (Windows development only)

**What it does**:
- Exposes Windows COM3 port as TCP server on port 8282
- Allows Docker containers to access USB Zigbee coordinator
- Required for local development on Windows

**Usage**:
```bash
# From project root
python scripts/serial_bridge.py

# Or from scripts directory
cd scripts
python serial_bridge.py
```

**When to use**:
- ✅ Local Windows development
- ❌ Raspberry Pi production (uses USB directly)

**Requirements**:
- Python 3.x
- `pyserial` package: `pip install pyserial`
- Zigbee dongle connected to COM3

**Configuration**:
Edit line 11 in the script to change COM port if needed:
```python
COM_PORT = "COM3"  # Change this if your dongle is on a different port
```

## 🔧 Directory Convention

### Why `scripts/` and not root?

**Problems with root location**:
- ❌ Clutters project root
- ❌ Mixes utilities with core project files
- ❌ Not standard for auxiliary scripts
- ❌ Harder to find and organize

**Benefits of `scripts/` directory**:
- ✅ Industry standard (Python.org recommendation)
- ✅ Clean project root
- ✅ Clear separation: core code vs utilities
- ✅ Easy to add more scripts
- ✅ Better for `.dockerignore` (exclude entire directory)

### Standard Project Structure

```
smart-home/
├── src/                 # Main application code
├── scripts/             # Auxiliary scripts (this directory)
├── tests/               # Test files
├── docs/                # Documentation
├── infrastructure/      # Service configurations
├── data/                # Runtime data
└── [config files]       # docker-compose.yml, .env, etc.
```

## 📚 Scripts vs Source Code

| Aspect | `src/` | `scripts/` |
|--------|--------|------------|
| **Purpose** | Main application | Development utilities |
| **Deployment** | Deployed to production | Not deployed |
| **Docker** | Inside containers | Run on host |
| **Import** | Importable modules | Standalone executables |
| **Testing** | Unit tested | Usually not tested |

## 🆕 Adding New Scripts

When adding a new script to this directory:

1. **Name it descriptively**: `setup_database.py`, `migrate_data.py`, `backup_config.py`
2. **Add shebang**: `#!/usr/bin/env python3`
3. **Make it executable** (optional, Unix): `chmod +x script_name.py`
4. **Document usage** in this README
5. **Add dependencies** to `requirements-dev.txt` if needed

### Script Template

```python
#!/usr/bin/env python3
"""
Brief description of what this script does.

Usage:
    python scripts/script_name.py [options]

Requirements:
    - Dependency 1
    - Dependency 2
"""

def main():
    # Your script logic here
    pass

if __name__ == "__main__":
    main()
```

## 🚫 What NOT to Put Here

- ❌ Main application code (belongs in `src/`)
- ❌ Tests (belongs in `tests/`)
- ❌ Configuration files (belongs in `infrastructure/` or root)
- ❌ Docker-related files (belongs in root)
- ❌ CI/CD pipelines (belongs in `.github/workflows/`)

## 🔗 Related

- Main application: `src/backend/`
- Docker setup: See [DOCKER.md](../DOCKER.md)
- Project structure: See [README.md](../README.md)

---

**Last updated**: June 24, 2026
