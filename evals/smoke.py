from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile

from thunorheim.dm_agent import DMAgent
from thunorheim.world_state import WorldState

if isinstance(sys.stdout, io.TextIOWrapper):  # model prose isn't always cp1252-safe
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
        for c in dm.last_trace.get("calls", []):
            ttft = f" ttft {c['ttft_ms']}ms" if c["ttft_ms"] else ""
            errors = f" errors={c['errors']}" if c["errors"] else ""
            print(f"    {c['role']:8} {c['provider']}:{c['model']}  {c['ms']}ms{ttft}{errors}")
        print(snapshot(ws))
        print()

    os.remove(tmp)


if __name__ == "__main__":
    main()
