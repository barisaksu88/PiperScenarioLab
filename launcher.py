"""ScenarioLab launcher: build frontend, start backend, manage local LLM, open UI."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

import uvicorn

from scenario_lab_config import (
    DEBUG_DIR,
    FRONTEND_DIST_DIR,
    FRONTEND_SRC_DIR,
    RUNS_DEBUG_DIR,
    config_summary,
    load_runtime_config,
)
from scenario_engine.debug import (
    record_latest_run,
    set_current_debug_run_dir,
    snapshot_state,
    timestamped_run_dir,
    write_env_snapshot,
    write_jsonl,
    write_resolved_config,
    write_text_artifact,
)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _setup_logging(run_dir: Path) -> tuple[logging.Logger, Path, Path]:
    launcher_log = run_dir / "launcher.log"
    backend_log = run_dir / "backend.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.setLevel(logging.INFO)
    launcher_fh = logging.FileHandler(launcher_log, encoding="utf-8")
    launcher_fh.setFormatter(fmt)
    launcher_fh.setLevel(logging.INFO)
    backend_fh = logging.FileHandler(backend_log, encoding="utf-8")
    backend_fh.setFormatter(fmt)
    backend_fh.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(launcher_fh)
    backend_logger = logging.getLogger("uvicorn")
    backend_logger.setLevel(logging.INFO)
    backend_logger.addHandler(backend_fh)
    logging.getLogger("uvicorn.error").addHandler(backend_fh)
    logging.getLogger("uvicorn.access").addHandler(backend_fh)
    logging.getLogger("app").addHandler(backend_fh)
    logging.getLogger("scenario_engine").addHandler(backend_fh)
    return logging.getLogger("launcher"), launcher_log, backend_log


def _wait_for_http(url: str, timeout_s: float, logger: logging.Logger) -> bool:
    deadline = time.time() + timeout_s
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if 200 <= getattr(resp, "status", 200) < 300:
                    return True
        except Exception as exc:
            last_error = exc
            logger.info("Waiting for %s (%s)", url, exc)
            time.sleep(1)
    logger.error("Timed out waiting for %s: %s", url, last_error)
    return False


def _run_command(command: list[str], cwd: Path, log_path: Path, logger: logging.Logger) -> int:
    logger.info("Running command: %s", " ".join(command))
    with log_path.open("a", encoding="utf-8") as fh:
        proc = subprocess.Popen(command, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert proc.stdout is not None
        for line in proc.stdout:
            fh.write(line)
            fh.flush()
        return proc.wait()


def build_frontend(cfg, run_dir: Path, logger: logging.Logger) -> bool:
    _ensure_dir(FRONTEND_SRC_DIR)
    log_path = run_dir / "frontend_build.log"
    node_modules = FRONTEND_SRC_DIR / "node_modules"
    package_json = FRONTEND_SRC_DIR / "package.json"
    if not package_json.exists():
        log_path.write_text("frontend package.json missing\n", encoding="utf-8")
        raise RuntimeError(f"Frontend build config missing: {package_json}")

    npm_cmd = resolve_npm_command()
    if not npm_cmd:
        raise RuntimeError("npm is not available in PATH")

    if not node_modules.exists():
        code = _run_command(npm_cmd + ["install"], FRONTEND_SRC_DIR, log_path, logger)
        if code != 0:
            raise RuntimeError(f"npm install failed with exit code {code}")

    code = _run_command(npm_cmd + ["run", "build"], FRONTEND_SRC_DIR, log_path, logger)
    if code != 0:
        if FRONTEND_DIST_DIR.exists() and cfg.scenario_allow_stale_frontend:
            logger.warning("Frontend build failed, but stale dist exists and is allowed.")
            return False
        raise RuntimeError(f"Frontend build failed with exit code {code}")
    return True


def shutil_which(name: str) -> Optional[str]:
    from shutil import which

    return which(name)


def resolve_npm_command() -> Optional[list[str]]:
    for candidate in (shutil_which("npm.cmd"), shutil_which("npm.exe"), shutil_which("npm")):
        if candidate:
            return [candidate]
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        for candidate in (
            Path(program_files) / "nodejs" / "npm.cmd",
            Path(program_files) / "nodejs" / "npm.exe",
        ):
            if candidate.exists():
                return [str(candidate)]
    return None


class LlamaServerManager:
    def __init__(self, cfg, run_dir: Path, logger: logging.Logger):
        self.cfg = cfg
        self.run_dir = run_dir
        self.logger = logger
        self.process: subprocess.Popen | None = None
        self.owned_by_scenario_lab = False
        self.log_path = run_dir / "llama_server.log"

    def _health_url(self) -> str:
        return self.cfg.scenario_llm_base_url.rstrip("/") + "/health"

    def _health_check(self) -> bool:
        try:
            with urllib.request.urlopen(self._health_url(), timeout=3) as resp:
                return 200 <= getattr(resp, "status", 200) < 300
        except Exception:
            return False

    def _resolve(self) -> tuple[Path, Path]:
        exe = Path(
            os.environ.get("SCENARIO_LLAMA_SERVER_EXE")
            or self.cfg.piper_config.get("LLAMA_SERVER_EXE")
            or ""
        )
        model = Path(
            os.environ.get("SCENARIO_MODEL_PATH")
            or self.cfg.piper_config.get("MODEL_PATH")
            or ""
        )
        if not exe:
            raise RuntimeError("SCENARIO_LLAMA_SERVER_EXE or Piper LLAMA_SERVER_EXE is required for piper mode")
        if not model:
            raise RuntimeError("SCENARIO_MODEL_PATH or Piper MODEL_PATH is required for piper mode")
        if not exe.exists():
            raise RuntimeError(f"llama-server executable not found: {exe}")
        if not model.exists():
            raise RuntimeError(f"model path not found: {model}")
        return exe, model

    def _build_command(self) -> list[str]:
        exe, model = self._resolve()
        bind_host = os.environ.get("SCENARIO_LLAMA_BIND_HOST") or self.cfg.piper_config.get("LLAMA_SERVER_BIND_HOST") or "127.0.0.1"
        ctx_size = os.environ.get("SCENARIO_CTX_SIZE") or self.cfg.piper_config.get("CONTEXT_SIZE") or 4096
        gpu_layers = os.environ.get("SCENARIO_GPU_LAYERS") or self.cfg.piper_config.get("LLAMA_SERVER_GPU_LAYERS") or 0
        reasoning_budget = os.environ.get("SCENARIO_REASONING_BUDGET") or self.cfg.piper_config.get("LLAMA_SERVER_REASONING_BUDGET")
        mmproj = os.environ.get("SCENARIO_MMPROJ_PATH") or self.cfg.piper_config.get("MMPROJ_PATH")
        port = urllib.parse.urlparse(self.cfg.scenario_llm_base_url).port or 8080

        cmd = [
            str(exe),
            "-m",
            str(model),
            "--host",
            str(bind_host),
            "--port",
            str(port),
            "--ctx-size",
            str(ctx_size),
            "--gpu-layers",
            str(gpu_layers),
        ]
        if reasoning_budget not in (None, ""):
            cmd += ["--reasoning-budget", str(reasoning_budget)]
        if mmproj:
            mmproj_path = Path(mmproj)
            if not mmproj_path.exists():
                raise RuntimeError(f"mmproj path not found: {mmproj_path}")
            cmd += ["--mmproj", str(mmproj_path)]
        return cmd

    def ensure_running(self) -> bool:
        if self._health_check():
            self.logger.info("Reusing existing llama-server at %s", self.cfg.scenario_llm_base_url)
            self.owned_by_scenario_lab = False
            return False
        if not self.cfg.scenario_auto_start_llm:
            raise RuntimeError(f"Local LLM is not healthy at {self.cfg.scenario_llm_base_url} and auto-start is disabled")
        cmd = self._build_command()
        self.logger.info("Launching llama-server: %s", " ".join(cmd))
        with self.log_path.open("a", encoding="utf-8") as fh:
            self.process = subprocess.Popen(cmd, stdout=fh, stderr=fh, cwd=str(Path(cmd[0]).parent))
        self.owned_by_scenario_lab = True
        timeout_s = float(self.cfg.piper_config.get("LLAMA_SERVER_HEALTH_TIMEOUT_S") or self.cfg.scenario_llm_timeout_seconds)
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self._health_check():
                self.logger.info("llama-server is healthy")
                return True
            self.logger.info("Model still loading at %s...", self.cfg.scenario_llm_base_url)
            time.sleep(2)
        raise RuntimeError("llama-server did not become healthy in time")

    def stop(self) -> None:
        if not self.process or not self.owned_by_scenario_lab or not self.cfg.scenario_stop_llm_on_exit:
            return
        self.logger.info("Stopping owned llama-server process")
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except Exception:
            self.logger.warning("Force-killing unresponsive llama-server")
            self.process.kill()


def _start_backend(cfg, logger: logging.Logger):
    import app as scenario_app

    config = uvicorn.Config(
        scenario_app.app,
        host=cfg.scenario_host,
        port=cfg.scenario_port,
        log_level="info",
        reload=False,
        access_log=True,
    )
    server = uvicorn.Server(config)

    def run():
        server.run()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return server, thread, scenario_app


def main() -> int:
    cfg = load_runtime_config()
    _ensure_dir(DEBUG_DIR)
    _ensure_dir(RUNS_DEBUG_DIR)
    run_dir = timestamped_run_dir(RUNS_DEBUG_DIR)
    _ensure_dir(run_dir)
    set_current_debug_run_dir(run_dir)
    record_latest_run(DEBUG_DIR, run_dir)
    write_env_snapshot(run_dir)
    write_resolved_config(run_dir, cfg)
    write_text_artifact("session_snapshot_initial.json", "{}")
    write_text_artifact("session_snapshot_latest.json", "{}")

    logger, launcher_log, backend_log = _setup_logging(run_dir)
    logger.info("Resolved ScenarioLab config: %s", config_summary(cfg))
    logger.info("Resolved Piper repo dir: %s", getattr(cfg, "piper_repo_dir", None))
    logger.info("Piper config import succeeded: %s", getattr(cfg, "piper_config_import_succeeded", False))
    logger.info(
        "Resolved llama-server url/model: %s / %s",
        getattr(cfg, "scenario_llm_base_url", None),
        getattr(cfg, "scenario_llm_model", None),
    )

    try:
        if cfg.scenario_rebuild_frontend_on_boot:
            build_frontend(cfg, run_dir, logger)
            logger.info("Frontend build complete")
        else:
            logger.info("Frontend rebuild disabled")
    except Exception as exc:
        logger.error("Frontend build failed: %s", exc)
        if not FRONTEND_DIST_DIR.exists() or not cfg.scenario_allow_stale_frontend:
            return 1

    llama_manager = None
    if cfg.scenario_llm_mode == "piper":
        llama_manager = LlamaServerManager(cfg, run_dir, logger)
        try:
            llama_manager.ensure_running()
        except Exception as exc:
            logger.error("LLM startup failed: %s", exc)
            if not cfg.scenario_allow_llm_fallback:
                return 1
            logger.warning("SCENARIO_ALLOW_LLM_FALLBACK is enabled; continuing with fallback/minimal LLM responses.")

    server, thread, scenario_app = _start_backend(cfg, logger)
    backend_url = f"http://{cfg.scenario_host}:{cfg.scenario_port}"
    logger.info("Backend startup URL: %s", backend_url)
    if not _wait_for_http(f"{backend_url}/api/scenarios", timeout_s=30, logger=logger):
        return 1

    try:
        import urllib.request

        with urllib.request.urlopen(f"{backend_url}/api/state", timeout=5) as resp:
            state = json.loads(resp.read().decode("utf-8"))
            snapshot_state("session_snapshot_initial.json", state)
            snapshot_state("session_snapshot_latest.json", state)
    except Exception:
        pass

    url = backend_url + "/"
    logger.info("Window startup target: %s", url)
    window_started = False
    if cfg.scenario_window_enabled:
        try:
            import webview  # type: ignore

            logger.info("Opening pywebview window")
            window_started = True
            webview.create_window("Piper Scenario Lab", url, width=1400, height=900)
            webview.start(debug=False)
        except Exception as exc:
            logger.warning("pywebview unavailable, falling back to browser: %s", exc)
    if not window_started:
        webbrowser.open(url)
        logger.info("Browser fallback opened: %s", url)

    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        if llama_manager is not None:
            llama_manager.stop()
        logger.info("Launcher exiting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
