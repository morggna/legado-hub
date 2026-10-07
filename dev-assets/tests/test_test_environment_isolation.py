from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app import config
from app.services import plugin_runtime_state
from conftest import pytest_ignore_collect


def test_pytest_runtime_paths_do_not_use_workspace_data() -> None:
    backend_root = (Path(__file__).resolve().parents[2] / "backend").resolve()
    runtime_root = config.DATA_DIR.resolve().parent

    assert runtime_root != backend_root
    assert not runtime_root.is_relative_to(backend_root)
    assert hasattr(config, "RUNTIME_DIR")
    assert config.DATA_DIR.resolve().parent == runtime_root
    assert config.CONFIG_DIR.resolve().parent == runtime_root
    assert config.GENERATED_DIR.resolve().parent == runtime_root
    assert config.RUNTIME_DIR.resolve().parent == runtime_root
    assert config.DB_PATH.resolve().parent == config.DATA_DIR.resolve()
    assert config.APP_CONFIG_PATH.resolve().parent == config.CONFIG_DIR.resolve()
    assert config.COOKIE_DIR.resolve().parent == config.CONFIG_DIR.resolve()
    assert plugin_runtime_state.RUNTIME_DIR.resolve() == config.RUNTIME_DIR.resolve()
    assert plugin_runtime_state.STATE_FILE.resolve().parent == config.RUNTIME_DIR.resolve()

    writable_paths = (
        config.DATA_DIR,
        config.CONFIG_DIR,
        config.GENERATED_DIR,
        config.RUNTIME_DIR,
        config.DB_PATH,
        config.APP_CONFIG_PATH,
        config.COOKIE_DIR,
    )
    for writable_path in writable_paths:
        assert writable_path.resolve().is_relative_to(runtime_root)


def test_pytest_ignore_collect_defers_for_allowlisted_test() -> None:
    assert pytest_ignore_collect(Path(__file__), None) is None


def test_pytest_ignore_collect_ignores_test_outside_allowlist() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    test_path = repo_root / "dev-assets/tests/test_ai_client.py"

    assert pytest_ignore_collect(test_path, None) is True


def test_plugin_scheduler_initialization_does_not_mutate_cookie_store(
    tmp_path, monkeypatch
) -> None:
    from app.services.cookie_store import CookieStore
    from app.source_plugins import scheduler as scheduler_module

    cookie_store = CookieStore(base_dir=tmp_path / "cookies")
    cookie_store.save("no_cookie_source", {"cookies": {}})
    plugin = SimpleNamespace(
        metadata=SimpleNamespace(
            id="no_cookie_source",
            enabled=True,
            declares_cookies=False,
        )
    )
    loader = SimpleNamespace(load_all=lambda: {"no_cookie_source": plugin})
    monkeypatch.setattr(scheduler_module, "CookieStore", lambda: cookie_store)

    scheduler_module.PluginScheduler(loader=loader, config={})

    assert cookie_store.path_for("no_cookie_source").exists()


def test_plugin_scheduler_propagates_loader_failure() -> None:
    from app.source_plugins import scheduler as scheduler_module

    def load_all():
        raise RuntimeError("broken plugin")

    loader = SimpleNamespace(load_all=load_all)

    with pytest.raises(RuntimeError, match="broken plugin"):
        scheduler_module.PluginScheduler(loader=loader, config={})


def test_lexicon_updater_uses_target_filesystem_for_temp_directory(
    tmp_path, monkeypatch
) -> None:
    from app.services.lexicon_updater import LexiconUpdater

    lexicon_dir = tmp_path / "lexicons"
    download_dirs: list[Path] = []
    updater = LexiconUpdater(lexicon_dir=lexicon_dir)

    def fake_download(target_dir: Path) -> str:
        download_dirs.append(target_dir)
        (target_dir / "words.txt").write_text("测试\n", encoding="utf-8")
        return "test-sha"

    monkeypatch.setattr(updater, "_download_lexicon", fake_download)

    result = updater.check_and_update()

    assert result.success is True
    assert len(download_dirs) == 1
    assert download_dirs[0].parent == lexicon_dir
    assert not download_dirs[0].exists()


def test_docker_plugin_delivery_contract() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    dockerignore = (repo_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    gitignore = (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines()
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (repo_root / "deploy/docker/entrypoint.sh").read_text(encoding="utf-8")
    # This contract covers the preserved upstream Docker deployment. The fork's
    # root README documents its source-built, single-entrypoint deployment.
    readme = (repo_root / "docs/architecture/upstream-readme.md").read_text(encoding="utf-8")
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text(encoding="utf-8"))
    plugin_mount = yaml.safe_load(
        (repo_root / "docker-compose.plugins.yml").read_text(encoding="utf-8")
    )
    browserless_mount = yaml.safe_load(
        (repo_root / "docker-compose.browserless.yml").read_text(encoding="utf-8")
    )

    assert "x-legadohub-image" not in compose
    assert "legadohub-init" not in compose["services"]
    assert compose["services"]["legadohub"]["image"] == "xzixmn/legado-hub:latest"
    assert "pull_policy" not in compose["services"]["legadohub"]
    assert "depends_on" not in compose["services"]["legadohub"]
    assert "plugins/sources/official/*" in dockerignore
    assert "!plugins/sources/official/qidian_com_web/**" in dockerignore
    assert "plugins/sources/official/*" in gitignore
    assert "!plugins/sources/official/qidian_com_web/**" in gitignore
    assert (repo_root / "plugins/sources/official/qidian_com_web/source.py").is_file()
    assert "plugins/sources/thirdparty" not in dockerignore
    assert "backend/runtime" in dockerignore
    assert all(path in dockerignore for path in ("data", "config", "generated", "runtime"))
    assert "plugins/sources/thirdparty/ /opt/legadohub/plugins/thirdparty/" in dockerfile
    assert "plugins/sources/official/qidian_com_web/ /opt/legadohub/plugins/official/qidian_com_web/" in dockerfile
    assert "ENTRYPOINT [\"legadohub-entrypoint\"]" in dockerfile
    assert "USER root" in dockerfile
    assert "USER legadohub" not in dockerfile
    assert "gosu" in dockerfile
    assert "COPY --chown=legadohub:legadohub plugins/ /app/plugins/" not in dockerfile
    assert "/opt/legadohub/plugins/thirdparty" in entrypoint
    assert "/app/plugins/sources/thirdparty" in entrypoint
    assert "/opt/legadohub/plugins/official" in entrypoint
    assert "/app/plugins/sources/official" in entrypoint
    assert 'cp -R "$source" "$target/$name"' in entrypoint
    assert "cp -a" not in entrypoint
    assert "[ -e \"$target/$name\" ] && continue" in entrypoint
    assert "gosu" in entrypoint
    assert "PUID" in entrypoint
    assert "PGID" in entrypoint

    def _volume_targets(entries: list[object]) -> list[str]:
        return [str(item).strip("'\"") for item in entries if isinstance(item, str) and ":" in str(item)]

    def _env_map(raw: object) -> dict[str, str]:
        if isinstance(raw, dict):
            return {str(key): str(value) for key, value in raw.items()}
        if isinstance(raw, list):
            parsed: dict[str, str] = {}
            for item in raw:
                text = str(item)
                key, sep, value = text.partition("=")
                if sep:
                    parsed[key] = value
            return parsed
        raise AssertionError(f"unexpected environment shape: {type(raw)!r}")

    volumes = _volume_targets(compose["services"]["legadohub"]["volumes"])
    assert "./data:/app/backend/data" in volumes
    assert "./config:/app/backend/config" in volumes
    assert "./generated:/app/backend/generated" in volumes
    assert "./runtime:/app/backend/runtime" in volumes
    assert "./plugins/sources/thirdparty:/app/plugins/sources/thirdparty" in volumes
    assert compose["services"]["legadohub"].get("read_only") is not True
    assert compose["services"]["legadohub"]["ports"] == [
        "8765:8765",
        "8766:8766",
    ]
    environment = _env_map(compose["services"]["legadohub"]["environment"])
    assert "LEGADOHUB_EXTERNAL_HOST" not in environment
    assert environment.get("TZ") == "Asia/Shanghai"
    assert environment.get("PUID") == "1000"
    assert environment.get("PGID") == "1000"
    assert environment.get("LEGADOHUB_CHOWN_DATA") == "${LEGADOHUB_CHOWN_DATA:-0}"
    assert "UMASK" not in environment
    assert "LEGADOHUB_PUBLIC_MODE" not in environment
    assert environment.get("LEGADOHUB_PUBLIC_BASE_URL") == "${LEGADOHUB_PUBLIC_BASE_URL:-}"
    assert compose["services"]["legadohub"]["container_name"] == "legadohub"
    assert compose["services"]["legadohub"]["security_opt"] == [
        "no-new-privileges:true"
    ]
    assert compose["services"]["legadohub"]["cap_drop"] == ["ALL"]
    assert set(compose["services"]["legadohub"]["cap_add"]) == {
        "CHOWN",
        "DAC_OVERRIDE",
        "SETGID",
        "SETUID",
    }
    assert "network_mode" not in compose["services"]["legadohub"]
    assert compose["services"]["legadohub"]["networks"] == ["legadohub_internal"]
    assert compose["networks"]["legadohub_internal"]["driver"] == "bridge"
    assert "networks" not in browserless_mount
    assert browserless_mount["services"]["browserless"]["networks"] == [
        "legadohub_internal"
    ]
    assert compose["services"]["legadohub"]["logging"] == {
        "driver": "json-file",
        "options": {"max-size": "10m", "max-file": "3"},
    }
    assert not (repo_root / "docker-compose.public.yml").exists()
    assert not (repo_root / "deploy/caddy/Caddyfile").exists()
    assert "runtime directory is not writable" in entrypoint
    assert "--initialize-runtime" in entrypoint
    assert "LEGADOHUB_CHOWN_DATA" in entrypoint
    assert "app.db-wal" in entrypoint
    assert "app.db-journal" in entrypoint
    assert "must not run as root" in entrypoint
    assert "as_app_user test -w" in entrypoint
    assert "for data_entry in /app/backend/data/*" in entrypoint
    assert "UMASK" not in entrypoint
    assert "UMASK" not in dockerfile
    assert "docker run -d" in readme
    assert "--log-opt max-size=10m" in readme
    assert "--security-opt no-new-privileges:true" in readme
    plain_readme = readme.replace("**", "")
    assert "不要用 `docker compose restart` 加载新环境变量。" in plain_readme
    assert "exec gosu" in entrypoint
    assert "./plugins/sources/official:/app/plugins/sources/official" in volumes
    assert list(plugin_mount["services"]) == ["legadohub"]
    assert any(
        volume.endswith(":/app/plugins/sources/thirdparty")
        for volume in plugin_mount["services"]["legadohub"]["volumes"]
    )


def test_windows_bootstrap_does_not_require_dotenv() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    start_script = (repo_root / "start.bat").read_text(encoding="utf-8")

    assert ".env.example" not in start_script
    assert 'in (".env")' not in start_script.lower()
    assert not (repo_root / ".env.example").exists()
