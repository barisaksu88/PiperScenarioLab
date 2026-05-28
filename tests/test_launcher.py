import json
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SCENARIO_LLM_MODE", "mock")

import pytest

import launcher
from scenario_engine.debug import record_latest_run, timestamped_run_dir
from scenario_lab_config import load_runtime_config


def test_config_bridge_falls_back_without_piper(monkeypatch):
    monkeypatch.delenv("PIPER_REPO_DIR", raising=False)
    monkeypatch.setenv("SCENARIO_LLM_MODE", "mock")
    cfg = load_runtime_config()
    assert cfg.scenario_llm_mode == "mock"
    assert cfg.scenario_llm_base_url.startswith("http://")
    assert cfg.piper_config_import_succeeded in {True, False}


def test_debug_run_folder_creation(tmp_path):
    run_dir = timestamped_run_dir(tmp_path)
    run_dir.mkdir(parents=True, exist_ok=True)
    record_latest_run(tmp_path, run_dir)
    latest = (tmp_path / "latest_run.txt").read_text(encoding="utf-8")
    assert latest == str(run_dir)


def test_health_check_reuses_existing_server(monkeypatch, tmp_path):
    cfg = SimpleNamespace(
        scenario_llm_base_url="http://127.0.0.1:8080",
        scenario_auto_start_llm=True,
        scenario_llm_timeout_seconds=1,
        scenario_stop_llm_on_exit=True,
        piper_config={},
    )
    mgr = launcher.LlamaServerManager(cfg, tmp_path, launcher.logging.getLogger("test"))
    monkeypatch.setattr(mgr, "_health_check", lambda: True)
    assert mgr.ensure_running() is False
    assert mgr.owned_by_scenario_lab is False


def test_health_check_launches_and_waits(monkeypatch, tmp_path):
    cfg = SimpleNamespace(
        scenario_llm_base_url="http://127.0.0.1:8080",
        scenario_auto_start_llm=True,
        scenario_llm_timeout_seconds=1,
        scenario_stop_llm_on_exit=True,
        piper_config={
            "LLAMA_SERVER_EXE": str(tmp_path / "llama-server.exe"),
            "MODEL_PATH": str(tmp_path / "model.gguf"),
        },
    )
    (tmp_path / "llama-server.exe").write_text("x", encoding="utf-8")
    (tmp_path / "model.gguf").write_text("x", encoding="utf-8")
    mgr = launcher.LlamaServerManager(cfg, tmp_path, launcher.logging.getLogger("test"))
    popen_calls = []

    class DummyProc:
        def __init__(self):
            self.stdout = None
        def terminate(self):
            return None
        def wait(self, timeout=None):
            return 0
        def kill(self):
            return None

    monkeypatch.setattr(mgr, "_health_check", lambda: len(popen_calls) > 0)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: popen_calls.append((args, kwargs)) or DummyProc())
    assert mgr.ensure_running() is True
    assert mgr.owned_by_scenario_lab is True
    assert popen_calls
