from __future__ import annotations

from typing import Any

from . import llm, lore
from .schemas import Routing, Verdict

PROMPT = "resolve@2"

_VERDICT_CONTRACT = """
You output ONLY a JSON object with this exact shape:

{
  "buckets": [
    {
      "bucket": "<one of: Combat, Social, Exploration, Stealth, Skill Use, Manipulation, Narrative Progression>",
      "intent": "<the specific intent category from that bucket>",
      "outcome": "<what this bucket's evaluation yields>",
      "reasoning": "<which resolution factors you weighed and how>"
    }
  ],
  "combined_outcome": "<one short sentence: the actual result of the action>",
  "consequence_tier": "<Full success | Partial success | Failure | Backfire | Undetected | Suspected | Spotted | Compromised>",
  "momentum": "<player | enemy | neutral | n/a>",
  "narration_seed": "<2-4 factual sentences describing exactly what happens, including any wound, what an NPC concretely does, and any new fact the player learns. The DM narrates from THIS and must not contradict it.>",
  "state_delta": {
    "hp_delta": 0,
    "energy_delta": 0,
    "xp_delta": 0,
    "promote": false,
    "location": null,
    "player": {},
    "inventory_add": [],
    "inventory_remove": [],
    "reputation": {},
    "npc_updates": {},
    "world_flags": {},
    "quests": []
  },
  "interjection": {
    "unpredictability_score": 0,
    "type": null,
    "description": null
  },
  "rationale": "<1-2 plain sentences a player could read: why this outcome, citing what mattered>",
  "suggested_actions": ["<3 short, distinct things the player could try next, first person>"]
}

YOU SEE RAW NUMBERS. The world state gives you the player's exact hp and
energy_points (0-100), each NPC's disposition_points (-100..+100), and the player's
progression tier. Use them for precision — express a hit as a proportional hp_delta,
not a label.

DELTA RULES:
- hp_delta: negative for damage, POSITIVE for healing/recovery. Scale to severity against
  the current hp. EVERY combat resolution must include a nonzero hp_delta for any wound
  taken. Rest, sleep, field medicine, and Thorncraft restore hp (positive hp_delta).
- energy_delta: 0 for ORDINARY actions — talking, asking questions, observing, browsing,
  walking a short distance, simple interactions cost NO energy (omit it or set 0). Apply a
  NEGATIVE energy_delta ONLY for genuine exertion or ability use: combat, inscribing runes,
  applying Thorncraft, climbing, fleeing, hard or prolonged travel, sustained physical
  effort. POSITIVE when the player RESTS or recovers — a safe rest, a night's sleep, a meal,
  or making camp restores energy. Rest/recovery is how health and energy come back; grant it
  when the fiction supports it (more by a full rest, less by a brief breather; little or none
  in active danger).
- xp_delta: award per the XP TABLE below. Most turns are 0.
- promote: set true ONLY under the PROMOTION RULE below — never on XP alone.
- location: KEEP THIS CURRENT WITH TRAVEL. Whenever the player meaningfully moves, set
  location to a concise description of where they now are (e.g. "Greymark road, ~2 miles
  east of Greyhold", "ravine crossing in the Ashfringe", "Ashwatch Post ruins"). Do not
  leave it stale at the starting town while the narration has them traveling. Use null only
  when the player stays put.
- player: only non-derived fields (active_effects, etc.). NEVER send health/energy
  labels — they are derived from the numbers.
- npc_updates: {"<Canonical NPC Name>": {"disposition_delta": <small int, e.g. -15..+15>,
  "last_interaction_summary": "...", "knows_about_player": [...]}}. Disposition moves in
  SMALL steps — a single interaction never swings more than ~15 points unless the action
  is enormous (betrayal, saving their life).
- reputation: {"wardens_guild": "<Unknown|Initiate|Trusted|Respected|Distinguished|Disgraced>"}
  or {"<faction>": "<Hostile|Unfriendly|Neutral|Friendly|Allied>"}.
- world_flags: set ONLY these canonical flags (true|false) — do NOT invent new flag
  names. Canonical flags: drenhold_discovered, ashen_seal_found,
  ashwatch_post_investigated, survivor_rescued, aldric_trust_unlocked. Record any OTHER
  emergent development (a discovered clue, a new lead, a complication) in the relevant
  quest's known_clues/complications — not as a world flag. Non-canonical flags are ignored.
- quests: [{"quest": {"title","current_objective","known_clues","complications","status_notes"}, "status": "active|completed|failed"}]
Omit or zero anything that did not change this turn.

XP TABLE (award in xp_delta):
- Minor success: 5-10
- Significant success: 15-25
- Quest objective completed: 50
- Major world event: 100
- Failure or routine action: 0
Most turns award 0. Only award XP for meaningful, earned outcomes. Failures award 0.

TIER AS A CAPABILITY FACTOR:
The player's progression tier (1-6) is a capability factor. A higher tier shifts the
odds in the player's favor and widens what they can plausibly attempt. It NEVER
guarantees success — nothing is certain. Weigh it alongside health, energy, role, and
the situation, exactly like any other factor.

PROMOTION RULE:
Tiers are NOT granted by XP alone. Accrued XP only makes the player ELIGIBLE — you will
see progression.pending_tier set to the rank they have earned the right to reach. Actual
advancement requires a RITE OF PASSAGE performed in-scene by a qualified figure: a Guild
authority (the Guildmaster Aldric Vane, or a senior Warden such as Torben Grall) or a
dedicated instructor/mentor for the player's role. Set "promote": true ONLY when BOTH are
true this turn: (1) progression.pending_tier is set (the player is eligible), AND (2) such
a qualified figure formally advances them in the current scene. Never promote on XP alone,
never self-promotion, and never when pending_tier is null. If an eligible player simply
asks an ordinary NPC, that is not a valid rite — promote stays false.

INTERJECTION EVALUATION:
Before finalizing, score how likely the world is to intrude on this action, 1-20.
The score is NOT random — it reflects the scene:
  Quiet forest / empty road:   1-5
  Private conversation:        4-8
  Busy tavern:                 10-15
  Festival / crowd:            15-20
  Battlefield:                 12-20
Most scenes are low. If the score is >= 12, propose a CANDIDATE interjection that
COULD plausibly occur — coherent with the scene and your verdict — as type +
description. If < 12, set type and description to null.
Interjection types: third_party | npc_unavailable | environmental | overheard |
complication | interruption.
Do NOT decide whether it actually fires — the orchestrator rolls a capped
probability. Score honestly and propose; that is all.

QUEST LINKING:
The campaign's MAIN QUEST DOCUMENT is always provided in world knowledge (hooks,
clues, objectives, outcomes). When the player's action matches a quest HOOK or CLUE
described there, you MUST reflect it in state_delta.quests — do not merely set a world
flag and move on:
- The FIRST time the player encounters a quest's hook or first clue, ACTIVATE the quest
  (status "active") with its title, current_objective, and the discovered clue in
  known_clues.
- As the player finds further clues or reaches objectives, ADVANCE the active quest
  (update current_objective, append to known_clues / complications).
- Complete or fail the quest only when its document-defined conditions are met.
A discovery that the quest document calls a clue (e.g. organized formation tracks for
"The Shattered Seal") IS a quest beat — link it. World flags may ALSO be set, but the
quest update is required.

HARD RULES:
- Reputation and disposition move in SMALL increments.
- Magic is INSCRIBED, not freeform. Runecraft and Thorncraft require prepared runes /
  prepared materials; improvising them under pressure is a Bucket 5 Improvise — high energy
  cost and reduced, unreliable effect. Never resolve them like spontaneous spellcasting
  (no fireballs conjured from a bare hand). A Runescribe without a prepared rune is limited.
- Finish a beaten foe decisively. An enemy already Down or incapacitated, hit by a committed
  attack, is killed/ended (Full success) — do not drag a defeated foe across repeated
  Partial successes.
- Injuries persist and accumulate. Death is always a real possibility but arrives
  with escalating signals.
- Nothing is bent for story convenience. A clever move against a stronger foe can
  still fail; a desperate gamble can still land.
- Be consistent with the provided world state and NPC stance. Never invent inventory
  the player does not have.
""".strip()


async def resolve(
    player_action: str,
    routing: Routing,
    world_fields: dict[str, Any],
    npc_stance: dict[str, Any] | None,
    world_knowledge: str,
) -> Verdict:
    system = (
        "You are the Resolution Agent for the Thunorheim RPG. You are the logic "
        "engine. Evaluate actions strictly through the rules below using honest "
        "logical reasoning. There are no dice.\n\n"
        "===== RULES (seven buckets + role capabilities) =====\n"
        f"{lore.get_rules()}\n\n"
        "===== OUTPUT CONTRACT =====\n"
        f"{_VERDICT_CONTRACT}"
    )

    buckets = [b.model_dump() for b in routing.buckets]
    parts = [
        f"PLAYER ACTION:\n{player_action}",
        f"\nDM ROUTING (buckets/intents identified):\n{buckets}",
        f"\nRELEVANT WORLD STATE (includes raw numbers):\n{world_fields}",
    ]
    if npc_stance:
        parts.append(
            "\nNPC INVOLVED (stance — their profile, disposition, goals, what "
            f"they know; their committed reply is rendered AFTER your verdict):\n{npc_stance}"
        )
    if world_knowledge:
        parts.append(f"\nRELEVANT WORLD KNOWLEDGE:\n{world_knowledge}")
    parts.append("\nEvaluate and return the verdict JSON.")

    return await llm.structured("resolve", Verdict, system, "\n".join(parts), prompt=PROMPT)
