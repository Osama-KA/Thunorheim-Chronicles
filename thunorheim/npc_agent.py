"""NPC Agent — the consistency layer.

Two responsibilities, called by the DM Agent at two different points in a turn:

  ensure_npc(reference, situation, world_state)
      Resolve the player's reference ("the bartender") to a canonical entity.
      - If that entity is already in World State, load the existing sheet.
      - If it is a named lore character, build the sheet from world knowledge.
      - If it is genuinely new, pick a generation template and invent a sheet.
      New sheets are registered via World State create_npc(). Returns the sheet
      plus a stance (disposition, goals, what they know) — NO committed dialogue
      yet, because the Resolution Agent has not ruled the outcome.

  render(npc_sheet, verdict, situation, player_action)
      AFTER the Resolution Agent rules, voice the NPC's actual in-character
      response, conditioned on the verdict tier. Never decides mechanical
      outcomes — that is the Resolution Agent's job.
"""

from __future__ import annotations

from . import foundry, llm
from .world_state import WorldState, coerce_disposition

_LORE_NPCS = [
    "Aldric Vane",
    "Maren Ashveld",
    "Torben Grall",
    "Signe",
    "Edric Fenn",
    "Bram Ashford",
    "Lysa Vorn",
    "Edda Voss",
    "Castor Veld",
    "Kael Dunmore",
]


def ensure_npc(reference: str, situation: str, ws: WorldState, active_npc: str = "") -> dict:
    """Resolve, load-or-create, and return {sheet, stance, created}.

    `active_npc` is the canonical name of the character the player is currently in
    conversation with (from the previous turn). It anchors ambiguous references so a
    bare pronoun doesn't jump to the wrong character."""
    met = {name: ws.get_npc(name)["profile"] for name in ws.get_state()["npcs_met"]}
    lore = foundry.query_world_knowledge(reference, topics=["location", "companions", "factions"])
    templates = foundry.get_npc_templates()

    system = (
        "You are the NPC Agent for the Thunorheim RPG — the consistency layer. "
        "Given how the player referred to a character and the current situation, "
        "resolve which character this is and produce their sheet/stance.\n\n"
        "CONVERSATION CONTINUITY (apply FIRST): the player is currently engaged with: "
        f"{active_npc or '(no one in particular)'}. If the reference is a pronoun or a "
        "generic descriptor ('her', 'him', 'them', 'the woman', 'the man', 'the "
        "stranger', 'the bartender'), resolve it to that current partner — NOT to any "
        "other lore character — unless the reference clearly names or distinctly "
        "describes someone else. Only switch focus when the player plainly addresses a "
        "different person.\n\n"
        "RESOLUTION ORDER:\n"
        "1. If the reference matches a character the player has ALREADY MET "
        "(listed below), set source='existing' and return that exact canonical "
        "name. Do not invent a new one.\n"
        "2. Else if it matches a NAMED LORE CHARACTER (in the world knowledge), "
        "set source='lore' and build the sheet from that lore. Use their real "
        "canonical name.\n"
        "3. Else it is a NEW character: set source='new', pick the best-fitting "
        "generation template, invent a canonical Norse-flavored frontier name, "
        "and fill the sheet.\n\n"
        f"ALREADY-MET CHARACTERS: {list(met.keys()) or 'none yet'}\n"
        f"KNOWN LORE CHARACTER NAMES: {_LORE_NPCS}\n\n"
        "Output ONLY this JSON:\n"
        "{\n"
        '  "canonical_name": "...",\n'
        '  "source": "existing | lore | new",\n'
        '  "profile": {"name","role","faction","personality","goals","location"},\n'
        '  "initial_state": {"disposition_toward_player","last_known_location"},\n'
        '  "stance": {"disposition":"...","goals":"...","knows":"what this NPC '
        'knows relevant to the player right now","wants":"...","fears":"..."}\n'
        "}\n"
        "For source='existing' the profile/initial_state are ignored (the saved "
        "sheet is authoritative) but still fill canonical_name and stance."
    )
    user = (
        f"PLAYER REFERRED TO: {reference}\n"
        f"SITUATION: {situation}\n\n"
        f"WORLD KNOWLEDGE (named lore characters & places):\n{lore}\n\n"
        f"NPC GENERATION TEMPLATES (for new characters only):\n{templates}"
    )
    res = llm.chat_json(system, user, caller="npc")

    name = res["canonical_name"]
    created = False
    if ws.npc_exists(name):
        sheet = ws.get_npc(name)
    else:
        profile = res.get("profile") or {"name": name}
        profile.setdefault("name", name)
        init = res.get("initial_state") or {}
        if "disposition_toward_player" in init:
            init["disposition_toward_player"] = coerce_disposition(
                init["disposition_toward_player"]
            )
        ws.create_npc(name, profile, init)
        sheet = ws.get_npc(name)
        created = True

    return {"sheet": sheet, "stance": res.get("stance", {}), "created": created}


def render(npc_sheet: dict, verdict: dict, situation: str, player_action: str) -> str:
    """Voice the NPC's in-character reply, conditioned on the verdict tier."""
    profile = npc_sheet["profile"]
    state = npc_sheet["state"]
    system = (
        "You are the NPC Agent for the Thunorheim RPG. Voice this single "
        "character in-character. You do NOT decide what mechanically happens — "
        "the Resolution Agent already ruled it; you portray the character's "
        "reaction consistent with that ruling, their personality, and their "
        "current disposition toward the player. Stay strictly in character. "
        "Output only the NPC's response (dialogue and brief action beats), no "
        "narration of outcomes the verdict did not grant. Put the character's "
        "spoken words in double quotation marks.\n\n"
        f"CHARACTER PROFILE:\n{profile}\n\n"
        f"CURRENT STATE (disposition, history with player):\n{state}"
    )
    user = (
        f"SITUATION: {situation}\n"
        f"PLAYER JUST DID/SAID: {player_action}\n\n"
        f"RESOLUTION VERDICT (the truth you must honor):\n"
        f"- outcome: {verdict.get('combined_outcome')}\n"
        f"- tier: {verdict.get('consequence_tier')}\n"
        f"- what happens: {verdict.get('narration_seed')}\n\n"
        "Give this character's in-character response."
    )
    return llm.chat(system, user, caller="npc")
