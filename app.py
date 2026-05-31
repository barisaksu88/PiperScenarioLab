"""PiperScenarioLab - FastAPI application."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from scenario_lab_config import FRONTEND_DIST_DIR
from scenario_engine.engine import ScenarioEngine
from scenario_engine.llm_client import LLMClient, LLMMode, PiperLLMAdapter
from scenario_engine.models import (
    APIResponse,
    ScenariosListResponse,
    SessionLogEntry,
    SessionStateResponse,
    TurnInput,
    TurnResult,
)
from scenario_engine.scenario_generator import ScenarioGenerator
from scenario_engine.storage import Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Startup / Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create storage, LLM client, engine, and auto-load scenario."""
    llm_mode_str = os.environ.get("SCENARIO_LLM_MODE", "mock").lower()
    try:
        llm_mode = LLMMode(llm_mode_str)
    except ValueError:
        llm_mode = LLMMode.MOCK
        llm_mode_str = LLMMode.MOCK.value

    storage = Storage(
        scenarios_dir=os.environ.get("SCENARIO_STORAGE_DIR", "scenarios"),
        sessions_dir=os.environ.get("SCENARIO_SESSIONS_DIR", "sessions"),
    )

    llm_config = {
        "base_url": os.environ.get("SCENARIO_LLM_BASE_URL", "http://127.0.0.1:8081"),
        "model": os.environ.get("SCENARIO_LLM_MODEL", "qwen"),
        "timeout_seconds": float(os.environ.get("SCENARIO_LLM_TIMEOUT_SECONDS") or 120.0),
    }

    if llm_mode == LLMMode.PIPER:
        llm_client = PiperLLMAdapter(
            piper_repo_dir=os.environ.get("PIPER_REPO_DIR"),
            config=llm_config,
        )
        LOG.info(
            "ScenarioLab piper mode configured for %s model=%s timeout=%ss",
            llm_client.base_url,
            llm_client.model,
            llm_client.timeout_seconds,
        )
    else:
        llm_client = LLMClient(mode=llm_mode)

    engine = ScenarioEngine(storage=storage, llm_client=llm_client)

    # Try to restore the most recent session, otherwise fall back to tiny_fantasy_sample
    sessions = storage.list_sessions()
    if sessions:
        # Sort by updated_at descending to get the most recent
        most_recent = sorted(sessions, key=lambda s: s.get("updated_at", ""), reverse=True)[0]
        try:
            await engine.load_session(most_recent["session_id"])
            LOG.info("Restored session %s (scenario: %s)", most_recent["session_id"], most_recent.get("scenario_id", "unknown"))
        except Exception as e:
            LOG.error("Could not restore session %s: %s", most_recent["session_id"], e)
            # Do not silently fall back to sample when a session exists but failed to load.
            # The user expects to continue their saved game; a fallback would be confusing.
    else:
        try:
            await engine.load_scenario("tiny_fantasy_sample")
        except Exception as e:
            LOG.warning("Could not auto-load tiny_fantasy_sample: %s", e)

    app.state.engine = engine
    app.state.llm_mode = llm_client.mode.value
    app.state.llm_config = llm_config

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


class LoadSessionRequest(BaseModel):
    session_id: str


class DeleteSessionRequest(BaseModel):
    session_id: str


class GenerateScenarioRequest(BaseModel):
    title_hint: str = ""
    genre: str = "fantasy"
    length: str = "short"
    difficulty: str = "medium"
    tone: str = "mysterious"
    theme: str = ""


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


@app.post("/api/scenario/generate", response_model=APIResponse)
async def generate_scenario(request: Request, body: GenerateScenarioRequest):
    """Generate a new scenario using the LLM and save it to disk."""
    cfg = request.app.state.llm_config
    generator = ScenarioGenerator(
        base_url=cfg["base_url"],
        model=cfg["model"],
        timeout_seconds=cfg["timeout_seconds"],
    )
    try:
        scenario = await generator.generate(
            title_hint=body.title_hint,
            genre=body.genre,
            length=body.length,
            difficulty=body.difficulty,
            tone=body.tone,
            theme=body.theme,
        )
        # Save to scenarios dir
        scenarios_dir = Path(os.environ.get("SCENARIO_STORAGE_DIR", "scenarios"))
        scenarios_dir.mkdir(parents=True, exist_ok=True)
        # Create safe filename from title
        safe_title = "".join(c if c.isalnum() else "_" for c in scenario.metadata.title).lower()
        if not safe_title:
            safe_title = "generated_scenario"
        scenario_id = safe_title
        path = scenarios_dir / f"{scenario_id}.json"
        # If file exists, append a number
        counter = 1
        original_id = scenario_id
        while path.exists():
            scenario_id = f"{original_id}_{counter}"
            path = scenarios_dir / f"{scenario_id}.json"
            counter += 1
        path.write_text(scenario.model_dump_json(indent=2), encoding="utf-8")
        return APIResponse(
            success=True,
            data={"scenario_id": scenario_id, "title": scenario.metadata.title},
            message=f"Generated scenario '{scenario.metadata.title}' saved as {scenario_id}.json",
        )
    except Exception as e:
        LOG.exception("Scenario generation failed")
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


@app.get("/api/sessions")
async def list_sessions(request: Request):
    """List saved sessions."""
    engine = _get_engine(request)
    return engine.storage.list_sessions()


@app.post("/api/session/save", response_model=APIResponse)
async def save_session(request: Request):
    """Explicitly save the current session state."""
    engine = _get_engine(request)
    if not engine.scenario:
        raise HTTPException(status_code=400, detail="No scenario loaded")
    try:
        session_state = engine._build_session_state_dict()
        engine.storage.save_session(engine.session_id, session_state)
        return APIResponse(
            success=True,
            data={"session_id": engine.session_id},
            message="Session saved",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/session/load", response_model=APIResponse)
async def load_session(request: Request, body: LoadSessionRequest):
    """Load a previously saved session and continue where it left off."""
    engine = _get_engine(request)
    try:
        await engine.load_session(body.session_id)
        state = engine.get_state()
        return APIResponse(
            success=True,
            data={
                "session_id": engine.session_id,
                "state": state.model_dump(mode="json"),
            },
            message="Session loaded",
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{body.session_id}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/session/delete", response_model=APIResponse)
async def delete_session(request: Request, body: DeleteSessionRequest):
    """Delete a saved session and its log."""
    engine = _get_engine(request)
    try:
        deleted = engine.storage.delete_session(body.session_id)
        return APIResponse(
            success=deleted,
            message="Session deleted" if deleted else "Session not found",
        )
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

WEB_DIR = FRONTEND_DIST_DIR if FRONTEND_DIST_DIR.exists() else (Path(__file__).parent / "web")
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="static")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
