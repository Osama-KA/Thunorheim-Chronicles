# NPC Generation Templates

These templates are used by the NPC Agent ONLY when a character is introduced
who does not already exist in World State and does not match a named NPC in the
world knowledge (starting_location, party_profiles, factions). The NPC Agent
picks the template that best fits the situation the DM Agent routed, then fills
in the blanks to produce a concrete NPC sheet via create_npc().

Named lore NPCs (Aldric Vane, Maren Ashveld, Torben Grall, Signe, Edric Fenn,
Bram Ashford, Lysa Vorn, Edda Voss, Castor Veld, Kael Dunmore) must NEVER be
generated from a template — read them from world knowledge instead.

Each generated NPC sheet must conform to the npcs_met schema:
profile { name, role, faction, personality, goals, location }
state { disposition_toward_player, last_interaction_summary, knows_about_player,
last_known_location }

Always generate a canonical name before calling create_npc(). Frontier names in
Thunorheim are short and Norse-flavored (Bren, Halla, Osric, Sigrún, Tovald,
Yrsa, Gunnar, Mette).

---

## Template 1 — Friendly / Cooperative

Use when the situation implies the NPC has no reason to oppose the player: a
fellow Warden, a grateful townsperson, a talkative merchant, someone the player
has just helped.

- default disposition: Friendly
- role: commoner, junior Warden, tradesperson, contract worker
- faction: usually Warden's Guild affiliate or unaffiliated frontier folk
- personality scaffold: open, talkative, a little worn down by frontier life,
  willing to share rumors and directions, grateful for competence
- goals pattern: get through the day, stay safe, see the Greymark held back
- speech style: plain, warm, practical
- tends to know: local rumors, who's who in Greyhold, surface-level Guild gossip
- does NOT know: classified Guild intelligence, anything about Drenhold

## Template 2 — Hostile / Antagonistic

Use when the situation establishes the NPC as a threat or adversary: a thug, a
corrupted-adjacent zealot, a rival operative, someone the player has wronged.

- default disposition: Hostile (or Unfriendly if not yet provoked to violence)
- role: brigand, rival contractor, Valdenmoor enforcer, frontier opportunist
- faction: unaffiliated, criminal, or quietly Valdenmoor-aligned
- personality scaffold: guarded, aggressive or coldly transactional, treats the
  player as an obstacle or a mark
- goals pattern: take what they want, protect their interest, win the exchange
- speech style: clipped, threatening, or falsely polite over menace
- tends to know: their own agenda, who hired them if anyone
- combat note: Resolution Agent assigns the behavior archetype (Aggressive,
  Cowardly, Tactical, etc.) — the NPC Agent only voices the character

## Template 3 — Neutral / Wary

Use as the default when the situation gives no strong signal: a stranger on the
road, a guard doing their job, a closed-off survivor, a busy shopkeeper.

- default disposition: Neutral
- role: guard, traveler, laborer, refugee, minor official
- faction: unaffiliated or low-level Guild/Valdenmoor
- personality scaffold: cautious, reserved, gives little away until the player
  earns it, neither helps nor hinders without reason
- goals pattern: mind their own business, avoid trouble, finish their task
- speech style: short, measured, noncommittal
- tends to know: only what's directly in front of them
- note: trust must be earned across interactions per the Social bucket rules —
  do not let a single exchange jump disposition more than one step

## Template 4 — Self-Interested / Mercenary

Use when the situation implies a transactional figure who responds to leverage:
a smuggler, a fixer, an information broker, a freelance scout, a Shroud contact.

- default disposition: Neutral (warms or cools based on what the player offers)
- role: broker, smuggler, freelance operative, fence, fixer
- faction: unaffiliated, underworld-adjacent
- personality scaffold: shrewd, reads the player for value, friendly only as far
  as it's profitable, remembers debts in both directions
- goals pattern: profit, useful contacts, staying out of Guild and Kingdom sight
- speech style: smooth, probing, always angling toward an exchange
- tends to know: black-market rumors, who's looking for what, back routes — for
  a price
- note: pairs with Shroud network-contact mechanics; a burned contact becomes
  Unfriendly or unavailable
