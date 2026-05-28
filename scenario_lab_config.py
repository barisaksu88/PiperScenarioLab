"""ScenarioLab configuration and Piper config bridge."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
STATE_DIR = DATA_DIR / "state"
DEBUG_DIR = DATA_DIR / "debug"
RUNS_DEBUG_DIR = DEBUG_DIR / "runs"
FRONTEND_SRC_DIR = ROOT_DIR / "web_ui" / "frontend"
FRONTEND_DIST_DIR = FRONTEND_SRC_DIR / "dist"
SCENARIOS_DIR = ROOT_DIR / "scenarios"
SESSIONS_DIR = ROOT_DIR / "sessions"


def _default_piper_repo_dir() -> Path:
    if os.name == "nt":
        return Path(r"C:\Projects\Piper")
    return Path("/mnt/c/Projects/Piper")


@dataclass
class ScenarioLabRuntimeConfig:
    scenario_host: str = "127.0.0.1"
    scenario_port: int = 8000
    scenario_llm_mode: str = "mock"
    scenario_llm_base_url: str = "http://127.0.0.1:8080"
    scenario_llm_model: str = "qwen"
    scenario_llm_timeout_seconds: float = 300.0
    scenario_debug_llm: bool = False
    scenario_window_enabled: bool = True
    scenario_rebuild_frontend_on_boot: bool = True
    scenario_auto_start_llm: bool = False
    scenario_stop_llm_on_exit: bool = False
    scenario_allow_stale_frontend: bool = False
    piper_repo_dir: Path = field(default_factory=_default_piper_repo_dir)
    piper_config: Dict[str, Any] = field(default_factory=dict)
    piper_config_import_succeeded: bool = False

    @property
    def base_url(self) -> str:
        return f"http://{self.scenario_host}:{self.scenario_port}"

    def as_json(self) -> Dict[str, Any]:
        data = asdict(self)
        data["piper_repo_dir"] = str(self.piper_repo_dir)
        return data


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bridge_piper_config(piper_repo_dir: Path) -> tuple[bool, Dict[str, Any]]:
    if not piper_repo_dir.exists():
        return False, {}

    added = False
    repo_str = str(piper_repo_dir)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)
        added = True
    try:
        spec = importlib.util.find_spec("config")
        if spec is None:
            return False, {}
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
    except Exception:
        return False, {}
    finally:
        if added and sys.path and sys.path[0] == repo_str:
            sys.path.pop(0)

    cfg = getattr(module, "CFG", None)
    if cfg is None:
        return False, {}

    keys = [
        "LLAMA_SERVER_URL",
        "LLAMA_SERVER_MODEL",
        "LLAMA_SERVER_EXE",
        "MODEL_PATH",
        "CONTEXT_SIZE",
        "LLAMA_SERVER_GPU_LAYERS",
        "LLAMA_SERVER_BIND_HOST",
        "LLAMA_SERVER_HEALTH_TIMEOUT_S",
        "LLAMA_SERVER_REASONING_BUDGET",
        "MMPROJ_PATH",
    ]
    data = {key: getattr(cfg, key, None) for key in keys}
    return True, data


def load_runtime_config() -> ScenarioLabRuntimeConfig:
    piper_repo_dir = Path(os.environ.get("PIPER_REPO_DIR") or _default_piper_repo_dir())
    bridge_ok, bridge_cfg = _bridge_piper_config(piper_repo_dir)

    llm_mode = os.environ.get("SCENARIO_LLM_MODE", "mock").strip().lower()
    llm_base_url = os.environ.get("SCENARIO_LLM_BASE_URL") or str(bridge_cfg.get("LLAMA_SERVER_URL") or "http://127.0.0.1:8080")
    llm_model = os.environ.get("SCENARIO_LLM_MODEL") or str(bridge_cfg.get("LLAMA_SERVER_MODEL") or "qwen")
    timeout_seconds = float(os.environ.get("SCENARIO_LLM_TIMEOUT_SECONDS") or 300.0)

    debug_llm_env = os.environ.get("SCENARIO_DEBUG_LLM")
    debug_llm = _env_bool("SCENARIO_DEBUG_LLM", llm_mode == "piper")
    if debug_llm_env is None:
        debug_llm = llm_mode == "piper"

    auto_start_llm = _env_bool("SCENARIO_AUTO_START_LLM", llm_mode == "piper")
    stop_llm_on_exit = _env_bool("SCENARIO_STOP_LLM_ON_EXIT", llm_mode == "piper")

    cfg = ScenarioLabRuntimeConfig(
        scenario_host=os.environ.get("SCENARIO_HOST", "127.0.0.1"),
        scenario_port=int(os.environ.get("SCENARIO_PORT", "8000")),
        scenario_llm_mode=llm_mode,
        scenario_llm_base_url=llm_base_url,
        scenario_llm_model=llm_model,
        scenario_llm_timeout_seconds=timeout_seconds,
        scenario_debug_llm=debug_llm,
        scenario_window_enabled=_env_bool("SCENARIO_WINDOW_ENABLED", True),
        scenario_rebuild_frontend_on_boot=_env_bool("SCENARIO_REBUILD_FRONTEND_ON_BOOT", True),
        scenario_auto_start_llm=auto_start_llm,
        scenario_stop_llm_on_exit=stop_llm_on_exit,
        scenario_allow_stale_frontend=_env_bool("SCENARIO_ALLOW_STALE_FRONTEND", False),
        piper_repo_dir=piper_repo_dir,
        piper_config=bridge_cfg,
        piper_config_import_succeeded=bridge_ok,
    )
    if llm_mode == "piper" and not os.environ.get("SCENARIO_DEBUG_LLM"):
        cfg.scenario_debug_llm = True
    return cfg


def config_summary(cfg: ScenarioLabRuntimeConfig) -> str:
    return json.dumps(cfg.as_json(), indent=2, default=str)
