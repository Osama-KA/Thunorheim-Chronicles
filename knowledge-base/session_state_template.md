# Thunorheim Session State
# This file is the mutable truth of the campaign.
# Updated after every turn. Never uploaded to Foundry IQ.
# Lives in /state/session_state.json
#
# Numeric layer: hp, energy_points, disposition_points, and the progression
# block are the SOURCE OF TRUTH. The labels (health, energy,
# disposition_toward_player, title) are DERIVED from them and never set
# directly. The Resolution Agent emits numeric deltas (hp_delta, energy_delta,
# xp_delta, disposition_delta); World State applies them, clamps, and re-derives
# the labels.

---

## TEMPLATE STRUCTURE

{
  "player": {
    "name": "",
    "role": "",
    "hp": 100,
    "health": "Fresh",
    "energy_points": 100,
    "energy": "Full",
    "location": "Greyhold",
    "active_effects": []
  },

  "inventory": [],

  "quests": {
    "active": [],
    "completed": [],
    "failed": []
  },

  "reputation": {
    "wardens_guild": "Initiate",
    "factions": {
      "valdenmoor": "Neutral"
    }
  },

  "npcs_met": {},

  "world_flags": {
    "drenhold_discovered": false,
    "ashen_seal_found": false,
    "ashwatch_post_investigated": false,
    "survivor_rescued": false,
    "aldric_trust_unlocked": false
  },

  "progression": {
    "xp": 0,
    "tier": 1,
    "title": "Recruit",
    "xp_to_next": 100,
    "pending_tier": null
  },

  "session": {
    "turn": 0,
    "current_scene": "",
    "last_scene_summary": "",
    "open_threads": [],
    "active_npc": ""
  }
}

---

## FIELD DEFINITIONS

### player
name — the player's chosen character name
role — Warden, Runescribe, Shroud, or Thornwarden
hp — integer 0-100, the SOURCE OF TRUTH for health
health — DERIVED label from hp (see Health Track below)
energy_points — integer 0-100, the SOURCE OF TRUTH for energy
energy — DERIVED label from energy_points (see Energy Track below)
location — current location in Thunorheim
active_effects — ongoing conditions, rune effects, Thorncraft
treatments, or Blight exposure

### Health Track (derived from hp)
100        → Fresh
75-99      → Scratched
50-74      → Hurt
25-49      → Wounded
10-24      → Critical
1-9        → Down
0          → Dead

### Energy Track (derived from energy_points)
76-100     → Full
51-75      → Strained
26-50      → Drained
1-25       → Empty
0          → Collapsed

### inventory
A flat list of item strings the player is currently carrying.
If an item is not in this list the player does not have it.

### quests
active / completed / failed — lists of quest objects.
Each quest object:
{
  "title": "",
  "current_objective": "",
  "known_clues": [],
  "complications": [],
  "status_notes": ""
}
The Resolution Agent links discoveries to quests: encountering a quest's
hook or first clue activates it; later clues advance it. The main quest
document is always available to Resolution for this.

### reputation
wardens_guild — overall standing with the Guild
Values: Unknown, Initiate, Trusted, Respected, Distinguished, Disgraced
factions — standing per named faction
Values: Hostile, Unfriendly, Neutral, Friendly, Allied

### npcs_met
Keyed by canonical NPC name. Created on first encounter, updated after
each interaction.

Each NPC entry:
{
  "profile": {
    "name": "",
    "role": "",
    "faction": "",
    "personality": "",
    "goals": "",
    "location": ""
  },
  "state": {
    "disposition_toward_player": "Neutral",
    "disposition_points": 0,
    "last_interaction_summary": "",
    "knows_about_player": [],
    "last_known_location": ""
  }
}

disposition_points — integer -100..+100, the SOURCE OF TRUTH
disposition_toward_player — DERIVED label (see below)

### Disposition Track (derived from disposition_points)
+61 to +100    → Allied
+21 to +60     → Friendly
+1  to +20     → Trusting
0              → Neutral
-1  to -20     → Unfriendly
-21 to -60     → Hostile
-61 to -100    → On sight

### world_flags
Boolean flags tracking whether significant binary world milestones have
occurred. This is a CLOSED, canonical vocabulary — only the flags defined in
the schema can be set, and names are normalized (case/separators) so variants
match. The Resolution Agent cannot invent new flags at runtime; a stray flag is
ignored rather than added. Emergent developments (a discovered clue, a new
lead, a complication) belong in the relevant quest's known_clues / complications
or in open_threads, not here. New canonical flags are added deliberately to the
schema as the campaign grows, not improvised mid-play.

### progression
xp — total experience points (source of truth for advancement)
tier — current rank tier, 1-6
title — DERIVED from role + tier (e.g. Warden tier 2 = "Tracker")
xp_to_next — XP remaining to reach the next tier threshold (null at tier 6)
pending_tier — the tier the player has EARNED the right to reach but has
not yet been promoted to, or null. XP alone never promotes — crossing a
threshold sets pending_tier; actual advancement requires a rite of passage
performed by a qualified figure (Guild authority or role instructor), which
the Resolution Agent signals with "promote": true.

Tier thresholds (XP): 1 = 0, 2 = 100, 3 = 250, 4 = 500, 5 = 900, 6 = 1500
Titles per role:
  Warden:      Recruit, Tracker, Warden, Greymark Veteran, Ironclad, Legendary Warden
  Runescribe:  Apprentice, Inscriber, Runescribe, Arcanist, Lorekeeper, Legendary Runescribe
  Shroud:      Shadow, Operative, Shroud, Ghostblade, Whisper, Legendary Shroud
  Thornwarden: Herbalist, Field Medic, Thornwarden, Blightwalker, Thornweaver, Legendary Thornwarden

### session
turn — increments by one after every resolved player action
current_scene — one line: where the player is and what is happening
last_scene_summary — two to three sentences on the previous turn
open_threads — unresolved situations the world is responding to
active_npc — canonical name of the character the player is currently in
conversation with. Set by the DM Agent after any NPC turn and used to anchor
ambiguous references ("her", "the woman") so pronouns resolve to the current
partner instead of jumping to another character. Empty when no one is engaged.

---

## EXAMPLE POPULATED STATE

{
  "player": {
    "name": "Edwyn Carr",
    "role": "Warden",
    "hp": 62,
    "health": "Hurt",
    "energy_points": 63,
    "energy": "Strained",
    "location": "Ashfringe road, two miles east of Greyhold",
    "active_effects": ["Thorncraft resistance salve active"]
  },

  "inventory": [
    "longsword",
    "Warden field kit",
    "Thorncraft resistance salve x1 remaining",
    "torch x2",
    "Guild contract document"
  ],

  "quests": {
    "active": [
      {
        "title": "The Shattered Seal",
        "current_objective": "Reach Ashwatch Post and determine what destroyed it",
        "known_clues": ["Organized formation tracks found on the eastern road"],
        "complications": ["Greywalker signs spotted near the waystation"],
        "status_notes": "Aldric requested no paperwork on this contract"
      }
    ],
    "completed": [],
    "failed": []
  },

  "reputation": {
    "wardens_guild": "Trusted",
    "factions": {
      "valdenmoor": "Neutral"
    }
  },

  "npcs_met": {
    "Aldric Vane": {
      "profile": {
        "name": "Aldric Vane",
        "role": "Guildmaster of Greyhold",
        "faction": "Wardens Guild",
        "personality": "Pragmatic, politically shrewd, carries the weight of hard decisions privately",
        "goals": "Determine what is happening in the Greymark before the kingdoms find out",
        "location": "Greyhold Guild Hall"
      },
      "state": {
        "disposition_toward_player": "Friendly",
        "disposition_points": 40,
        "last_interaction_summary": "Privately briefed the player on the missing outposts and assigned the Ashwatch Post investigation off the books",
        "knows_about_player": [
          "Capable enough to trust with sensitive work",
          "Assigned to Ashwatch Post investigation"
        ],
        "last_known_location": "Greyhold Guild Hall"
      }
    }
  },

  "world_flags": {
    "drenhold_discovered": false,
    "ashen_seal_found": false,
    "ashwatch_post_investigated": false,
    "survivor_rescued": false,
    "aldric_trust_unlocked": true
  },

  "progression": {
    "xp": 120,
    "tier": 1,
    "title": "Recruit",
    "xp_to_next": 0,
    "pending_tier": 2
  },

  "session": {
    "turn": 4,
    "current_scene": "Player on the eastern road, Greymark visible on the horizon, Greywalker tracks spotted ahead",
    "last_scene_summary": "Player left Greyhold after briefing with Aldric. Found formation tracks on the eastern road. Greywalker signs near the waystation suggest something is active between here and Ashwatch Post.",
    "open_threads": [
      "Greywalker activity on the eastern road",
      "Castor Veld noticed the player leaving with a Guild kit — may investigate"
    ],
    "active_npc": ""
  }
}
