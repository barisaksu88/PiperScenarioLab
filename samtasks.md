# PiperScenarioLab — Active Task List

## Status: IN PROGRESS

---

## 1. COMPLETED (Tested & Verified)

### API Endpoints
- [x] `/api/scenarios` — Lists all available scenarios
- [x] `/api/scenario/new` — Loads a scenario and initializes session
- [x] `/api/scenario/load` — Restores saved session
- [x] `/api/state` — Returns full session state (scenario, player, NPCs, objectives, inventory, skills, flags, **stats**, **time_of_day**)
- [x] `/api/turn` — Processes player turn (input validation → LLM → validation → state update)
- [x] `/api/save` — Persists session to disk
- [x] `/api/sessions` — Lists saved sessions with metadata
- [x] `/api/reset` — Resets to initial scenario state
- [x] `/api/scenario/generate` — LLM generates new scenario from parameters
- [x] **`/api/use_item`** — Uses an inventory item, triggers LLM narration
- [x] Response times acceptable (<2s mock, ~8-10s piper per turn)
- [x] Error handling works (graceful on invalid input, missing session)

### D&D Enhancements (2026-06-01)
- [x] **Character Stats** — STR/DEX/CON/INT/WIS/CHA, generated via 3d6 drop lowest on scenario load
- [x] **HP/Max HP** — D&D 5e style: 10 + CON modifier
- [x] **XP/Level** — Level up when XP reaches level*100 threshold; +5 max HP, full heal on level up
- [x] **Time-of-day cycle** — morning → afternoon → evening → night, advances each turn
- [x] **Auto-item pickup** — Items in `items_present` automatically added to inventory when entering scene (tracked via `picked_up_items`)
- [x] **NPC Scheduling** — NPCs have `schedule: {morning, afternoon, evening, night -> scene_id}`, auto-reposition each turn
- [x] **Item Usability** — Items have `usable`, `effect_description`, `consumable` fields
- [x] **Item Usage UI** — "Use" buttons on usable inventory items; calls `/api/use_item`
- [x] **Stat/HP/XP changes from LLM** — `StateDelta` supports `stats_changes`, `hp_change`, `xp_change`
- [x] **Stat display in sidebar** — 6-stat grid + HP bar + LV/XP row
- [x] **Time-of-day display** — Emoji icon + text in scenario info panel
- [x] **Narrator prompt** — Injects stats, HP, time-of-day; mandates NPCs speak when present; prevents auto-completing all objectives at once; instructs LLM to add items to inventory on discovery
- [x] **Scenario builder prompt** — Generates larger scenarios (3-5 acts, 4-8 NPCs/items/skills, 30-60 min); includes `usable`, `schedule`, `stats` fields in output schema
- [x] **JSON nesting bug fix** — `repair.py` detects when LLM outputs entire TurnProposal JSON inside the `narration` field and re-extracts

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
- [x] Duplicate stats/time-of-day in UI fixed (clear old elements before rendering new ones)

---

## 2. IN PROGRESS / NEEDS WORK

### Important: Game Still Short (Needs Longer Scenarios)
**Problem:** Even with larger scenarios, the game can complete in 3-5 turns if the LLM auto-completes objectives aggressively.
**Status:** Narrator prompt now prevents auto-completing >1 objective per turn. Scenario builder generates larger scenarios. But the LLM may still be too generous.
**Fix Plan:**
- [ ] **Add minimum turns per act** — engine should not auto-complete act until minimum 3 turns passed
- [ ] **Add item-gating to objectives** — objectives should require finding/using specific items (LLM-generated scenarios now have items, but engine doesn't enforce item-gating)
- [ ] **Add clue prerequisites to objectives** — some objectives require clues from previous acts

### Important: Items Need More Purpose
**Status:** Auto-pickup works, items are added to inventory, `/api/use_item` endpoint exists. But:
- LLM may not consistently generate `inventory_add` in state_delta
- Items don't have mechanical effects on gameplay (no stat bonuses, no locked doors that require keys)
**Fix Plan:**
- [ ] **Add item combination logic** — some items combine to create new items
- [ ] **Add stat bonuses from items** — e.g., weapon gives +2 STR
- [ ] **Add locked content requiring items** — e.g., door requires Rusted Iron Key to open

### Important: NPCs Still Need More Life
**Status:** NPCs now have schedules and move between scenes based on time. Narrator prompt mandates they speak when present. But:
- Relationship changes are still invisible to the player (no UI)
- No NPC-initiated dialogue (player always acts first)
- NPCs don't have daily routines visible in UI
**Fix Plan:**
- [ ] **Add relationship display to UI** — show trust/fear/respect bars for each NPC
- [ ] **Add NPC-initiated dialogue** — NPCs can speak first when player enters a scene
- [ ] **Add NPC status effects** — e.g., "wounded", "hostile", "friendly" visible in sidebar

### Important: Missing Combat
**Status:** Stats exist, HP exists, but no actual combat system.
**Fix Plan:**
- [ ] **Add combat encounters** — hostile NPCs with attack/defense mechanics
- [ ] **Add dice rolls to narrator prompt** — "Roll d20 + stat vs DC" for challenging actions
- [ ] **Add damage/death** — HP can go to 0, game over if player dies

### Important: World Still Static Between Playthroughs
**Status:** Time-of-day changes scenes dynamically. But:
- No weather/environmental effects
- No persistent world state across sessions
- No random encounters
**Fix Plan:**
- [ ] **Add weather system** — rain, fog, wind that affect gameplay
- [ ] **Add persistent world flags** — flags that carry across sessions (e.g., "village burned")
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
| 5c7baa1 | Add D&D-style stats, item usage, NPC scheduling, time-of-day system |
| bdc7ef3 | Fix duplicate stats/time-of-day in UI; add cleanup on renderSidebar |

---

*Last updated: 2026-06-01 19:30*
