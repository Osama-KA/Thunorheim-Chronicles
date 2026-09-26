"""Full-pipeline stress test — three continuous 10-turn runs (social / combat /
exploration) through the real Foundry agents.

Each run is reactive: a player-simulator LLM reads the running narration and emits
the next in-character action, with a few crafted hard actions injected at fixed
turns to stress the Resolution Agent. Per-turn telemetry is captured via harness-
side wrappers (no source edits), automated assertions run every turn, and a
transcript + assertion summary are written to pipeline_runs/.

Run: uv run python evals/stress.py
"""

from __future__ import annotations

import asyncio
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
CANONICAL_FLAGS = {
    "drenhold_discovered",
    "ashen_seal_found",
    "ashwatch_post_investigated",
    "survivor_rescued",
    "aldric_trust_unlocked",
}
ALLOWED_TIERS = {
    "Full success",
    "Partial success",
    "Failure",
    "Backfire",
    "Undetected",
    "Suspected",
    "Spotted",
    "Compromised",
}

# --- Telemetry capture --------------------------------------------------------
CAP: dict = {}
_orig_route = dm_agent.route
_orig_resolve = resolution_agent.resolve
_orig_dm_fields = dm_agent._dm_fields
_orig_render = npc_agent.render


async def _w_route(*a, **k):
    r = await _orig_route(*a, **k)
    CAP["routing"] = r.model_dump()
    return r


async def _w_resolve(*a, **k):
    v = await _orig_resolve(*a, **k)
    CAP["verdict"] = v.model_dump()
    return v


def _w_dm_fields(ws):
    r = _orig_dm_fields(ws)
    CAP["dm_fields"] = r
    return r


async def _w_render(sheet, *a, **k):
    CAP["npc_sheet"] = sheet
    return await _orig_render(sheet, *a, **k)


dm_agent.route = _w_route
resolution_agent.resolve = _w_resolve
dm_agent._dm_fields = _w_dm_fields
npc_agent.render = _w_render


# --- Player simulator ---------------------------------------------------------
def simulate_player(role: str, theme: str, scene: str, last_narration: str) -> str:
    system = (
        "You are role-playing the PLAYER in a turn-based text RPG set in Thunorheim, a "
        "grim Norse dark-fantasy frontier. Output ONE short in-character action in FIRST "
        f"PERSON (1-2 sentences) for your character, a {role}. React to what just "
        "happened — keep the scene continuous.\n"
        "STRICT RULES: describe ONLY what YOUR character does, says, or attempts. NEVER "
        "narrate the world, other characters' actions, or the outcome (do not write 'a "
        "guard appears', 'the door opens', or 'I succeed'). No meta-commentary. "
        f"Stay on theme: {theme}."
    )
    user = (
        f"CURRENT SCENE: {scene}\n\nWHAT JUST HAPPENED (DM):\n{last_narration}\n\nYour next action:"
    )
    for attempt in range(3):
        try:
            out = asyncio.run(llm.text("sim", system, user, prompt="sim@1"))
            if out:
                return out
        except Exception:
            if attempt == 2:
                raise
    # never feed an empty action to the pipeline
    return "I steady myself and take stock of the situation around me."


# --- Run definitions ----------------------------------------------------------
# injections: {turn: (action, kind)}; kind drives expectation-specific assertions.
RUNS = [
    {
        "name": "combat",
        "role": "Warden",
        "seed": 11,
        "theme": "hunt and fight the corrupted creatures stalking the Greymark road",
        "opening": "I head out through the Greywall Gate into the Greymark, blade ready, "
        "tracking whatever has been moving on the road east.",
        "injections": {
            3: (
                "I pull a vial of greywater extract from my kit and hurl it at the nearest creature.",
                "absent_item",
            ),
            5: (
                "I kick a loose boulder down the slope to stagger it, then leap after and drive my blade into the vein lines on its flank.",
                "multibucket",
            ),
            8: (
                "Bleeding and slowed, I ignore the brightening veins and charge straight in for the kill.",
                "reckless",
            ),
            9: ("The Greywalker shudders and drops dead at my feet.", "overreach"),
        },
    },
    {
        "name": "social",
        "role": "Shroud",
        "seed": 22,
        "theme": "work the Ashen Flagon and Guild Hall — read people, gather information, build leverage",
        "opening": "I settle into a corner of the Ashen Flagon and start reading the room for who knows the most.",
        "injections": {
            4: (
                "I lean on the nervous stranger at the bar, implying I know a secret of theirs, to force them to talk.",
                "manip",
            ),
            7: (
                "I march up to Aldric and demand he hand over the classified outpost reports right now.",
                "demand",
            ),
            9: ("Aldric nods, unlocks his desk, and hands me the sealed dossier.", "overreach"),
        },
    },
    {
        "name": "exploration",
        "role": "Runescribe",
        "seed": 33,
        "theme": "travel east toward Ashwatch Post, investigating the road, terrain, and any signs",
        "opening": "I leave Greyhold through the Greywall Gate and head east down the road toward Ashwatch Post, watching the ground.",
        "injections": {
            2: (
                "I slow down and carefully search the road surface ahead for tracks or signs of passage.",
                "tracks",
            ),
            5: (
                "I throw out my hand and hurl a ball of fire at the dry scrub to clear the way.",
                "rolemismatch",
            ),
            7: (
                "Exhausted, I try to scramble across the crumbling Blight-rotted ravine ledge.",
                "hazard",
            ),
            9: (
                "A hidden door grinds open in the rock, revealing the gates of Drenhold.",
                "overreach",
            ),
        },
    },
]


# --- State snapshot -----------------------------------------------------------
def snapshot(ws: WorldState) -> dict:
    s = ws.get_state()
    p, prog = s["player"], s["progression"]
    return {
        "turn": s["session"]["turn"],
        "hp": p["hp"],
        "health": p["health"],
        "ep": p["energy_points"],
        "energy": p["energy"],
        "location": p["location"],
        "xp": prog["xp"],
        "tier": prog["tier"],
        "title": prog["title"],
        "pending_tier": prog["pending_tier"],
        "inventory": list(s["inventory"]),
        "npcs": {
            n: (d["state"]["disposition_toward_player"], d["state"]["disposition_points"])
            for n, d in s["npcs_met"].items()
        },
        "active_quests": [q["title"] for q in s["quests"]["active"]],
        "flags_set": sorted(k for k, v in s["world_flags"].items() if v),
    }


# --- Assertions ---------------------------------------------------------------
def run_assertions(run, turn, kind, pre, post, prose, results):
    def chk(name, ok, detail=""):
        results.append((run["name"], turn, name, bool(ok), detail))

    overreach = kind == "overreach"
    if overreach:
        chk(
            "F.overreach_short_circuit",
            prose.startswith("!!! PLAYER OVERREACH")
            and post["turn"] == pre["turn"]
            and post["hp"] == pre["hp"]
            and post["xp"] == pre["xp"]
            and len(post["npcs"]) == len(pre["npcs"]),
            f"turn {pre['turn']}->{post['turn']} hp {pre['hp']}->{post['hp']}",
        )
        return  # no further state-change assertions on a short-circuited turn

    chk("A.turn_increment", post["turn"] == pre["turn"] + 1, f"{pre['turn']}->{post['turn']}")
    chk(
        "B.health_sync",
        0 <= post["hp"] <= 100
        and 0 <= post["ep"] <= 100
        and derive_health(post["hp"]) == post["health"]
        and derive_energy(post["ep"]) == post["energy"],
        f"hp{post['hp']}={post['health']} ep{post['ep']}={post['energy']}",
    )
    npc_ok = all(
        -100 <= dp <= 100 and derive_disposition(dp) == lbl for lbl, dp in post["npcs"].values()
    )
    chk("C.npc_integrity", npc_ok and len(post["npcs"]) >= len(pre["npcs"]), str(post["npcs"]))
    chk("D.canonical_flags", set(post["flags_set"]) <= CANONICAL_FLAGS, str(post["flags_set"]))
    chk(
        "E.progression",
        1 <= post["tier"] <= 6
        and post["title"] == title_for(run["role"], post["tier"])
        and post["xp"] >= pre["xp"]
        and (post["pending_tier"] is None or post["pending_tier"] > post["tier"]),
        f"t{post['tier']} {post['title']} xp{post['xp']} pend{post['pending_tier']}",
    )

    verdict = CAP.get("verdict") or {}
    if verdict:
        chk(
            "H.verdict_schema",
            all(
                k in verdict
                for k in ("buckets", "combined_outcome", "consequence_tier", "narration_seed")
            )
            and verdict.get("consequence_tier") in ALLOWED_TIERS,
            str(verdict.get("consequence_tier")),
        )
    dmf = CAP.get("dm_fields") or {}
    leak = [k for k in ("hp", "energy_points") if k in (dmf.get("player") or {})]
    sheet = CAP.get("npc_sheet")
    sheet_leak = sheet is not None and "disposition_points" in sheet.get("state", {})
    chk(
        "I.number_isolation", not leak and not sheet_leak, f"dm_leak={leak} sheet_leak={sheet_leak}"
    )

    if kind == "absent_item":
        tier = verdict.get("consequence_tier")
        added = [i for i in post["inventory"] if "greywater" in i.lower()]
        chk("G.absent_item", tier != "Full success" and not added, f"tier={tier} added={added}")
    if kind == "tracks":
        chk(
            "J.quest_linking",
            "The Shattered Seal" in post["active_quests"],
            str(post["active_quests"]),
        )


# --- Transcript ---------------------------------------------------------------
def fmt_turn(turn, kind, action, prose, post):
    v = CAP.get("verdict") or {}
    sd = v.get("state_delta") or {}
    ij = v.get("interjection") or {}
    buckets = ", ".join(f"{b.get('bucket')}/{b.get('intent')}" for b in (v.get("buckets") or []))
    lines = [
        f"## Turn {turn}" + (f"  [INJECT: {kind}]" if kind else ""),
        f"**Action:** {action}",
        "",
        f"**Routing:** overreach={(CAP.get('routing') or {}).get('overreach_detected')} "
        f"npc={(CAP.get('routing') or {}).get('npc_involved')} "
        f"ref={(CAP.get('routing') or {}).get('npc_reference')}",
    ]
    if v:
        lines += [
            f"**Verdict:** {v.get('consequence_tier')} | momentum={v.get('momentum')} | buckets=[{buckets}]",
            f"**Deltas:** hp={sd.get('hp_delta')} energy={sd.get('energy_delta')} xp={sd.get('xp_delta')} "
            f"promote={sd.get('promote')} flags={sd.get('world_flags')} npc={list((sd.get('npc_updates') or {}).keys())}",
            f"**Interjection score:** {ij.get('unpredictability_score')}",
        ]
    lines += [
        "",
        "**DM narration:**",
        prose,
        "",
        f"**State after:** turn {post['turn']} | {post['health']}({post['hp']})/{post['energy']}({post['ep']}) "
        f"| {post['title']} t{post['tier']} xp{post['xp']} pend{post['pending_tier']} | @ {post['location']}",
        f"  npcs={post['npcs']}",
        f"  quests={post['active_quests']} | flags={post['flags_set']} | inv={post['inventory']}",
        "\n---\n",
    ]
    return "\n".join(lines)


# --- Driver -------------------------------------------------------------------
def run_one(run, results):
    tmp = os.path.join(tempfile.gettempdir(), f"pl_{run['name']}.json")
    if os.path.exists(tmp):
        os.remove(tmp)
    ws = WorldState(tmp)
    ws.update_player(name="Test Operative", role=run["role"])
    ws.grant_starting_loadout(run["role"])
    ws.update_session(
        current_scene=f"A {run['role']} in Greyhold, beginning a {run['name']} scenario."
    )
    ws.save_state()
    dm_agent.seed_interjections(run["seed"])
    dm = dm_agent.DMAgent(ws)

    transcript = [f"# Pipeline run: {run['name']}  (role: {run['role']})\n"]
    last = ws.get_field("session.current_scene")
    for turn in range(1, 11):
        if turn == 1:
            action, kind = run["opening"], None
        elif turn in run["injections"]:
            action, kind = run["injections"][turn]
        else:
            action, kind = (
                simulate_player(
                    run["role"], run["theme"], ws.get_field("session.current_scene"), last
                ),
                None,
            )
        CAP.clear()
        pre = snapshot(ws)
        try:
            prose = asyncio.run(dm.run_turn(action))
        except Exception as exc:
            prose = f"[ERROR: {exc}]"
            results.append((run["name"], turn, "RUN_TURN_EXCEPTION", False, repr(exc)))
            traceback.print_exc()
        post = snapshot(ws)
        run_assertions(run, turn, kind, pre, post, prose, results)
        transcript.append(fmt_turn(turn, kind, action, prose, post))
        last = prose
        if dm.game_over:
            transcript.append("\n**[GAME OVER — player died]**\n")
            break

    with open(os.path.join(OUT_DIR, f"transcript_{run['name']}.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(transcript))
    if os.path.exists(tmp):
        os.remove(tmp)


def main():
    results: list = []
    for run in RUNS:
        print(f"=== RUN: {run['name']} ===", flush=True)
        run_one(run, results)
        print(f"    {run['name']} done.", flush=True)

    # Summary
    by_run: dict = {}
    fails = []
    for rn, turn, name, ok, detail in results:
        by_run.setdefault(rn, [0, 0])
        by_run[rn][0 if ok else 1] += 0 if ok else 0
        by_run[rn][0] += 1 if ok else 0
        by_run[rn][1] += 0 if ok else 1
        if not ok:
            fails.append(f"  [{rn} t{turn}] {name}: {detail}")

    lines = ["PIPELINE ASSERTION SUMMARY", "=" * 30]
    for rn, (p, f) in by_run.items():
        lines.append(f"{rn:12s}  PASS={p}  FAIL={f}")
    lines.append("")
    lines.append(f"TOTAL FAILURES: {len(fails)}")
    lines += fails if fails else ["  (none)"]
    summary = "\n".join(lines)
    with open(os.path.join(OUT_DIR, "assertions_summary.txt"), "w", encoding="utf-8") as fh:
        fh.write(summary)
    print("\n" + summary, flush=True)
    print("\nPIPELINE_TEST DONE", flush=True)


if __name__ == "__main__":
    main()
