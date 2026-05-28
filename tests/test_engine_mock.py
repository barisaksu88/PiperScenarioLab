import os

os.environ.setdefault("SCENARIO_LLM_MODE", "mock")

import pytest
import pytest_asyncio
from scenario_engine.storage import Storage
from scenario_engine.llm_client import LLMClient, LLMMode
from scenario_engine.engine import ScenarioEngine
from scenario_engine.models import TurnInput


@pytest.fixture
def storage():
    return Storage("scenarios", "sessions")


@pytest.fixture
def mock_llm():
    return LLMClient(mode=LLMMode.MOCK)


@pytest_asyncio.fixture
async def engine(storage, mock_llm):
    eng = ScenarioEngine(storage=storage, llm_client=mock_llm)
    await eng.load_scenario("tiny_fantasy_sample")
    return eng


@pytest.mark.asyncio
async def test_engine_loads_scenario(engine):
    """Engine loads tiny_fantasy_sample, scenario and player state are set."""
    assert engine.scenario is not None
    assert engine.scenario.metadata.title == "The Bellkeeper's Secret"
    assert engine.validator is not None
    assert engine.actor_selector is not None
    assert engine.turn_number == 0
    assert engine.scenario.player.current_scene == "village_square"


@pytest.mark.asyncio
async def test_engine_take_turn_returns_result(engine):
    """Take a turn with 'look around', verify TurnResult with narration, dialogue, options."""
    result = await engine.take_turn(TurnInput(user_input="look around"))
    assert result is not None
    assert result.turn_number == 1
    assert result.narration != ""
    assert isinstance(result.narration, str)
    assert len(result.narration) > 0
    assert isinstance(result.npc_dialogue, list)
    assert len(result.next_options) > 0
    assert result.validation is not None
    assert result.player_state is not None


@pytest.mark.asyncio
async def test_npc_dialogue_in_result(engine):
    """TurnResult.npc_dialogue is non-empty list of DialogueLine."""
    result = await engine.take_turn(TurnInput(user_input="look around"))
    assert isinstance(result.npc_dialogue, list)
    assert len(result.npc_dialogue) >= 1
    first = result.npc_dialogue[0]
    assert first.speaker_id == "mara_bellkeeper"
    assert first.speaker_name == "Mara"
    assert first.text != ""


@pytest.mark.asyncio
async def test_state_updates_after_turn(engine):
    """Flags or inventory updated after turn."""
    pre_flags = dict(engine.scenario.player.flags)
    pre_inventory = list(engine.scenario.player.inventory)
    pre_clues = list(engine.scenario.player.clues)

    await engine.take_turn(TurnInput(user_input="look around"))

    post_flags = dict(engine.scenario.player.flags)
    post_inventory = list(engine.scenario.player.inventory)
    post_clues = list(engine.scenario.player.clues)

    changed = (
        post_flags != pre_flags
        or post_inventory != pre_inventory
        or post_clues != pre_clues
    )
    assert changed


@pytest.mark.asyncio
async def test_session_log_written(engine):
    """After taking a turn, log file exists and has entry."""
    await engine.take_turn(TurnInput(user_input="look around"))
    log = engine.get_session_log()
    assert len(log) >= 1
    entry = log[0]
    assert entry.turn_number == 1
    assert entry.user_input == "look around"
    assert entry.narration != ""


@pytest.mark.asyncio
async def test_reset_returns_initial_state(engine):
    """Take a turn, reset, verify state matches initial."""
    initial_scene = engine.scenario.player.current_scene
    initial_inventory = list(engine.scenario.player.inventory)
    initial_flags = dict(engine.scenario.player.flags)
    initial_turn = engine.turn_number

    await engine.take_turn(TurnInput(user_input="look around"))
    assert engine.turn_number == 1

    await engine.reset()
    assert engine.turn_number == initial_turn
    assert engine.scenario.player.current_scene == initial_scene
    assert engine.scenario.player.inventory == initial_inventory
    assert dict(engine.scenario.player.flags) == initial_flags


@pytest.mark.asyncio
async def test_multiple_turns_increment(engine):
    """Take 3 turns, verify turn_number == 3."""
    await engine.take_turn(TurnInput(user_input="look around"))
    await engine.take_turn(TurnInput(user_input="talk to mara"))
    await engine.take_turn(TurnInput(user_input="go to the tower"))
    assert engine.turn_number == 3


@pytest.mark.asyncio
async def test_get_state_returns_current(engine):
    """After taking a turn, get_state() returns updated state."""
    pre_state = engine.get_state()
    assert pre_state.turn_number == 0

    await engine.take_turn(TurnInput(user_input="look around"))

    post_state = engine.get_state()
    assert post_state.turn_number == 1
    assert post_state.scenario is not None
    assert post_state.scenario.title == "The Bellkeeper's Secret"
    assert post_state.player is not None
