import subprocess

from scripts.gen_secrets import _EXCLUDE, gen_token


def test_gen_token_length():
    length = 32
    token = gen_token(length)
    assert len(token) == length


def test_gen_token_excludes_characters():
    token = gen_token(1000)
    for char in _EXCLUDE:
        assert char not in token, f"Character {char} found in generated token"


def test_gen_secrets_script_execution():
    # Use uv run to execute the script as requested
    result = subprocess.run(
        ["uv", "run", "scripts/gen_secrets.py"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "JWT_SIGNING_KEY:" in result.stdout
    assert "REFRESH_TOKEN_PEPPER:" in result.stdout
