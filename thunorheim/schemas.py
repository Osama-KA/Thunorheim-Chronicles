from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, model_validator

TIERS = (
    "Full success",
    "Partial success",
    "Failure",
    "Backfire",
    "Undetected",
    "Suspected",
    "Spotted",
    "Compromised",
)


def _normalize_tier(value: Any) -> Any:
    if isinstance(value, str):
        for tier in TIERS:
            if value.strip().lower() == tier.lower():
                return tier
    return value


Tier = Annotated[
    Literal[
        "Full success",
        "Partial success",
        "Failure",
        "Backfire",
        "Undetected",
        "Suspected",
        "Spotted",
        "Compromised",
    ],
    BeforeValidator(_normalize_tier),
]


class Lenient(BaseModel):
    """Models often write `null` for "nothing"; treat it as the field's default."""

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


# --- DM routing ---------------------------------------------------------------


class RoutedBucket(Lenient):
    bucket: str
    intent: str = ""
    why: str = ""


class Routing(Lenient):
    overreach_detected: bool = False
    overreach_explanation: str = ""
    buckets: list[RoutedBucket] = []
    npc_involved: bool = False
    npc_reference: str = ""
    knowledge_topics: list[str] = []
    scene_note: str = ""


# --- Resolution verdict ---------------------------------------------------------


class BucketResult(Lenient):
    bucket: str
    intent: str = ""
    outcome: str = ""
    reasoning: str = ""


class Quest(Lenient):
    title: str = Field(min_length=1)
    current_objective: str = ""
    known_clues: list[str] = []
    complications: list[str] = []
    status_notes: str = ""


class QuestUpdate(Lenient):
    quest: Quest
    status: Literal["active", "completed", "failed"] = "active"


class NpcUpdate(Lenient):
    disposition_delta: int = 0
    last_interaction_summary: str | None = None
    knows_about_player: list[str] | None = None
    last_known_location: str | None = None


class PlayerChanges(Lenient):
    active_effects: list[str] | None = None


class StateDelta(Lenient):
    hp_delta: int = 0
    energy_delta: int = 0
    xp_delta: int = 0
    promote: bool = False
    location: str | None = None
    player: PlayerChanges = PlayerChanges()
    inventory_add: list[str] = []
    inventory_remove: list[str] = []
    reputation: dict[str, str] = {}
    npc_updates: dict[str, NpcUpdate] = {}
    world_flags: dict[str, bool] = {}
    quests: list[QuestUpdate] = []


class Interjection(Lenient):
    unpredictability_score: int = 0
    type: str | None = None
    description: str | None = None


class Verdict(Lenient):
    buckets: list[BucketResult] = []
    combined_outcome: str = Field(min_length=1)
    consequence_tier: Tier
    momentum: str = "n/a"
    narration_seed: str = Field(min_length=1)
    state_delta: StateDelta = StateDelta()
    interjection: Interjection = Interjection()
    rationale: str = ""
    suggested_actions: list[str] = []


# --- NPC resolution ---------------------------------------------------------------


class NpcInitialState(Lenient):
    disposition_toward_player: str = "Neutral"
    last_known_location: str = ""


class NpcResolution(Lenient):
    canonical_name: str = Field(min_length=1)
    source: str = ""
    profile: dict[str, Any] = {}
    initial_state: NpcInitialState = NpcInitialState()
    stance: dict[str, Any] = {}
