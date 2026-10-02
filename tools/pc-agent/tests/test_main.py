"""Minimal tests for pc-agent.

Full integration tests require Docker Desktop on Windows.
These tests only verify the code is syntactically correct.
"""


def test_syntax():
    """Verify main.py has valid Python syntax."""
    from pathlib import Path
    import ast
    
    main_py = Path(__file__).parent.parent / "src" / "main.py"
    source = main_py.read_text()
    
    # This will raise SyntaxError if invalid
    ast.parse(source)
    assert True


def test_requirements_exist():
    """Verify requirements.txt exists."""
    from pathlib import Path
    
    req = Path(__file__).parent.parent / "requirements.txt"
    assert req.exists()
    content = req.read_text()
    assert "fastapi" in content
    assert "docker" in content
