"""Basic tests for pc-agent.

Full integration tests require Docker and run locally on Windows.
These minimal tests verify the module can be imported and basic structure.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_imports():
    """Verify main module can be imported."""
    # Mock docker before import
    from unittest.mock import MagicMock
    sys.modules["docker"] = MagicMock()
    sys.modules["docker.errors"] = MagicMock()
    
    # Now import should work
    import main
    assert main.app is not None
    assert main.POWER_SCRIPTS == {
        "gaming": "ModoGaming.ps1",
        "servidor": "ModoServidor.ps1",
        "balanced": "ModoBalanced.ps1",
    }


def test_env_defaults():
    """Verify environment variable defaults are set."""
    from unittest.mock import MagicMock
    sys.modules["docker"] = MagicMock()
    sys.modules["docker.errors"] = MagicMock()
    
    import main
    # Default paths should be E:\ based
    assert "valheim-server" in str(main.VALHEIM_SERVER_DIR)
