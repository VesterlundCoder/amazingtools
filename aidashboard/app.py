#!/usr/bin/env python3
"""
Adria AI Visibility Dashboard
Dynamic analysis interface for exploring AI tracking results.

Run locally:   streamlit run app.py
Deploy:        Push to GitHub → connect to Streamlit Community Cloud
"""

import io, json, os, re, time, traceback, contextlib
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from openai import OpenAI

# ── Config (reads from st.secrets for cloud, env var for local) ─────────────
def get_openai_key() -> str:
    try:
        return st.secrets["OPENAI_API_KEY"]
    except Exception:
        return os.environ.get("OPENAI_API_KEY", "")

DATA_DIR    = Path(os.environ.get("DATA_DIR", "data/adria_runs"))
CLIENT_NAME = "Adria"
COMPETITORS = ["Kabe", "Buerstner", "Dethleffs"]
ALL_BRANDS  = [CLIENT_NAME] + COMPETITORS

st.set_page_config(
    page_title="Adria – AI Visibility Dashboard",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ═══════════════════════════════════════════════════════════════════════════════
# Data helpers
# ═══════════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=30)
def load_run_data(run_dir_str: str) -> tuple:
    run_dir = Path(run_dir_str)

    def read_source(rdir, key):
        csvs   = sorted(rdir.glob(f"adria_{key}_*.csv"))
        jsonls = sorted(rdir.glob(f"{key}_progress.jsonl"))
        if csvs:
            return pd.read_csv(csvs[-1])
        elif jsonls:
            rows = []
            with open(jsonls[-1], encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except Exception:
                            pass
            return pd.DataFrame(rows) if rows else pd.DataFrame()
        return pd.DataFrame()

    return read_source(run_dir, "google_ai_mode"), read_source(run_dir, "chatgpt")


def get_available_runs() -> list:
    if not DATA_DIR.exists():
        return []
    return [str(r) for r in sorted(DATA_DIR.glob("run_*"), reverse=True)]


def enrich_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if df.empty:
        for brand in ALL_BRANDS:
            df[f"mentions_{brand.lower()}"] = pd.Series(dtype=bool)
        df["has_response"] = pd.Series(dtype=bool)
        return df
    response_col = df.get("response", pd.Series(dtype=str)).fillna("").str.lower()
    for brand in ALL_BRANDS:
        df[f"mentions_{brand.lower()}"] = response_col.str.contains(brand.lower(), na=False)
    df["has_response"] = df["response"].fillna("").str.len() > 20
    return df


def build_summary(df_g: pd.DataFrame, df_c: pd.DataFrame) -> str:
    parts = []
    for label, df in [("Google AI Mode", df_g), ("ChatGPT", df_c)]:
        if df.empty:
            parts.append(f"{label}: no data yet")
            continue
        df_e   = enrich_df(df)
        total  = len(df_e)
        rates  = {b: round(df_e[f"mentions_{b.lower()}"].mean() * 100, 1)
                  for b in ALL_BRANDS if f"mentions_{b.lower()}" in df_e.columns}
        parts.append(f"{label}: {total} rows | mention rates: {rates}")
    return "\n\n".join(parts)


def run_analysis(question: str, df_g: pd.DataFrame, df_c: pd.DataFrame) -> dict:
    oai = OpenAI(api_key=get_openai_key())
    cols = ("prompt_id, original_query, prompt_type, prompt_text, response, "
            "success, latency_ms, cosine_score, timestamp, "
            "mentions_adria, mentions_kabe, mentions_buerstner, mentions_dethleffs, has_response")

    system = (
        "You are a data analyst. The user asks questions about two pandas DataFrames:\n"
        "`df_google` (Google AI Mode results) and `df_chatgpt` (ChatGPT results).\n"
        f"Columns (when non-empty): {cols}\n"
        "Boolean columns (mentions_*, has_response) are pre-computed.\n"
        "IMPORTANT: Either DataFrame may be empty — always guard with `if not df.empty`.\n\n"
        "RESPOND WITH TWO SECTIONS SEPARATED BY ---EXPLANATION---:\n"
        "SECTION 1: Only valid Python code (no markdown fences, no prose).\n"
        "  - Use print() for all numeric/text answers.\n"
        "  - Optionally assign a plotly figure to `fig` (do NOT call fig.show()).\n"
        "  - Available names: df_google, df_chatgpt, pd, px, go, np\n"
        "SECTION 2 (after ---EXPLANATION---): 1-3 sentence Swedish summary shown above output."
    )

    resp = oai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system},
                  {"role": "user",   "content": question}],
        temperature=0.1,
        max_tokens=1500
    )
    raw = resp.choices[0].message.content

    if "---EXPLANATION---" in raw:
        code_part, explanation = raw.split("---EXPLANATION---", 1)
    else:
        code_part, explanation = raw, ""

    code        = re.sub(r"```python|```", "", code_part).strip()
    explanation = explanation.strip()

    buf      = io.StringIO()
    local_ns = {"df_google": df_g, "df_chatgpt": df_c,
                 "pd": pd, "px": px, "go": go, "np": np}
    error    = None
    with contextlib.redirect_stdout(buf):
        try:
            exec(code, local_ns)
        except Exception as e:
            error = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"

    fig = local_ns.get("fig")
    if fig is not None:
        fig.update_layout(plot_bgcolor="#0E1117", paper_bgcolor="#0E1117",
                          font_color="white", legend_bgcolor="#0E1117")

    return {"code": code, "text_output": buf.getvalue().strip(),
            "fig": fig, "explanation": explanation, "error": error}


# ═══════════════════════════════════════════════════════════════════════════════
# Sidebar
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.title("📡 Adria AIV Dashboard")
    st.caption("AI Visibility Tracker — Live Analysis")

    runs = get_available_runs()
    if runs:
        selected_run = st.selectbox("Select run", runs,
                                    format_func=lambda p: Path(p).name)
    else:
        selected_run = None
        st.warning("No tracking runs found yet.\nStart `client_adria.py` to begin.")

    auto_refresh = st.toggle("Auto-refresh (30s)", value=False)
    if st.button("🔄 Refresh data now"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.markdown("**Client:** Adria")
    st.markdown("**Competitors:** Kabe · Buerstner · Dethleffs")
    st.markdown("**Platforms:** Google AI Mode · ChatGPT")

    log_path = Path("adria_tracker.log")
    if log_path.exists():
        st.divider()
        st.caption("Tracker log (last 20 lines)")
        with open(log_path, encoding="utf-8") as f:
            lines = f.readlines()
        st.code("".join(lines[-20:]), language=None)

if auto_refresh:
    time.sleep(30)
    st.cache_data.clear()
    st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# Load & enrich data
# ═══════════════════════════════════════════════════════════════════════════════

if selected_run:
    df_google, df_chatgpt = load_run_data(selected_run)
    df_google  = enrich_df(df_google)
    df_chatgpt = enrich_df(df_chatgpt)
else:
    df_google = df_chatgpt = pd.DataFrame()

g_count = len(df_google)
c_count = len(df_chatgpt)

# ── Top metrics ──────────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
col1.metric("Google AI Mode results", g_count)
col2.metric("ChatGPT results", c_count)
if not df_google.empty and "mentions_adria" in df_google.columns:
    col3.metric("Adria rate (Google)", f"{round(df_google['mentions_adria'].mean()*100,1)}%")
if not df_chatgpt.empty and "mentions_adria" in df_chatgpt.columns:
    col4.metric("Adria rate (ChatGPT)", f"{round(df_chatgpt['mentions_adria'].mean()*100,1)}%")

st.divider()

tab_charts, tab_data, tab_ask = st.tabs(["📊 Overview", "📋 Raw Data", "💬 Ask the Data"])

# ─── Overview ────────────────────────────────────────────────────────────────
with tab_charts:
    if df_google.empty and df_chatgpt.empty:
        st.info("No data yet. Start the tracker and return here.")
    else:
        dark = dict(plot_bgcolor="#0E1117", paper_bgcolor="#0E1117",
                    font_color="white", legend_bgcolor="#0E1117")
        colors = ["#4A90D9", "#E8755A"]

        brand_rows = []
        for brand in ALL_BRANDS:
            col = f"mentions_{brand.lower()}"
            for lbl, df in [("Google AI Mode", df_google), ("ChatGPT", df_chatgpt)]:
                if not df.empty and col in df.columns:
                    brand_rows.append({"Brand": brand, "Platform": lbl,
                                       "Mention Rate (%)": round(df[col].mean()*100, 1)})
        if brand_rows:
            fig = px.bar(pd.DataFrame(brand_rows), x="Brand", y="Mention Rate (%)",
                         color="Platform", barmode="group",
                         title="Brand Mention Rates by Platform",
                         color_discrete_sequence=colors, height=380)
            fig.update_layout(**dark)
            st.plotly_chart(fig, use_container_width=True)

        type_rows = []
        for lbl, df in [("Google AI Mode", df_google), ("ChatGPT", df_chatgpt)]:
            if not df.empty and "prompt_type" in df.columns and "mentions_adria" in df.columns:
                for ptype, grp in df.groupby("prompt_type"):
                    type_rows.append({"Prompt Type": ptype, "Platform": lbl,
                                      "Adria Rate (%)": round(grp["mentions_adria"].mean()*100, 1)})
        if type_rows:
            fig2 = px.bar(pd.DataFrame(type_rows), x="Prompt Type", y="Adria Rate (%)",
                          color="Platform", barmode="group",
                          title="Adria Mention Rate by Prompt Type",
                          color_discrete_sequence=colors, height=360)
            fig2.update_layout(**dark)
            st.plotly_chart(fig2, use_container_width=True)

        len_rows = []
        for lbl, df in [("Google AI Mode", df_google), ("ChatGPT", df_chatgpt)]:
            if not df.empty and "response" in df.columns:
                tmp = df[df["response"].fillna("").str.len() > 0].copy()
                tmp["resp_len"] = tmp["response"].str.len()
                tmp["Platform"] = lbl
                len_rows.append(tmp[["Platform", "resp_len"]])
        if len_rows:
            fig3 = px.histogram(pd.concat(len_rows), x="resp_len", color="Platform",
                                nbins=40, barmode="overlay",
                                title="Response Length Distribution",
                                labels={"resp_len": "Characters"},
                                color_discrete_sequence=colors, height=320, opacity=0.7)
            fig3.update_layout(**dark)
            st.plotly_chart(fig3, use_container_width=True)

        if not df_google.empty and "mentions_adria" in df_google.columns and "original_query" in df_google.columns:
            st.subheader("Queries where Adria appears — Google AI Mode (top 20)")
            top_q = (df_google[df_google["mentions_adria"]]
                     .groupby("original_query")
                     .agg(count=("mentions_adria", "sum"))
                     .sort_values("count", ascending=False)
                     .head(20).reset_index())
            if not top_q.empty:
                fig4 = px.bar(top_q, x="count", y="original_query", orientation="h",
                              height=500, color_discrete_sequence=["#4A90D9"])
                fig4.update_layout(yaxis={"categoryorder": "total ascending"}, **dark)
                st.plotly_chart(fig4, use_container_width=True)

# ─── Raw Data ────────────────────────────────────────────────────────────────
with tab_data:
    cg, cc = st.columns(2)
    display_cols = ["original_query", "prompt_type", "response",
                    "mentions_adria", "success", "latency_ms"]
    with cg:
        st.subheader(f"Google AI Mode ({g_count} rows)")
        if not df_google.empty:
            st.dataframe(df_google[[c for c in display_cols if c in df_google.columns]],
                         use_container_width=True, height=500)
        else:
            st.info("No data yet")
    with cc:
        st.subheader(f"ChatGPT ({c_count} rows)")
        if not df_chatgpt.empty:
            st.dataframe(df_chatgpt[[c for c in display_cols if c in df_chatgpt.columns]],
                         use_container_width=True, height=500)
        else:
            st.info("No data yet")

# ─── Ask the Data ────────────────────────────────────────────────────────────
with tab_ask:
    st.subheader("💬 Ask the Data")
    st.caption("Ställ valfri fråga — omnämnandegrad, plattformsjämförelser, specifika varumärken, "
               "eller 'visa ett diagram över…'. Svaren beräknas direkt på rådatan.")

    if "current_answer"  not in st.session_state: st.session_state.current_answer  = None
    if "saved_answers"   not in st.session_state: st.session_state.saved_answers   = []
    if "pending_question" not in st.session_state: st.session_state.pending_question = ""

    quick_questions = [
        "Hur många gånger rekommenderas Kabe, Buerstner eller Dethleffs men INTE Adria? Visa per plattform.",
        "Hur hög är Adrias omnämnandegrad på Google AI Mode vs ChatGPT? Visa som stapeldiagram.",
        "Vilka prompt-typer (how_to, recommendation etc.) ger bäst synlighet för Adria?",
        "Visa top 15 frågor där Adria INTE nämns men konkurrenter gör det — möjligheter.",
    ]
    qq_cols = st.columns(4)
    for i, (col, q) in enumerate(zip(qq_cols, quick_questions)):
        if col.button(q[:42] + "…", key=f"qq_{i}", use_container_width=True):
            st.session_state.pending_question = q
            st.session_state.current_answer   = None
            st.rerun()

    st.divider()

    with st.form(key="analysis_form", clear_on_submit=True):
        user_q = st.text_area("Din fråga:", value=st.session_state.pending_question,
                              height=80,
                              placeholder="T.ex. Hur många gånger nämns Adria utan konkurrenter på Google?")
        submitted = st.form_submit_button("🔍 Analysera", use_container_width=True)

    if submitted and user_q.strip():
        st.session_state.pending_question = ""
        st.session_state.current_answer   = None
        with st.spinner("Analyserar datan — genererar och kör kod..."):
            try:
                result = run_analysis(user_q.strip(), df_google, df_chatgpt)
                result["question"]  = user_q.strip()
                result["timestamp"] = datetime.now().strftime("%H:%M:%S")
                st.session_state.current_answer = result
            except Exception:
                st.session_state.current_answer = {
                    "question": user_q.strip(), "explanation": "",
                    "text_output": "", "fig": None, "code": "",
                    "error": traceback.format_exc(),
                    "timestamp": datetime.now().strftime("%H:%M:%S")
                }
        st.rerun()

    ca = st.session_state.current_answer
    if ca:
        st.markdown(f"### ❓ {ca['question']}")
        st.caption(f"Beräknat {ca['timestamp']}")

        if ca.get("explanation"):
            st.info(ca["explanation"])

        if ca.get("error"):
            st.error(f"Kodfel:\n```\n{ca['error']}\n```")
        else:
            if ca.get("text_output"):
                st.code(ca["text_output"], language=None)
            if ca.get("fig") is not None:
                st.plotly_chart(ca["fig"], use_container_width=True)
            if not ca.get("text_output") and ca.get("fig") is None:
                st.warning("Koden kördes men producerade ingen synlig output. Prova att omformulera.")

        b1, b2, _ = st.columns([2, 2, 8])
        if b1.button("💾 Spara svar", key="save_btn", use_container_width=True):
            st.session_state.saved_answers.append(dict(ca))
            st.session_state.current_answer = None
            st.rerun()
        if b2.button("🗑️ Rensa", key="clear_btn", use_container_width=True):
            st.session_state.current_answer = None
            st.rerun()

        with st.expander("Visa genererad kod", expanded=False):
            st.code(ca.get("code", ""), language="python")

    if st.session_state.saved_answers:
        st.divider()
        st.markdown("### 📌 Sparade svar")
        for idx, saved in enumerate(reversed(st.session_state.saved_answers)):
            real_idx = len(st.session_state.saved_answers) - 1 - idx
            with st.expander(f"**{saved['question'][:80]}** — {saved.get('timestamp','')}",
                             expanded=(idx == 0)):
                if saved.get("explanation"): st.info(saved["explanation"])
                if saved.get("text_output"): st.code(saved["text_output"], language=None)
                if saved.get("fig") is not None:
                    st.plotly_chart(saved["fig"], use_container_width=True)
                dc, _ = st.columns([2, 10])
                if dc.button("🗑️ Ta bort", key=f"del_{real_idx}"):
                    st.session_state.saved_answers.pop(real_idx)
                    st.rerun()
