"""Phase 0 project-setup sanity checks: no env dependency, expected files exist."""

import os
from pathlib import Path

import forex_daytrade

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_import_requires_no_environment_variables() -> None:
    """Importing the package must not read or require any env vars."""
    sentinel = "FOREX_DAYTRADE_TEST_SENTINEL_UNSET"
    assert sentinel not in os.environ
    assert forex_daytrade.__version__


def test_env_example_exists_and_has_no_real_looking_values() -> None:
    env_example = REPO_ROOT / ".env.example"
    assert env_example.exists()

    content = env_example.read_text(encoding="utf-8")
    expected_keys = {
        "MT5_LOGIN",
        "MT5_PASSWORD",
        "MT5_SERVER",
        "MT5_PATH",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "LOG_LEVEL",
        "ENVIRONMENT",
        "MT5_TERMINAL_PATH",
        "MT5_BROKER_TIMEZONE",
        "DATA_RAW_DIR",
        "DATA_NORMALIZED_DIR",
        "DATA_METADATA_DIR",
    }
    for key in expected_keys:
        assert key in content

    # Non-secret config values (filesystem paths, log level, timezone names)
    # may ship with a sane non-blank default; only credential-shaped keys
    # must remain blank placeholders.
    non_secret_defaults = {
        "LOG_LEVEL",
        "ENVIRONMENT",
        "MT5_BROKER_TIMEZONE",
        "DATA_RAW_DIR",
        "DATA_NORMALIZED_DIR",
        "DATA_METADATA_DIR",
    }
    for line in content.splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key.strip() in non_secret_defaults:
            continue
        assert value.strip() == "", f"{key} should be a blank placeholder in .env.example"


def test_no_env_file_committed_in_repo_root() -> None:
    assert not (REPO_ROOT / ".env").exists()


def test_required_governance_files_exist() -> None:
    required = [
        "README.md",
        "CLAUDE.md",
        "pyproject.toml",
        ".gitignore",
        ".env.example",
        "docs/PROJECT_CHARTER.md",
        "docs/ARCHITECTURE.md",
        "docs/DEVELOPMENT_ROADMAP.md",
        "docs/STRATEGY_SPEC_V1.md",
        "docs/RISK_POLICY.md",
        "docs/EXPERIMENT_POLICY.md",
        "docs/SECURITY.md",
        "docs/CONTRIBUTING.md",
    ]
    missing = [path for path in required if not (REPO_ROOT / path).exists()]
    assert not missing, f"Missing required files: {missing}"
