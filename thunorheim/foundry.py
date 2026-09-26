"""Foundry IQ interface — static world + rules knowledge retrieval.

Foundry IQ holds knowledge that never changes during play: world lore (locations,
factions, characters, monsters, the artifact) and the seven-bucket rules. This
module is the single seam the rest of the system goes through to read it.

Backing store: Azure AI Search index connected to Foundry IQ knowledge base.
Local markdown fallback for get_rules() and get_npc_templates() since those
are baked into agent prompts and don't need search.
"""

from __future__ import annotations

import os
from functools import cache

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from dotenv import load_dotenv

load_dotenv()

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KB_DIR = os.path.join(_PROJECT_ROOT, "knowledge-base")

# Topic -> source document filenames in the search index.
# These match metadata_storage_path values returned by Azure AI Search.
_TOPIC_DOCS = {
    "world":      ["world_summary.md"],
    "location":   ["starting_location.md"],
    "quest":      ["main_quest.md"],
    "companions": ["party_profiles.md"],
    "party":      ["party_profiles.md"],
    "factions":   ["factions.md"],
    "artifact":   ["artifact.md"],
    "monster":    ["monster.md"],
    "creature":   ["monster.md"],
}


def _get_search_client() -> SearchClient:
    return SearchClient(
        endpoint=os.environ["AZURE_SEARCH_ENDPOINT"],
        index_name=os.environ["AZURE_SEARCH_INDEX"],
        credential=AzureKeyCredential(os.environ["AZURE_SEARCH_KEY"]),
    )


def _search(query: str, top: int = 5, filter_expr: str | None = None) -> list[dict]:
    """Run a search query and return raw result dicts."""
    client = _get_search_client()
    kwargs = {"top": top}
    if filter_expr:
        kwargs["filter"] = filter_expr
    results = client.search(query, **kwargs)
    return [dict(r) for r in results]


def _format_results(results: list[dict]) -> str:
    """Format search results into readable text for agent consumption."""
    if not results:
        return ""
    parts = []
    for r in results:
        source = r.get("metadata_storage_path", "unknown")
        snippet = r.get("snippet", "")
        if snippet:
            parts.append(f"# SOURCE: {source}\n\n{snippet}")
    return "\n\n---\n\n".join(parts)


@cache
def _read_local(filename: str) -> str:
    """Read a local knowledge-base file. Used for rules and templates only."""
    path = os.path.join(_KB_DIR, filename)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def get_rules() -> str:
    """The full seven-bucket rules + role-capability reference.

    Baked directly into the Resolution Agent's prompt from local file.
    Rules are static and small — no need to search for them."""
    return _read_local("homebrew_rules.md")


def get_npc_templates() -> str:
    """The new-NPC generation templates."""
    return _read_local("npc_templates.md")


def get_main_quest() -> str:
    """The campaign's main quest document (hooks, clues, outcomes, GM secrets).

    Always injected into the Resolution Agent's context so it can LINK a player's
    discovery to quest activation/advancement. The main quest is the campaign
    backbone — too important to depend on the DM's per-turn topic prediction or on
    a search hit, so it is read locally like the rules."""
    return _read_local("main_quest.md")


def query_world_knowledge(query: str, topics: list[str] | None = None) -> str:
    """Return relevant world-knowledge from Foundry IQ via Azure AI Search.

    If topics are given, builds a filter to target those specific source documents.
    Otherwise runs a semantic search against the full index.
    Falls back to empty string on any search error so a failed retrieval
    never crashes a turn.
    """
    try:
        if topics:
            # Collect the target filenames for these topics
            target_files = []
            for topic in topics:
                target_files.extend(_TOPIC_DOCS.get(topic, []))

            # De-dup preserving order
            seen: set[str] = set()
            ordered = [f for f in target_files if not (f in seen or seen.add(f))]

            if not ordered:
                # Topics given but none mapped — fall back to free search
                results = _search(query, top=5)
            else:
                # Filter to only the relevant source documents
                # Azure AI Search filter syntax for metadata_storage_path
                filter_clauses = " or ".join(
                    f"metadata_storage_path eq '{fname}'" for fname in ordered
                )
                results = _search(query, top=8, filter_expr=filter_clauses)
        else:
            # Free semantic search across the whole index
            results = _search(query, top=5)

        return _format_results(results)

    except Exception as exc:
        # Never crash a turn over a retrieval failure
        print(f"[Foundry IQ retrieval warning: {exc}]")
        return ""