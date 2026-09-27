from __future__ import annotations

import copy
import json
import os
from typing import Any

# --- Allowed value sets -------------------------------------------------------

HEALTH_TRACK = ["Fresh", "Scratched", "Hurt", "Wounded", "Critical", "Down", "Dead"]
ENERGY_TRACK = ["Full", "Strained", "Drained", "Empty", "Collapsed"]
ROLES = ["Warden", "Runescribe", "Shroud", "Thornwarden"]
GUILD_REPUTATION = ["Unknown", "Initiate", "Trusted", "Respected", "Distinguished", "Disgraced"]
FACTION_REPUTATION = ["Hostile", "Unfriendly", "Neutral", "Friendly", "Allied"]
# Order matters for coerce substring matching: "Unfriendly" must be tested before
# "Friendly" (since "friendly" is a substring of "unfriendly").
NPC_DISPOSITION = ["On sight", "Hostile", "Unfriendly", "Neutral", "Trusting", "Friendly", "Allied"]

# --- Derivation bands (descending threshold, label) ---------------------------

HEALTH_BANDS = [
    (100, "Fresh"),
    (75, "Scratched"),
    (50, "Hurt"),
    (25, "Wounded"),
    (10, "Critical"),
    (1, "Down"),
    (0, "Dead"),
]
ENERGY_BANDS = [(76, "Full"), (51, "Strained"), (26, "Drained"), (1, "Empty"), (0, "Collapsed")]
DISPOSITION_BANDS = [
    (61, "Allied"),
    (21, "Friendly"),
    (1, "Trusting"),
    (0, "Neutral"),
    (-20, "Unfriendly"),
    (-60, "Hostile"),
    (-100, "On sight"),
]

# Label -> representative points, so a disposition given as a label (e.g. an NPC's
# initial stance) maps onto the numeric scale.
DISPOSITION_MIDPOINTS = {
    "Allied": 80,
    "Friendly": 40,
    "Trusting": 10,
    "Neutral": 0,
    "Unfriendly": -10,
    "Hostile": -40,
    "On sight": -80,
}

# --- Progression --------------------------------------------------------------

TIER_THRESHOLDS = [0, 100, 250, 500, 900, 1500]  # index i -> tier i+1
ROLE_TITLES = {
    "Warden": ["Recruit", "Tracker", "Warden", "Greymark Veteran", "Ironclad", "Legendary Warden"],
    "Runescribe": [
        "Apprentice",
        "Inscriber",
        "Runescribe",
        "Arcanist",
        "Lorekeeper",
        "Legendary Runescribe",
    ],
    "Shroud": ["Shadow", "Operative", "Shroud", "Ghostblade", "Whisper", "Legendary Shroud"],
    "Thornwarden": [
        "Herbalist",
        "Field Medic",
        "Thornwarden",
        "Blightwalker",
        "Thornweaver",
        "Legendary Thornwarden",
    ],
}


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))


def _derive(value: int, bands: list[tuple[int, str]]) -> str:
    for threshold, label in bands:
        if value >= threshold:
            return label
    return bands[-1][1]


def derive_health(hp: int) -> str:
    return _derive(clamp(hp, 0, 100), HEALTH_BANDS)


def derive_energy(ep: int) -> str:
    return _derive(clamp(ep, 0, 100), ENERGY_BANDS)


def derive_disposition(points: int) -> str:
    return _derive(clamp(points, -100, 100), DISPOSITION_BANDS)


def disposition_label_to_points(label: str) -> int:
    return DISPOSITION_MIDPOINTS.get(label, 0)


def title_for(role: str, tier: int) -> str:
    titles = ROLE_TITLES.get(role)
    if not titles:
        return "Recruit"
    return titles[clamp(tier, 1, len(titles)) - 1]


def _normalize_flag(flag: str) -> str:
    """Fold case/separator variants so 'Drenhold Discovered' and 'drenhold-discovered'
    both match the canonical 'drenhold_discovered'."""
    return str(flag).strip().lower().replace(" ", "_").replace("-", "_")


def coerce_disposition(value: Any) -> str:
    """Map a numeric or prose disposition to an enum label. Numeric -> derived;
    string -> substring match; otherwise Neutral. Used at model boundaries."""
    if isinstance(value, bool):
        return "Neutral"
    if isinstance(value, (int, float)):
        return derive_disposition(int(value))
    if isinstance(value, str):
        for level in NPC_DISPOSITION:
            if level.lower() in value.lower():
                return level
    return "Neutral"


_DEFAULT_STATE = {
    "player": {
        "name": "",
        "role": "",
        "hp": 100,
        "health": "Fresh",
        "energy_points": 100,
        "energy": "Full",
        "location": "Greyhold",
        "active_effects": [],
    },
    "inventory": [],
    "quests": {"active": [], "completed": [], "failed": []},
    "reputation": {"wardens_guild": "Initiate", "factions": {"valdenmoor": "Neutral"}},
    "npcs_met": {},
    "world_flags": {
        "drenhold_discovered": False,
        "ashen_seal_found": False,
        "ashwatch_post_investigated": False,
        "survivor_rescued": False,
        "aldric_trust_unlocked": False,
    },
    "progression": {
        "xp": 0,
        "tier": 1,
        "title": "Recruit",
        "xp_to_next": 100,
        "pending_tier": None,
    },
    "session": {
        "turn": 0,
        "current_scene": "",
        "last_scene_summary": "",
        "open_threads": [],
        "active_npc": "",
    },
}

# Starting kit per role, granted at character creation so the player always has a
# defined loadout (weapons/tools stay consistent instead of being improvised).
ROLE_LOADOUTS = {
    "Warden": ["longsword", "Warden field kit", "hooded cloak", "flint and tinder", "torch x2"],
    "Runescribe": [
        "walking staff",
        "rune-slate",
        "iron inscribing stylus",
        "satchel of blank flint chips",
        "lantern",
    ],
    "Shroud": [
        "pair of throwing knives",
        "lockpicks",
        "dark hooded cloak",
        "smoke vial",
        "coin purse",
    ],
    "Thornwarden": [
        "curved knife",
        "Thorncraft kit",
        "herb pouch",
        "Thorncraft resistance salve x2",
        "grey cloak",
    ],
}

# Per-turn caps. A schema-valid delta can still be an unearned windfall; these bound
# what one verdict can grant, whatever the model claims.
MAX_XP_PER_TURN = 100  # "major world event" in the XP table; XP never goes down
MAX_DISPOSITION_STEP = 30  # rules: ~15 per interaction, more only for huge moments
MAX_ITEMS_PER_TURN = 3
MAX_TEXT = 120  # an item name or a location, not a paragraph

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_PATH = os.path.join(_PROJECT_ROOT, "state", "session_state.json")


class StateValidationError(ValueError):
    """Raised when an agent tries to write a value outside the allowed set."""


def _require(value: Any, allowed: list, label: str) -> Any:
    if value not in allowed:
        raise StateValidationError(
            f"Invalid {label}: {value!r}. Allowed: {', '.join(map(str, allowed))}"
        )
    return value


class WorldState:
    def __init__(self, path: str = _DEFAULT_PATH):
        self.path = path
        self._state: dict = self._load()
        self._snapshot: dict | None = None

    # ------------------------------------------------------------------ load/save
    def _load(self) -> dict:
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as fh:
                text = fh.read().strip()
            if text:
                return json.loads(text)
        return copy.deepcopy(_DEFAULT_STATE)

    def save_state(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self._state, fh, indent=2, ensure_ascii=False)

    # ----------------------------------------------------------------- transaction
    def begin_turn(self) -> None:
        self._snapshot = copy.deepcopy(self._state)

    def commit(self) -> None:
        self.save_state()
        self._snapshot = None

    def rollback(self) -> None:
        if self._snapshot is not None:
            self._state = self._snapshot
            self._snapshot = None

    # ---------------------------------------------------------------------- reads
    def get_state(self) -> dict:
        return copy.deepcopy(self._state)

    def get_field(self, path: str) -> Any:
        node: Any = self._state
        for part in path.split("."):
            node = node[part]
        return copy.deepcopy(node)

    def get_npc(self, name: str) -> dict | None:
        npc = self._state["npcs_met"].get(name)
        return copy.deepcopy(npc) if npc else None

    def npc_exists(self, name: str) -> bool:
        return name in self._state["npcs_met"]

    def get_world_flags(self) -> dict:
        return copy.deepcopy(self._state["world_flags"])

    def get_progression(self) -> dict:
        return copy.deepcopy(self._state["progression"])

    # ------------------------------------------------------------- numeric writers
    def set_hp(self, value: int) -> None:
        p = self._state["player"]
        p["hp"] = clamp(value, 0, 100)
        p["health"] = derive_health(p["hp"])

    def adjust_hp(self, delta: int) -> None:
        self.set_hp(self._state["player"]["hp"] + int(delta))

    def set_energy(self, value: int) -> None:
        p = self._state["player"]
        p["energy_points"] = clamp(value, 0, 100)
        p["energy"] = derive_energy(p["energy_points"])

    def adjust_energy(self, delta: int) -> None:
        self.set_energy(self._state["player"]["energy_points"] + int(delta))

    def adjust_npc_disposition(self, name: str, delta: int) -> None:
        if name not in self._state["npcs_met"]:
            raise StateValidationError(f"Unknown NPC: {name!r}")
        st = self._state["npcs_met"][name]["state"]
        st["disposition_points"] = clamp(st.get("disposition_points", 0) + int(delta), -100, 100)
        st["disposition_toward_player"] = derive_disposition(st["disposition_points"])

    def _refresh_progress(self) -> None:
        """Recompute derived progression fields. XP sets ELIGIBILITY (pending_tier);
        it never advances the tier on its own — that requires a promotion rite via
        promote(). Title always reflects the CURRENT tier."""
        prog = self._state["progression"]
        xp = prog["xp"]
        eligible = 1
        for i, threshold in enumerate(TIER_THRESHOLDS):
            if xp >= threshold:
                eligible = i + 1
        prog["pending_tier"] = eligible if eligible > prog["tier"] else None
        prog["title"] = title_for(self._state["player"].get("role", ""), prog["tier"])
        if prog["tier"] >= len(TIER_THRESHOLDS):
            prog["xp_to_next"] = None
        else:
            prog["xp_to_next"] = max(0, TIER_THRESHOLDS[prog["tier"]] - xp)

    def add_xp(self, delta: int) -> dict | None:
        """Accrue XP. Crossing a threshold makes the player ELIGIBLE for the next
        tier (pending_tier) but does NOT promote them — returns a
        promotion_available event the first time eligibility is reached."""
        prog = self._state["progression"]
        before = prog.get("pending_tier")
        prog["xp"] = max(0, prog["xp"] + int(delta))
        self._refresh_progress()
        if prog.get("pending_tier") and prog["pending_tier"] != before:
            return {
                "type": "promotion_available",
                "tier": prog["pending_tier"],
                "title": title_for(self._state["player"].get("role", ""), prog["pending_tier"]),
            }
        return None

    def promote(self) -> dict | None:
        """Advance one tier via a rite of passage. Only succeeds when the player is
        eligible (pending_tier set by accrued XP). Returns a tier_up event or None.
        The narrative gate — that a qualified mentor/Guild authority performs the
        rite — is enforced by the Resolution Agent, which only emits promote when
        such a figure advances an eligible player."""
        prog = self._state["progression"]
        pending = prog.get("pending_tier")
        if not pending or pending <= prog["tier"]:
            return None
        old_tier = prog["tier"]
        prog["tier"] += 1
        self._refresh_progress()
        return {"type": "tier_up", "from": old_tier, "to": prog["tier"], "title": prog["title"]}

    # --------------------------------------------------------------------- writes
    def update_player(self, **changes: Any) -> None:
        player = self._state["player"]
        for key, value in changes.items():
            if key in ("health", "energy"):
                continue  # derived only — never set directly
            if key == "hp":
                self.set_hp(value)
            elif key == "energy_points":
                self.set_energy(value)
            elif key == "role":
                if value:
                    _require(value, ROLES, "role")
                player["role"] = value
                self._refresh_progress()  # refresh title for the new role
            elif key in player:
                player[key] = value
            else:
                raise StateValidationError(f"Unknown player field: {key!r}")

    def create_npc(self, name: str, profile: dict, state: dict | None = None) -> None:
        if name in self._state["npcs_met"]:
            raise StateValidationError(f"NPC already exists: {name!r}")
        npc_state = {
            "disposition_toward_player": "Neutral",
            "disposition_points": 0,
            "last_interaction_summary": "",
            "knows_about_player": [],
            "last_known_location": profile.get("location", ""),
        }
        if state:
            s = dict(state)
            if "disposition_points" in s:
                npc_state["disposition_points"] = clamp(s.pop("disposition_points"), -100, 100)
            elif "disposition_toward_player" in s:
                npc_state["disposition_points"] = disposition_label_to_points(
                    coerce_disposition(s.pop("disposition_toward_player"))
                )
            npc_state.update(s)
        npc_state["disposition_points"] = clamp(npc_state["disposition_points"], -100, 100)
        npc_state["disposition_toward_player"] = derive_disposition(npc_state["disposition_points"])
        self._state["npcs_met"][name] = {"profile": profile, "state": npc_state}

    def update_npc_state(self, name: str, **changes: Any) -> None:
        if name not in self._state["npcs_met"]:
            raise StateValidationError(f"Unknown NPC: {name!r}")
        st = self._state["npcs_met"][name]["state"]
        for key, value in changes.items():
            if key == "disposition_points":
                st["disposition_points"] = clamp(value, -100, 100)
                st["disposition_toward_player"] = derive_disposition(st["disposition_points"])
            elif key == "disposition_toward_player":
                st["disposition_points"] = disposition_label_to_points(coerce_disposition(value))
                st["disposition_toward_player"] = derive_disposition(st["disposition_points"])
            else:
                st[key] = value

    def update_reputation(self, target: str, value: str) -> None:
        if target == "wardens_guild":
            _require(value, GUILD_REPUTATION, "guild reputation")
            self._state["reputation"]["wardens_guild"] = value
        else:
            _require(value, FACTION_REPUTATION, "faction reputation")
            self._state["reputation"]["factions"][target] = value

    @staticmethod
    def _coerce_reputation(target: str, value: Any) -> str | None:
        """Map a model-supplied reputation value to the target's enum. The Guild and
        faction scales differ (the Guild has no 'Neutral'); a value off the wrong scale
        is mapped to the nearest sensible one, or dropped (None) — never raised, so a
        stray reputation value can't roll back a good turn."""
        allowed = GUILD_REPUTATION if target == "wardens_guild" else FACTION_REPUTATION
        if value in allowed:
            return value
        if not isinstance(value, str):
            return None
        low = value.strip().lower()
        for a in allowed:
            if a.lower() == low:
                return a
        # cross-scale synonyms (model using faction words for Guild standing, etc.)
        synonyms = {
            "wardens_guild": {
                "neutral": "Initiate",
                "unknown": "Unknown",
                "friendly": "Trusted",
                "trusting": "Trusted",
                "allied": "Respected",
                "unfriendly": "Initiate",
                "hostile": "Disgraced",
            },
            "_faction": {
                "initiate": "Neutral",
                "unknown": "Neutral",
                "trusted": "Friendly",
                "respected": "Friendly",
                "distinguished": "Allied",
                "disgraced": "Hostile",
            },
        }
        table = synonyms["wardens_guild"] if target == "wardens_guild" else synonyms["_faction"]
        return table.get(low)

    def update_quest(self, quest: dict, status: str = "active") -> None:
        if status not in ("active", "completed", "failed"):
            raise StateValidationError(f"Invalid quest status: {status!r}")
        title = quest.get("title")
        for bucket in ("active", "completed", "failed"):
            self._state["quests"][bucket] = [
                q for q in self._state["quests"][bucket] if q.get("title") != title
            ]
        self._state["quests"][status].append(quest)

    def set_world_flag(self, flag: str, value: bool) -> bool:
        """Set a CANONICAL world flag. The vocabulary is closed: only flags already
        present in world_flags (seeded from _DEFAULT_STATE) can be toggled, and names
        are normalized so case/separator variants still match. A non-canonical flag is
        IGNORED, not raised — so a stray model flag never rolls back a turn, and the
        flags dict stays a stable, consistent set. Other developments belong in quest
        known_clues/complications, not in world_flags. Returns True if a canonical flag
        was set, False if the flag was ignored."""
        flags = self._state["world_flags"]
        key = _normalize_flag(flag)
        if key not in flags:
            return False
        if isinstance(value, str):
            value = value.strip().lower() not in ("false", "0", "no", "")
        flags[key] = bool(value)
        return True

    def update_session(self, **changes: Any) -> None:
        session = self._state["session"]
        for key, value in changes.items():
            if key not in session:
                raise StateValidationError(f"Unknown session field: {key!r}")
            session[key] = value

    def increment_turn(self) -> int:
        self._state["session"]["turn"] += 1
        return self._state["session"]["turn"]

    # --------------------------------------------------------------- inventory helpers
    def grant_starting_loadout(self, role: str | None = None) -> None:
        """Grant the role's starting kit if the inventory is empty. Idempotent —
        does nothing once the player has any items."""
        if self._state["inventory"]:
            return
        role = role or self._state["player"].get("role", "")
        self._state["inventory"].extend(ROLE_LOADOUTS.get(role, []))

    def add_item(self, item: str) -> None:
        self._state["inventory"].append(item)

    def remove_item(self, item: str) -> bool:
        if item in self._state["inventory"]:
            self._state["inventory"].remove(item)
            return True
        return False

    def apply_delta(self, delta: dict) -> list[dict]:
        """Apply a structured state delta from the Resolution Agent. Returns a list
        of mechanical events (tier_up, death, down) for the DM to narrate.

        Recognized keys (all optional):
          hp_delta: int, energy_delta: int, xp_delta: int
          location: str
          player: {active_effects, name, ...}   (health/energy ignored — derived)
          inventory_add: [str], inventory_remove: [str]
          reputation: {target: value}
          npc_updates: {name: {disposition_delta: int, disposition_toward_player,
                               last_interaction_summary, knows_about_player, ...}}
          world_flags: {flag: bool}
          quests: [{quest: {...}, status: "active|completed|failed"}]
        Every value passes through the clamping/validating setters, so a malformed
        delta is repaired or rejected rather than corrupting the save, and the
        per-turn caps (MAX_*) bound how much a single verdict can grant.
        """
        events: list[dict] = []
        if not delta:
            return events

        if delta.get("hp_delta"):
            before = self._state["player"]["health"]
            self.adjust_hp(delta["hp_delta"])
            after = self._state["player"]["health"]
            if after == "Dead" and before != "Dead":
                events.append({"type": "death"})
            elif after == "Down" and before != "Down":
                events.append({"type": "down"})
        if delta.get("energy_delta"):
            self.adjust_energy(delta["energy_delta"])
        if delta.get("location"):
            self.update_player(location=str(delta["location"])[:MAX_TEXT])
        if delta.get("player"):
            changes = {
                k: v
                for k, v in delta["player"].items()
                if v is not None and k not in ("health", "energy", "hp", "energy_points")
            }
            if changes:
                self.update_player(**changes)
        if delta.get("xp_delta"):
            event = self.add_xp(clamp(delta["xp_delta"], 0, MAX_XP_PER_TURN))
            if event:
                events.append(event)
        if delta.get("promote"):
            event = self.promote()
            if event:
                events.append(event)

        for item in (delta.get("inventory_add") or [])[:MAX_ITEMS_PER_TURN]:
            self.add_item(str(item)[:MAX_TEXT])
        for item in delta.get("inventory_remove", []) or []:
            self.remove_item(item)
        for target, value in (delta.get("reputation") or {}).items():
            value = self._coerce_reputation(target, value)
            if value is not None:
                self.update_reputation(target, value)
        for name, changes in (delta.get("npc_updates") or {}).items():
            if not self.npc_exists(name):
                continue
            changes = dict(changes)
            if "disposition_delta" in changes:
                step = changes.pop("disposition_delta")
                self.adjust_npc_disposition(
                    name, clamp(step, -MAX_DISPOSITION_STEP, MAX_DISPOSITION_STEP)
                )
            if changes:
                self.update_npc_state(name, **changes)
        for flag, value in (delta.get("world_flags") or {}).items():
            self.set_world_flag(flag, value)
        for entry in delta.get("quests", []) or []:
            self.update_quest(entry["quest"], entry.get("status", "active"))

        return events
