from __future__ import annotations

from typing import Any

from . import llm, lore
from .schemas import NpcResolution, Verdict
from .world_state import WorldState, coerce_disposition

ENSURE_PROMPT = "npc-ensure@2"
RENDER_PROMPT = "npc-render@2"

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


async def ensure_npc(
    reference: str, situation: str, ws: WorldState, active_npc: str = ""
) -> dict[str, Any]:
    """Resolve, load-or-create, and return {sheet, stance, created}.

    `active_npc` is the canonical name of the character the player is currently in
    conversation with (from the previous turn). It anchors ambiguous references so a
    bare pronoun doesn't jump to the wrong character."""
    met = list(ws.get_state()["npcs_met"])
    knowledge = lore.query_world_knowledge(["location", "companions", "factions"])
    templates = lore.get_npc_templates()

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
        f"ALREADY-MET CHARACTERS: {met or 'none yet'}\n"
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
        f"WORLD KNOWLEDGE (named lore characters & places):\n{knowledge}\n\n"
        f"NPC GENERATION TEMPLATES (for new characters only):\n{templates}"
    )
    res = await llm.structured("npc", NpcResolution, system, user, prompt=ENSURE_PROMPT)

    name = res.canonical_name
    created = False
    if not ws.npc_exists(name):
        profile = {**res.profile, "name": name}
        init = res.initial_state.model_dump()
        init["disposition_toward_player"] = coerce_disposition(init["disposition_toward_player"])
        ws.create_npc(name, profile, init)
        created = True

    return {"sheet": ws.get_npc(name), "stance": res.stance, "created": created}


async def render(
    npc_sheet: dict[str, Any], verdict: Verdict, situation: str, player_action: str
) -> str:
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
        f"- outcome: {verdict.combined_outcome}\n"
        f"- tier: {verdict.consequence_tier}\n"
        f"- what happens: {verdict.narration_seed}\n\n"
        "Give this character's in-character response."
    )
    return await llm.text("npc", system, user, prompt=RENDER_PROMPT)
