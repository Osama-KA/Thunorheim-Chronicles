"""Thunorheim — Streamlit front end.

A wide landscape view: the generated world image as a full-page backdrop, dark
frosted-glass panels, medieval typography, a chat-style narration log on the left,
and a live world-state + agent-trace sidebar on the right.

Run locally:  .venv/Scripts/streamlit run app.py
Requires a valid `az login` (same Foundry auth the engine uses).
"""

from __future__ import annotations

import base64
import copy
import html
import json
import os
import re

import streamlit as st

from thunorheim.dm_agent import DMAgent
from thunorheim.world_state import _DEFAULT_STATE, ROLES, WorldState

ROOT = os.path.dirname(os.path.abspath(__file__))
SAVE_PATH = WorldState().path  # default state/session_state.json

ROLE_DESC = {
    "Warden": "frontier hunter — blade, tracking, survival in the Greymark",
    "Runescribe": "arcane scholar — inscribed runes, Blight analysis, old lore",
    "Shroud": "operative — infiltration, information, leverage and deception",
    "Thornwarden": "Blight-healer — Thorncraft, resistance, field surgery",
}

OPENING_NARRATION = (
    "The Ashen Flagon is loud and warm, and the door bangs shut on the cold behind you. "
    "Greyhold — the last Guild town before the Greymark — smells of cookfire smoke and "
    "tallow and the faint mineral tang the locals call greydust. Across the room a story "
    "is being told in low voices about Ashwatch Post going silent. Wardens drink before "
    "they head east, and harder when they come back. You have just arrived, and the night "
    "is yours to spend. What do you do?"
)

st.set_page_config(page_title="Thunorheim", layout="wide", initial_sidebar_state="collapsed")


# --------------------------------------------------------------------------- styling
@st.cache_data
def _bg_b64() -> str:
    with open(os.path.join(ROOT, "background.png"), "rb") as fh:
        return base64.b64encode(fh.read()).decode()


def inject_css() -> None:
    bg = _bg_b64()
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@500;700&family=IM+Fell+English&family=MedievalSharp&display=swap');

        html, body {{ height: 100vh; margin: 0; background: #0a0806; overflow: hidden; overscroll-behavior: none; }}
        [data-testid="stApp"], [data-testid="stAppViewContainer"] {{ height: 100vh; overflow: hidden; }}
        [data-testid="stApp"] {{
            background:
                linear-gradient(rgba(10,8,6,0.40), rgba(8,6,4,0.66)),
                url("data:image/png;base64,{bg}");
            background-size: cover; background-position: center; background-attachment: fixed;
        }}
        [data-testid="stHeader"] {{ background: transparent; height: 0; }}
        [data-testid="stToolbar"] {{ display: none; }}
        [data-testid="stAppViewContainer"], [data-testid="stMain"] {{ background: transparent; }}
        [data-testid="stMain"] {{ height: 100vh; overflow: hidden; }}
        .block-container {{ padding-top: 1.3rem; padding-bottom: 0.5rem; max-width: 1500px; }}
        /* bottom chat bar — remove the default white, let the backdrop show */
        [data-testid="stBottom"], [data-testid="stBottom"] > div,
        [data-testid="stBottomBlockContainer"] {{ background: transparent !important; }}
        [data-testid="stBottomBlockContainer"] {{ padding-top: 4px; padding-bottom: 14px; max-width: 1500px; }}

        html, body, [data-testid="stAppViewContainer"], p, span, div, label, input, textarea {{
            font-family: 'IM Fell English', Georgia, serif; color: #e9dcc1;
        }}
        h1, h2, h3, .title, .frost h3 {{
            font-family: 'Cinzel', 'MedievalSharp', serif; color: #e0a94a;
            letter-spacing: 1px; text-shadow: 0 2px 6px rgba(0,0,0,0.6);
        }}
        .title-xl {{ font-family: 'MedievalSharp','Cinzel',serif; font-size: 4.2rem; color: #e6b24e;
            text-align:center; letter-spacing: 6px; text-shadow: 0 3px 14px rgba(0,0,0,0.8); margin: 0; }}
        .subtitle {{ text-align:center; color:#c9b48f; font-size:1.1rem; margin-top:-6px; }}

        .frost {{ background: rgba(25,18,12,0.72); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
            border: 1px solid rgba(200,150,80,0.35); border-radius: 10px; padding: 14px 18px; margin-bottom: 14px;
            box-shadow: 0 4px 18px rgba(0,0,0,0.55); }}
        .frost h3 {{ margin: 0 0 8px 0; font-size: 1.05rem; border-bottom: 1px solid rgba(200,150,80,0.25);
            padding-bottom: 6px; }}

        /* the only two scroll regions on the page; nothing else scrolls */
        .chatlog {{ height: calc(100vh - 195px); overflow-y: auto; overscroll-behavior: contain; padding-right: 10px; }}
        .side-scroll {{ height: calc(100vh - 120px); overflow-y: auto; overscroll-behavior: contain; padding-right: 6px; }}
        .chatlog::-webkit-scrollbar, .side-scroll::-webkit-scrollbar {{ width: 8px; }}
        .chatlog::-webkit-scrollbar-thumb, .side-scroll::-webkit-scrollbar-thumb {{
            background: rgba(200,150,80,0.35); border-radius: 4px; }}
        .dm-msg {{ background: rgba(28,21,14,0.66); border-left: 3px solid #d9a441; border-radius: 6px;
            padding: 12px 16px; margin: 10px 0; line-height: 1.6; }}
        .player-msg {{ background: rgba(18,26,32,0.6); border-right: 3px solid #6fa8c7; border-radius: 6px;
            padding: 10px 16px; margin: 10px 0 10px 18%; color: #cfe3ee; font-style: italic; text-align: right; }}
        .overreach-msg {{ background: rgba(70,20,15,0.72); border: 1px solid #c0392b; border-radius: 6px;
            padding: 12px 16px; margin: 10px 0; color: #f0c8bc; }}
        .overreach-msg b {{ color: #e8a08c; letter-spacing: 1px; }}
        .system-msg {{ text-align:center; color:#caa85f; font-style:italic; margin: 14px 0; }}

        .bar {{ height: 15px; background: rgba(0,0,0,0.5); border-radius: 8px; overflow: hidden;
            border: 1px solid rgba(0,0,0,0.5); margin: 3px 0; }}
        .bar-fill {{ height: 100%; border-radius: 8px 0 0 8px; }}
        .muted {{ color: #b9a888; font-size: 0.86rem; }}
        .chip {{ display:inline-block; background: rgba(200,150,80,0.16); border:1px solid rgba(200,150,80,0.4);
            border-radius: 12px; padding: 2px 10px; margin: 2px 3px; font-size: 0.82rem; }}
        .npc-row {{ display:flex; justify-content:space-between; padding: 2px 0; }}

        .stButton > button {{ background: rgba(25,18,12,0.8); color: #e0a94a; border: 1px solid rgba(200,150,80,0.5);
            border-radius: 8px; font-family: 'Cinzel', serif; letter-spacing: 1px; padding: 0.5rem 1.4rem; }}
        .stButton > button:hover {{ border-color: #e0a94a; color: #f1c873; background: rgba(40,28,18,0.85); }}
        [data-testid="stChatInput"] {{ background: rgba(18,13,9,0.88); border: 1px solid rgba(200,150,80,0.45);
            border-radius: 10px; backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px); }}
        [data-testid="stChatInput"] textarea {{ background: transparent; color: #e9dcc1; }}
        .stTextInput input {{ background: rgba(18,13,9,0.85); color: #e9dcc1; border: 1px solid rgba(200,150,80,0.4); }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- helpers
_QUOTE_OPEN = re.compile(r'(^|[\s([{<—-])"')


def smart_quotes(text: str) -> str:
    """Convert straight double quotes to typographic open/close quotes, so the
    old-style body font shows a distinct opening and closing quote on dialogue."""
    text = text.replace("“", '"').replace("”", '"')  # normalize first
    text = _QUOTE_OPEN.sub(lambda m: m.group(1) + "“", text)  # opener after start/space/bracket/dash
    return text.replace('"', "”")  # everything else closes


def esc(text: str) -> str:
    return html.escape(smart_quotes(text or "")).replace("\n", "<br>")


def bar(label: str, value: int, color: str, sublabel: str) -> str:
    pct = max(0, min(100, value))
    return (
        f"<div style='display:flex;justify-content:space-between;'>"
        f"<span class='muted'>{label}</span><span class='muted'>{value}/100</span></div>"
        f"<div class='bar'><div class='bar-fill' style='width:{pct}%;background:{color};'></div></div>"
        f"<div class='muted' style='margin-bottom:8px;'>{sublabel}</div>"
    )


def disp_color(points: int) -> str:
    if points >= 21:
        return "#7fc97f"
    if points >= 1:
        return "#b5d6a0"
    if points == 0:
        return "#cbb890"
    if points >= -20:
        return "#d8b06a"
    if points >= -60:
        return "#d98b5a"
    return "#c0563f"


def has_save() -> bool:
    try:
        return bool(WorldState().get_field("player.name"))
    except Exception:
        return False


def new_world() -> WorldState:
    with open(SAVE_PATH, "w", encoding="utf-8") as fh:
        json.dump(copy.deepcopy(_DEFAULT_STATE), fh, indent=2, ensure_ascii=False)
    return WorldState()


# --------------------------------------------------------------------------- sidebar
def render_sidebar(ws: WorldState, dm: DMAgent) -> None:
    """Render the whole world-state sidebar as ONE bounded scroll block, so it
    scrolls on its own without growing the page."""
    s = ws.get_state()
    p, prog = s["player"], s["progression"]
    blocks: list[str] = []

    # identity + progression
    pending = prog.get("pending_tier")
    xp_line = (
        "<span style='color:#e6b24e;'>⚜ Ready for advancement — seek a Guild mentor</span>"
        if pending else
        (f"{prog['xp_to_next']} XP to next rank" if prog.get("xp_to_next") is not None else "Legendary — max rank")
    )
    blocks.append(
        f"<div class='frost'><h3>{esc(p['name'] or 'Nameless')}</h3>"
        f"<div style='color:#e0a94a;font-family:Cinzel,serif;'>{esc(prog['title'])} "
        f"<span class='muted'>· {esc(p['role'])} · Tier {prog['tier']}</span></div>"
        f"<div class='muted'>XP {prog['xp']} — {xp_line}</div></div>"
    )

    # condition
    blocks.append(
        f"<div class='frost'><h3>Condition</h3>"
        f"{bar('Health', p['hp'], '#a83232', p['health'])}"
        f"{bar('Energy', p['energy_points'], '#d9a441', p['energy'])}"
        f"<div class='muted'>\U0001f4cd {esc(p['location'])}</div>"
        + (f"<div class='muted'>Effects: {esc(', '.join(p['active_effects']))}</div>" if p['active_effects'] else "")
        + "</div>"
    )

    # inventory
    inv = s["inventory"]
    inv_html = ("".join(f"<div class='muted' style='padding:1px 0;'>• {esc(i)}</div>" for i in inv)
                if inv else "<div class='muted'>(empty)</div>")
    blocks.append(f"<div class='frost'><h3>Inventory</h3>{inv_html}</div>")

    # quests
    if s["quests"]["active"]:
        rows = ""
        for q in s["quests"]["active"]:
            clues = "".join(f"<li class='muted'>{esc(c)}</li>" for c in q.get("known_clues", []))
            rows += (f"<div style='margin-bottom:6px;'><b style='color:#e0a94a;'>{esc(q['title'])}</b>"
                     f"<div class='muted'>{esc(q.get('current_objective',''))}</div>"
                     + (f"<ul style='margin:4px 0 0 16px;'>{clues}</ul>" if clues else "") + "</div>")
        blocks.append(f"<div class='frost'><h3>Active Quests</h3>{rows}</div>")

    # reputation
    blocks.append(
        f"<div class='frost'><h3>Standing</h3>"
        f"<div class='npc-row'><span>Warden's Guild</span><span style='color:#e0a94a;'>{esc(s['reputation']['wardens_guild'])}</span></div>"
        + "".join(
            f"<div class='npc-row'><span>{esc(k.title())}</span><span class='muted'>{esc(v)}</span></div>"
            for k, v in s["reputation"]["factions"].items()
        )
        + "</div>"
    )

    # npcs met
    if s["npcs_met"]:
        rows = ""
        for name, npc in s["npcs_met"].items():
            stt = npc["state"]
            pts = stt.get("disposition_points", 0)
            sign = f"+{pts}" if pts > 0 else str(pts)
            rows += (f"<div class='npc-row'><span>{esc(name)}</span>"
                     f"<span style='color:{disp_color(pts)};'>{esc(stt['disposition_toward_player'])} {sign}</span></div>")
        blocks.append(f"<div class='frost'><h3>People Met</h3>{rows}</div>")

    # world flags
    flags = [k.replace("_", " ").title() for k, v in s["world_flags"].items() if v]
    if flags:
        blocks.append("<div class='frost'><h3>The World Turns</h3>"
                      + "".join(f"<span class='chip'>{esc(f)}</span>" for f in flags) + "</div>")

    # agent trace
    tr = dm.last_trace
    if tr:
        chips = "".join(f"<span class='chip'>{esc(a)}</span>" for a in tr.get("agents", []))
        ij = tr.get("interjection") or {}
        if not tr.get("overreach"):
            peek = (
                f"<div class='muted' style='margin-top:8px;'>Verdict: "
                f"<b style='color:#e0a94a;'>{esc(str(tr.get('tier')))}</b> · momentum {esc(str(tr.get('momentum')))}</div>"
                f"<div class='muted'>Buckets: {esc(', '.join(tr.get('buckets', [])) or '—')}</div>"
                f"<div class='muted'>Interjection: score {ij.get('score')} · "
                f"{'FIRED' if ij.get('fired') else 'quiet'}</div>"
                + (f"<div class='muted'>Events: {esc(', '.join(tr.get('events', [])))}</div>" if tr.get("events") else "")
            )
        else:
            peek = "<div class='muted' style='margin-top:8px;color:#d98b5a;'>Overreach — turn rejected, no state change</div>"
        blocks.append(f"<div class='frost'><h3>Agents (last turn)</h3>{chips}{peek}</div>")

    st.markdown("<div class='side-scroll'>" + "".join(blocks) + "</div>", unsafe_allow_html=True)


# --------------------------------------------------------------------------- screens
def screen_launch() -> None:
    st.markdown("<div style='height:8vh;'></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='frost' style='max-width:720px;margin:0 auto;text-align:center;padding:34px;'>"
        "<div class='title-xl'>THUNORHEIM</div>"
        "<div class='subtitle'>A frontier holds the line against the Blight.</div></div>",
        unsafe_allow_html=True,
    )
    _, c, _ = st.columns([1, 1, 1])
    with c:
        if st.button("⚔  New Game", use_container_width=True):
            st.session_state.screen = "create"
            st.rerun()
        if st.button("📖  Continue", use_container_width=True, disabled=not has_save()):
            ws = WorldState()
            dm = DMAgent(ws)
            with st.spinner("Recalling the tale so far…"):
                recap = dm.recap()
            st.session_state.ws = ws
            st.session_state.dm = dm
            st.session_state.messages = [{"who": "dm", "text": recap}]
            st.session_state.game_over = ws.get_field("player.health") == "Dead"
            st.session_state.screen = "play"
            st.rerun()


def screen_create() -> None:
    st.markdown("<div style='height:5vh;'></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        st.markdown("<div class='frost'><h3>The Warden's Guild logs every new operative.</h3></div>",
                    unsafe_allow_html=True)
        name = st.text_input("Your name", value="", placeholder="Edwyn Carr")
        role = st.radio("Your calling", ROLES, format_func=lambda r: f"{r} — {ROLE_DESC[r]}")
        cols = st.columns(2)
        if cols[0].button("⚔  Begin", use_container_width=True):
            ws = new_world()
            ws.update_player(name=name.strip() or "Edwyn Carr", role=role)
            ws.grant_starting_loadout(role)
            ws.update_session(current_scene=f"{name.strip() or 'Edwyn Carr'} the {role} has just arrived "
                              "in Greyhold, stepping into the Ashen Flagon.")
            ws.save_state()
            st.session_state.ws = ws
            st.session_state.dm = DMAgent(ws)
            st.session_state.messages = [{"who": "dm", "text": OPENING_NARRATION}]
            st.session_state.game_over = False
            st.session_state.screen = "play"
            st.rerun()
        if cols[1].button("← Back", use_container_width=True):
            st.session_state.screen = "launch"
            st.rerun()


def screen_play() -> None:
    ws: WorldState = st.session_state.ws
    dm: DMAgent = st.session_state.dm
    left, right = st.columns([2, 1], gap="large")

    with right:
        render_sidebar(ws, dm)

    with left:
        log = "<div class='chatlog'>"
        for m in st.session_state.messages:
            who = m["who"]
            if who == "player":
                log += f"<div class='player-msg'>{esc(m['text'])}</div>"
            elif who == "overreach":
                body = esc(m["text"]).replace("!!! PLAYER OVERREACH DETECTED",
                                              "<b>⚠ PLAYER OVERREACH DETECTED</b>")
                log += f"<div class='overreach-msg'>{body}</div>"
            elif who == "system":
                log += f"<div class='system-msg'>{esc(m['text'])}</div>"
            else:
                log += f"<div class='dm-msg'>{esc(m['text'])}</div>"
        log += "</div>"
        st.markdown(log, unsafe_allow_html=True)
        if st.session_state.game_over:
            st.markdown("<div class='system-msg'>Your saga ends here. The Greymark keeps what it takes.</div>",
                        unsafe_allow_html=True)

    prompt = st.chat_input("What do you do?", disabled=st.session_state.game_over)
    if prompt:
        st.session_state.messages.append({"who": "player", "text": prompt})
        try:
            with st.spinner("The world responds…"):
                prose = dm.run_turn(prompt)
            kind = "overreach" if dm.last_trace.get("overreach") else "dm"
            st.session_state.messages.append({"who": kind, "text": prose})
            if dm.game_over:
                st.session_state.game_over = True
        except Exception as exc:
            st.session_state.messages.append(
                {"who": "system", "text": f"[The turn faltered and was rolled back — state unchanged.] {exc}"}
            )
        st.rerun()


# --------------------------------------------------------------------------- main
inject_css()
ss = st.session_state
ss.setdefault("screen", "launch")
ss.setdefault("messages", [])
ss.setdefault("ws", None)
ss.setdefault("dm", None)
ss.setdefault("game_over", False)

if ss.screen == "launch":
    screen_launch()
elif ss.screen == "create":
    screen_create()
elif ss.screen == "play" and ss.ws is not None:
    screen_play()
else:
    ss.screen = "launch"
    screen_launch()
