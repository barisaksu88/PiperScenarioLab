"""ScenarioLab debug/audit artifact helpers."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_CURRENT_DEBUG_RUN_DIR: Optional[Path] = None


def set_current_debug_run_dir(path: Path | None) -> None:
    global _CURRENT_DEBUG_RUN_DIR
    _CURRENT_DEBUG_RUN_DIR = path


def get_current_debug_run_dir() -> Optional[Path]:
    return _CURRENT_DEBUG_RUN_DIR


def _safe_write(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except Exception:
        pass


def write_jsonl(path: Path, payload: Any) -> None:
    try:
        line = json.dumps(payload, ensure_ascii=False, default=str)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def write_text_artifact(name: str, text: str) -> None:
    run_dir = get_current_debug_run_dir()
    if run_dir is None:
        return
    _safe_write(run_dir / name, text)


def snapshot_state(name: str, scenario_state: Any) -> None:
    run_dir = get_current_debug_run_dir()
    if run_dir is None:
        return
    try:
        payload = scenario_state.model_dump(mode="json") if hasattr(scenario_state, "model_dump") else scenario_state
    except Exception:
        payload = str(scenario_state)
    _safe_write(run_dir / name, json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def write_env_snapshot(run_dir: Path) -> None:
    try:
        env = {k: v for k, v in os.environ.items() if k.startswith("SCENARIO_") or k.startswith("PIPER_")}
        _safe_write(run_dir / "env_snapshot.json", json.dumps(env, indent=2, ensure_ascii=False, default=str))
    except Exception:
        pass


def write_resolved_config(run_dir: Path, payload: Any) -> None:
    try:
        data = payload.as_json() if hasattr(payload, "as_json") else payload
        _safe_write(run_dir / "resolved_config.json", json.dumps(data, indent=2, ensure_ascii=False, default=str))
    except Exception:
        pass


def latest_run_file(debug_dir: Path) -> Path:
    return debug_dir / "latest_run.txt"


def record_latest_run(debug_dir: Path, run_dir: Path) -> None:
    _safe_write(latest_run_file(debug_dir), str(run_dir))


def timestamped_run_dir(base_dir: Path) -> Path:
    return base_dir / datetime.now().strftime("%Y%m%d_%H%M%S")
