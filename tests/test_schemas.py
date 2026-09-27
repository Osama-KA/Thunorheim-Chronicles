import pytest
from pydantic import ValidationError

from thunorheim.schemas import NpcResolution, Routing, StateDelta, Verdict

MINIMAL = {
    "combined_outcome": "It lands.",
    "consequence_tier": "Full success",
    "narration_seed": "The blade bites deep.",
}


def test_a_minimal_verdict_gets_safe_defaults():
    verdict = Verdict.model_validate(MINIMAL)
    assert verdict.state_delta == StateDelta()
    assert verdict.suggested_actions == []


@pytest.mark.parametrize("tier", ["partial SUCCESS", "  Partial success "])
def test_tier_casing_is_normalized(tier):
    verdict = Verdict.model_validate({**MINIMAL, "consequence_tier": tier})
    assert verdict.consequence_tier == "Partial success"


def test_an_invented_tier_is_rejected():
    with pytest.raises(ValidationError):
        Verdict.model_validate({**MINIMAL, "consequence_tier": "Critical hit"})


@pytest.mark.parametrize("missing", ["combined_outcome", "consequence_tier", "narration_seed"])
def test_a_verdict_without_its_core_fields_is_rejected(missing):
    with pytest.raises(ValidationError):
        Verdict.model_validate({k: v for k, v in MINIMAL.items() if k != missing})


def test_null_means_default():
    routing = Routing.model_validate(
        {"overreach_explanation": None, "npc_reference": None, "buckets": None}
    )
    assert (routing.overreach_explanation, routing.npc_reference, routing.buckets) == ("", "", [])


def test_unknown_fields_cannot_smuggle_writes():
    delta = StateDelta.model_validate(
        {
            "npc_updates": {"Signe": {"disposition_delta": 5, "disposition_points": 100}},
            "player": {"hp": 100, "active_effects": ["bleeding"]},
            "gold": 9999,
        }
    ).model_dump(exclude_none=True)
    assert delta["npc_updates"]["Signe"] == {"disposition_delta": 5}
    assert delta["player"] == {"active_effects": ["bleeding"]}
    assert "gold" not in delta


def test_a_new_npc_starts_from_a_label_not_raw_points():
    npc = NpcResolution.model_validate(
        {
            "canonical_name": "Brenna",
            "initial_state": {"disposition_toward_player": "Friendly", "disposition_points": 100},
        }
    )
    assert npc.initial_state.model_dump() == {
        "disposition_toward_player": "Friendly",
        "last_known_location": "",
    }
