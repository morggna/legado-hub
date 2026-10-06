"""Root conftest for dev-assets/tests.

Some test files depend on external plugin fixtures or modules that are not
present in this checkout. They are excluded from the default test run so the
suite remains green for the code that is maintained here.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Upstream tests exercise the preserved legacy public/Legado integration.
# New account/invite tests explicitly select the production account surface.
os.environ["LEGADOHUB_AUTH_MODE"] = "legacy"

_TEST_RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="legado-hub-pytest-"))

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALLOWED_TEST_FILES = {
    line[1:].replace("\\", "/")
    for line in (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    if line.startswith("!dev-assets/tests/") and line.endswith(".py")
}

_EXCLUDED = {
    "dev-assets/tests/benchmarks",
    "dev-assets/tests/scripts",
    "dev-assets/tests/source_plugins",
    "dev-assets/tests/source_plugins/test_context.py",
    "dev-assets/tests/source_plugins/test_initial_plugins.py",
    "dev-assets/tests/test_69shuba_domain_fallback.py",
    "dev-assets/tests/test_69shuba_tw_simplified.py",
    "dev-assets/tests/test_live_acceptance.py",
    "dev-assets/tests/test_qidian_auth_status.py",
    "dev-assets/tests/test_qidian_reviews.py",
    "dev-assets/tests/test_twkan_browser_fallback.py",
    "dev-assets/tests/test_plugin_auth_repository.py",
    "dev-assets/tests/test_plugin_health_repository.py",
    "dev-assets/tests/official_auth/test_official_auth.py",
}


def pytest_configure(config):
    from app import config as app_config

    data_dir = _TEST_RUNTIME_ROOT / "data"
    config_dir = _TEST_RUNTIME_ROOT / "config"
    generated_dir = _TEST_RUNTIME_ROOT / "generated"
    runtime_dir = _TEST_RUNTIME_ROOT / "runtime"
    data_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    generated_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    app_config.DATA_DIR = data_dir
    app_config.CONFIG_DIR = config_dir
    app_config.GENERATED_DIR = generated_dir
    app_config.RUNTIME_DIR = runtime_dir
    app_config.DB_PATH = data_dir / "app.db"
    app_config.APP_CONFIG_PATH = config_dir / "app_config.json"
    app_config.COOKIE_DIR = config_dir / "cookies"

    from app.storage.db import initialize_database
    from app.services.user_auth import UserAuthService

    initialize_database(app_config.DB_PATH)
    auth = UserAuthService(app_config.DB_PATH)
    if auth.user_count() == 0:
        auth.bootstrap_admin("admin", "admin123")


def pytest_ignore_collect(collection_path, config):
    rel_str = collection_path.as_posix().replace("\\", "/")
    marker = "dev-assets/tests/"
    marker_index = rel_str.find(marker)
    if marker_index >= 0:
        rel_str = rel_str[marker_index:]
    if rel_str.startswith("dev-assets/tests/") and rel_str.endswith(".py"):
        if rel_str not in _ALLOWED_TEST_FILES:
            return True
        return None
    if any(rel_str == ex or rel_str.startswith(ex + "/") for ex in _EXCLUDED):
        return True
    return None


@pytest.fixture(autouse=True)
def reset_subscription_rate_limiter():
    from app.services.reading_limits import reading_access_limiter
    from app.services.user_auth import auth_rate_limiter
    from app.services.user_subscriptions import subscription_rate_limiter

    reading_access_limiter.reset()
    auth_rate_limiter.reset()
    subscription_rate_limiter.reset()
    yield
    reading_access_limiter.reset()
    auth_rate_limiter.reset()
    subscription_rate_limiter.reset()


def pytest_unconfigure(config):
    shutil.rmtree(_TEST_RUNTIME_ROOT, ignore_errors=True)
