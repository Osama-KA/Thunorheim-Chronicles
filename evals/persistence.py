"""Final persistence test — one long, continuous, reactive 75-turn playthrough
through the real Foundry pipeline.

A goal-driven AI player pursues the Ashwatch Post / Shattered Seal arc. Mid-run we
tear down and rebuild WorldState/DMAgent from the save file (cross-session
persistence), and at a few points we deliberately return to an early NPC (memory
callbacks). Per-turn persistence assertions run throughout; a transcript and a
persistence summary are written to pipeline_runs/.

Run: uv run python evals/persistence.py
"""

from __future__ import annotations

import json
import os
import tempfile
import traceback

import thunorheim.dm_agent as dm_agent
import thunorheim.llm as llm
import thunorheim.npc_agent as npc_agent
import thunorheim.resolution_agent as resolution_agent
from thunorheim.world_state import (
    WorldState,
    derive_disposition,
    derive_energy,
    derive_health,
    title_for,
)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline_runs")
os.makedirs(OUT_DIR, exist_ok=True)
SIM_MODEL = os.environ["AZURE_AI_MODEL_DEPLOYMENT"]
CANONICAL_FLAGS = {
    "drenhold_discovered", "ashen_seal_found", "ashwatch_post_investigated",
    "survivor_rescued", "aldric_trust_unlocked",
}
N_TURNS = 75
RELOAD_AT = 38
CALLBACKS = {25, 50, 70}
SEED = 99
NAME, ROLE = "Edwyn Carr", "Warden"
GOAL = ("investigate why Ashwatch Post went silent (the Shattered Seal): gather word in "
        "Greyhold, talk to people, travel east into the Greymark, find and follow clues, "
        "fight only when forced, and rest when worn down")

# --- telemetry capture --------------------------------------------------------
CAP: dict = {}
_orig_route = dm_agent.route
_orig_resolve = resolution_agent.resolve
_orig_ensure = npc_agent.ensure_npc


def _w_route(*a, **k):
    r = _orig_route(*a, **k)
    CAP["routing"] = r
    return r


def _w_resolve(*a, **k):
    v = _orig_resolve(*a, **k)
    CAP["verdict"] = v
    return v


def _w_ensure(*a, **k):
    r = _orig_ensure(*a, **k)
    CAP["npc_resolved"] = r["sheet"]["profile"].get("name")
    return r


dm_agent.route = _w_route
resolution_agent.resolve = _w_resolve
npc_agent.ensure_npc = _w_ensure


# --- goal-driven player simulator --------------------------------------------
def simulate_player(ws: WorldState, last_narration: str) -> str:
    s = ws.get_state()
    quests = [f"{q['title']}: {q.get('current_objective','')}" for q in s["quests"]["active"]]
    system = (
        f"You are role-playing the PLAYER, {NAME}, a {ROLE} in Thunorheim (grim Norse dark "
        "fantasy). Output ONE short in-character action in FIRST PERSON (1-2 sentences), "
        "reacting to what just happened and keeping the story continuous.\n"
        f"YOUR GOAL: {GOAL}.\n"
        "STRICT: describe ONLY what your character does, says, or attempts — NEVER narrate "
        "the world, other characters' actions, or outcomes. Act consistently with your past. "
        "When badly worn or wounded, choose to rest. Vary what you do; make real progress."
    )
    user = (
        f"LOCATION: {s['player']['location']} | Condition: {s['player']['health']}, {s['player']['energy']}\n"
        f"ACTIVE QUEST: {quests or 'none yet'}\n"
        f"PEOPLE MET: {list(s['npcs_met'].keys()) or 'no one yet'}\n\n"
        f"WHAT JUST HAPPENED (DM):\n{last_narration}\n\nYour next action:"
    )
    for attempt in range(3):
        try:
            r = llm._openai_client().chat.completions.create(
                model=SIM_MODEL,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            out = (r.choices[0].message.content or "").strip()
            if out:
                return out
        except Exception:
            if attempt == 2:
                raise
    return "I take stock of my surroundings and steady myself for what comes next."


# --- snapshot + assertions ----------------------------------------------------
def snapshot(ws: WorldState) -> dict:
    s = ws.get_state()
    p, prog = s["player"], s["progression"]
    return {
        "turn": s["session"]["turn"], "hp": p["hp"], "health": p["health"],
        "ep": p["energy_points"], "energy": p["energy"], "location": p["location"],
        "xp": prog["xp"], "tier": prog["tier"], "title": prog["title"], "pending": prog["pending_tier"],
        "inv": list(s["inventory"]),
        "npcs": {n: (d["state"]["disposition_toward_player"], d["state"]["disposition_points"],
                     bool(d["state"].get("last_interaction_summary"))) for n, d in s["npcs_met"].items()},
        "quests": {q["title"]: (q.get("current_objective", ""), len(q.get("known_clues", [])))
                   for q in s["quests"]["active"]},
        "done_quests": [q["title"] for q in s["quests"]["completed"]],
        "flags": sorted(k for k, v in s["world_flags"].items() if v),
        "rep": s["reputation"]["wardens_guild"],
    }


def assert_turn(turn, kind, pre, post, prose, results):
    def chk(name, ok, detail=""):
        results.append((turn, name, bool(ok), detail))

    overreach = (CAP.get("routing") or {}).get("overreach_detected")
    if overreach:
        chk("turn_frozen_on_overreach", post["turn"] == pre["turn"] and post["hp"] == pre["hp"])
        return
    chk("turn_increment", post["turn"] == pre["turn"] + 1, f"{pre['turn']}->{post['turn']}")
    chk("health_sync", 0 <= post["hp"] <= 100 and derive_health(post["hp"]) == post["health"]
        and 0 <= post["ep"] <= 100 and derive_energy(post["ep"]) == post["energy"],
        f"hp{post['hp']}={post['health']} ep{post['ep']}={post['energy']}")
    chk("npc_integrity",
        all(-100 <= dp <= 100 and derive_disposition(dp) == lbl for lbl, dp, _ in post["npcs"].values())
        and len(post["npcs"]) >= len(pre["npcs"]),
        f"{len(post['npcs'])} npcs")
    chk("canonical_flags", set(post["flags"]) <= CANONICAL_FLAGS, str(post["flags"]))
    chk("progression", 1 <= post["tier"] <= 6 and post["title"] == title_for(ROLE, post["tier"])
        and post["xp"] >= pre["xp"] and (post["pending"] is None or post["pending"] > post["tier"]),
        f"t{post['tier']} {post['title']} xp{post['xp']} pend{post['pending']}")
    # location must not silently reset to the start town once we've left it
    if pre["location"] not in ("Greyhold", "") and "greyhold" not in pre["location"].lower():
        chk("location_no_reset", post["location"] != "Greyhold", f"{pre['location']} -> {post['location']}")
    # mundane talk must not drain energy
    dom = ((CAP.get("verdict") or {}).get("buckets") or [{}])
    is_social_only = dom and all(b.get("bucket") in ("Social", "Narrative Progression") for b in dom)
    ed = ((CAP.get("verdict") or {}).get("state_delta") or {}).get("energy_delta") or 0
    if is_social_only:
        chk("no_energy_drain_on_talk", ed >= 0, f"energy_delta={ed} buckets={[b.get('bucket') for b in dom]}")
    if kind == "callback":
        early = CAP.get("_callback_name")
        chk("memory_callback_same_npc", CAP.get("npc_resolved") == early
            and early in post["npcs"] and len(post["npcs"]) == len(pre["npcs"]),
            f"resolved={CAP.get('npc_resolved')} expected={early}")


def main():
    tmp = os.path.join(tempfile.gettempdir(), "persist.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    ws = WorldState(tmp)
    ws.update_player(name=NAME, role=ROLE)
    ws.grant_starting_loadout(ROLE)
    ws.update_session(current_scene=f"{NAME} the {ROLE} has just arrived in Greyhold, stepping into the Ashen Flagon.")
    ws.save_state()
    dm_agent.seed_interjections(SEED)
    dm = dm_agent.DMAgent(ws)

    transcript = [f"# Persistence run — {NAME} the {ROLE}, {N_TURNS} turns\n"]
    results: list = []
    met_order: list = []
    last = ws.get_field("session.current_scene")
    reload_ok = None

    for turn in range(1, N_TURNS + 1):
        kind = None
        if turn in CALLBACKS and met_order:
            kind = "callback"
            early = met_order[0]
            action = (f"I seek out {early} again, reminding them of what passed between us before, "
                      "and press them for anything new on the silent outposts.")
        else:
            action = simulate_player(ws, last)

        CAP.clear()
        if kind == "callback":
            CAP["_callback_name"] = met_order[0]
        pre = snapshot(ws)
        try:
            prose = dm.run_turn(action)
        except Exception as exc:
            prose = f"[ERROR: {exc}]"
            results.append((turn, "RUN_TURN_EXCEPTION", False, repr(exc)))
            traceback.print_exc()
        post = snapshot(ws)
        for n in post["npcs"]:
            if n not in met_order:
                met_order.append(n)
        assert_turn(turn, kind, pre, post, prose, results)

        v = CAP.get("verdict") or {}
        tag = f"  [{kind}]" if kind else ""
        transcript.append(
            f"## Turn {turn}{tag}\n**Action:** {action}\n\n"
            f"**Verdict:** {v.get('consequence_tier')} | buckets="
            f"{[b.get('bucket') for b in (v.get('buckets') or [])]} | "
            f"hp_d={ (v.get('state_delta') or {}).get('hp_delta') } "
            f"e_d={ (v.get('state_delta') or {}).get('energy_delta') } "
            f"xp_d={ (v.get('state_delta') or {}).get('xp_delta') } "
            f"promote={ (v.get('state_delta') or {}).get('promote') }\n\n"
            f"{prose}\n\n"
            f"**State:** turn {post['turn']} | {post['health']}({post['hp']})/{post['energy']}({post['ep']}) "
            f"| {post['title']} t{post['tier']} xp{post['xp']} | @ {post['location']}\n"
            f"  npcs={post['npcs']}\n  quests={post['quests']} done={post['done_quests']} "
            f"flags={post['flags']} rep={post['rep']}\n\n---\n"
        )
        last = prose
        print(f"TURN {turn}/{N_TURNS} | {post['health']}/{post['energy']} t{post['tier']} "
              f"xp{post['xp']} npcs={len(post['npcs'])} @ {post['location'][:40]}", flush=True)

        if dm.game_over:
            transcript.append("\n**[GAME OVER — player died]**\n")
            print("GAME OVER — player died", flush=True)
            break

        if turn == RELOAD_AT:
            print("SAVE/RELOAD test…", flush=True)
            before = ws.get_state()
            ws.save_state()
            ws_re = WorldState(tmp)
            after = ws_re.get_state()
            reload_ok = json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)
            results.append((turn, "save_reload_deep_equal", reload_ok,
                            "state identical after reload" if reload_ok else "MISMATCH"))
            ws = ws_re
            dm = dm_agent.DMAgent(ws)  # fresh agent on reloaded state
            transcript.append(f"\n**[SAVE/RELOAD at turn {turn} — deep-equal: {reload_ok}]**\n\n---\n")
            print(f"SAVE/RELOAD deep-equal: {reload_ok}", flush=True)

    # summary
    fails = [r for r in results if not r[2]]
    final = snapshot(ws)
    lines = ["PERSISTENCE TEST SUMMARY", "=" * 30,
             f"Turns run: {final['turn']}",
             f"Assertions: PASS={sum(1 for r in results if r[2])} FAIL={len(fails)}",
             f"Save/reload deep-equal: {reload_ok}",
             f"Final: {final['health']}({final['hp']})/{final['energy']}({final['ep']}) "
             f"{final['title']} tier{final['tier']} xp{final['xp']} @ {final['location']}",
             f"NPCs met ({len(final['npcs'])}): " + ", ".join(
                 f"{n} {lbl}{('+' if pts>0 else '')}{pts}" for n, (lbl, pts, _) in final["npcs"].items()),
             f"Active quests: {final['quests']}",
             f"Completed quests: {final['done_quests']}",
             f"World flags: {final['flags']}",
             f"Guild reputation: {final['rep']}", "",
             "FAILURES:" if fails else "FAILURES: (none)"]
    lines += [f"  turn {t}: {n} :: {d}" for t, n, ok, d in fails]
    summary = "\n".join(lines)
    with open(os.path.join(OUT_DIR, "persistence_summary.txt"), "w", encoding="utf-8") as fh:
        fh.write(summary)
    with open(os.path.join(OUT_DIR, "transcript_persistence.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(transcript))
    print("\n" + summary + "\n\nPERSISTENCE DONE", flush=True)
    if os.path.exists(tmp):
        os.remove(tmp)


if __name__ == "__main__":
    main()
