# Thunorheim

> *A frontier holds the line against the Blight.*

Thunorheim is a persistent-memory narrative RPG powered by a four-agent reasoning
system. It began as a submission for the Microsoft AI Skills Fest — Agents League,
Challenge B: Role-Play-Game System, built on Azure AI Foundry.

> **Status:** being rebuilt for v1. The hackathon version (Azure AI Foundry) is tagged
> [`v0.1.0`](../../tree/v0.1.0); the current code runs on any OpenAI-compatible provider
> (see `models.toml`). Sections below that mention Azure describe the hackathon build and
> will be rewritten when v1 ships.

Every choice leaves a permanent mark. The world remembers. Consequences are enforced
by logic, not narrative convenience. No matter how long the campaign runs, nothing
important gets lost.

---

## What This Is

Thunorheim is two things simultaneously.

As a **game**, it is a high fantasy narrative RPG set in a world scarred by a spreading
corruption called the Blight. Players choose one of four roles — Warden, Runescribe,
Shroud, or Thornwarden — and operate as licensed Guild hunters navigating monster
contracts, political intrigue, and a deepening mystery at the heart of a dying frontier.
The world has its own momentum. It does not wait for the player, and it does not forget
them either.

As a **system**, it is a demonstration of what multi-agent reasoning architecture can do
that a single language model cannot. Four specialized agents — each with a distinct,
non-overlapping responsibility — coordinate through a structured turn pipeline to
produce outcomes that are logically grounded, consequence-aware, and persistent across
every session. The architecture solves real problems that make long-form AI-driven
campaigns break down in practice. The world is not a story being written around the
player. It is a living system that responds to them.

---

## The Problem It Solves

Anyone who has tried to run a long campaign with a raw language model knows exactly how
it breaks down.

**Context windows fill up.** Old facts fall off. The NPC the player met three sessions
ago becomes a stranger. Established details drift. The model reconstructs the world
freshly from whatever context it can still see — and gets it wrong.

**Consequences do not stick.** The model optimizes for satisfying responses in the
moment. It unconsciously softens outcomes, lets the player succeed when they should
not, and bends the world toward whatever feels narratively convenient right now rather
than what logically follows from what actually happened.

**Rules get applied inconsistently.** The same action resolves differently depending
on the scene, the model's current context, and what sounds good. There is no consistent
rule engine — just vibes.

**State evaporates.** Inventory, health, reputation, relationships — none of it is
actually tracked. It exists in context until it does not.

**Logical progression collapses.** The world stops feeling like a place with its own
momentum and starts feeling like a story being written around the player to make them
feel good.

These are not model problems. They are architecture problems. Thunorheim is the
architecture solution.

---

## Architecture Overview

Thunorheim separates the things a language model is good at (language, character,
judgment) from the things it is bad at (consistency, memory, honest bookkeeping) and
gives each to a component built for it.

```
        Player action
             │
             ▼
   ┌───────────────────┐   1. classify intent · detect overreach · route
   │     DM AGENT       │──────────────────────────────────────────────┐
   │  (orchestrator)    │                                               │
   └─────────┬─────────┘                                                │
             │ (if a character is involved)                             │
             ▼                                                          │
   ┌───────────────────┐   resolve reference → canonical NPC,           │
   │     NPC AGENT      │   load-or-create, return stance               │
   └─────────┬─────────┘                                                │
             ▼                                                          │
   ┌───────────────────┐   weigh the rule buckets, no dice,             │
   │ RESOLUTION AGENT   │   emit a structured verdict + state delta     │
   └─────────┬─────────┘                                                │
             ▼                                                          │
   ┌───────────────────┐   validate every change, clamp, commit         │
   │  WORLD STATE       │   the turn as one transaction                 │
   │  (pure Python)     │                                               │
   └─────────┬─────────┘                                                │
             ▼                                                          ▼
        NPC reply (in character)  ──────────►  2. DM narrates the outcome
                                                  faithfully → Player sees this
```

The DM Agent is the orchestrator and the only thing the player ever sees. There is **no
fixed agent order** — the DM routes each turn dynamically based on what the action
actually requires. The whole turn runs inside a World State **transaction**: if anything
fails partway through, the turn rolls back and nothing is half-written.

Two kinds of knowledge live in two different places:

- **Static knowledge** (lore, locations, factions, the rules) lives in **Foundry IQ**
  (Azure AI Search) and never changes during play.
- **Mutable knowledge** (health, energy, inventory, quests, reputation, every NPC ever
  met, world flags, session continuity) lives in the **World State** and changes every
  single turn.

---

## The Four Agents

**DM Agent** — *orchestrator + intent classifier + router + narrator.* Every turn begins
and ends here. Its first pass classifies the action into rule buckets, checks for
**overreach** (a player trying to author the world rather than their own actions),
decides whether an NPC is involved, and selects which world knowledge the turn needs.
Its second pass narrates the resolved outcome — and is bound to narrate it *faithfully*,
never upgrading a failure into a success.

**Resolution Agent** — *the logic engine.* Receives the action, the NPC's stance, the
relevant world state (with raw numbers), and the seven-bucket rules. It evaluates what
*actually* happens through honest logical reasoning — **no dice, no narrative
convenience** — and emits a structured JSON verdict: per-bucket evaluation, a consequence
tier, a factual narration seed, and a validated numeric state delta. It writes nothing
itself; it hands the delta to World State.

**NPC Agent** — *the consistency layer.* Resolves how the player referred to a character
("the bartender", "her") to a single canonical entity, loads that character's persisted
sheet or builds a new one from lore/templates, and voices an in-character response
conditioned on the verdict. It never decides mechanical outcomes — only character.

**World State Agent** — *the single source of truth.* Pure Python, no model. The only
component that writes to the save. It is the deterministic guardrail: it validates every
change against the rules (health/energy/disposition tracks, reputation scales, canonical
world flags), clamps numbers into range, derives display labels from those numbers, and
commits each turn as an atomic transaction. A malformed value from a model is repaired or
rejected — it can never corrupt the save.

---

## Key Features

- **Persistent memory that actually persists.** Player stats, inventory, quests,
  reputation, world flags, session continuity, and *every NPC ever met* (with their full
  profile and current disposition) are tracked in a single source of truth and survive
  across sessions. Quit and resume mid-campaign and nothing is lost — verified
  byte-for-byte.
- **No dice — logic-based resolution.** A seven-bucket rule system (Combat, Social,
  Exploration, Stealth, Skill Use, Manipulation, Narrative Progression) resolves every
  action by weighing defined factors. Smart plays have better odds; nothing is
  guaranteed; outcomes are never bent for story convenience.
- **Numeric core, narrative surface.** Health, energy, and NPC disposition are exact
  numbers (the source of truth) that derive human labels — *Fresh, Hurt, Wounded*;
  *Friendly +50* — so the model reasons with precision while the player reads prose.
- **Progression with a rite of passage.** Earning XP makes you *eligible* for the next
  rank, but advancement requires a formal rite from a qualified Guild authority — XP alone
  never promotes you.
- **Overreach detection.** The player controls their own character; the world is the DM's
  to describe. Attempts to author world events ("a dragon appears and dies") are caught
  and rejected without touching state.
- **A world that intrudes.** A probability-capped interjection system lets the world
  occasionally act on its own — a third party walks in, a complication lands — scored by
  the scene and gated so it stays rare and earned.
- **Quest linking.** Discoveries are automatically tied to quest state: finding the right
  clue activates and advances the main quest rather than vanishing into prose.
- **Transactional integrity.** Each turn commits atomically. A failure mid-turn rolls the
  whole turn back — the save is never left half-written.

---

## Microsoft Foundry Integration

Thunorheim is built **on** Azure AI Foundry, not merely against an API.

- **Foundry Agent Service.** The three reasoning agents — `dm-agent`,
  `resolution-agent`, and `npc-agent` — are registered as named prompt agents in the
  Foundry project and invoked through the **Responses API** (a conversation is created,
  then a response is requested against the agent by `agent_reference`). Each agent shows
  up as a distinct, traceable agent in the Foundry portal, so the multi-agent reasoning
  is observable end to end.
- **Model.** All reasoning runs on a `gpt-5-mini` deployment in the Foundry project.
- **Foundry IQ (grounding).** The world's static knowledge is indexed in Azure AI Search
  and retrieved at runtime to ground every resolution — keeping the narrative consistent
  with a canonical knowledge base far larger than any context window.
- **Auth.** Access uses `DefaultAzureCredential`, which works unchanged from a developer
  machine (`az login`) and from a managed identity in the cloud — see *Deployment Story*.

The World State Agent is deliberately **not** a model — it is the deterministic Python
core that the hosted agents read and write through. This split (hosted reasoning agents +
local deterministic truth) is the heart of the design.

---

## External Tool Integration

Per the requirement, Thunorheim integrates external tools/APIs **where they add real
value** — and the test of "real value" is load-bearing: remove the integration and the
system breaks.

- **Azure AI Foundry Agent Service** *(external API).* The entire turn pipeline is
  external-API-driven multi-agent orchestration. The agents are hosted Foundry agents
  invoked via the Responses API. *Remove it and there is no game.*
- **Azure AI Search — Foundry IQ** *(external service).* Runtime retrieval-augmented
  grounding of lore, the seven-bucket rules, NPC profiles, and the main quest. It is what
  keeps the world coherent and what makes quest-linking possible across a long campaign.
  *Remove it and the narrative and quest logic break.*

Both pass the load-bearing test. Several further integrations were scoped and
deliberately deferred as not adding proportional value for this build (generative scene
art, a Cosmos DB persistence backend, exposing the World State as an MCP server) — they
are clean future extensions, not requirements the game depends on.

---

## Synthetic Data

The entire knowledge base is **synthetic** — original fiction authored for this project.
There is no real-world data, no personal data, and no external dataset; everything the
world "knows" was written for Thunorheim and indexed into Foundry IQ.

The corpus (`knowledge-base/`) includes:

- `world_summary.md` — the world, the Blight, the Warden's Guild, magic systems
- `starting_location.md` — Greyhold, its NPCs, tensions, and secrets
- `main_quest.md` — *The Shattered Seal*: hooks, clues, branches, and outcomes
- `party_profiles.md` — companion characters
- `factions.md` — the Warden's Guild and the Kingdom of Valdenmoor
- `monster.md` / `artifact.md` — the Greywalker and the Ashen Seal
- `homebrew_rules.md` — the seven-bucket resolution system and role capabilities
- `npc_templates.md` — generation templates for new, unscripted NPCs
- `session_state_template.md` — the schema for the mutable save

At runtime, a second body of data is **generated**: the session state itself —
every stat, item, quest, NPC sheet, and world flag — is produced and evolved by play and
stored in `state/session_state.json`.

---

## Responsible AI

- **Azure content safety / Prompt Shields** are active on the model deployment — prompt
  injection and jailbreak attempts are filtered at the platform layer.
- **Honest resolution, by design.** The Resolution Agent is explicitly forbidden from
  bending outcomes for narrative convenience or sycophancy. Failure is narrated as
  failure; the DM's narration is bound to the verdict and cannot soften it. The system is
  built specifically to *resist* the "tell the user what they want to hear" failure mode.
- **Authorship boundaries.** Overreach detection enforces a clear line between what the
  player may author (their own character) and what the system authors (the world),
  preventing players from dictating outcomes or world facts.
- **No fabricated state.** The pure-Python World State validates and clamps every change;
  the model cannot invent inventory the player does not have, set an off-track value, or
  corrupt the save. Bad model output is repaired or rejected, never persisted.
- **Bounded, fictional content.** All content is original dark-fantasy fiction with no
  real-world people, places, or groups as targets.

---

## Evaluations and Testing

The system was validated with layered automated and model-in-the-loop testing, all run
through the real Foundry pipeline.

- **Unit / invariant checks (deterministic).** Numeric derivation and clamping, the
  health/energy/disposition number↔label sync, progression and the promotion rite,
  canonical-flag enforcement, the interjection probability gate, transaction
  rollback, and DM/NPC number-isolation.
- **Pipeline stress test** (`pipeline_test.py`) — three continuous 10-turn playthroughs
  (social, combat, exploration) driven by an AI player, with crafted hard actions to
  stress the Resolution Agent. **194/194 automated assertions passed.**
- **Diagnostic gate** — targeted checks of the headline feature paths the long runs
  hadn't naturally triggered: the promotion rite, a fired interjection, death/game-over,
  the Thornwarden role, and save/resume. All passed.
- **Final persistence test** (`persistence_test.py`) — one continuous **75-turn** reactive
  playthrough, including a mid-run **save/reload** (the world rebuilt from disk was
  **byte-for-byte identical** and play continued) and memory-callback probes (returning to
  an NPC met dozens of turns earlier resolved to the same character with accumulated
  history — no duplicates). **398/400 assertions passed**; the two failures were a single
  malformed-JSON turn that rolled back cleanly (now hardened with a retry).

Issues found during testing were fixed and re-verified — including NPC reference
continuity, location tracking, an invalid default reputation value, and JSON-resilience
on rare malformed model output.

---

## Setup and Running

**Prerequisites**

- [uv](https://docs.astral.sh/uv/) (installs Python 3.13 for you)
- An API key for at least one provider in `models.toml` (Gemini, Groq, or NVIDIA);
  roles skip providers without a key

**Install**

```bash
uv sync
```

**Configure** — copy `.env.example` to `.env` and fill it in.

**Run**

```bash
uv run streamlit run app.py      # the full graphical experience
uv run python main.py            # terminal version
```

**Test**

```bash
uv run pytest                          # unit + orchestration tests (no keys needed)
uv run python evals/smoke.py           # quick 3-turn live smoke test
uv run python evals/stress.py          # 3 x 10-turn live pipeline stress test
uv run python evals/persistence.py     # 75-turn live persistence test
```

State persists in `state/session_state.json` between turns and sessions; **Continue** in
the UI resumes the saved campaign with a DM-generated recap.

---

## Deployment Story

**What is already cloud-hosted.** The reasoning core is genuinely a hosted, managed-cloud
system: the three agents run in **Azure AI Foundry Agent Service**, the model is a hosted
**gpt-5-mini** deployment, and grounding is served by **Azure AI Search (Foundry IQ)**.
The multi-agent reasoning, the model, and the knowledge base all already live in Azure.

**What runs locally for the demo.** The Streamlit front-end and the pure-Python World
State core run on the developer machine and talk to the hosted Foundry backend via
`DefaultAzureCredential` (`az login`).

**Hosting the full stack.** Promoting the front-end to a fully hosted deployment is a
short, well-defined path:

1. **Containerize** — a `Dockerfile` from `python:3.13-slim`, `pip install -r
   requirements.txt`, expose `8501`, and
   `streamlit run app.py --server.address 0.0.0.0 --server.port 8501`.
2. **Registry** — push the image to **Azure Container Registry**.
3. **Host** — deploy to **Azure Container Apps** (or App Service for Containers); a single
   replica, scale-to-zero, suffices for the demo.
4. **Auth with zero code change** — give the Container App a **system-assigned managed
   identity** and grant it RBAC (Azure AI / Cognitive Services User on the Foundry
   project; Search Index Data Reader on the Search service). `DefaultAzureCredential`
   already used by the app automatically detects the managed identity in-cloud — the same
   code that uses `az login` locally needs no modification.
5. **Config & secrets** — supply `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT`,
   and the Search settings as Container App environment variables; store the Search key in
   **Azure Key Vault** (or drop the key entirely in favor of managed-identity RBAC on
   Search).
6. **Multi-user persistence** — the only change needed for cloud-scale saves is the World
   State storage seam: swap the single local `session_state.json` for **Azure Cosmos DB**
   or **Blob Storage** (one keyed document per player). The agents and rules are
   unaffected.

The architecture was built with this seam in mind: the deterministic core is isolated
behind a single file-I/O boundary, and auth is already cloud-portable — so the local demo
and a fully hosted deployment are the same application.

---

## The World — Thunorheim

Thunorheim is a continent of competing human kingdoms and frontier settlements bound
together by one existential threat: **the Blight**, a spreading corruption that seeps
from deep within the earth, warping creatures into monsters and rotting the land. Regions
consumed by it are called the **Greymark**. It grows slowly and never retreats.
Unpredictable surges of corrupted creatures — **Riftings** — devastate any settlement
caught unprepared, and they are coming more often than they used to.

The **Warden's Guild** is the only institution that crosses kingdom borders without
friction: licensed hunters and scouts who put themselves between the Greymark and the
people. The player is one of them, operating out of **Greyhold**, the last real settlement
before the Greymark begins.

Players choose a role, each with its own way of meeting the world:

- **Warden** — frontline hunter, tracker, survivor of the Greymark.
- **Runescribe** — arcane scholar; magic here is *inscribed* into runes, not cast.
- **Shroud** — operative of infiltration, information, and leverage.
- **Thornwarden** — controversial Blight-healer who walks the line between curing
  corruption and wielding it.

The campaign opens with **The Shattered Seal**: Warden outposts to the east have gone
silent, the Guildmaster is hiding how bad it has gotten from the watching kingdoms, and a
single word — **DRENHOLD** — keeps surfacing where it should not. Something in the deep
Greymark is not acting on instinct. It is acting with purpose.

The world has its own momentum. It does not wait for you. It does not forget you.
