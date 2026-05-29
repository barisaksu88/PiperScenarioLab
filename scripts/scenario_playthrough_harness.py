"""Automated playthrough harness for PiperScenarioLab.

Runs a scenario to completion (or max turns), captures turn payloads,
and prints a compact report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scenario_engine.engine import ScenarioEngine
from scenario_engine.llm_client import LLMClient, LLMMode, PiperLLMAdapter
from scenario_engine.models import TurnInput
from scenario_engine.storage import Storage


def _build_client(mode: str) -> LLMClient:
    if mode == "piper":
        return PiperLLMAdapter(config={})
    return LLMClient(mode=LLMMode.MOCK)


async def _run_playthrough(
    scenario_id: str,
    mode: str,
    max_turns: int = 30,
    turns: List[str] | None = None,
) -> Dict[str, Any]:
    engine = ScenarioEngine(
        storage=Storage("scenarios", "sessions"),
        llm_client=_build_client(mode),
    )
    await engine.load_scenario(scenario_id)
    results = []
    ending = None
    user_inputs = list(turns) if turns else []
    for turn_idx in range(max_turns):
        if ending:
            break
        if turn_idx < len(user_inputs):
            user_input = user_inputs[turn_idx]
        else:
            # Use one of the next_options from the previous turn
            if results and results[-1].get("next_options"):
                opts = results[-1]["next_options"]
                # Prefer options that advance the story
                user_input = opts[0] if opts else "Continue."
            else:
                user_input = "Look around."
        result = await engine.take_turn(TurnInput(user_input=user_input))
        results.append(
            {
                "user_input": user_input,
                "turn_number": result.turn_number,
                "narration": result.narration,
                "dialogue_count": len(result.npc_dialogue),
                "speakers": [line.speaker_name for line in result.npc_dialogue],
                "next_options": result.next_options,
                "ending": result.ending,
            }
        )
        if result.ending:
            ending = result.ending
            break

    return {
        "mode": mode,
        "scenario_id": scenario_id,
        "results": results,
        "ending": ending,
        "turns_taken": len(results),
        "final_state": engine.get_state().model_dump(mode="json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a ScenarioLab playthrough and print a report.")
    parser.add_argument("--mode", choices=["mock", "piper"], default=os.environ.get("SCENARIO_LLM_MODE", "mock"))
    parser.add_argument("--scenario", default="tiny_fantasy_sample")
    parser.add_argument("--turn", action="append", dest="turns", help="Add a turn. Can be repeated.")
    parser.add_argument("--max-turns", type=int, default=30)
    parser.add_argument("--json-out", type=Path, help="Write full results to a JSON file.")
    args = parser.parse_args()

    payload = asyncio.run(
        _run_playthrough(
            args.scenario,
            args.mode,
            max_turns=args.max_turns,
            turns=args.turns,
        )
    )

    for item in payload["results"]:
        print(f"Turn {item['turn_number']}: {item['user_input']}")
        print(f"  dialogue_count={item['dialogue_count']} speakers={item['speakers']}")
        print(f"  narration={item['narration'][:160]}")
        print(f"  next_options={item['next_options']}")
        if item.get("ending"):
            print(f"  ENDING={item['ending'][:200]}")

    if payload.get("ending"):
        print(f"\n>>> SCENARIO COMPLETE in {payload['turns_taken']} turns <<<")
        print(f"Ending: {payload['ending'][:300]}")
    else:
        print(f"\n>>> SCENARIO INCOMPLETE after {payload['turns_taken']} turns <<<")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"wrote {args.json_out}")

    return 0 if payload.get("ending") else 1


if __name__ == "__main__":
    raise SystemExit(main())
