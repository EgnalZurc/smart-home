# Contributing to Smart Home Control

Thank you for your interest in contributing! This document explains how to collaborate on the project.

---

## 🌟 Ways to Contribute

- 🐛 Report bugs
- 💡 Suggest new features
- 📝 Improve documentation
- 🔧 Submit code (pull requests)
- 🧪 Test in different environments
- 🌍 Translate documentation

---

## 🐛 Reporting Bugs

### Before reporting

1. Search existing [Issues](https://github.com/EgnalZurc/smart-home/issues)
2. Test with latest code version
3. Verify problem is reproducible

### Create Issue

Include:
- **Clear description** of the problem
- **Steps to reproduce** (1, 2, 3...)
- **Expected behavior** vs **actual behavior**
- **Relevant logs** (use `docker-compose logs`)
- **Environment**: OS, Docker version, Raspberry Pi model
- **Screenshots** (if applicable)

---

## 💡 Suggesting Features

### Propose new feature

1. Open [Issue](https://github.com/EgnalZurc/smart-home/issues/new) with `enhancement` label
2. Describe:
   - What problem does it solve?
   - How would it work?
   - Does it affect existing hardware or require new hardware?
   - Does it fit in existing phase or require new phase?

### Propose new phase

See [README.md - Adding new phases](README.md#adding-new-phases)

1. Create document `docs/phaseN-name.md`
2. Define requirements (F{N}.1, F{N}.2, ...)
3. Specify additional hardware
4. Design logic/architecture
5. Open Pull Request with proposal

---

## 🔧 Contributing Code

### Development Setup

```bash
# Fork repository on GitHub

# Clone your fork
git clone https://github.com/YOUR_USERNAME/smart-home.git
cd smart-home

# Add upstream
git remote add upstream https://github.com/EgnalZurc/smart-home.git

# Create branch for your feature
git checkout -b feature/descriptive-name
```

### Local Development

```bash
# Use docker-compose.override.yml for development
docker-compose up -d --build

# View logs
docker-compose logs -f

# Restart backend after changes
docker restart smart-home-backend
```

### Before Commit

```bash
# Verify no credentials
git status
git diff

# Verify .env is NOT staged
git status | grep .env

# Verify Python (if you modified backend)
cd src/backend
python -m pytest  # If tests exist

# Verify nothing breaks
docker-compose up -d --build
curl http://localhost:8080/api/status
```

### Commit and Push

```bash
# Descriptive commits
git add .
git commit -m "feat: Clear description of feature"

# Push to your fork
git push origin feature/descriptive-name
```

### Pull Request

1. Go to your fork on GitHub
2. Click "Compare & pull request"
3. Fill template:
   - **Description**: What does your PR do?
   - **Related issue**: Fixes #123
   - **Tests**: How did you test it?
   - **Checklist**: Mark completed items

---

## 📝 Code Style

### Python (Backend)

- **PEP 8** (standard style guide)
- **Type hints** when possible
- **Docstrings** for public functions
- **Logs** with appropriate levels (INFO, WARNING, ERROR)

```python
async def get_sensor_reading(sensor_id: str) -> dict | None:
    """Get latest reading from a sensor.
    
    Args:
        sensor_id: Unique ID of Zigbee sensor
        
    Returns:
        Dict with temperature, humidity, battery and timestamp.
        None if sensor doesn't exist.
    """
    # Implementation
```

### JavaScript (Frontend)

- **ES6+** modern syntax
- **camelCase** for variables and functions
- **Comments** in complex parts
- **Async/await** for promises

```javascript
async function updateSensorData() {
    try {
        const response = await fetch('/api/sensors');
        const data = await response.json();
        renderSensors(data);
    } catch (error) {
        console.error('Error fetching sensors:', error);
    }
}
```

### Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: Add support for motion sensors
fix: Fix temperature average calculation
docs: Update deployment guide
refactor: Simplify AC controller logic
test: Add tests for state machine
chore: Update dependencies
```

---

## 🧪 Tests

### Run Tests

```bash
cd src/backend
python -m pytest
python -m pytest tests/test_state_machine.py -v
```

### Add Tests

- Unit tests for business logic
- Integration tests for API endpoints
- Tests in `src/backend/tests/`

```python
def test_temperature_average():
    """Test temperature average calculation"""
    sensors = [
        {'temperature': 25.0},
        {'temperature': 26.0},
        {'temperature': 24.0},
    ]
    assert calculate_average(sensors) == 25.0
```

---

## 📚 Documentation

### Update Documentation

If your PR affects:
- **Functionality**: Update README.md
- **Deployment**: Update DEPLOY.md
- **Usage**: Update QUICKSTART.md
- **Architecture**: Update corresponding docs/

### Create New Documentation

- Markdown with consistent formatting
- Code examples when relevant
- Screenshots if they help understanding
- Links to external documentation

---

## 🔐 Security

### Report Vulnerability

**DO NOT** open public issue. Send private email to:
- **Email**: [acmlsn@gmail.com](mailto:acmlsn@gmail.com)
- **Subject**: `[SECURITY] Brief description`

Include:
- Vulnerability description
- Steps to reproduce
- Potential impact
- Possible solution (if you know it)

### Best Practices

- ❌ **NEVER** commit credentials (`.env`, passwords, API keys)
- ✅ Use `.env.example` for templates
- ✅ Verify `.gitignore` before commit
- ✅ Use GitHub Actions secrets for CI/CD

---

## 📦 Releases

### Versioning

Follow [Semantic Versioning](https://semver.org/):
- `MAJOR.MINOR.PATCH` (e.g.: `1.2.3`)
- **MAJOR**: Incompatible changes
- **MINOR**: New compatible functionality
- **PATCH**: Compatible bug fixes

### Create Release

1. Update `CHANGELOG.md` (if exists)
2. Tag in Git: `git tag v1.2.0`
3. Push tag: `git push origin v1.2.0`
4. GitHub Actions builds Docker image automatically
5. Create release on GitHub with notes

---

## 🤝 Code of Conduct

### Our Commitment

- 🤗 Welcoming and inclusive environment
- 🎯 Focus on what's best for the community
- 😊 Respect and empathy towards other contributors
- 🙏 Accept constructive criticism
- 🌍 Diversity of experiences and perspectives

### Expected Behavior

- ✅ Welcoming and inclusive language
- ✅ Respect different viewpoints
- ✅ Accept constructive criticism
- ✅ Focus on what's best for community

### Unacceptable Behavior

- ❌ Offensive or inappropriate language
- ❌ Trolling or derogatory comments
- ❌ Public or private harassment
- ❌ Publishing others' private information

---

## 📧 Contact

- **Issues**: [GitHub Issues](https://github.com/EgnalZurc/smart-home/issues)
- **Email**: acmlsn@gmail.com
- **Twitter**: _Coming soon_

---

## ⭐ Acknowledgments

All contributors will be recognized in:
- README.md (Contributors section)
- CHANGELOG.md (per release)
- GitHub contributors page

---

## 📄 License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).

---

**Thank you for contributing!** 🎉

Your help makes this project better for everyone.
