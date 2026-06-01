# Kimi Code Task: PiperScenarioLab D&D Enhancements

## Context
PiperScenarioLab is a D&D scenario engine with web UI. The backend is FastAPI (app.py), engine in scenario_engine/, frontend in web_ui/frontend/.

## Goal
Add three major features to make the game feel more like D&D and more alive:

### 1. Character Stats System
**File to modify:** `scenario_engine/models.py`, `scenario_engine/engine.py`

Add six D&D-style stats to `PlayerState`:
```python
class CharacterStats(BaseModel):
    strength: int = Field(default=10, ge=1, le=20)
    dexterity: int = Field(default=10, ge=1, le=20)
    constitution: int = Field(default=10, ge=1, le=20)
    intelligence: int = Field(default=10, ge=1, le=20)
    wisdom: int = Field(default=10, ge=1, le=20)
    charisma: int = Field(default=10, ge=1, le=20)
    hp: int = Field(default=20, ge=0)
    max_hp: int = Field(default=20, ge=1)
    xp: int = Field(default=0, ge=0)
    level: int = Field(default=1, ge=1, le=20)
```

Add `stats: CharacterStats = Field(default_factory=CharacterStats)` to `PlayerState`.
Add `stats: CharacterStats = Field(default_factory=CharacterStats)` to `TurnResult` and `SessionStateResponse` so the UI can display them.

In `scenario_engine/engine.py`, when initializing a session, generate random stats (3d6 drop lowest for each, D&D standard). Store them in the session's player state.

### 2. Item Usage System
**Files to modify:** `scenario_engine/models.py`, `scenario_engine/engine.py`, `app.py`, frontend `index.html`

Add to `Item` model:
```python
usable: bool = False
effect_description: str = ""  # What happens when used
consumable: bool = False  # If true, removed from inventory after use
```

Add new endpoint to `app.py`:
```python
@app.post("/api/use_item")
async def use_item(request: Request, item_id: str):
    """Use an item from inventory. Applies effects and narrates result."""
```

The endpoint should:
1. Check if item is in player inventory
2. Check if item is usable
3. Call LLM with a prompt like "The player uses {item_name}. Describe what happens. Apply any relevant state changes."
4. If consumable, remove from inventory
5. Return narration and state_delta

In the frontend `index.html`, add a "Use" button next to each inventory item. On click, call `/api/use_item` and display the result.

### 3. NPC Scheduling System
**Files to modify:** `scenario_engine/models.py`, `scenario_engine/engine.py`

Add to `NPC` model:
```python
schedule: Dict[str, str] = Field(default_factory=dict)  # time_of_day -> scene_id
```

Add time-of-day tracking to `PlayerState` or session state. Simple cycle: morning → afternoon → evening → night → morning. Advance after each turn.

In `scenario_engine/engine.py`, after each turn, update all NPCs' `current_scene` based on their schedule. If no schedule defined, keep them in their current scene.

Also add a "last_spoke" field to NPCs to track when they last had dialogue, and in the narrator prompt, prioritize NPCs who haven't spoken recently.

### 4. Auto-item pickup
**File to modify:** `scenario_engine/engine.py`

When the player enters a scene (either at game start or via `move_player_to_scene`), automatically add all `items_present` in that scene to the player's inventory IF those items haven't been picked up before. Track picked-up items via a `picked_up_items` flag set.

### Constraints
- Do NOT change the existing JSON schema for `TurnProposal` or `StateDelta` unless absolutely necessary
- Keep changes backward-compatible with existing scenarios
- Do NOT add multiplayer features
- The LLM client (`scenario_engine/llm_client.py`) should NOT be modified for these changes
- Frontend changes should be minimal — just add Use buttons to inventory items, and stat display somewhere in the sidebar

## Files you can read for context
- `scenario_engine/models.py` - Pydantic models
- `scenario_engine/engine.py` - Game engine
- `app.py` - FastAPI endpoints
- `web_ui/frontend/index.html` - Frontend UI
- `profiles/fantasy_tiny/prompts/narrator_turn.txt` - LLM prompt template
