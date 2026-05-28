"""PiperScenarioLab - FastAPI application."""

import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from scenario_engine.engine import ScenarioEngine
from scenario_engine.llm_client import LLMClient, LLMMode, PiperLLMAdapter, LLMClientError
from scenario_engine.models import (
    APIResponse,
    ScenariosListResponse,
    SessionLogEntry,
    SessionStateResponse,
    TurnInput,
    TurnResult,
)
from scenario_engine.storage import Storage

# ---------------------------------------------------------------------------
# Startup / Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create storage, LLM client, engine, and auto-load scenario."""
    # Read SCENARIO_LLM_MODE env var (default "mock")
    llm_mode_str = os.environ.get("SCENARIO_LLM_MODE", "mock").lower()
    try:
        llm_mode = LLMMode(llm_mode_str)
    except ValueError:
        llm_mode = LLMMode.MOCK
        llm_mode_str = LLMMode.MOCK.value

    # Create Storage
    storage = Storage(
        scenarios_dir=os.environ.get("SCENARIO_STORAGE_DIR", "scenarios"),
        sessions_dir=os.environ.get("SCENARIO_SESSIONS_DIR", "sessions"),
    )

    # Create LLMClient
    if llm_mode == LLMMode.PIPER:
        llm_client = PiperLLMAdapter(
            piper_repo_dir=os.environ.get("PIPER_REPO_DIR"),
            config={
                "base_url": os.environ.get("SCENARIO_LLM_BASE_URL"),
                "model": os.environ.get("SCENARIO_LLM_MODEL"),
                "timeout_seconds": os.environ.get("SCENARIO_LLM_TIMEOUT_SECONDS"),
            },
        )
        LOG.info("ScenarioLab piper mode configured for %s model=%s timeout=%ss", llm_client.base_url, llm_client.model, llm_client.timeout_seconds)
    else:
        llm_client = LLMClient(mode=llm_mode)

    # Create ScenarioEngine
    engine = ScenarioEngine(storage=storage, llm_client=llm_client)

    # Auto-load tiny_fantasy_sample on startup
    try:
        await engine.load_scenario("tiny_fantasy_sample")
    except Exception as e:
        LOG.warning("Could not auto-load tiny_fantasy_sample: %s", e)

    # Store engine as app.state.engine
    app.state.engine = engine
    app.state.llm_mode = llm_client.mode.value

    yield

    # Shutdown (nothing to clean up)


# ---------------------------------------------------------------------------
# FastAPI App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PiperScenarioLab",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API Models
# ---------------------------------------------------------------------------

class NewScenarioRequest(BaseModel):
    scenario_id: str


class LoadScenarioRequest(BaseModel):
    scenario_id: str
    session_id: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_engine(request: Request) -> ScenarioEngine:
    return request.app.state.engine


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/scenarios", response_model=ScenariosListResponse)
async def list_scenarios(request: Request):
    """List scenario files with id and title."""
    engine = _get_engine(request)
    scenarios = engine.storage.list_scenarios()
    return ScenariosListResponse(scenarios=scenarios)


@app.post("/api/scenario/new", response_model=APIResponse)
async def new_scenario(request: Request, body: NewScenarioRequest):
    """Start a new scenario session. Returns success, session_id, and scenario metadata."""
    engine = _get_engine(request)
    try:
        await engine.new_scenario(body.scenario_id)
        state = engine.get_state()
        return APIResponse(
            success=True,
            data={
                "session_id": engine.session_id,
                "scenario": state.scenario.model_dump(mode="json") if state.scenario else None,
            },
            message=f"New session started with scenario '{body.scenario_id}'",
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scenario '{body.scenario_id}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scenario/load", response_model=APIResponse)
async def load_scenario(request: Request, body: LoadScenarioRequest):
    """Load a scenario (optionally into an existing session). Returns success, session_id, and state."""
    engine = _get_engine(request)
    try:
        if body.session_id:
            engine.session_id = body.session_id
        await engine.load_scenario(body.scenario_id)
        state = engine.get_state()
        return APIResponse(
            success=True,
            data={
                "session_id": engine.session_id,
                "state": state.model_dump(mode="json"),
            },
            message=f"Scenario '{body.scenario_id}' loaded",
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Scenario '{body.scenario_id}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/state", response_model=SessionStateResponse)
async def get_state(request: Request):
    """Return current engine state."""
    engine = _get_engine(request)
    if not engine.scenario:
        raise HTTPException(status_code=400, detail="No scenario loaded")
    return engine.get_state()


@app.post("/api/turn", response_model=TurnResult)
async def take_turn(request: Request, body: TurnInput):
    """Take a turn with user input. Returns TurnResult with narration, dialogue, state delta, and options."""
    engine = _get_engine(request)
    if not engine.scenario:
        raise HTTPException(status_code=400, detail="No scenario loaded")
    try:
        result = await engine.take_turn(body)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reset", response_model=APIResponse)
async def reset(request: Request):
    """Reset engine to initial scenario state."""
    engine = _get_engine(request)
    if not engine.scenario:
        raise HTTPException(status_code=400, detail="No scenario loaded")
    try:
        await engine.reset()
        state = engine.get_state()
        return APIResponse(
            success=True,
            data=state.model_dump(mode="json"),
            message="Engine reset to initial state",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/session/log")
async def get_session_log(request: Request):
    """Return session log entries."""
    engine = _get_engine(request)
    try:
        log = engine.get_session_log()
        return [entry.model_dump(mode="json") for entry in log]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mode")
async def get_mode(request: Request):
    """Return current LLM mode."""
    return {"mode": request.app.state.llm_mode}


# ---------------------------------------------------------------------------
# Static Files
# ---------------------------------------------------------------------------

# Determine the correct path for the web directory
WEB_DIR = Path(__file__).parent / "web"
if not WEB_DIR.exists():
    WEB_DIR = Path("web")

app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="static")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger(__name__)
