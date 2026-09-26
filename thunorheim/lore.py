"""Static world knowledge from knowledge-base/: lore, rules, NPC templates.

Topic lookup returns whole documents. Chunked, ranked retrieval replaces this in
the memory phase (P8); callers only see query_world_knowledge().
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

KB_DIR = Path(__file__).resolve().parent.parent / "knowledge-base"

TOPIC_DOCS = {
    "world": ["world_summary.md"],
    "location": ["starting_location.md"],
    "quest": ["main_quest.md"],
    "companions": ["party_profiles.md"],
    "party": ["party_profiles.md"],
    "factions": ["factions.md"],
    "artifact": ["artifact.md"],
    "monster": ["monster.md"],
    "creature": ["monster.md"],
}


@cache
def read(filename: str) -> str:
    return (KB_DIR / filename).read_text(encoding="utf-8")


def get_rules() -> str:
    """The seven-bucket rules + role capabilities, baked into the Resolution prompt."""
    return read("homebrew_rules.md")


def get_npc_templates() -> str:
    return read("npc_templates.md")


def get_main_quest() -> str:
    """Always given to Resolution so a discovery can be linked to the quest."""
    return read("main_quest.md")


def query_world_knowledge(topics: list[str]) -> str:
    """The documents behind the requested topics, each once, in request order."""
    files = dict.fromkeys(f for topic in topics for f in TOPIC_DOCS.get(topic, []))
    return "\n\n---\n\n".join(f"# SOURCE: {f}\n\n{read(f)}" for f in files)
