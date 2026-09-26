"""Thunorheim — persistent-memory narrative RPG. Terminal entry point.

Thin I/O loop only. The DM Agent is the orchestrator; this just reads player
input, hands each action to DMAgent.run_turn(), and prints the narration. State
persists in state/session_state.json between turns and between sessions.
"""

from __future__ import annotations

import contextlib
import sys

from thunorheim.dm_agent import DMAgent
from thunorheim.world_state import ROLES, WorldState

# Model prose can contain characters outside the Windows console codepage; keep the
# CLI from crashing on them.
with contextlib.suppress(AttributeError, ValueError):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BANNER = r"""
=========================================================
                    T H U N O R H E I M
        A frontier holds the line against the Blight.
=========================================================
"""


def create_character(ws: WorldState) -> None:
    print("The Warden's Guild logs every new operative. Two questions.\n")
    name = input("  Your name: ").strip() or "Edwyn Carr"
    print(f"\n  Roles: {', '.join(ROLES)}")
    role = ""
    while role not in ROLES:
        role = input("  Your role: ").strip().title()
        if role not in ROLES:
            print(f"  Pick one of: {', '.join(ROLES)}")
    ws.update_player(name=name, role=role)
    ws.grant_starting_loadout(role)
    ws.update_session(
        current_scene=f"{name} the {role} has just arrived in Greyhold, "
        "the last Guild town before the Greymark, stepping into the Ashen Flagon."
    )
    ws.save_state()
    print(f"\n  Logged. {name} the {role}. The Ashen Flagon is loud and warm.\n")


def opening_scene(ws: WorldState) -> None:
    s = ws.get_state()
    print(
        f"\nYou are {s['player']['name']}, a {s['player']['role']} newly arrived in "
        "Greyhold. The Ashen Flagon sits across from the Guild Hall — contracts get "
        "picked up here, rumors get traded, and Wardens drink before heading into "
        "the Greymark. The room is full. Somewhere a story is being told about "
        "Ashwatch Post going silent.\n\n"
        "What do you do? (type 'quit' to stop — your progress is saved every turn)\n"
    )


def main() -> None:
    print(BANNER)
    ws = WorldState()
    dm = DMAgent(ws)

    if not ws.get_field("player.name"):
        create_character(ws)
    else:
        print(
            f"  Welcome back, {ws.get_field('player.name')} "
            f"the {ws.get_field('player.role')}. Turn {ws.get_field('session.turn')}.\n"
        )

    opening_scene(ws)

    while True:
        try:
            action = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nThe saga waits. State saved.")
            break
        if not action:
            continue
        if action.lower() in ("quit", "exit"):
            print("\nThe saga waits. State saved.")
            break
        try:
            print("\n" + dm.run_turn(action) + "\n")
        except Exception as exc:  # turn already rolled back inside run_turn
            print(f"\n[The turn faltered and was rolled back — state is unchanged.]\n{exc}\n")
            continue
        if dm.game_over:
            print("=" * 57)
            print("  Your saga ends here. The Greymark keeps what it takes.")
            print("=" * 57)
            break


if __name__ == "__main__":
    main()
