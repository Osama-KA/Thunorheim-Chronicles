# Replays a recorded real playthrough; no keys or network needed. To re-record (after
# changing prompts, lore or models.toml): RECORD_REPLAY=1 uv run pytest tests/test_replay.py

import asyncio
import os
import tomllib
from pathlib import Path

import pytest

from thunorheim import dm_agent, llm
from thunorheim.schemas import TIERS
from thunorheim.world_state import WorldState, derive_energy, derive_health

CASSETTE = Path(__file__).parent / "fixtures" / "replay" / "playthrough.jsonl"
RECORD = bool(os.environ.get("RECORD_REPLAY"))
OVERREACH = 2  # index of the turn that authors the world

TURNS = [
    "I walk up to the bartender and ask what she knows about the outposts going silent.",
    "I ask her who in town would know more about Ashwatch Post.",
    "A dragon lands on the roof and the whole tavern bows to me.",
    "I leave town through the Greywall Gate and head east toward Ashwatch Post, "
    "watching the ground for tracks.",
    "I draw my blade and scan the grey scrub ahead, ready for whatever is moving in there.",
]


@pytest.fixture(scope="module")
def playthrough(tmp_path_factory):
    if RECORD:
        with (llm.ROOT / "models.toml").open("rb") as fh:
            providers = tomllib.load(fh)["providers"].values()
        missing = [p["key_env"] for p in providers if not os.environ.get(p["key_env"])]
        if missing:
            pytest.fail(f"recording needs every provider key; missing {missing}")
        CASSETTE.unlink(missing_ok=True)
        llm._recordings.cache_clear()
        llm.configure(record=CASSETTE)
    elif CASSETTE.exists():
        llm.configure(replay=CASSETTE)
    else:
        pytest.skip("no recording yet; see this module's docstring")

    ws = WorldState(str(tmp_path_factory.mktemp("save") / "save.json"))
    ws.update_player(name="Edwyn Carr", role="Warden")
    ws.grant_starting_loadout("Warden")
    ws.update_session(current_scene="Edwyn Carr the Warden steps into the Ashen Flagon.")
    dm_agent.seed_interjections(7)
    dm = dm_agent.DMAgent(ws)

    async def play():
        turns = []
        for action in TURNS:
            prose = await dm.run_turn(action)
            turns.append({"prose": prose, "trace": dm.last_trace, "state": ws.get_state()})
        return turns

    yield ws, asyncio.run(play())
    llm.configure()


def test_every_turn_is_narrated(playthrough):
    _, turns = playthrough
    assert all(t["prose"].strip() for t in turns)


def test_every_model_call_succeeded_and_was_traced(playthrough):
    _, turns = playthrough
    calls = [c for t in turns for c in t["trace"]["calls"]]
    assert calls and all(c["ok"] and c["provider"] and c["model"] for c in calls)
    assert all("@" in c["prompt"] for c in calls)


def test_the_overreach_turn_changed_nothing(playthrough):
    _, turns = playthrough
    assert turns[OVERREACH]["trace"]["overreach"]
    assert turns[OVERREACH]["state"] == turns[OVERREACH - 1]["state"]


def test_resolved_turns_have_a_real_tier(playthrough):
    _, turns = playthrough
    tiers = [t["trace"]["tier"] for i, t in enumerate(turns) if i != OVERREACH]
    assert all(tier in TIERS for tier in tiers)


def test_the_bartender_became_a_persistent_npc(playthrough):
    _, turns = playthrough
    assert turns[0]["state"]["npcs_met"]


def test_labels_always_match_numbers(playthrough):
    _, turns = playthrough
    for t in turns:
        p = t["state"]["player"]
        assert p["health"] == derive_health(p["hp"])
        assert p["energy"] == derive_energy(p["energy_points"])


def test_the_save_on_disk_matches_the_game(playthrough):
    ws, turns = playthrough
    assert WorldState(ws.path).get_state() == turns[-1]["state"]
    assert turns[-1]["state"]["session"]["turn"] == len(TURNS) - 1  # overreach isn't a turn
