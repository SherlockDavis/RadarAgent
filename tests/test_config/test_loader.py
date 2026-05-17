from __future__ import annotations

from radaragent.config import load_settings


def test_settings_has_smtp_auth_sqlite_defaults(tmp_path):
    yaml_text = """
llm:
  provider: openai
  api_key: dummy
storage:
  type: chroma
  sqlite_path: ./data/radaragent.db
"""
    p = tmp_path / "s.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    s = load_settings(p)
    assert s.storage.sqlite_path == "./data/radaragent.db"
    assert s.auth.session_ttl_days == 30
    assert s.smtp is None
    assert s.digest.history_context_size == 5


def test_settings_parses_smtp(tmp_path):
    yaml_text = """
llm:
  provider: openai
  api_key: dummy
smtp:
  host: smtp.example.com
  port: 587
  username: u
  password: p
  use_tls: true
  from_addr: bot@example.com
"""
    p = tmp_path / "s.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    s = load_settings(p)
    assert s.smtp is not None
    assert s.smtp.host == "smtp.example.com"
    assert s.smtp.port == 587


def test_interests_config_removed():
    import radaragent.config as cfg

    assert not hasattr(cfg, "InterestsConfig")
    assert not hasattr(cfg, "load_interests")
