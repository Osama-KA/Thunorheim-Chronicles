import asyncio
from pathlib import Path

import pytest

from thunorheim import dm_agent, lore, npc_agent, resolution_agent
from thunorheim.schemas import Interjection, Routing, Verdict
from thunorheim.world_state import WorldState

ACTION = "I ask the grizzled warden what happened at Ashwatch."
ROUTING = Routing.model_validate(
    {
        "overreach_detected": False,
        "buckets": [{"bucket": "Social", "intent": "Gather info"}],
        "npc_involved": True,
        "npc_reference": "the grizzled warden",
        "knowledge_topics": [],
        "scene_note": "In the Ashen Flagon.",
    }
)
VERDICT = Verdict.model_validate(
    {
        "buckets": [{"bucket": "Social", "intent": "Gather info"}],
        "combined_outcome": "Torben shares what he saw.",
        "consequence_tier": "Partial success",
        "momentum": "player",
        "narration_seed": "Torben lowers his voice and describes the tracks.",
        "state_delta": {"xp_delta": 5, "npc_updates": {"Torben Grall": {"disposition_delta": 10}}},
        "interjection": {"unpredictability_score": 3},
    }
)


def play(dm, action=ACTION):
    return asyncio.run(dm.run_turn(action))


@pytest.fixture
def ws(tmp_path):
    ws = WorldState(str(tmp_path / "save.json"))
    ws.update_player(name="Edwyn", role="Warden")
    return ws


@pytest.fixture
def seen(monkeypatch):
    """Swap every model call for a canned answer and record what each one received."""
    seen: dict = {}

    async def ensure_npc(reference, situation, ws, active_npc=""):
        if not ws.npc_exists("Torben Grall"):
            ws.create_npc("Torben Grall", {"name": "Torben Grall"}, {"disposition_points": 30})
        return {"sheet": ws.get_npc("Torben Grall"), "stance": {}, "created": True}

    async def resolve(**kwargs):
        seen["resolve"] = kwargs
        return VERDICT

    async def render(sheet, verdict, situation, action):
        seen["render_sheet"] = sheet
        return '"Sit. Keep your voice down."'

    async def route(action, ws):
        return ROUTING

    async def narrate(*args):
        return "Torben leans in."

    monkeypatch.setattr(dm_agent, "route", route)
    monkeypatch.setattr(dm_agent, "narrate", narrate)
    monkeypatch.setattr(npc_agent, "ensure_npc", ensure_npc)
    monkeypatch.setattr(npc_agent, "render", render)
    monkeypatch.setattr(resolution_agent, "resolve", resolve)
    monkeypatch.setattr(lore, "get_main_quest", lambda: "MAIN QUEST")
    return seen


def test_a_turn_commits_its_changes_and_trace(ws, seen):
    dm = dm_agent.DMAgent(ws)
    assert play(dm) == "Torben leans in."

    saved = WorldState(ws.path).get_state()  # re-read from disk
    assert saved["session"]["turn"] == 1
    assert saved["session"]["active_npc"] == "Torben Grall"
    assert saved["npcs_met"]["Torben Grall"]["state"]["disposition_points"] == 40
    assert saved["progression"]["xp"] == 5
    assert dm.last_trace["agents"] == [
        "DM · route",
        "NPC · ensure (Torben Grall)",
        "Resolution",
        "NPC · render",
        "DM · narrate",
    ]


def test_a_failed_turn_rolls_back_everything(ws, seen, monkeypatch):
    async def timeout(**kwargs):
        raise TimeoutError("model timed out")

    monkeypatch.setattr(resolution_agent, "resolve", timeout)
    before = ws.get_state()
    with pytest.raises(TimeoutError):
        play(dm_agent.DMAgent(ws))
    assert ws.get_state() == before  # including the NPC created mid-turn
    assert not Path(ws.path).exists()


def test_overreach_is_rejected_before_anything_runs(ws, seen, monkeypatch):
    async def route(action, ws):
        return Routing(overreach_detected=True, overreach_explanation="You declared its death.")

    monkeypatch.setattr(dm_agent, "route", route)
    before = ws.get_state()

    message = play(dm_agent.DMAgent(ws), "A dragon appears and dies at my feet.")

    assert "OVERREACH" in message and "You declared its death." in message
    assert "resolve" not in seen
    assert ws.get_state() == before


def test_resolution_sees_numbers_but_the_npc_voice_does_not(ws, seen):
    play(dm_agent.DMAgent(ws))
    fields = seen["resolve"]["world_fields"]
    assert fields["player"]["hp"] == 100
    assert fields["involved_npc"]["disposition_points"] == 30
    assert "disposition_points" not in seen["render_sheet"]["state"]


def test_the_dm_view_carries_labels_only(ws):
    view = dm_agent._dm_fields(ws)
    assert not {"hp", "energy_points"} & view["player"].keys()
    assert "progression" not in view and view["rank"] == "Recruit"


@pytest.mark.parametrize(
    ("score", "probability"), [(0, 0.0), (11, 0.0), (12, 0.30 / 9), (20, 0.30), (40, 0.30)]
)
def test_interjection_probability_is_gated_and_capped(score, probability):
    assert dm_agent.interjection_probability(score) == pytest.approx(probability)


def test_the_orchestrator_not_the_model_rolls_interjections(ws):
    dm = dm_agent.DMAgent(ws)
    dm_agent.seed_interjections(7)

    def fired(score):
        candidate = Interjection(unpredictability_score=score, description="a door bangs open")
        return sum(dm._roll_interjection(candidate) is not None for _ in range(1000))

    assert fired(11) == 0
    assert 240 < fired(20) < 360  # ~30% ceiling
