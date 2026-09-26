"""Scripted playtest / smoke test for the Thunorheim agent pipeline.

Runs a fixed sequence of turns against a throwaway state file (never touches
state/session_state.json) and prints the narration plus a state snapshot after
each turn. Useful for demos and as a regression check that the four-agent loop
still works end to end.

    uv run python evals/smoke.py
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from thunorheim.dm_agent import DMAgent
from thunorheim.world_state import WorldState

SCRIPT = [
    # (label, action)
    (
        "Social / new-NPC pipeline (bartender -> Maren)",
        "I walk up to the bartender and ask what she knows about the outposts going silent.",
    ),
    (
        "Exploration (find the formation tracks)",
        "I leave town through the Greywall Gate and head east down the road toward "
        "Ashwatch Post, watching the ground for tracks.",
    ),
    (
        "Combat (Greywalker — valid player action)",
        "I draw my blade and scan the grey scrub ahead, ready for whatever is moving in there.",
    ),
]


def snapshot(ws: WorldState) -> str:
    s = ws.get_state()
    p = s["player"]
    return (
        f"    [turn {s['session']['turn']}] "
        f"{p['health']}/{p['energy']} @ {p['location']} | "
        f"npcs={list(s['npcs_met'].keys())} | "
        f"active_quests={[q['title'] for q in s['quests']['active']]} | "
        f"flags_set={[k for k, v in s['world_flags'].items() if v]}"
    )


def main() -> None:
    tmp = os.path.join(tempfile.gettempdir(), "thunor_playtest_state.json")
    if os.path.exists(tmp):
        os.remove(tmp)

    ws = WorldState(tmp)
    ws.update_player(name="Edwyn Carr", role="Warden")
    ws.update_session(
        current_scene="Edwyn the Warden just arrived in Greyhold, in the Ashen Flagon."
    )
    ws.save_state()
    dm = DMAgent(ws)

    for label, action in SCRIPT:
        print("=" * 70)
        print(f"TURN: {label}")
        print(f"> {action}\n")
        try:
            print(asyncio.run(dm.run_turn(action)))
        except Exception as exc:
            print(f"[turn rolled back] {exc}")
        print()
        print(snapshot(ws))
        print()

    os.remove(tmp)


if __name__ == "__main__":
    main()
