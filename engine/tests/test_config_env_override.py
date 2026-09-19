"""Tests for the environment-over-`.env` precedence rule (config.load_config).

Why: `load_config()` used to read ONLY the project `.env`, so a per-run override

    env -u PYTHONPATH STRAPI_URL=http://127.0.0.1:9 .venv/bin/python -m engine.cli run-batch 1

was silently dropped and the command ran against LIVE Strapi (one topic flipped
pending -> drafting with real LLM spend; write-up in t_c447e2b8). These tests pin
the rule that replaced the silence — standard dotenv precedence, the real
environment wins — and pin that the override is visible (key names only, never a
value) instead of silent.

The last two tests are subprocess-level so `pytest engine/tests -q` proves the
acceptance criteria against the real CLI, not just the loader.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    CONFIG_KEYS,
    ENV_PATH,
    Config,
    _resolve_env,
    load_config,
    redact,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# A `.env` fixture with one connection setting + one gated flag + two secrets.
DOTENV_BODY = "\n".join(
    [
        "# comment line is ignored",
        "STRAPI_URL=http://file-host:1337",
        "STRAPI_ENGINE_TOKEN=file-engine-token",
        "OPENROUTER_API_KEY=file-or-key",
        "GEMINI_API_KEY=file-gemini-key",
        "AUTO_PUBLISH_ENABLED=false",
        "PREMIUM_MODEL_ENABLED=false",
        "DASHBOARD_ADMIN_TOKEN=file-dash-token",
    ]
) + "\n"


@pytest.fixture()
def dotenv(tmp_path: Path) -> Path:
    p = tmp_path / ".env"
    p.write_text(DOTENV_BODY)
    return p


# --------------------------------------------------------------- precedence


def test_process_env_overrides_dotenv_value(dotenv, monkeypatch):
    monkeypatch.setenv("STRAPI_URL", "http://127.0.0.1:9")
    cfg = load_config(env_path=dotenv)
    assert cfg.strapi_url == "http://127.0.0.1:9"
    assert cfg.env_overrides == ("STRAPI_URL",)


def test_process_env_overrides_key_absent_from_dotenv(tmp_path, monkeypatch):
    """The reported trap: the real `.env` has no STRAPI_URL at all, so the value
    came from the http://localhost:1337 default — an env value must still win."""
    p = tmp_path / ".env"
    p.write_text(
        "\n".join(
            [
                "STRAPI_ENGINE_TOKEN=file-engine-token",
                "OPENROUTER_API_KEY=file-or-key",
            ]
        )
        + "\n"
    )
    assert load_config(env_path=p, environ={}).strapi_url == "http://localhost:1337"
    monkeypatch.setenv("STRAPI_URL", "http://shadow:1")
    cfg = load_config(env_path=p)
    assert cfg.strapi_url == "http://shadow:1"
    assert cfg.env_overrides == ("STRAPI_URL",)


def test_empty_env_value_does_not_clobber_dotenv(dotenv, monkeypatch):
    """`FOO=` on the command line behaves as unset, not as 'blank it out'."""
    monkeypatch.setenv("STRAPI_URL", "")
    cfg = load_config(env_path=dotenv)
    assert cfg.strapi_url == "http://file-host:1337"
    assert cfg.env_overrides == ()


def test_whitespace_only_env_value_counts_as_unset(dotenv, monkeypatch):
    monkeypatch.setenv("STRAPI_URL", "   ")
    cfg = load_config(env_path=dotenv)
    assert cfg.strapi_url == "http://file-host:1337"
    assert cfg.env_overrides == ()


def test_absent_env_var_leaves_dotenv_value(dotenv, monkeypatch):
    monkeypatch.delenv("STRAPI_URL", raising=False)
    cfg = load_config(env_path=dotenv)
    assert cfg.strapi_url == "http://file-host:1337"
    assert cfg.env_overrides == ()


def test_env_can_override_a_secret_and_the_engine_token(dotenv, monkeypatch):
    monkeypatch.setenv("STRAPI_ENGINE_TOKEN", "shadow-engine-token")
    monkeypatch.setenv("DASHBOARD_ADMIN_TOKEN", "shadow-dash-token")
    monkeypatch.setenv("GEMINI_API_KEY", "shadow-gemini-key")
    cfg = load_config(env_path=dotenv)
    assert cfg.strapi_engine_token == "shadow-engine-token"
    assert cfg.dashboard_admin_token == "shadow-dash-token"
    assert cfg.gemini_api_key == "shadow-gemini-key"
    assert set(cfg.env_overrides) == {
        "STRAPI_ENGINE_TOKEN",
        "DASHBOARD_ADMIN_TOKEN",
        "GEMINI_API_KEY",
    }


def test_required_keys_can_come_from_the_environment_alone(tmp_path, monkeypatch):
    """A `.env` with no tokens at all is satisfied by the process environment."""
    p = tmp_path / ".env"
    p.write_text("STRAPI_URL=http://file-host:1337\n")
    monkeypatch.setenv("STRAPI_ENGINE_TOKEN", "env-token")
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-or-key")
    cfg = load_config(env_path=p)
    assert cfg.strapi_engine_token == "env-token"
    assert cfg.openrouter_api_key == "env-or-key"


def test_missing_from_both_sources_still_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("STRAPI_ENGINE_TOKEN", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    p = tmp_path / ".env"
    p.write_text("STRAPI_URL=http://file-host:1337\n")
    with pytest.raises(RuntimeError) as exc:
        load_config(env_path=p)
    assert "STRAPI_ENGINE_TOKEN" in str(exc.value)


# ------------------------------------------------------------------- flags


@pytest.mark.parametrize(
    "key, env_value, expected",
    [
        ("AUTO_PUBLISH_ENABLED", "true", True),
        ("AUTO_PUBLISH_ENABLED", "1", True),
        ("AUTO_PUBLISH_ENABLED", "yes", True),
        ("AUTO_PUBLISH_ENABLED", "TRUE", True),
        ("AUTO_PUBLISH_ENABLED", "false", False),
        ("AUTO_PUBLISH_ENABLED", "0", False),
        ("PREMIUM_MODEL_ENABLED", "true", True),
        ("PREMIUM_MODEL_ENABLED", "false", False),
    ],
)
def test_boolean_flags_are_overridable_both_ways(dotenv, monkeypatch, key, env_value, expected):
    monkeypatch.setenv(key, env_value)
    cfg = load_config(env_path=dotenv)
    got = cfg.auto_publish_enabled if key == "AUTO_PUBLISH_ENABLED" else cfg.premium_enabled
    assert got is expected


def test_env_can_turn_off_a_flag_the_file_enabled(tmp_path, monkeypatch):
    """The safety direction that matters: env must be able to DISABLE publishing."""
    p = tmp_path / ".env"
    p.write_text(DOTENV_BODY.replace("AUTO_PUBLISH_ENABLED=false", "AUTO_PUBLISH_ENABLED=true"))
    monkeypatch.setenv("AUTO_PUBLISH_ENABLED", "false")
    cfg = load_config(env_path=p)
    assert cfg.auto_publish_enabled is False
    assert cfg.env_overrides == ("AUTO_PUBLISH_ENABLED",)


# -------------------------------------------------------- scope / isolation


def test_unrelated_env_vars_are_ignored(dotenv, monkeypatch):
    monkeypatch.setenv("FOO", "bar")
    monkeypatch.setenv("PATH", "/usr/bin")
    cfg = load_config(env_path=dotenv)
    assert cfg.env_overrides == ()


def test_env_names_are_case_sensitive(dotenv, monkeypatch):
    monkeypatch.setenv("strapi_url", "http://lowercase:1")
    cfg = load_config(env_path=dotenv)
    assert cfg.strapi_url == "http://file-host:1337"
    assert cfg.env_overrides == ()


def test_explicit_empty_environ_reads_the_file_only(dotenv):
    """`environ={}` isolates the file — no dependence on the test runner's shell."""
    cfg = load_config(env_path=dotenv, environ={})
    assert cfg.strapi_url == "http://file-host:1337"
    assert cfg.env_overrides == ()


def test_identical_value_in_both_sources_is_not_reported(dotenv, monkeypatch):
    monkeypatch.setenv("STRAPI_URL", "http://file-host:1337")
    cfg = load_config(env_path=dotenv)
    assert cfg.env_overrides == ()


def test_resolve_env_returns_names_and_resolved_pairs(dotenv, monkeypatch):
    monkeypatch.setenv("STRAPI_URL", "http://shadow:1")
    resolved, overridden = _resolve_env(env_path=dotenv, environ=dict(os.environ))
    assert resolved["STRAPI_URL"] == "http://shadow:1"
    assert resolved["STRAPI_ENGINE_TOKEN"] == "file-engine-token"
    assert overridden == ("STRAPI_URL",)


def test_all_documented_keys_are_overridable(dotenv):
    environ = {k: f"env-{k.lower()}" for k in CONFIG_KEYS}
    resolved, overridden = _resolve_env(env_path=dotenv, environ=environ)
    assert set(overridden) == set(CONFIG_KEYS)
    for key in CONFIG_KEYS:
        assert resolved[key] == f"env-{key.lower()}"


# ------------------------------------------------------- secrets stay secret


def test_override_notice_names_keys_but_never_values(dotenv, monkeypatch, capsys):
    monkeypatch.setenv("STRAPI_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("STRAPI_ENGINE_TOKEN", "SENTINEL-ENGINE-TOKEN")
    monkeypatch.setenv("DASHBOARD_ADMIN_TOKEN", "SENTINEL-DASH-TOKEN")
    cfg = load_config(env_path=dotenv)
    captured = capsys.readouterr()
    assert "STRAPI_URL" in captured.err
    assert captured.out == ""  # never stdout: that is the run-batch result channel
    # Not even the non-secret shadow URL is echoed — the notice names keys only.
    for leak in ("SENTINEL-ENGINE-TOKEN", "SENTINEL-DASH-TOKEN", "http://127.0.0.1:9"):
        assert leak not in captured.err
        assert leak not in captured.out
    for secret in ("SENTINEL-ENGINE-TOKEN", "SENTINEL-DASH-TOKEN"):
        assert secret not in repr(cfg)
        assert secret not in str(redact(cfg))
    assert cfg.strapi_engine_token == "SENTINEL-ENGINE-TOKEN"


def test_no_notice_when_nothing_is_overridden(dotenv, capsys):
    load_config(env_path=dotenv, environ={})
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_redact_reports_override_names_only(dotenv, monkeypatch):
    monkeypatch.setenv("STRAPI_ENGINE_TOKEN", "SENTINEL-ENGINE-TOKEN")
    cfg = load_config(env_path=dotenv)
    safe = redact(cfg)
    assert safe["env_overrides"] == ["STRAPI_ENGINE_TOKEN"]
    assert "SENTINEL-ENGINE-TOKEN" not in str(safe)


@pytest.mark.parametrize("field_name", ["strapi_engine_token", "openrouter_api_key", "gemini_api_key", "dashboard_admin_token"])
def test_every_declared_secret_field_is_repr_masked(field_name):
    """`Config._secret_fields` promised masking that the old field definition did
    not actually deliver: `repr=False` was set on the *tuple* field, so
    `repr(cfg)` printed every token. Pin the pairing so it cannot drift back."""
    assert field_name in Config._secret_fields
    assert Config.__dataclass_fields__[field_name].repr is False


def test_config_repr_and_str_leak_no_secret(dotenv, monkeypatch):
    monkeypatch.setenv("STRAPI_ENGINE_TOKEN", "SENTINEL-ENGINE-TOKEN")
    monkeypatch.setenv("OPENROUTER_API_KEY", "SENTINEL-OR-KEY")
    monkeypatch.setenv("GEMINI_API_KEY", "SENTINEL-GEMINI-KEY")
    monkeypatch.setenv("DASHBOARD_ADMIN_TOKEN", "SENTINEL-DASH-TOKEN")
    cfg = load_config(env_path=dotenv)
    rendered = repr(cfg) + str(cfg) + f"{cfg}"
    for sentinel in ("SENTINEL-ENGINE-TOKEN", "SENTINEL-OR-KEY", "SENTINEL-GEMINI-KEY", "SENTINEL-DASH-TOKEN"):
        assert sentinel not in rendered
    assert cfg.strapi_engine_token == "SENTINEL-ENGINE-TOKEN"  # still usable in memory


def test_the_real_dotenv_is_never_modified_by_an_override(monkeypatch):
    before = hashlib.sha256(ENV_PATH.read_bytes()).hexdigest()
    monkeypatch.setenv("STRAPI_URL", "http://127.0.0.1:9")
    load_config()
    monkeypatch.delenv("STRAPI_URL", raising=False)
    load_config()
    assert hashlib.sha256(ENV_PATH.read_bytes()).hexdigest() == before


# -------------------------------------------------- real CLI (subprocess)


def _run_cli(*args: str, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(env_overrides or {})
    return subprocess.run(
        [sys.executable, "-m", "engine.cli", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


DEAD_URL = "http://127.0.0.1:9"


def test_cli_next_honours_the_shadow_url_and_fails_fast():
    """Acceptance: the override is real — the read-only `next` command cannot
    reach a live topic through a dead STRAPI_URL, and it says so loudly.

    `localhost:1337` (the `.env`/default target) answers; only 127.0.0.1:9 is
    refused, so a connection-refused exit proves which URL the client used."""
    proc = _run_cli("next", env_overrides={"STRAPI_URL": DEAD_URL})
    assert proc.returncode != 0, "a dead STRAPI_URL must not produce a healthy exit"
    assert "Next: " not in proc.stdout, "the shadow URL reached live Strapi"
    assert proc.stdout == ""
    assert "Connection refused" in proc.stderr
    assert "Strapi request failed for /api/topics" in proc.stderr
    # ...and the operator is told why, by name (never by value).
    assert "process environment overrides .env for: STRAPI_URL" in proc.stderr


def test_cli_run_batch_zero_still_refuses_with_exit_2_before_any_network():
    """Acceptance: the zero-limit refusal is unchanged AND precedes the network —
    it must refuse even when the (dead) shadow URL could not answer at all."""
    proc = _run_cli("run-batch", "0", env_overrides={"STRAPI_URL": DEAD_URL})
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert "refused" in proc.stderr
    assert "Strapi request failed" not in proc.stderr  # nothing was ever sent


def test_cli_info_shows_the_override_receipt_without_secrets():
    """`info` is the sanctioned inspection surface: it reports the override by
    name, and its secret fields stay masked (key_set booleans only)."""
    proc = _run_cli("info", env_overrides={"STRAPI_URL": DEAD_URL, "DASHBOARD_ADMIN_TOKEN": "SENTINEL"})
    assert proc.returncode == 0
    assert '"env_overrides": [' in proc.stdout
    assert DEAD_URL in proc.stdout  # strapi_url itself is not a secret
    assert "SENTINEL" not in proc.stdout
    assert "SENTINEL" not in proc.stderr


def test_no_override_keeps_the_cli_output_byte_clean():
    """The 09:00 cron runs `run-batch 2 2>&1 | tee log` and reads the FIRST line as
    the batch summary, so a normal run must emit no notice at all — and a refused
    batch must still have the refusal as the merged first line. (No override here;
    this stays offline because a zero limit refuses before any network use.)"""
    proc = _run_cli("run-batch", "0")
    assert proc.returncode == 2
    assert "[config]" not in proc.stderr
    assert "[config]" not in proc.stdout
    merged = (proc.stderr + proc.stdout).splitlines()
    assert merged[0].startswith("run-batch: refused")