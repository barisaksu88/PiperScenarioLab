# Piper Scenario Engine — Design Document

## 1. Purpose

This document defines the intended architecture, scope, and direction for the standalone **Piper Scenario Engine** project.

The purpose is to prevent drift. The feature must not collapse into a simple DND toy, a loose chatbot mode, or a pile of hard-coded roleplay tricks. It should become a reusable scenario engine that can power fantasy roleplay, DND-like adventures, flight training scenarios, detective simulations, survival scenarios, procedural decision training, and other interactive simulations.

The short version:

> Piper should be able to run structured interactive scenarios where the model narrates and performs characters, but the actual world state is controlled by validated JSON/Pydantic state.

The model may create atmosphere, dialogue, consequences, options, and proposed changes. It must not directly rewrite reality.

---

## 2. Bottom Line

The core design principle is:

> **The LLM narrates and proposes. Python validates and applies. JSON/Pydantic state is the source of truth.**

This means:

- The model does not directly mutate game/training state.
- Scenario state lives in structured JSON.
- Pydantic schemas define valid state shape.
- The validator decides which proposed changes are legal.
- The UI displays state from JSON, not from freeform narration.
- NPCs/actors have structured persona cards so they remain consistent.
- Scenario profiles define genre-specific behavior without polluting the base engine.

The first test scenario can be a tiny DND/fantasy scenario, but the architecture must remain generic.

---

## 3. End Goal

The long-term goal is to create a **general-purpose Piper Scenario Engine** that can later be integrated into Piper as a mode.

Examples of future use:

### Fantasy / DND-like roleplay

The user enters a village, talks to NPCs, gains items, discovers clues, unlocks acts, and reaches one of several endings.

### Flight training scenario

The user activates a realistic aviation scenario. Piper presents a phase of flight, weather, aircraft state, failures, cabin reports, ATC responses, and evaluates the user’s decisions against validated procedure/checklist logic.

### Detective scenario

The user investigates a case. NPCs know different information, clues must be discovered legally, contradictions can be detected, and the case resolves based on gathered evidence.

### Survival scenario

The user manages resources, injuries, time, weather, shelter, morale, and navigation decisions.

### Custom roleplay

The user describes a scenario and Piper builds a structured simulation with acts, scenes, NPCs, objectives, items, clues, and possible outcomes.

The engine should eventually become Piper’s “holodeck”: a structured interactive world with rules, memory, actors, consequences, and UI feedback.

---

## 4. What This Is Not

This project is not:

- A DND-only app.
- A combat simulator.
- A dice engine first.
- A visual novel only.
- A freeform chatbot with extra flavor text.
- A flight simulator.
- A replacement for certified training material.
- A Piper integration in v0.1.
- A voice, image, memory, or avatar feature in v0.1.

The first implementation should stay deliberately small, boring, and testable.

---

## 5. Project Strategy

The first version should be built outside Piper as a standalone lab:

```text
C:\Projects\PiperScenarioLab\
```

It should use Piper’s existing Python venv where possible, so dependencies are not duplicated.

Example run approach:

```powershell
cd C:\Projects\PiperScenarioLab
C:\Projects\Piper\.venv\Scripts\python.exe -m pip install -r requirements.txt
set SCENARIO_LLM_MODE=mock
C:\Projects\Piper\.venv\Scripts\python.exe app.py
```

The first milestone is not “perfect roleplay.”

The first milestone is:

> Prove that the engine loop, JSON state, validator, mock LLM, storage, and UI work end-to-end.

Once that is stable, a real local LLM adapter can be added.

---

## 6. Recommended Initial Folder Structure

```text
PiperScenarioLab/
  app.py
  README.md
  requirements.txt

  scenario_engine/
    __init__.py
    models.py
    engine.py
    validator.py
    storage.py
    llm_client.py
    repair.py
    actor_selector.py
    dialogue.py
    profile_base.py

  profiles/
    fantasy_tiny/
      __init__.py
      profile.py
      prompts/
        scenario_builder.txt
        scenario_repair.txt
        narrator_turn.txt
        turn_repair.txt
        npc_dialogue.txt

    flight_training/
      __init__.py
      profile.py
      prompts/
        placeholder.txt

  scenarios/
    tiny_fantasy_sample.json
    tiny_flight_placeholder.json

  sessions/
    .gitkeep

  web/
    index.html
    style.css
    app.js

  tests/
    test_models.py
    test_validator.py
    test_engine_mock.py
```

This structure separates the reusable engine from scenario-specific profiles.

---

## 7. Core Architecture

The project should be composed of these main layers:

### 7.1 Scenario Engine

The scenario engine coordinates the full turn cycle.

Responsibilities:

- Load scenario/session state.
- Receive user input.
- Determine active/relevant actors.
- Build the prompt for the LLM or mock LLM.
- Parse the returned `TurnProposal`.
- Validate proposed state changes.
- Apply legal changes.
- Save updated state.
- Return a `TurnResult` to the UI.

The engine should not contain hard-coded fantasy, DND, or aviation assumptions.

### 7.2 Pydantic Models

Pydantic models define valid state shape.

They should cover:

- Scenario
- ScenarioMetadata
- ScenarioProfile
- PlayerState
- Act
- Scene / Location
- Objective
- NPC
- NPCPersona
- NPCRelationship
- NPCTrigger
- DialogueLine
- Item / Artifact
- Skill / Perk
- FlagState
- TurnInput
- TurnProposal
- StateDelta
- TurnResult
- ValidationResult
- SessionLogEntry

Pydantic is important because it gives:

- Type safety.
- JSON validation.
- Structured serialization.
- Cleaner repair workflows.
- Better integration with prompts and tests.

### 7.3 Validator

The validator is the anti-hallucination guard.

It decides whether proposed state changes are legal.

Examples:

- Reject adding an item that does not exist in the scenario.
- Reject moving to a nonexistent scene.
- Reject revealing a clue the current NPC/location cannot reveal.
- Reject completing an objective before requirements are met.
- Clamp relationship changes within allowed bounds.
- Reject granting skills/perks unless they are listed or dynamically allowed by the profile.
- Reject act progression unless completion conditions are satisfied.

The validator may:

- Fully accept a state delta.
- Partially accept legal changes and reject illegal ones.
- Return warnings.
- Request a repaired proposal.

The validator should produce useful error messages so debugging is easy.

### 7.4 Storage Layer

Storage should use JSON files in v0.1.

Suggested layout:

```text
scenarios/*.json
sessions/*.json
```

Scenario files are definitions/templates.

Session files are active playthroughs.

A session log should preserve:

- Timestamp.
- User input.
- Narration.
- NPC dialogue.
- Accepted state changes.
- Rejected state changes.
- Validator warnings.
- Generated options.

This allows later replay, debugging, grading, and memory integration.

### 7.5 LLM Client Adapter

The engine should call the LLM through an adapter interface.

Required modes:

```text
SCENARIO_LLM_MODE=mock
SCENARIO_LLM_MODE=piper
```

v0.1 must run in mock mode without any real model.

The future Piper mode should connect to Piper’s existing local LLM client or model stack with minimal rewrite.

The adapter should make it easy to swap:

- Mock LLM.
- Piper local model.
- llama.cpp server.
- Future local inference backend.

The engine should not care which backend is used.

---

## 8. Scenario Profiles

The base engine must remain generic.

Scenario-specific rules belong in profiles.

Examples:

```text
profiles/fantasy_tiny/
profiles/flight_training/
profiles/detective/
profiles/survival/
```

A profile should define:

- `profile_id`
- Display name
- Prompt template paths
- Allowed dynamic creation rules
- Validation extensions
- UI labels/preferences
- Profile-specific state extensions
- Optional default scenario builder logic

### 8.1 Fantasy Tiny Profile

The first implementation should include a tiny fantasy/DND-like profile.

Recommended scope:

- 2–3 acts.
- 2 NPCs.
- 2–3 locations.
- 1 artifact.
- 2 skills/perks.
- 3 clues/objectives.
- Simple NPC relationship changes.
- No complex combat system.
- No dice system unless extremely minimal and isolated.

The purpose is to test the engine, not build full DND.

### 8.2 Flight Training Placeholder Profile

A placeholder flight training profile should be created, but not fully implemented yet.

It should include schema extension points for:

- Aircraft.
- Phase of flight.
- Weather.
- Failures.
- ATC actor.
- Cabin crew actor.
- Dispatch/company actor.
- ECAM/checklist placeholders.
- Objectives.
- Grading/assessment hooks.

It should not encode real proprietary SOPs or pretend to be authoritative.

It should make clear that verified procedures will later be plugged in by the user.

The reason to add this placeholder early is to prevent the base engine from becoming fantasy-only.

---

## 9. NPC / Actor System

The engine should treat NPCs and scenario actors as first-class objects.

Most scenarios will need them.

Examples:

- A DND vendor who becomes hostile because the player insults him.
- A fantasy companion hiding information.
- A guard blocking access to a location.
- A cabin crew member reporting smoke or fire.
- ATC responding to an emergency request.
- Dispatch giving operational information.
- A doctor, mechanic, investigator, passenger, mayor, witness, hostile creature, etc.

Piper should not be only a narrator. Piper should become:

> Narrator + actor director + NPC voices, while JSON remains the script bible.

### 9.1 NPC Persona Cards

Each NPC/actor should have a structured persona card.

Example fantasy NPC:

```json
{
  "id": "mara_bellkeeper",
  "name": "Mara",
  "role": "Bellkeeper",
  "current_scene": "village_square",
  "persona": {
    "voice": "guarded, rural, suspicious",
    "motives": ["protect the village", "hide her brother's crime"],
    "fears": ["the mayor", "the curse returning"],
    "temperament": "defensive",
    "speech_style": "short, indirect, avoids names"
  },
  "relationship_to_player": {
    "trust": 20,
    "fear": 35,
    "hostility": 10,
    "respect": 5
  },
  "knows": ["bell_was_stolen", "mayor_lied"],
  "can_reveal": ["old_tracks", "ash_symbol"],
  "triggers": [
    {
      "condition": "player_accuses_mara",
      "effect": "increase_hostility"
    }
  ],
  "status": "available"
}
```

Example flight actor:

```json
{
  "id": "cabin_lead",
  "name": "Senior Cabin Crew",
  "role": "Cabin report source",
  "current_scene": "aircraft_cabin",
  "persona": {
    "voice": "calm but urgent",
    "motives": ["protect passengers", "give concise reports"],
    "fears": ["fire spreading", "passenger panic"],
    "temperament": "professional under stress",
    "speech_style": "short operational cabin reports"
  },
  "relationship_to_player": {
    "trust": 70,
    "fear": 45,
    "hostility": 0,
    "respect": 80
  },
  "knows": ["smoke_seen_row_18", "passenger_panic_level"],
  "can_reveal": ["visible_flames", "smell_of_electrical_burning"],
  "triggers": [],
  "status": "available"
}
```

### 9.2 Dialogue Output

The model should output NPC dialogue separately from narration.

Example:

```json
{
  "narration": "The bell tower creaks above you as the square falls quiet.",
  "npc_dialogue": [
    {
      "speaker_id": "mara_bellkeeper",
      "speaker_name": "Mara",
      "role": "Bellkeeper",
      "tone": "guarded",
      "text": "Some things are better left buried under that hill."
    }
  ],
  "state_delta": {
    "flags": {
      "met_mara": true
    }
  },
  "next_options": [
    "Ask Mara what happened to the bell",
    "Inspect the bell tower",
    "Leave for the tavern"
  ]
}
```

The UI must display dialogue as dialogue cards or rows, not bury it inside narration.

### 9.3 Actor Selection

v0.1 should not call the LLM separately for every NPC.

Instead:

```text
actor_selector.py decides relevant actors
one LLM call generates narration + relevant dialogue + state_delta
```

Future version:

```text
important NPCs may get separate per-actor inference
```

The code should be ready for this future split, but not require it now.

---

## 10. Engine Loop

The intended runtime loop:

```text
User input
→ load current scenario/session state
→ determine relevant actors/NPCs
→ build LLM prompt from:
   - scenario state
   - profile rules
   - current act
   - current scene
   - relevant NPC persona cards
   - recent session log
→ LLM/mock LLM returns TurnProposal
→ parse with Pydantic
→ if invalid JSON, run repair prompt/mock repair
→ validator checks StateDelta
→ apply only valid changes
→ save updated state to JSON
→ append session log
→ return TurnResult to UI
```

The model’s output is a proposal, not truth.

The saved JSON state is truth.

---

## 11. State Delta Model

The model should not rewrite the full state every turn.

It should propose a delta.

Example:

```json
{
  "flags": {
    "met_mara": true,
    "found_ash_symbol": true
  },
  "inventory_add": ["cracked_silver_medallion"],
  "clues_add": ["ash_symbol"],
  "relationship_changes": [
    {
      "npc_id": "mara_bellkeeper",
      "trust": -5,
      "hostility": 10
    }
  ],
  "move_player_to_scene": "bell_tower",
  "complete_objectives": ["inspect_village_square"]
}
```

The validator decides which parts are legal.

This avoids the model overwriting unrelated state or inventing a new world every turn.

---

## 12. Prompt Strategy

Prompting is important, but prompts alone are not enough.

The reliable stack is:

```text
Prompt constraints
+ Pydantic validation
+ state-delta validator
+ repair loop
+ tests
```

Prompt templates should include:

- `scenario_builder.txt`
- `scenario_repair.txt`
- `narrator_turn.txt`
- `turn_repair.txt`
- `npc_dialogue.txt`

Prompts should instruct the model to:

- Output valid JSON only when structured output is required.
- Preserve existing state.
- Never invent inventory, NPCs, scenes, clues, skills, or objectives unless profile rules allow it.
- Propose state changes only through `state_delta`.
- Keep NPC dialogue consistent with persona cards.
- Keep NPC knowledge limited to what the NPC knows.
- Avoid revealing secrets too early.
- Use the current scene and current act.
- Return three useful next options.
- Keep dialogue separate from narration.

The repair prompts should take invalid JSON or invalid proposals and ask the model to return a corrected structure without changing the intended meaning more than necessary.

---

## 13. Mock LLM Mode

Mock mode is mandatory.

The app must be testable without a real model.

Mock mode should:

- Load the sample fantasy scenario.
- Accept user turns.
- Produce valid canned `TurnProposal` outputs.
- Include narration.
- Include NPC dialogue.
- Include state deltas.
- Update inventory/clues/objectives/relationships.
- Produce three options.
- Exercise the validator.
- Save session logs.

This proves the product skeleton before the local LLM gets involved.

The first success condition:

> Run the app in mock mode, click/type one action, see narration/dialogue/state update in the UI, and see the session JSON updated on disk.

---

## 14. Web UI

The lab should use a minimal web UI, not DearPyGui.

Reason:

- Piper’s future direction is likely web UI.
- Browser UI is easier to iterate.
- It can later be absorbed into Piper with less rework.
- It separates backend state from frontend display cleanly.

Recommended layout:

```text
Left/main panel:
  narration log
  dialogue cards

Right/sidebar:
  scenario title
  current act
  current scene
  active NPCs
  objectives
  inventory
  skills/perks
  clues
  flags/debug state

Bottom:
  free text input
  Send button
  three generated option buttons
```

The UI does not need to be beautiful in v0.1.

It should be practical and make state visible.

State visibility is crucial because the whole point is that the user can see what the scenario believes is true.

---

## 15. Backend API

A simple FastAPI backend is recommended.

Required endpoints:

```text
GET  /api/scenarios
POST /api/scenario/new
POST /api/scenario/load
GET  /api/state
POST /api/turn
POST /api/reset
GET  /api/session/log
```

The backend should also serve the static web UI.

The API should return structured JSON responses.

---

## 16. Scenario Building Phase

Long-term, scenario creation should happen through multiple passes.

Example:

```text
Pass 1: world, tone, genre, premise
Pass 2: acts, beginning, possible endings
Pass 3: scenes and locations
Pass 4: NPCs and persona cards
Pass 5: items, artifacts, skills, perks
Pass 6: objectives, clues, flags, progression conditions
Pass 7: validation and repair
```

This makes complex scenario creation more reliable than asking the model for everything at once.

v0.1 can use a hand-written sample scenario and a simple builder stub.

The long-term scenario builder should produce a locked scenario JSON file before play begins.

---

## 17. Flight Training Direction

Flight training scenarios are the most unique future application.

The same engine can support them because aviation scenarios also have:

- Current state.
- Actors.
- Events.
- Procedures.
- Objectives.
- Consequences.
- Timelines.
- Communication.
- Decision points.

Example actors:

- ATC.
- Cabin crew.
- First officer.
- Dispatch.
- Maintenance.
- Purser.
- Passengers.
- Company operations.

Example state:

```json
{
  "aircraft": "A320",
  "phase_of_flight": "climb",
  "weather": "IMC",
  "failures": ["engine_abnormal_placeholder"],
  "state": {
    "altitude": 7000,
    "speed": 250,
    "atc_informed": false,
    "cabin_report_received": false
  },
  "objectives": [
    "aviate",
    "navigate",
    "communicate",
    "assess_failure",
    "choose_safe_plan"
  ]
}
```

The placeholder should avoid pretending to be a certified procedure source.

Later, verified procedure logic can be added by the user.

The future flight profile could support:

- Scenario generation by aircraft/phase/failure/weather.
- Cabin reports.
- ATC dialogue.
- Time pressure.
- ECAM/checklist objective placeholders.
- Decision grading.
- Debrief after scenario completion.
- Mistake tracking.
- Replay log.

This is not v0.1.

But v0.1 must keep extension points open for it.

---

## 18. Tests

Tests should be included from the start.

Recommended initial tests:

- Pydantic models load the sample scenario.
- Validator rejects nonexistent item.
- Validator rejects nonexistent scene.
- Validator rejects impossible objective completion.
- Mock engine accepts a turn and updates state.
- NPC dialogue appears in `TurnResult`.
- Session save/load works.

Tests keep the system from becoming a beautiful liar.

---

## 19. README Requirements

The README should include:

- What the project is.
- What it is not.
- Exact run commands.
- How to use Piper’s existing venv.
- How to run mock mode.
- How to run tests.
- Folder structure.
- Architecture explanation.
- Engine loop explanation.
- Validator explanation.
- NPC/actor explanation.
- How future Piper integration should work.
- How future flight training profile should expand.
- Known limitations.

---

## 20. Kimi Web / Agent Swarm Handoff Guidance

The initial Kimi Web run should be broad enough to create the repo skeleton, test loop, UI, mock mode, schemas, and sample scenario.

The goal of that pass:

> Create a strong jump-start scaffold, not a perfect finished product.

Kimi should:

- Build the repo on its own machine.
- Keep it standalone.
- Test it there.
- Provide a downloadable zip or patch.
- Include honest known failures.
- Include run commands.
- Include tests.

Kimi should not:

- Modify Piper directly.
- Integrate voice.
- Integrate image generation.
- Build full combat.
- Build certified aviation procedures.
- Depend on cloud APIs.
- Hard-code DND assumptions into the base engine.

The broad one-off pass should lay rails wide enough for future work.

---

## 21. v0.1 Success Criteria

v0.1 is successful when:

1. The project runs standalone.
2. It uses mock LLM mode.
3. The web UI loads.
4. A sample fantasy scenario loads.
5. The user can enter a turn.
6. The engine returns narration.
7. The engine returns NPC dialogue.
8. The validator applies legal state changes.
9. The sidebar updates inventory/objectives/clues/flags.
10. Session JSON is saved.
11. Basic tests pass.
12. The base engine remains profile-generic.
13. A flight training placeholder exists without contaminating the base engine.

That is enough.

Anything beyond that is v0.2+.

---

## 22. Future Roadmap

### v0.1 — Standalone mock lab

- FastAPI backend.
- Plain web UI.
- Pydantic schemas.
- JSON storage.
- Mock LLM.
- Tiny fantasy profile.
- Flight placeholder profile.
- NPC dialogue cards.
- Validator.
- Tests.

### v0.2 — Real local LLM adapter

- Connect to Piper’s local model stack or llama.cpp server.
- Add JSON repair loop.
- Improve prompt templates.
- Add scenario builder pass.
- Add better actor selection.

### v0.3 — Scenario generation

- Generate scenario files from user request.
- Multi-pass builder.
- Scenario validation and repair.
- Save reusable scenario templates.

### v0.4 — Better NPC behavior

- More nuanced relationship changes.
- NPC memory within session.
- NPC secrets and reveal conditions.
- Optional per-actor inference for major NPCs.

### v0.5 — Flight training prototype

- Structured aviation profile.
- Non-authoritative simplified procedures.
- ATC/cabin crew/dispatch actors.
- Objective grading placeholders.
- Debrief log.

### v1.0 — Piper integration

- Integrate as Piper Scenario Mode.
- Use Piper’s LLM client, memory, voice, and UI shell.
- Optional TTS actor voices.
- Optional visuals/avatar support.
- Persistent scenario library.

---

## 23. Design Risks

### Risk: DND concepts leak into the base engine

Mitigation:

Use generic base terms: scenario, act, scene, actor, objective, item, skill, flag, resource, dialogue.

Fantasy-specific concepts stay in `profiles/fantasy_tiny`.

### Risk: Model invents state

Mitigation:

Use state deltas, Pydantic validation, validator checks, repair loop, and visible UI state.

### Risk: UI becomes the product too early

Mitigation:

Keep v0.1 UI simple. Prioritize engine correctness.

### Risk: Flight training becomes unsafe or overconfident

Mitigation:

Start with placeholders. Do not encode real SOPs until verified by the user. Treat future aviation mode as training aid/simulation, not authoritative operational guidance.

### Risk: Too many LLM calls

Mitigation:

Use one inference per turn in v0.1. Actor selector chooses relevant NPCs. Add per-actor inference later only where useful.

### Risk: Scenario generation is too ambitious

Mitigation:

Start with a hand-written sample scenario and mock mode. Add multi-pass generation later.

---

## 24. Core Mantra

Use this to judge every design decision:

> Is this building a reusable scenario engine, or just a fantasy chatbot wearing armor?

The desired answer is always:

> Reusable scenario engine.

---

## 25. Final Summary

The Piper Scenario Engine should be a standalone, local-first, JSON/Pydantic-driven interactive scenario system.

The first test profile is tiny fantasy/DND, but the architecture must support future flight training, detective, survival, and custom simulations.

The model should create narration and dialogue, but not own reality.

NPCs/actors should have structured persona cards and produce separate dialogue lines in the UI.

The validator should guard the state.

The UI should expose the current world state clearly.

Mock mode should prove the loop before real LLM integration.

The end goal is for Piper to become a structured scenario director: narrator, actor manager, examiner, and simulation host — with JSON as the script bible and Python as the referee.

