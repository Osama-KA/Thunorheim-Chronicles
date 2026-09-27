from pathlib import Path

import pytest

from thunorheim.world_state import (
    StateValidationError,
    WorldState,
    coerce_disposition,
    derive_disposition,
    derive_energy,
    derive_health,
)


@pytest.fixture
def ws(tmp_path):
    ws = WorldState(str(tmp_path / "save.json"))
    ws.update_player(name="Edwyn", role="Warden")
    return ws


# --- numbers are the truth, labels are derived ------------------------------


@pytest.mark.parametrize(
    ("hp", "label"),
    [(150, "Fresh"), (100, "Fresh"), (99, "Scratched"), (75, "Scratched"), (74, "Hurt"),
     (50, "Hurt"), (49, "Wounded"), (25, "Wounded"), (24, "Critical"), (10, "Critical"),
     (9, "Down"), (1, "Down"), (0, "Dead"), (-40, "Dead")],
)  # fmt: skip
def test_health_bands(hp, label):
    assert derive_health(hp) == label


@pytest.mark.parametrize(
    ("ep", "label"),
    [(100, "Full"), (76, "Full"), (75, "Strained"), (51, "Strained"), (50, "Drained"),
     (26, "Drained"), (25, "Empty"), (1, "Empty"), (0, "Collapsed")],
)  # fmt: skip
def test_energy_bands(ep, label):
    assert derive_energy(ep) == label


@pytest.mark.parametrize(
    ("points", "label"),
    [(500, "Allied"), (61, "Allied"), (60, "Friendly"), (21, "Friendly"), (20, "Trusting"),
     (1, "Trusting"), (0, "Neutral"), (-1, "Unfriendly"), (-20, "Unfriendly"),
     (-21, "Hostile"), (-60, "Hostile"), (-61, "On sight"), (-500, "On sight")],
)  # fmt: skip
def test_disposition_bands(points, label):
    assert derive_disposition(points) == label


@pytest.mark.parametrize(
    ("value", "label"),
    [("Unfriendly", "Unfriendly"),  # "friendly" is a substring: order must not misfire
     ("rather unfriendly now", "Unfriendly"), ("Friendly", "Friendly"), (45, "Friendly"),
     (-70, "On sight"), (True, "Neutral"), (None, "Neutral"), ("baffled", "Neutral")],
)  # fmt: skip
def test_prose_dispositions_coerce_to_the_enum(value, label):
    assert coerce_disposition(value) == label


def test_hp_is_clamped_and_its_label_follows(ws):
    ws.apply_delta({"hp_delta": 500})
    assert ws.get_field("player.hp") == 100
    ws.apply_delta({"hp_delta": -60})
    assert ws.get_field("player.health") == "Wounded"


def test_labels_cannot_be_written_directly(ws):
    ws.update_player(health="Fresh", energy="Full")
    ws.apply_delta({"hp_delta": -95, "player": {"health": "Fresh", "hp": 100}})
    assert (ws.get_field("player.hp"), ws.get_field("player.health")) == (5, "Down")


def test_damage_emits_down_then_death_once(ws):
    assert ws.apply_delta({"hp_delta": -95}) == [{"type": "down"}]
    assert ws.apply_delta({"hp_delta": -50}) == [{"type": "death"}]
    assert ws.apply_delta({"hp_delta": -10}) == []


# --- the untrusted-model boundary ---------------------------------------------


def test_off_track_role_is_rejected(ws):
    with pytest.raises(StateValidationError):
        ws.update_player(role="Bard")


def test_unknown_player_field_is_rejected(ws):
    with pytest.raises(StateValidationError):
        ws.apply_delta({"player": {"mana": 50}})


@pytest.mark.parametrize(
    ("target", "value", "expected"),
    [
        ("wardens_guild", "Trusted", "Trusted"),
        ("wardens_guild", "Neutral", "Initiate"),  # faction word on the Guild scale
        ("wardens_guild", "nonsense", "Initiate"),  # dropped; the default stands
        ("valdenmoor", "Respected", "Friendly"),
        ("valdenmoor", "hostile", "Hostile"),
    ],
)
def test_reputation_is_coerced_onto_the_right_scale(ws, target, value, expected):
    ws.apply_delta({"reputation": {target: value}})
    rep = ws.get_state()["reputation"]
    actual = rep["wardens_guild"] if target == "wardens_guild" else rep["factions"][target]
    assert actual == expected


def test_only_canonical_world_flags_can_be_set(ws):
    ws.apply_delta(
        {
            "world_flags": {
                "Drenhold Discovered": True,
                "survivor-rescued": "false",
                "dragon_slain": True,
            }
        }
    )
    flags = ws.get_world_flags()
    assert flags["drenhold_discovered"] is True
    assert flags["survivor_rescued"] is False
    assert "dragon_slain" not in flags


def test_updates_for_unknown_npcs_are_ignored(ws):
    ws.apply_delta({"npc_updates": {"Nobody": {"disposition_delta": 5}}})
    assert ws.get_state()["npcs_met"] == {}


def test_npc_disposition_moves_in_capped_steps(ws):
    ws.create_npc(
        "Torben Grall", {"name": "Torben Grall"}, {"disposition_toward_player": "Friendly"}
    )
    assert ws.get_npc("Torben Grall")["state"]["disposition_points"] == 40
    ws.apply_delta({"npc_updates": {"Torben Grall": {"disposition_delta": 500}}})
    st = ws.get_npc("Torben Grall")["state"]
    assert (st["disposition_points"], st["disposition_toward_player"]) == (70, "Allied")


def test_npc_disposition_stays_in_range(ws):
    ws.create_npc("Signe", {"name": "Signe"}, {"disposition_points": 90})
    ws.apply_delta({"npc_updates": {"Signe": {"disposition_delta": 30}}})
    assert ws.get_npc("Signe")["state"]["disposition_points"] == 100


def test_duplicate_npc_is_rejected(ws):
    ws.create_npc("Signe", {"name": "Signe"})
    with pytest.raises(StateValidationError):
        ws.create_npc("Signe", {"name": "Signe"})


# --- progression: XP makes you eligible, a rite promotes you -----------------------


def test_xp_grants_eligibility_not_rank(ws):
    events = ws.apply_delta({"xp_delta": 120})
    prog = ws.get_progression()
    assert events == [{"type": "promotion_available", "tier": 2, "title": "Tracker"}]
    assert (prog["tier"], prog["pending_tier"], prog["title"]) == (1, 2, "Recruit")
    assert ws.apply_delta({"xp_delta": 10}) == []  # eligibility is announced once


def test_promotion_rite_advances_exactly_one_tier(ws):
    for _ in range(6):
        ws.apply_delta({"xp_delta": 100})  # 600 XP: eligible all the way to tier 4
    assert ws.apply_delta({"promote": True}) == [
        {"type": "tier_up", "from": 1, "to": 2, "title": "Tracker"}
    ]
    assert ws.get_progression()["pending_tier"] == 4


def test_one_verdict_cannot_grant_a_windfall(ws):
    ws.apply_delta(
        {
            "xp_delta": 5000,
            "inventory_add": ["crown", "dragon egg", "bag of gold", "legendary sword"],
            "location": "x" * 500,
        }
    )
    assert ws.get_progression()["xp"] == 100
    assert ws.get_state()["inventory"] == ["crown", "dragon egg", "bag of gold"]
    assert len(ws.get_field("player.location")) == 120


def test_xp_never_goes_down(ws):
    ws.apply_delta({"xp_delta": 50})
    ws.apply_delta({"xp_delta": -30})
    assert ws.get_progression()["xp"] == 50


def test_promotion_without_eligibility_is_a_no_op(ws):
    assert ws.apply_delta({"promote": True}) == []
    assert ws.get_progression()["tier"] == 1


# --- quests & inventory -----------------------------------------------------------


def test_quest_moves_between_buckets_without_duplicating(ws):
    quest = {"title": "The Shattered Seal", "current_objective": "Reach Ashwatch"}
    ws.apply_delta({"quests": [{"quest": quest}]})
    ws.apply_delta({"quests": [{"quest": quest, "status": "completed"}]})
    quests = ws.get_state()["quests"]
    assert quests["active"] == []
    assert [q["title"] for q in quests["completed"]] == ["The Shattered Seal"]


def test_starting_loadout_is_granted_once(ws):
    ws.grant_starting_loadout("Warden")
    ws.grant_starting_loadout("Warden")
    assert ws.get_state()["inventory"].count("longsword") == 1


def test_removing_an_item_the_player_lacks_is_harmless(ws):
    ws.grant_starting_loadout("Warden")
    before = ws.get_state()["inventory"]
    ws.apply_delta({"inventory_remove": ["dragon egg"]})
    assert ws.get_state()["inventory"] == before


# --- turn transaction -----------------------------------------------------------


def test_rollback_restores_the_snapshot(ws):
    ws.begin_turn()
    before = ws.get_state()
    ws.apply_delta({"hp_delta": -50, "inventory_add": ["torch"], "xp_delta": 30})
    ws.rollback()
    assert ws.get_state() == before


def test_nothing_reaches_disk_until_commit(ws):
    ws.begin_turn()
    ws.apply_delta({"hp_delta": -30})
    assert not Path(ws.path).exists()
    ws.commit()
    assert WorldState(ws.path).get_state() == ws.get_state()
