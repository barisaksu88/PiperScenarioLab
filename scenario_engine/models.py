"""Pydantic models for PiperScenarioLab."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


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
