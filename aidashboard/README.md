# Adria AI Visibility Dashboard

Interactive dashboard for exploring AI Visibility tracking results for Adria (husvagnar/husbilar) across Google AI Mode and ChatGPT.

---

## Files

| File | Purpose |
|------|---------|
| `app.py` | Main Streamlit dashboard application |
| `requirements.txt` | Python dependencies |
| `.env.example` | Environment variable template |

---

## Run Locally

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set your OpenAI API key
export OPENAI_API_KEY="sk-proj-..."

# 3. Point to your data folder (default: data/adria_runs)
export DATA_DIR="/Users/davidv2/Desktop/VINC/amazing-aiv/data/adria_runs"

# 4. Launch
streamlit run app.py --server.port 8502
```

---

## Deploy to Streamlit Community Cloud (free)

1. Push this folder to a GitHub repository (public or private)
2. Go to → **https://share.streamlit.io**
3. Click **"New app"** → connect your GitHub repo
4. Set **Main file path** to `app.py`
5. Under **Advanced settings → Secrets**, add:
   ```toml
   OPENAI_API_KEY = "sk-proj-...your-key..."
   ```
6. Click **Deploy** — you get a public URL like `https://your-app.streamlit.app`
7. Embed that URL in your website with an `<iframe>`:
   ```html
   <iframe
     src="https://your-app.streamlit.app?embed=true"
     width="100%"
     height="900"
     frameborder="0">
   </iframe>
   ```

---

## Data Format

The dashboard reads from run directories inside `DATA_DIR`. Each run folder contains:

- `google_ai_mode_progress.jsonl` — live results (written during tracking)
- `chatgpt_progress.jsonl` — live results (written during tracking)
- `adria_google_ai_mode_YYYYMMDD_HHMMSS.csv` — final CSV after run completes
- `adria_chatgpt_YYYYMMDD_HHMMSS.csv` — final CSV after run completes

Expected columns per row:
`prompt_id`, `original_query`, `prompt_type`, `prompt_text`, `response`,
`success`, `latency_ms`, `cosine_score`, `timestamp`

---

## Features

- **Overview tab** — Brand mention rate charts, prompt type breakdown, response length distribution
- **Raw Data tab** — Searchable/filterable DataFrames for both platforms
- **Ask the Data tab** — GPT-4o generates and executes Python code against the real data, returning actual numbers + Plotly charts
  - 💾 Save answers to a persistent "Saved Answers" section
  - 🗑️ Clear current answer when asking a new question
  - Quick-action buttons for common analyses

---

## Produced by VINC — AI Visibility Tracker
