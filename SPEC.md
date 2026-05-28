# PiperScenarioLab — SPEC.md

## 1. Folder Structure

```
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

## 2. Pydantic Models (scenario_engine/models.py)

All models use pydantic v2 (BaseModel, Field, field_validator).

### Core Models

```python
class NPCRelationship(BaseModel):
    trust: int = Field(default=0, ge=-100, le=100)
    fear: int = Field(default=0, ge=-100, le=100)
    hostility: int = Field(default=0, ge=-100, le=100)
    respect: int = Field(default=0, ge=-100, le=100)

class NPCPersona(BaseModel):
    voice: str = ""
    motives: List[str] = Field(default_factory=list)
    fears: List[str] = Field(default_factory=list)
    temperament: str = ""
    speech_style: str = ""

class NPCTrigger(BaseModel):
    condition: str
    effect: str

class NPC(BaseModel):
    id: str
    name: str
    role: str = ""
    current_scene: str = ""
    persona: NPCPersona = Field(default_factory=NPCPersona)
    relationship_to_player: NPCRelationship = Field(default_factory=NPCRelationship)
    knows: List[str] = Field(default_factory=list)
    can_reveal: List[str] = Field(default_factory=list)
    triggers: List[NPCTrigger] = Field(default_factory=list)
    status: str = "available"  # available, unavailable, hostile, dead, etc.

class DialogueLine(BaseModel):
    speaker_id: str
    speaker_name: str
    role: str = ""
    tone: str = ""
    text: str

class Objective(BaseModel):
    id: str
    description: str
    status: str = "active"  # active, complete, failed
    required_flags: List[str] = Field(default_factory=list)
    required_clues: List[str] = Field(default_factory=list)

class Scene(BaseModel):
    id: str
    name: str
    description: str = ""
    connected_scenes: List[str] = Field(default_factory=list)
    npcs_present: List[str] = Field(default_factory=list)
    items_present: List[str] = Field(default_factory=list)
    clues_present: List[str] = Field(default_factory=list)

class Act(BaseModel):
    id: str
    name: str
    description: str = ""
    scenes: Dict[str, Scene] = Field(default_factory=dict)
    objectives: Dict[str, Objective] = Field(default_factory=dict)
    completion_flags: List[str] = Field(default_factory=list)

class Item(BaseModel):
    id: str
    name: str
    description: str = ""
    category: str = "general"  # general, artifact, tool, consumable

class Skill(BaseModel):
    id: str
    name: str
    description: str = ""
    category: str = "general"

class FlagState(BaseModel):
    flags: Dict[str, Any] = Field(default_factory=dict)

class PlayerState(BaseModel):
    current_act: str = ""
    current_scene: str = ""
    inventory: List[str] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    clues: List[str] = Field(default_factory=list)
    flags: Dict[str, Any] = Field(default_factory=dict)

class ScenarioMetadata(BaseModel):
    title: str
    description: str = ""
    author: str = ""
    version: str = "1.0"
    profile_id: str = ""
    difficulty: str = "medium"
    estimated_duration_minutes: int = 30

class ScenarioProfile(BaseModel):
    profile_id: str
    display_name: str
    allowed_dynamic_creation: List[str] = Field(default_factory=list)
    validation_rules: Dict[str, Any] = Field(default_factory=dict)
    prompt_template_dir: str = ""
    ui_labels: Dict[str, str] = Field(default_factory=dict)
    state_extensions: Dict[str, Any] = Field(default_factory=dict)

class Scenario(BaseModel):
    metadata: ScenarioMetadata
    profile: ScenarioProfile
    acts: Dict[str, Act] = Field(default_factory=dict)
    npcs: Dict[str, NPC] = Field(default_factory=dict)
    items: Dict[str, Item] = Field(default_factory=dict)
    skills: Dict[str, Skill] = Field(default_factory=dict)
    player: PlayerState = Field(default_factory=PlayerState)
    global_flags: Dict[str, Any] = Field(default_factory=dict)

    # Profile-specific extensions stored as flexible dict
    extensions: Dict[str, Any] = Field(default_factory=dict)
```

### Turn / Delta Models

```python
class TurnInput(BaseModel):
    user_input: str
    selected_option: Optional[str] = None

class StateDelta(BaseModel):
    flags: Dict[str, Any] = Field(default_factory=dict)
    inventory_add: List[str] = Field(default_factory=list)
    inventory_remove: List[str] = Field(default_factory=list)
    clues_add: List[str] = Field(default_factory=list)
    skills_add: List[str] = Field(default_factory=list)
    relationship_changes: List[Dict[str, Any]] = Field(default_factory=list)
    move_player_to_scene: Optional[str] = None
    move_npc_to_scene: List[Dict[str, str]] = Field(default_factory=list)
    complete_objectives: List[str] = Field(default_factory=list)
    fail_objectives: List[str] = Field(default_factory=list)
    npc_status_changes: Dict[str, str] = Field(default_factory=dict)

class TurnProposal(BaseModel):
    narration: str = ""
    npc_dialogue: List[DialogueLine] = Field(default_factory=list)
    state_delta: StateDelta = Field(default_factory=StateDelta)
    next_options: List[str] = Field(default_factory=list)
    error: Optional[str] = None

class ValidationResult(BaseModel):
    is_valid: bool = True
    accepted_delta: StateDelta = Field(default_factory=StateDelta)
    rejected_changes: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    requires_repair: bool = False

class TurnResult(BaseModel):
    turn_number: int = 0
    narration: str = ""
    npc_dialogue: List[DialogueLine] = Field(default_factory=list)
    state_delta: StateDelta = Field(default_factory=StateDelta)
    validation: ValidationResult = Field(default_factory=ValidationResult)
    next_options: List[str] = Field(default_factory=list)
    player_state: PlayerState = Field(default_factory=PlayerState)
    active_npcs: List[NPC] = Field(default_factory=list)
    current_act: Optional[str] = None
    current_scene: Optional[Scene] = None
    timestamp: str = ""

class SessionLogEntry(BaseModel):
    turn_number: int
    timestamp: str
    user_input: str
    narration: str
    npc_dialogue: List[DialogueLine] = Field(default_factory=list)
    accepted_state_delta: StateDelta = Field(default_factory=StateDelta)
    rejected_changes: List[Dict[str, Any]] = Field(default_factory=list)
    validator_warnings: List[str] = Field(default_factory=list)
    next_options: List[str] = Field(default_factory=list)
```

### API Response Models

```python
class APIResponse(BaseModel):
    success: bool = True
    data: Optional[Any] = None
    error: Optional[str] = None
    message: Optional[str] = None

class ScenariosListResponse(BaseModel):
    scenarios: List[Dict[str, str]] = Field(default_factory=list)

class SessionStateResponse(BaseModel):
    scenario: Optional[ScenarioMetadata] = None
    player: PlayerState = Field(default_factory=PlayerState)
    current_act: Optional[str] = None
    current_scene: Optional[Scene] = None
    active_npcs: List[NPC] = Field(default_factory=list)
    objectives: List[Objective] = Field(default_factory=list)
    inventory_items: List[Item] = Field(default_factory=list)
    skills: List[Skill] = Field(default_factory=list)
    flags: Dict[str, Any] = Field(default_factory=dict)
    turn_number: int = 0
```

## 3. Storage Layer (scenario_engine/storage.py)

```python
class Storage:
    def __init__(self, scenarios_dir: str = "scenarios", sessions_dir: str = "sessions"):
        self.scenarios_dir = Path(scenarios_dir)
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def list_scenarios(self) -> List[Dict[str, str]]:
        """Return list of available scenario files with id and title."""

    def load_scenario(self, scenario_id: str) -> Scenario:
        """Load a scenario definition from JSON."""

    def save_session(self, session_id: str, state: Dict[str, Any]) -> None:
        """Save session state to JSON."""

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load session state from JSON. Returns None if not found."""

    def session_exists(self, session_id: str) -> bool:
        """Check if a session file exists."""

    def append_log_entry(self, session_id: str, entry: SessionLogEntry) -> None:
        """Append a log entry to the session log."""

    def load_session_log(self, session_id: str) -> List[SessionLogEntry]:
        """Load full session log."""

    def generate_session_id(self) -> str:
        """Generate unique session ID."""
```

## 4. Validator (scenario_engine/validator.py)

```python
class Validator:
    def __init__(self, scenario: Scenario, profile: Any = None):
        self.scenario = scenario
        self.profile = profile

    def validate_turn(self, proposal: TurnProposal) -> ValidationResult:
        """
        Validate a TurnProposal's state_delta against scenario rules.
        Returns ValidationResult with accepted/rejected changes and warnings.
        """

    def _validate_inventory_changes(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject items not in scenario.items unless profile allows dynamic creation."""

    def _validate_scene_move(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject moves to nonexistent or disconnected scenes."""

    def _validate_clue_reveal(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject clues not present in current scene or NPC can_reveal."""

    def _validate_objective_completion(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject objective completion unless required flags/clues are met."""

    def _validate_relationship_bounds(self, delta: StateDelta, result: ValidationResult) -> None:
        """Clamp relationship values to [-100, 100]."""

    def _validate_skill_grants(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject skills not in scenario.skills unless profile allows."""

    def _validate_npc_status(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject status changes to nonexistent NPCs."""

    def _validate_act_progression(self, delta: StateDelta, result: ValidationResult) -> None:
        """Reject act changes unless completion conditions met."""
```

## 5. LLM Client (scenario_engine/llm_client.py)

```python
from enum import Enum

class LLMMode(str, Enum):
    MOCK = "mock"
    PIPER = "piper"

class LLMClient:
    """Adapter interface for LLM backends."""

    def __init__(self, mode: LLMMode = LLMMode.MOCK, config: Dict[str, Any] = None):
        self.mode = mode
        self.config = config or {}

    async def generate_turn(self, prompt: str, scenario: Scenario, context: Dict[str, Any]) -> TurnProposal:
        """Generate a TurnProposal. Mock mode returns canned responses."""

    async def repair_json(self, broken_json: str, schema_hint: str) -> Optional[Dict[str, Any]]:
        """Attempt to repair invalid JSON. Mock mode returns minimal valid dict."""

    async def build_scenario(self, prompt: str) -> Optional[Dict[str, Any]]:
        """Build a scenario from description. Mock returns None."""
```

### Mock Implementation

Mock mode must:
- Load canned responses keyed by user intent
- Produce valid Pydantic-parseable TurnProposal JSON
- Include narration, NPC dialogue, state_delta, next_options
- Support at least 5 different mock responses for variety
- Cycle through responses based on turn number

### Piper Adapter (thin wrapper)

```python
class PiperLLMAdapter(LLMClient):
    """
    Thin adapter around Piper's existing llm/client module.
    If Piper's client is available, wrap its shape.
    If not available, use a clean mock with the same interface.
    """

    def __init__(self, piper_client=None):
        # Try to import Piper's llm client
        # Fall back to mock if unavailable
        pass
```

## 6. Actor Selector (scenario_engine/actor_selector.py)

```python
class ActorSelector:
    """Select relevant NPCs/actors for the current turn."""

    def __init__(self, scenario: Scenario):
        self.scenario = scenario

    def select_actors(self, user_input: str, current_scene_id: str) -> List[NPC]:
        """
        Return list of NPCs relevant to this turn.
        Selection criteria:
        1. NPCs present in current_scene
        2. NPCs mentioned in user_input (simple keyword match)
        3. NPCs with triggers matching current flags
        Does NOT make LLM calls.
        """

    def build_persona_prompt(self, npcs: List[NPC]) -> str:
        """Build persona card text for selected NPCs to include in LLM prompt."""
```

## 7. Dialogue (scenario_engine/dialogue.py)

```python
class DialogueManager:
    """Process and format NPC dialogue output."""

    def process_dialogue(self, dialogue_lines: List[DialogueLine], scenario: Scenario) -> List[DialogueLine]:
        """
        Validate and enrich dialogue lines.
        - Ensure speaker_id exists in scenario.npcs
        - Fill in speaker_name and role from NPC data if missing
        - Filter out dialogue from NPCs who are unavailable/dead
        """

    def format_for_display(self, dialogue_lines: List[DialogueLine]) -> List[Dict[str, str]]:
        """Format dialogue lines for UI display."""

    def format_for_prompt(self, dialogue_lines: List[DialogueLine]) -> str:
        """Format recent dialogue for inclusion in LLM prompt context."""
```

## 8. Repair (scenario_engine/repair.py)

```python
class Repair:
    """Handle repair of invalid LLM outputs."""

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    async def repair_turn_proposal(self, broken: str, error: str, context: Dict[str, Any]) -> Optional[TurnProposal]:
        """
        Attempt to repair an invalid TurnProposal.
        1. Try JSON extraction (find JSON block in text)
        2. Try schema repair prompt via LLM
        3. Fallback to minimal valid TurnProposal
        """

    def extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON object from text that may contain markdown or extra content."""

    def minimal_fallback(self, context: Dict[str, Any]) -> TurnProposal:
        """Return a minimal valid TurnProposal when all repair fails."""
```

## 9. Profile Base (scenario_engine/profile_base.py)

```python
class ProfileBase(ABC):
    """Abstract base class for scenario profiles."""

    profile_id: str = ""
    display_name: str = ""
    allowed_dynamic_creation: List[str] = []
    prompt_template_dir: str = ""
    ui_labels: Dict[str, str] = {}

    @abstractmethod
    def get_validation_rules(self) -> Dict[str, Any]:
        """Return profile-specific validation rules."""

    @abstractmethod
    def load_prompt(self, prompt_name: str) -> str:
        """Load a prompt template by name."""

    @abstractmethod
    def get_state_extensions(self) -> Dict[str, Any]:
        """Return profile-specific state extension defaults."""

    @abstractmethod
    def check_dynamic_creation_allowed(self, entity_type: str) -> bool:
        """Check if profile allows dynamic creation of entity_type."""
```

## 10. Engine (scenario_engine/engine.py)

```python
class ScenarioEngine:
    """Main scenario engine coordinating the full turn cycle."""

    def __init__(
        self,
        storage: Storage,
        llm_client: LLMClient,
        session_id: Optional[str] = None
    ):
        self.storage = storage
        self.llm_client = llm_client
        self.session_id = session_id or self.storage.generate_session_id()
        self.scenario: Optional[Scenario] = None
        self.validator: Optional[Validator] = None
        self.actor_selector = ActorSelector(self.scenario) if self.scenario else None
        self.dialogue_manager = DialogueManager()
        self.repair = Repair(llm_client)
        self.turn_number: int = 0

    async def load_scenario(self, scenario_id: str) -> None:
        """Load a scenario definition and initialize session."""

    async def new_scenario(self, scenario_id: str) -> None:
        """Start a new session with the given scenario."""

    async def take_turn(self, turn_input: TurnInput) -> TurnResult:
        """
        Main turn loop:
        1. Load current state
        2. Select relevant actors
        3. Build LLM prompt
        4. Generate TurnProposal
        5. Parse and validate
        6. Repair if invalid
        7. Validate state delta
        8. Apply valid changes
        9. Save state
        10. Log entry
        11. Return TurnResult
        """

    async def reset(self) -> None:
        """Reset to initial scenario state."""

    def get_state(self) -> SessionStateResponse:
        """Return current session state for UI."""

    def get_session_log(self) -> List[SessionLogEntry]:
        """Return full session log."""

    def _build_turn_prompt(self, turn_input: TurnInput, selected_npcs: List[NPC]) -> str:
        """Build the narrator turn prompt from templates and current state."""

    def _apply_state_delta(self, delta: StateDelta) -> None:
        """Apply validated state delta to current scenario state."""

    def _get_current_act(self) -> Optional[Act]:
        """Get current act from player state."""

    def _get_current_scene(self) -> Optional[Scene]:
        """Get current scene from player state."""

    def _get_active_npcs(self) -> List[NPC]:
        """Get NPCs in current scene with available status."""
```

## 11. API Endpoints (app.py)

```python
# FastAPI app with CORS, static files
app = FastAPI(title="PiperScenarioLab", version="0.1.0")

# Serve web UI static files
app.mount("/", StaticFiles(directory="web", html=True), name="web")

@app.get("/api/scenarios")
async def list_scenarios() -> ScenariosListResponse

@app.post("/api/scenario/new")
async def new_scenario(request: {"scenario_id": str}) -> APIResponse

@app.post("/api/scenario/load")
async def load_scenario(request: {"scenario_id": str, "session_id": Optional[str]}) -> APIResponse

@app.get("/api/state")
async def get_state() -> SessionStateResponse

@app.post("/api/turn")
async def take_turn(request: TurnInput) -> TurnResult

@app.post("/api/reset")
async def reset() -> APIResponse

@app.get("/api/session/log")
async def get_session_log() -> List[SessionLogEntry]
```

### Startup
```python
# On startup:
# 1. Read SCENARIO_LLM_MODE env var (default: mock)
# 2. Create Storage instance
# 3. Create LLMClient with appropriate mode
# 4. Create ScenarioEngine
# 5. If no scenario loaded, auto-load tiny_fantasy_sample
```

## 12. Fantasy Profile (profiles/fantasy_tiny/)

### profile.py
```python
class FantasyTinyProfile(ProfileBase):
    profile_id = "fantasy_tiny"
    display_name = "Tiny Fantasy"
    allowed_dynamic_creation = ["flags"]
    prompt_template_dir = "profiles/fantasy_tiny/prompts"
    ui_labels = {
        "acts_label": "Acts",
        "scenes_label": "Locations",
        "npcs_label": "Characters",
        "items_label": "Inventory",
        "skills_label": "Abilities",
        "clues_label": "Clues",
    }
```

### Prompts (profiles/fantasy_tiny/prompts/)

All prompts must:
- Require valid JSON output
- Include short schema hints for TurnProposal
- Include anti-drift instructions
- Reference persona cards for dialogue
- Keep dialogue separate from narration

### Scenario (scenarios/tiny_fantasy_sample.json)

Requirements:
- 2-3 acts (e.g., "arrival", "investigation", "resolution")
- 2 NPCs (e.g., "mara_bellkeeper", "eldric_mayor")
- 2-3 scenes (e.g., "village_square", "bell_tower", "mayor_office")
- 1 artifact item
- 2 skills/perks
- 3 clues/objectives
- Relationship that can shift based on player actions

## 13. Flight Training Profile (profiles/flight_training/)

### profile.py
```python
class FlightTrainingProfile(ProfileBase):
    profile_id = "flight_training"
    display_name = "Flight Training (Placeholder)"
    allowed_dynamic_creation = []
    prompt_template_dir = "profiles/flight_training/prompts"
    ui_labels = {
        "acts_label": "Phases",
        "scenes_label": "Situations",
        "npcs_label": "Crew / ATC",
        "items_label": "Systems",
        "skills_label": "Procedures",
        "clues_label": "Indications",
    }

    def get_state_extensions(self) -> Dict[str, Any]:
        return {
            "aircraft": {"type": "", "registration": ""},
            "phase_of_flight": "",
            "weather": {"condition": "", "visibility": 0, "wind": ""},
            "failures": [],
            "checklists": [],
            "atc_comms": [],
            "grading": {"score": 0, "notes": []},
        }
```

### Scenario (scenarios/tiny_flight_placeholder.json)

Requirements:
- Placeholder only, clearly marked as non-authoritative
- Schema extension points for aircraft, weather, failures
- ATC actor, cabin crew actor
- One sample situation (e.g., smoke report)
- Comments/TODOs where real procedures would go
- No real proprietary SOPs

## 14. Web UI (web/)

### Layout
```
+--------------------------------------------------+
| PiperScenarioLab                    [Mock Mode]  |
+----------------------------------+---------------+
|                                  | Scenario Title|
|  NARRATION LOG                   | Current Act   |
|                                  | Current Scene |
|  [timestamp] Narration text...   |               |
|                                  | Active NPCs   |
|  --- DIALOGUE ---                | - Mara        |
|  [Mara - Bellkeeper]             | - Eldric      |
|  "Some things are better..."     |               |
|  tone: guarded                   | Objectives    |
|                                  | - Find bell   |
|                                  | - Talk to Mara|
|                                  |               |
|                                  | Inventory     |
|                                  | - Lantern     |
|                                  |               |
|                                  | Skills        |
|                                  | - Perception  |
|                                  |               |
|                                  | Clues         |
|                                  | - Ash symbol  |
|                                  |               |
|                                  | Flags (debug) |
|                                  | met_mara: true|
+----------------------------------+---------------+
| [Free text input.........] [Send]                |
| [Option 1] [Option 2] [Option 3]                 |
+--------------------------------------------------+
```

### style.css
- Clean, low-saturation palette
- Dark sidebar (#2c2c2c), light main area (#f5f5f0)
- Dialogue cards with subtle border-left accent
- Monospace font for flags/debug
- Responsive: stack on narrow screens

### app.js
- Fetch /api/scenarios on load
- POST /api/scenario/new to start
- Poll or POST /api/turn for turns
- Display narration as text blocks
- Display dialogue as cards with speaker, role, tone, text
- Update sidebar after each turn
- Bind option buttons to send as user_input
- Allow free text input + Send

## 15. Tests

### test_models.py
- Test that tiny_fantasy_sample.json parses into Scenario
- Test that all nested models validate
- Test NPC relationship bounds

### test_validator.py
- Test validator rejects nonexistent item add
- Test validator rejects nonexistent scene move
- Test validator rejects clue not in scene/NPC
- Test validator rejects impossible objective completion
- Test validator clamps relationships
- Test validator accepts legal changes

### test_engine_mock.py
- Test engine loads scenario in mock mode
- Test engine takes a turn and returns TurnResult
- Test NPC dialogue appears in TurnResult
- Test state updates after turn
- Test session log is written
- Test reset returns to initial state

## 16. Mock Mode Behavior

When SCENARIO_LLM_MODE=mock:
- LLMClient.generate_turn returns canned TurnProposals
- At least 5 different responses cycled by turn number
- Responses include: narration, 1-2 dialogue lines, small state_delta, 3 options
- Mock responses exercise: inventory add, clue reveal, relationship change, flag set
- No external API calls made

## 17. Environment Variables

```bash
SCENARIO_LLM_MODE=mock          # mock | piper
SCENARIO_STORAGE_DIR=scenarios  # scenario definitions dir
SCENARIO_SESSIONS_DIR=sessions  # session save dir
```

## 18. Run Commands

```bash
# Install
pip install -r requirements.txt

# Run mock mode
SCENARIO_LLM_MODE=mock python app.py

# Run tests
pytest tests/ -v

# Windows
set SCENARIO_LLM_MODE=mock
python app.py
```
