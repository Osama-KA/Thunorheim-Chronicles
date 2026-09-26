"""DM Agent — the orchestrator and the voice of the world.

Every turn starts and ends here. There is no separate game loop; the DM Agent
drives the pipeline dynamically. The routing decision (call 1) chooses the shape
of the turn — there is NO fixed agent order:

  * No NPC involved  -> route -> resolve -> narrate
  * Existing NPC     -> route -> load NPC -> resolve -> NPC render -> narrate
  * New NPC          -> route -> create NPC from template -> resolve ->
                        NPC render -> narrate
  * Overreach        -> route -> short-circuit with a warning (no state change)

Number visibility: the DM and NPC agents only ever receive LABELS (Hurt, Drained,
Friendly, "Tracker"). The Resolution Agent receives the raw NUMBERS (hp,
energy_points, disposition_points, tier) so it can reason with precision.

The whole turn runs inside a World State transaction; any failure rolls it back so
state never ends up half-updated.
"""

from __future__ import annotations

import copy
import random

from . import foundry, llm, npc_agent, resolution_agent
from .world_state import WorldState

# Seedable RNG for the interjection gate (so tests are deterministic).
_rng = random.Random()


def seed_interjections(seed: int) -> None:
    """Seed the interjection RNG. Tests call this; normal play leaves it unseeded."""
    _rng.seed(seed)


def interjection_probability(score: int) -> float:
    """Capped probability curve: 0 below 12, ramping to a 30% ceiling at 20."""
    if score < 12:
        return 0.0
    return min(0.30, 0.30 * (score - 11) / 9)


# --- Context views ------------------------------------------------------------
# DM/NPC get labels only; Resolution gets the numbers.

def _dm_fields(ws: WorldState) -> dict:
    s = ws.get_state()
    return {
        "player": {k: v for k, v in s["player"].items() if k not in ("hp", "energy_points")},
        "inventory": s["inventory"],
        "reputation": s["reputation"],
        "active_quests": s["quests"]["active"],
        "world_flags": s["world_flags"],
        "rank": s["progression"]["title"],  # label only — no tier/xp numbers
        "session": s["session"],
    }


def _resolution_fields(ws: WorldState) -> dict:
    s = ws.get_state()
    return {
        "player": s["player"],            # full, with hp + energy_points
        "inventory": s["inventory"],
        "reputation": s["reputation"],
        "active_quests": s["quests"]["active"],
        "world_flags": s["world_flags"],
        "progression": s["progression"],  # full, with tier + xp
        "session": s["session"],
    }


def route(player_action: str, ws: WorldState) -> dict:
    """Call 1: classify intent, detect overreach, decide NPC involvement and which
    world knowledge to pull."""
    s = ws.get_state()
    met = list(s["npcs_met"].keys())
    system = (
        "You are the DM Agent for the Thunorheim RPG — orchestrator and intent "
        "classifier. Read the player's action and produce a routing decision. "
        "Do not narrate yet.\n\n"
        "FIRST, OVERREACH CHECK. The player controls ONLY their own character — "
        "their actions, intentions, words, and dialogue. The WORLD (what creatures "
        "appear, what NPCs do, what the environment does, what happens as a result) "
        "is the DM's to decide. Set overreach_detected=true ONLY when the player "
        "AUTHORS THE WORLD AS FACT — narrating events happening around them rather "
        "than what their own character does.\n"
        "  OVERREACH (reject): 'A Greywalker appears and attacks me', 'The guard "
        "suddenly agrees and opens the gate', 'An explosion rocks the building'.\n"
        "  NOT overreach (allow): 'I draw my blade and attack the guard' (a valid "
        "attempt — Resolution decides if it lands), 'I tell Aldric a Greywalker is "
        "on the east road' (the character speaking), 'I ask Maren if survivors saw "
        "monsters', 'I sit at a table', 'I climb the wall' (using ordinary existing "
        "scenery), 'I try to knock the guard out' (an attempt, not a declared "
        "result).\n"
        "Do NOT flag the player for claiming an OUTCOME ('I kill it') — that is just "
        "an attempt; Resolution rules the real result. Flag ONLY world/NPC/"
        "environment authoring. When in doubt, allow.\n"
        "If overreach_detected is true, quote the offending fragment in "
        "overreach_explanation and set buckets=[], npc_involved=false.\n\n"
        "The seven buckets are: Combat, Social, Exploration, Stealth, Skill Use, "
        "Manipulation, Narrative Progression. An action may touch several.\n\n"
        "Decide whether a specific NPC is involved. An NPC is a SAPIENT character "
        "who can communicate. Corrupted creatures, monsters, and animals (e.g. a "
        "Greywalker) are NOT NPCs: they have no dialogue and are resolved through "
        "the Combat bucket. For those set npc_involved=false. If a sapient NPC is "
        "involved, give the exact reference the player used. Decide which world-"
        "knowledge topics the Resolution Agent will need (any of: world, location, "
        "quest, companions, factions, artifact, monster).\n\n"
        f"CHARACTERS ALREADY MET: {met or 'none yet'}\n\n"
        "Output ONLY this JSON:\n"
        "{\n"
        '  "overreach_detected": true|false,\n'
        '  "overreach_explanation": "quote the authored fragment and why, or null",\n'
        '  "buckets": [{"bucket":"...","intent":"...","why":"..."}],\n'
        '  "npc_involved": true|false,\n'
        '  "npc_reference": "the words the player used for them, or null",\n'
        '  "knowledge_topics": ["..."],\n'
        '  "scene_note": "one line on where the player is and what is happening"\n'
        "}"
    )
    user = f"PLAYER ACTION:\n{player_action}\n\nCURRENT STATE:\n{_dm_fields(ws)}"
    return llm.chat_json(system, user, caller="dm")


def narrate(
    player_action: str,
    verdict: dict,
    npc_reply: str | None,
    events: list[dict],
    interjection: dict | None,
    ws: WorldState,
) -> str:
    """Call 2: narrate the outcome to the player, faithful to the verdict."""
    tier_up = next((e for e in events if e.get("type") == "tier_up"), None)
    promo_available = next((e for e in events if e.get("type") == "promotion_available"), None)
    death = any(e.get("type") == "death" for e in events)

    system = (
        "You are the DM Agent for the Thunorheim RPG — the voice of the world and "
        "the only thing the player ever sees. Narrate the outcome of the player's "
        "action in second person, in Thunorheim's grounded, weary dark-fantasy "
        "tone.\n\n"
        "ABSOLUTE RULE: the Resolution Verdict is ground truth. Narrate exactly the "
        "outcome and tier it specifies. NEVER upgrade a failure into a success or "
        "soften a backfire. If an NPC reply is provided, weave it in without "
        "contradicting it.\n"
        "DIALOGUE: put every character's spoken words inside double quotation marks "
        '("like this") so speech reads clearly apart from the narration.\n\n'
        "ASSEMBLY ORDER (keep it tight, 1-3 short paragraphs):\n"
        "1. Narrate the resolved outcome (and the NPC's reply if any).\n"
        "2. If an interjection is provided, weave it in as the world intruding — a "
        "third party, a complication, something shifting. It is the WORLD acting.\n"
        "3. If a tier-up is provided, mark it as a brief earned beat (a sense of "
        "growth), not a game menu.\n"
        "4. If death is provided, narrate it with finality.\n"
        "Keep the prose vivid but economical — each turn should MOVE THE SCENE FORWARD. "
        "Do not restate or recycle imagery, phrases, or beats from earlier turns, and "
        "don't pad a small outcome into a wall of text.\n"
        "Do not show stats, numbers, or JSON. End at a point that invites the "
        "player's next action (unless they died)."
    )
    user = (
        f"PLAYER ACTION:\n{player_action}\n\n"
        f"RESOLUTION VERDICT (ground truth):\n"
        f"- outcome: {verdict.get('combined_outcome')}\n"
        f"- tier: {verdict.get('consequence_tier')}\n"
        f"- momentum: {verdict.get('momentum')}\n"
        f"- what happens: {verdict.get('narration_seed')}\n"
    )
    if npc_reply:
        user += f"\nNPC IN-CHARACTER REPLY (honor this):\n{npc_reply}\n"
    if interjection:
        user += (
            f"\nWORLD INTERJECTION (fired — weave in): type={interjection.get('type')}; "
            f"{interjection.get('description')}\n"
        )
    if tier_up:
        user += f"\nTIER-UP (mark as a beat): the character is now a {tier_up.get('title')}.\n"
    if promo_available:
        user += (
            "\nPROMOTION AVAILABLE (hint subtly, do not state mechanics): the character "
            f"has grown enough to earn the rank of {promo_available.get('title')}, but must "
            "be formally advanced by a qualified mentor or Guild authority — they cannot "
            "promote themselves. Convey a sense of readiness, not a menu.\n"
        )
    if death:
        user += "\nDEATH: the player character has died. Narrate the end.\n"
    user += "\nNarrate."
    return llm.chat(system, user, caller="dm")


class DMAgent:
    """Orchestrates one turn end to end."""

    def __init__(self, ws: WorldState):
        self.ws = ws
        self.game_over = False
        self.last_trace: dict = {}  # per-turn telemetry for the UI trace panel

    def recap(self) -> str:
        """A short DM-voice 'story so far' from current state, for the Continue flow."""
        s = self.ws.get_state()
        p = s["player"]
        quests = [f"{q['title']} — {q.get('current_objective', '')}" for q in s["quests"]["active"]]
        system = (
            "You are the DM Agent for the Thunorheim RPG. In 2-3 sentences, second person, "
            "in the world's grounded weary dark-fantasy tone, remind the player where their "
            "story stands so they can pick it back up. No stats or lists — just the thread."
        )
        user = (
            f"PLAYER: {p['name']}, a {p['role']} ({s['progression']['title']}).\n"
            f"LOCATION: {p['location']}. Condition: {p['health']}, {p['energy']}.\n"
            f"LAST SCENE: {s['session'].get('last_scene_summary', '')}\n"
            f"CURRENT SCENE: {s['session'].get('current_scene', '')}\n"
            f"ACTIVE QUESTS: {quests or 'none yet'}\n"
            f"OPEN THREADS: {s['session'].get('open_threads', [])}\n"
            f"PEOPLE MET: {list(s['npcs_met'].keys()) or 'no one yet'}\n\n"
            "Give the 'story so far' recap."
        )
        return llm.chat(system, user, caller="dm")

    def _overreach_message(self, player_action: str, routing: dict) -> str:
        explanation = routing.get("overreach_explanation") or (
            "World events are the DM's domain, not the player's."
        )
        return (
            "!!! PLAYER OVERREACH DETECTED\n\n"
            f'You narrated a world event - "{player_action}".\n'
            "The world is the DM's to describe, not yours.\n\n"
            f"{explanation}\n\n"
            "Tell me what YOUR character does. The world will respond."
        )

    def _roll_interjection(self, interjection: dict) -> dict | None:
        score = interjection.get("unpredictability_score") or 0
        description = interjection.get("description")
        if score < 12 or not description:
            return None
        if _rng.random() < interjection_probability(score):
            return {"type": interjection.get("type"), "description": description, "score": score}
        return None

    def run_turn(self, player_action: str) -> str:
        ws = self.ws

        # --- Call 1: route (BEFORE the transaction, so overreach writes nothing) --
        routing = route(player_action, ws)
        if routing.get("overreach_detected"):
            self.last_trace = {"agents": ["DM · route"], "overreach": True,
                               "tier": None, "buckets": [], "momentum": None,
                               "interjection": {"score": None, "fired": False},
                               "events": [], "npc": None}
            return self._overreach_message(player_action, routing)

        ws.begin_turn()
        try:
            # --- NPC: load existing or create new (no dialogue yet) -----------
            npc_ctx = None
            if routing.get("npc_involved") and routing.get("npc_reference"):
                npc_ctx = npc_agent.ensure_npc(
                    routing["npc_reference"], routing.get("scene_note", ""), ws,
                    active_npc=ws.get_field("session.active_npc"),
                )

            # --- Pull the world knowledge the verdict needs -------------------
            # The main quest is ALWAYS injected so Resolution can link a discovery
            # to quest activation/advancement, regardless of what route() requested.
            knowledge_parts = [foundry.get_main_quest()]
            topics = [t for t in (routing.get("knowledge_topics") or []) if t != "quest"]
            if topics:
                extra = foundry.query_world_knowledge(player_action, topics=topics)
                if extra:
                    knowledge_parts.append(extra)
            knowledge = "\n\n---\n\n".join(p for p in knowledge_parts if p)

            # --- Resolution: numeric view (+ the involved NPC's numbers) -------
            res_fields = _resolution_fields(ws)
            if npc_ctx:
                st = npc_ctx["sheet"]["state"]
                res_fields["involved_npc"] = {
                    "name": npc_ctx["sheet"]["profile"].get("name"),
                    "disposition_points": st.get("disposition_points"),
                    "disposition": st.get("disposition_toward_player"),
                }
            verdict = resolution_agent.resolve(
                player_action=player_action,
                routing=routing,
                world_fields=res_fields,
                npc_stance=npc_ctx["stance"] if npc_ctx else None,
                world_knowledge=knowledge,
            )
            events = ws.apply_delta(verdict.get("state_delta") or {})

            # --- Interjection: orchestrator rolls the capped probability ------
            interjection = self._roll_interjection(verdict.get("interjection") or {})

            # --- NPC render: voice the reaction (labels only — strip numbers) -
            npc_reply = None
            if npc_ctx:
                sheet = copy.deepcopy(npc_ctx["sheet"])
                sheet["state"].pop("disposition_points", None)
                npc_reply = npc_agent.render(
                    sheet, verdict, routing.get("scene_note", ""), player_action
                )

            # --- Call 2: narrate ----------------------------------------------
            prose = narrate(player_action, verdict, npc_reply, events, interjection, ws)

            # --- Session continuity, then commit the turn ---------------------
            ws.increment_turn()
            session_update = {
                "current_scene": routing.get("scene_note", ws.get_field("session.current_scene")),
                "last_scene_summary": verdict.get("narration_seed", ""),
            }
            if npc_ctx:  # remember who the player is talking to, for next turn's pronouns
                session_update["active_npc"] = npc_ctx["sheet"]["profile"].get("name", "")
            ws.update_session(**session_update)
            ws.commit()

            if any(e.get("type") == "death" for e in events):
                self.game_over = True

            # --- Trace for the UI panel (which agents fired + verdict peek) ----
            npc_name = npc_ctx["sheet"]["profile"].get("name") if npc_ctx else None
            agents_fired = ["DM · route"]
            if npc_ctx:
                agents_fired.append(f"NPC · ensure ({npc_name})")
            agents_fired.append("Resolution")
            if npc_ctx:
                agents_fired.append("NPC · render")
            agents_fired.append("DM · narrate")
            self.last_trace = {
                "agents": agents_fired,
                "overreach": False,
                "tier": verdict.get("consequence_tier"),
                "buckets": [f"{b.get('bucket')}/{b.get('intent')}"
                            for b in (verdict.get("buckets") or [])],
                "momentum": verdict.get("momentum"),
                "interjection": {
                    "score": (verdict.get("interjection") or {}).get("unpredictability_score"),
                    "fired": interjection is not None,
                },
                "events": [e.get("type") for e in events],
                "npc": npc_name,
            }
            return prose

        except Exception:
            ws.rollback()
            raise
