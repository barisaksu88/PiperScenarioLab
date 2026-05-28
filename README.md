# PiperScenarioLab

A standalone, reusable scenario / roleplay / training engine built with FastAPI, Pydantic v2, and a mock-capable LLM client.

This project is intentionally separate from `C:\Projects\Piper`. It is a lab repo, not a direct Piper feature branch.

## What This Is

PiperScenarioLab is a **standalone reusable scenario/roleplay/training engine** that is:

- **JSON/Pydantic state-driven** -- scenario definitions are validated JSON files that deserialize into a tree of Pydantic models (acts, scenes, NPCs, items, skills, objectives, player state).
- **LLM narrates but Python validates** -- the LLM generates narrative text, NPC dialogue, and proposed state changes, but every proposed `StateDelta` is validated by a `Validator` before it touches game state. This prevents hallucinated items, impossible scene jumps, and invalid flags.
- **Profile-based** -- different scenario types (fantasy, flight training, medical sim, etc.) are supported via pluggable profiles with custom validation rules, UI labels, prompt templates, and state extensions.
- **NPC / actor system** -- NPCs carry persona cards (voice, motives, fears, temperament), relationship values that shift based on player actions, trigger conditions, and dialogue that is processed and validated separately from narration.
- **Anti-hallucination guard** -- the `Validator` checks every state delta against the scenario definition: items must exist, scenes must be connected, skills must be defined, and relationship values are clamped to [-100, 100].

## What This Is Not

- **Not D&D-only** -- the engine is generic; the included `fantasy_tiny` profile is just one example.
- **Not a combat sim** -- no combat system, dice rolls, or HP mechanics are included.
- **Not a flight simulator** -- the `flight_training` profile is a placeholder demonstrating extension points.
- **Not certified training** -- this is experimental software. Do not use for safety-critical training without review and certification.
- **Not a Piper integration (yet)** -- the Piper LLM adapter is a thin wrapper with a mock fallback. Real Piper integration is a future step.

## Architecture

The engine follows a strict turn loop:

```
User Input -> Load State -> Select Actors -> Build Prompt -> LLM Proposal
  -> Parse -> Validate -> Apply -> Save -> Return TurnResult
```

### Core Engine Loop

1. Load current scenario state
2. Select relevant NPCs/actors for the turn (rule-based, no LLM call)
3. Build a structured prompt with scene context, player state, and NPC persona cards
4. Ask the LLM for a `TurnProposal` (narration + dialogue + state delta + next options)
5. Parse the LLM response into Pydantic models
6. Repair invalid JSON if needed (extraction, schema repair, minimal fallback)
7. **Validate** every proposed state change against the scenario definition
8. Apply only accepted changes to player state, NPCs, inventory, flags, etc.
9. Save session state and append a log entry
10. Return a `TurnResult` with full turn data for the UI

### State Delta Validation

The `Validator` is the anti-hallucination layer. It checks:
- **Inventory**: items must be defined in `scenario.items` (unless profile allows dynamic creation)
- **Scene moves**: target scene must exist and be connected to the current scene
- **Clue reveals**: clue must be present in the current scene or in a present NPC's `can_reveal` list
- **Skill grants**: skills must be defined in `scenario.skills`
- **Objective completion**: required flags/clues must be met
- **Relationship bounds**: values clamped to [-100, 100]
- **NPC status changes**: target NPC must exist
- **Act progression**: flags referencing unknown acts produce warnings

Invalid changes are rejected individually; valid changes in the same proposal are still applied (partial acceptance).

### Profile System

Profiles define scenario-type-specific behavior:
- `FantasyTinyProfile` -- fantasy RPG with dynamic flag creation
- `FlightTrainingProfile` -- placeholder for aviation training with aircraft/weather/grading extensions

Each profile provides: validation rules, prompt templates, UI labels, and state extensions.

### NPC / Actor Layer

NPCs are rich data objects:
- **Persona card**: voice, motives, fears, temperament, speech style
- **Relationship matrix**: trust, fear, hostility, respect (all [-100, 100])
- **Knowledge**: what the NPC knows and what they can reveal
- **Triggers**: conditions (based on flags) that activate behavior
- **Status**: available, unavailable, hostile, dead

The `ActorSelector` chooses NPCs based on scene presence, name mentions in input, and trigger conditions. The `DialogueManager` validates and enriches dialogue lines, filters dead/unavailable NPCs, and fills in missing fields.

## Quick Start

```bash
# cd into the project directory
cd PiperScenarioLab

# Install dependencies
pip install -r requirements.txt

# Run in mock mode (no external LLM needed)
SCENARIO_LLM_MODE=mock python app.py

# Open the web UI
http://localhost:8000
```

### Windows

```cmd
cd PiperScenarioLab
pip install -r requirements.txt
set SCENARIO_LLM_MODE=mock && python app.py
```

Then open http://localhost:8000 in your browser.

## One-Command Launch

Recommended entrypoint:

```cmd
C:\Projects\Piper\.venv\Scripts\python.exe launcher.py
```

What the launcher does:

1. Resolves runtime config, including Piper config values when available.
2. Creates a timestamped debug run folder under `data/debug/runs/`.
3. Rebuilds the frontend from `web_ui/frontend/` on every launch.
4. Starts the FastAPI backend.
5. Opens a desktop window with `pywebview` when available, otherwise falls back to the default browser.
6. Writes launcher, backend, frontend build, and optional LLM debug artifacts for the current run.

## Using Piper's venv

If you are working within the Piper codebase:

```cmd
C:\Projects\Piper\.venv\Scripts\python.exe -m pip install -r requirements.txt
C:\Projects\Piper\.venv\Scripts\python.exe app.py
```

Or on PowerShell:

```powershell
& "C:\Projects\Piper\.venv\Scripts\python.exe" -m pip install -r requirements.txt
$env:SCENARIO_LLM_MODE="mock"; & "C:\Projects\Piper\.venv\Scripts\python.exe" app.py
```

## Piper Adapter Seam

This lab does not import or depend on Piper by default.

The nearest current Piper integration seam is:

- `C:\Projects\Piper\llm\llm_server_client.py`
- `LlamaServerClient.generate(messages, ...)`
- `LlamaServerConfig(...)`

The intended next step is to convert a scenario turn prompt into Piper-style chat `messages`, call `LlamaServerClient.generate(...)`, parse the returned text as `TurnProposal`, and keep the existing repair/validation path unchanged.

Today, `SCENARIO_LLM_MODE=piper` is safe but conservative:

- if a compatible Piper client seam is discoverable, the adapter records that seam for future wiring
- if not, it falls back to mock mode instead of crashing

## Local LLM Mode

`SCENARIO_LLM_MODE=piper` uses a local HTTP backend that speaks the OpenAI-compatible `/v1/chat/completions` shape.

Environment variables:

- `SCENARIO_LLM_BASE_URL` - default `http://127.0.0.1:8080`
- `SCENARIO_LLM_MODEL` - default `qwen`
- `SCENARIO_LLM_TIMEOUT_SECONDS` - default `30`
- `SCENARIO_DEBUG_LLM=1` - emit prompt length, raw output, parsed proposal, and validator rejection diagnostics
- `SCENARIO_AUTO_START_LLM=true|false` - control whether launcher starts `llama-server` automatically in `piper` mode
- `SCENARIO_ALLOW_LLM_FALLBACK=true|false` - allow backend startup to continue if local LLM auto-start fails
- `SCENARIO_WINDOW_ENABLED=true|false` - control desktop window/browser launch
- `SCENARIO_REBUILD_FRONTEND_ON_BOOT=true|false` - control frontend rebuild on every launch

### Manual smoke

Start your local `llama-server` or Piper-backed local LLM on the configured base URL, then run:

```cmd
set SCENARIO_LLM_MODE=piper
set SCENARIO_LLM_BASE_URL=http://127.0.0.1:8080
set SCENARIO_LLM_MODEL=qwen
set SCENARIO_LLM_TIMEOUT_SECONDS=30
C:\Projects\Piper\.venv\Scripts\python.exe app.py
```

Send one turn:

```bash
curl -s -X POST http://127.0.0.1:8000/api/turn ^
  -H "Content-Type: application/json" ^
  -d "{\"user_input\":\"Look around the village square\"}"
```

Expected output shape:

- `narration` is a string
- `npc_dialogue` is a list of dialogue objects
- `state_delta` is a JSON object
- `validation.accepted_delta` contains only legal changes
- `validation.rejected_changes` records anything the validator rejected

### Debug Artifacts

Latest run pointer:

- `data/debug/latest_run.txt`

Per-run artifacts:

- `launcher.log`
- `backend.log`
- `frontend_build.log`
- `env_snapshot.json`
- `resolved_config.json`
- `session_snapshot_initial.json`
- `session_snapshot_latest.json`
- `llama_server.log` when ScenarioLab starts the server itself
- `llm_http_payload_debug.jsonl` and other LLM debug files when `SCENARIO_DEBUG_LLM=1`

To review the last run, open the folder listed in `data/debug/latest_run.txt`.

## Running Tests

```bash
pytest tests/ -v
```

Windows with Piper's venv:

```cmd
C:\Projects\Piper\.venv\Scripts\python.exe -m pytest tests\ -v
```

## Verification Notes

Verified in this standalone repo with `C:\Projects\Piper\.venv\Scripts\python.exe`:

- `pytest tests/ -v` passes with all 28 tests green
- `SCENARIO_LLM_MODE=mock` serves the web UI and API locally
- free-text and option-button turns both update scenario state
- session logs are written under `sessions/`
- `SCENARIO_LLM_MODE=piper` starts safely without requiring Piper integration to be finished
- `SCENARIO_LLM_MODE=piper` now targets a local OpenAI-compatible endpoint and falls back cleanly if it cannot connect
- launcher-based boot attempts frontend rebuild and backend startup on every run

## Troubleshooting

- `npm missing`: install Node.js so `npm.cmd` is available on Windows PATH.
- `pywebview missing`: the launcher falls back to the default browser.
- `llama-server not found`: set `SCENARIO_LLAMA_SERVER_EXE` or make sure Piper config points to a valid exe.
- `model path not found`: set `SCENARIO_MODEL_PATH` or ensure Piper config points to a valid model file.
- `port already in use`: stop the existing process or change `SCENARIO_PORT`.
- `browser shows 0.0.0.0`: use the launcher URL from `http://127.0.0.1:<port>/` instead of binding host values.

This runs:
- `test_models.py` -- Pydantic model validation, bounds, defaults, JSON parsing
- `test_validator.py` -- State delta validation (accept, reject, clamp, partial)
- `test_engine_mock.py` -- Full engine integration with mock LLM (load, turn, dialogue, state, log, reset)

## Engine Loop

```
+------------+    +-------------+    +---------------+    +-------------+
| User Input | -> | Load State  | -> | Select Actors | -> | Build Prompt|
+------------+    +-------------+    +---------------+    +------+------+
                                                                  |
+----------------+    +----------+    +---------+    +-----------v-----------+
| Return Result  | <- |   Save   | <- |  Apply  | <- |  Validate Delta       |
| (TurnResult)   |    |  State   |    |  Delta  |    | (accept/reject/clamp) |
+----------------+    +----------+    +---------+    +-----------+-----------+
                                                          ^
+----------------+    +----------+    +-----------------+-----------------+
|  Log Entry     | <- |  Parse   | <- | LLM Proposal (TurnProposal JSON)    |
|  (append)      |    |  JSON    |    |                                     |
+----------------+    +----------+    +-----------------+-----------------+
                                                        |
                                               +--------v--------+
                                               |   Repair if     |
                                               |   invalid       |
                                               +-----------------+
```

## Project Structure

```
PiperScenarioLab/
  app.py                          # FastAPI entry point + static file serving
  README.md                       # This file
  requirements.txt                # Python dependencies

  scenario_engine/                # Core engine package
    __init__.py                   # Public exports
    models.py                     # All Pydantic v2 models
    engine.py                     # ScenarioEngine -- main turn coordinator
    validator.py                  # StateDelta validation (anti-hallucination)
    storage.py                    # JSON load/save for scenarios and sessions
    llm_client.py                 # LLM adapter (mock + Piper wrapper)
    repair.py                     # JSON repair and fallback for bad LLM output
    actor_selector.py             # Rule-based NPC selection
    dialogue.py                   # Dialogue validation and formatting
    profile_base.py               # Abstract base class for profiles

  profiles/                       # Scenario-type profiles
    fantasy_tiny/                 # Fantasy RPG profile (tested)
      __init__.py
      profile.py                  # FantasyTinyProfile
      prompts/                    # Prompt templates
        scenario_builder.txt
        scenario_repair.txt
        narrator_turn.txt
        turn_repair.txt
        npc_dialogue.txt

    flight_training/              # Flight training profile (placeholder)
      __init__.py
      profile.py                  # FlightTrainingProfile
      prompts/
        placeholder.txt

  scenarios/                      # Scenario definition JSON files
    tiny_fantasy_sample.json      # Fantasy demo scenario (3 acts, 2 NPCs, 4 scenes)
    tiny_flight_placeholder.json  # Flight placeholder scenario

  sessions/                       # Saved session state + logs
    .gitkeep

  web/                            # Static web UI
    index.html                    # Main layout
    style.css                     # Low-saturation dark/light theme
    app.js                        # Frontend logic

  tests/                          # pytest suite
    __init__.py
    test_models.py                # Pydantic model tests
    test_validator.py             # Validator logic tests
    test_engine_mock.py           # Engine integration tests (mock LLM)
```

## NPC / Actor System

### Persona Cards

Each NPC carries a full persona used to build LLM prompts:

```
--- NPC PERSONAS ---
Mara (Bellkeeper): Speaks slowly, chooses words carefully. Uses village proverbs.
Motives: protect the village, uncover the truth about the bell
Fears: the seal breaking, losing trust of the villagers
Knows: bell_history, the_seal, old_tracks
Can reveal: old_tracks, ash_symbol

Eldric (Mayor): Speaks like a politician. Deflects questions. Overly formal.
Motives: maintain control, hide the truth
Fears: exposure, losing authority
--- END NPC PERSONAS ---
```

### Relationship Values

Relationships are a 4-dimensional vector per NPC:
- **Trust** [-100, 100]
- **Fear** [-100, 100]
- **Hostility** [-100, 100]
- **Respect** [-100, 100]

Changes are additive and clamped to [-100, 100].

### Triggers

NPC triggers are condition/effect pairs evaluated each turn:
- Condition `"met_mara=true"` activates when that flag is set
- Effects are descriptive strings consumed by the LLM prompt

### Dialogue Separation

Dialogue is **never** embedded in narration text. It is returned as a separate array of `DialogueLine` objects with `speaker_id`, `speaker_name`, `role`, `tone`, `text`. The UI renders dialogue as cards with speaker header, tone tag, and quoted text.

## Validator

The `Validator` is the anti-hallucination guard. It ensures the LLM cannot:

| Check | What It Does |
|-------|-------------|
| **Inventory** | Rejects items not in `scenario.items` unless profile allows dynamic creation |
| **Scene Move** | Rejects moves to nonexistent or unconnected scenes |
| **Clue Reveal** | Rejects clues not in current scene or not in a present NPC's `can_reveal` |
| **Skill Grant** | Rejects skills not in `scenario.skills` unless profile allows dynamic creation |
| **Objective** | Rejects completion unless required flags and clues are met |
| **Relationship** | Clamps trust/fear/hostility/respect to [-100, 100] |
| **NPC Status** | Rejects status changes to nonexistent NPCs |
| **Act Progression** | Warns on flags referencing unknown acts |

### Partial Acceptance

The validator processes each change type independently. A single `TurnProposal` can have valid changes accepted and invalid changes rejected. The accepted changes are applied; rejected changes are recorded in `ValidationResult.rejected_changes` with reasons.

## Profiles

### fantasy_tiny (tested)

A small fantasy RPG scenario used for integration testing:
- **3 acts**: Village Arrival, The Investigation, What Lies Beneath
- **2 NPCs**: Mara (Bellkeeper), Eldric (Mayor)
- **4 scenes**: Village Square, Bell Tower, Mayor's Office, Hilltop Ruins
- **1 artifact**: Cracked Silver Medallion
- **2 skills**: Perception, Persuasion
- **Dynamic flags allowed**

### flight_training (placeholder)

A placeholder demonstrating non-fantasy profile extension:
- Extension fields: aircraft, phase_of_flight, weather, failures, checklists, ATC comms, grading
- Stricter validation: no dynamic creation allowed
- Different UI labels: Phases, Situations, Crew / ATC, Systems, Procedures, Indications

### Adding a New Profile

1. Create a directory under `profiles/your_profile/`
2. Subclass `ProfileBase` in `profile.py`
3. Implement all abstract methods
4. Add prompt templates in `prompts/`
5. Create a scenario JSON in `scenarios/`
6. The engine auto-detects scenarios by filename

## Future Piper Integration

The engine is designed for minimal rewrite when integrating with Piper:

- **Adapter pattern**: `PiperLLMAdapter` subclasses `LLMClient` with the same interface
- **Graceful fallback**: if Piper's LLM module is not importable, falls back to mock mode
- **Single point of contact**: only `llm_client.py` needs Piper-specific code
- **State is JSON-serializable**: Piper can read/write session state without understanding Pydantic

To wire Piper: implement `_generate_turn_piper()` to call Piper's LLM client, pass the persona prompt + scenario context, and parse the response into `TurnProposal.model_validate()`. No changes needed to `engine.py`, `validator.py`, `storage.py`, or `models.py`.

## Future Flight Training

Extension points for building a real flight training module:

| Extension | Where to Add |
|-----------|-------------|
| Aircraft state | `FlightTrainingProfile.get_state_extensions()` |
| Weather data | `FlightTrainingProfile.get_state_extensions()` |
| Failure injection | Scenario JSON `extensions` field |
| Checklist procedures | New model: `ChecklistItem` in `models.py` |
| ATC phraseology | Custom prompt template in `profiles/flight_training/prompts/` |
| Grading / scoring | New validator method or post-turn hook |
| Simulator integration | New adapter class in `scenario_engine/` |

## Known Limitations

- **Mock mode only**: no real LLM integration is currently wired; mock cycles through 5 canned responses
- **No real LLM yet**: Piper adapter is a stub with graceful fallback
- **No combat**: no HP, dice, damage, or combat actions
- **No dice**: no randomness mechanics
- **No memory**: engine does not persist LLM context across turns beyond scenario state
- **No voice**: no text-to-speech or speech-to-text
- **No images**: no image generation or display
- **Flight profile is placeholder**: no real procedures, no simulator connection, no authoritative training content

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/scenarios` | List available scenarios |
| `POST` | `/api/scenario/new` | Start a new scenario session |
| `POST` | `/api/scenario/load` | Load a scenario into an existing session |
| `GET` | `/api/state` | Get current session state |
| `POST` | `/api/turn` | Submit a player turn |
| `POST` | `/api/reset` | Reset to initial scenario state |
| `GET` | `/api/session/log` | Get full session log |

The web UI is served at `/` from the `web/` directory.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCENARIO_LLM_MODE` | `mock` | LLM backend: `mock` or `piper` |
| `SCENARIO_STORAGE_DIR` | `scenarios` | Directory for scenario definition JSON files |
| `SCENARIO_SESSIONS_DIR` | `sessions` | Directory for saved session state and logs |

## Tech Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.10+ | Runtime |
| FastAPI | >=0.104 | Web framework + API endpoints |
| Uvicorn | >=0.24 | ASGI server |
| Pydantic v2 | >=2.5 | Data validation and serialization |
| pytest | >=7.4 | Test framework |
| pytest-asyncio | >=0.21 | Async test support |
| python-multipart | >=0.0.6 | Form parsing (FastAPI dependency) |
| HTML/CSS/JS | Vanilla | Frontend (no build step) |
