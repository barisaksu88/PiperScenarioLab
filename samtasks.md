# PiperScenarioLab — Active Task List

## Status: IN PROGRESS

---

## 1. COMPLETED (Tested & Verified)

### API Endpoints
- [x] `/api/scenarios` — Lists all available scenarios
- [x] `/api/scenario/new` — Loads a scenario and initializes session
- [x] `/api/scenario/load` — Restores saved session
- [x] `/api/state` — Returns full session state (scenario, player, NPCs, objectives, inventory, skills, flags)
- [x] `/api/turn` — Processes player turn (input validation → LLM → validation → state update)
- [x] `/api/save` — Persists session to disk
- [x] `/api/sessions` — Lists saved sessions with metadata
- [x] `/api/reset` — Resets to initial scenario state
- [x] `/api/scenario/generate` — LLM generates new scenario from parameters
- [x] Response times acceptable (<2s mock, ~8-10s piper per turn)
- [x] Error handling works (graceful on invalid input, missing session)

### Game Flow
- [x] Mock mode: 3 turns → ending, score 1000
- [x] Piper mode: Generated scenarios load and play correctly
- [x] Scene transitions work (connected_scenes respected)
- [x] Act progression auto-completes when all objectives done
- [x] Ending overlay triggers with score, objectives, acts, turns
- [x] Save/Continue persists and restores full state
- [x] Impossible action validation: "You attempt the impossible, but the world resists your will"

### Fixes Applied
- [x] `/api/scenario/generate` works in mock mode (returns tweaked tiny_fantasy_sample)
- [x] `SCENARIO_HOST`/`SCENARIO_PORT` env vars for uvicorn binding
- [x] `.gitignore` ignores generated scenarios (keeps built-in samples)
- [x] Engine starts in act_1/scene_1 instead of "new_game" state

---

## 2. IN PROGRESS / NEEDS WORK

### Critical: Game Too Short
**Problem:** Scenarios complete in 3 turns. Player uses a skill → all objectives auto-complete → act advances → ending.
**Root Causes:**
- Scenario builder prompt: "Keep the scenario small: 2-3 acts, 2-4 scenes per act"
- Auto-completion logic completes ALL objectives in a single act simultaneously
- Narrator prompt says "complete objectives immediately when requirements met" — too aggressive
- No intermediate steps; objectives have no sub-requirements

**Fix Plan:**
- [ ] **Update scenario builder prompt** — increase scope: 4-6 acts, 4-6 scenes per act, 6-10 NPCs, 5-8 items, 5-8 skills
- [ ] **Add item-gating to objectives** — objectives should require finding/using specific items
- [ ] **Add clue prerequisites to objectives** — some objectives require clues from previous acts
- [ ] **Update narrator prompt** — don't auto-complete all objectives at once; require item interaction, dialogue, exploration
- [ ] **Add minimum turns per act** — engine should not auto-complete act until minimum turns passed

### Critical: Items Have No Purpose
**Problem:** Items exist in the data model and appear in inventory panel, but:
- LLM never generates `inventory_add` in state_delta
- Player cannot "use" items from UI
- Items have no effects — they're just labels
- No item interaction prompts in the UI

**Fix Plan:**
- [ ] **Update narrator prompt** — explicitly tell LLM to add items to inventory when player finds them
- [ ] **Update scenario builder** — include items in scenes with discoverability hints
- [ ] **Add "Use Item" UI** — dropdown or buttons for inventory items, POST `/api/use_item`
- [ ] **Add item effects to model** — items can unlock scenes, trigger NPC dialogue, complete objectives
- [ ] **Add item combination logic** — some items combine to create new items

### Critical: NPCs Feel Dead
**Problem:** NPCs are defined in scenarios but:
- Rarely speak during gameplay (LLM omits dialogue lines)
- Dialogue recovery fallback works but feels canned
- NPCs never move between scenes
- No relationship progression visible to player
- No NPC scheduling (NPCs don't have routines/lives)

**Fix Plan:**
- [ ] **Update narrator prompt** — stronger instruction: "If NPCs are present, they MUST speak"
- [ ] **Add NPC movement rules** — NPCs can move between connected scenes based on time/flags
- [ ] **Add relationship display to UI** — show trust/fear/respect bars for each NPC
- [ ] **Add NPC scheduling** — NPCs have daily routines (morning/afternoon/evening locations)
- [ ] **Add NPC-initiated dialogue** — NPCs can speak first when player enters a scene

### Important: Missing D&D Feel
**Problem:** No stats, no combat, no dice rolls, no character progression. Game feels like a linear story, not a role-playing game.

**Fix Plan:**
- [ ] **Add character stats model** — Strength, Dexterity, Intelligence, Charisma, Constitution, Wisdom
- [ ] **Add stat checks to narrator prompt** — "Roll d20 + stat vs DC" for challenging actions
- [ ] **Add skill stat requirements** — some skills require minimum stat levels
- [ ] **Add combat encounters** — hostile NPCs, health/HP system, attack/defense rolls
- [ ] **Add experience/leveling** — completing objectives grants XP, leveling improves stats

### Important: World Feels Static
**Problem:** Same scenes every time, nothing changes between playthroughs. No environmental effects.

**Fix Plan:**
- [ ] **Add time-of-day system** — scenes change based on time (morning/noon/evening/night)
- [ ] **Add weather/environmental effects** — rain, fog, wind affect gameplay
- [ ] **Add persistent world state** — flags that carry across sessions (e.g., "village burned")
- [ ] **Add random encounters** — chance of unexpected events each turn

---

## 3. BACKLOG (Not Started)

- [ ] **Multiplayer** — Explicitly excluded per user request
- [ ] **Achievement system** — Track completionist goals
- [ ] **Post-game analysis** — Show missed content, alternate paths
- [ ] **Scenario browser filtering** — Search by genre, difficulty, length
- [ ] **Character creator** — Custom name, background, starting stats
- [ ] **Combat system v2** — Turn-based combat with initiative, positioning
- [ ] **Inventory management v2** — Equip slots, item durability, weight limits

---

## 4. KNOWN BUGS

- [ ] **Generate modal doesn't auto-close** — After scenario generation completes, modal stays open showing "Generating...". Game loads behind it. Non-critical.
- [ ] **Mock mode responses repetitive** — Only 3-4 canned responses, gets boring quickly.
- [ ] **No XSS protection** — HTML tags in player input pass through to UI.

---

## Commits

| Commit | Description |
|--------|-------------|
| def1d36 | Engine fix: start in act_1/scene_1 instead of "new_game" |
| 9331d1c | Add generated scenario: The Crystal Spire |
| 280c81d | Ignore generated scenario JSONs, keep built-in samples |

---

*Last updated: 2026-06-01 07:20*
