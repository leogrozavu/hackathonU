# FC Universitatea Cluj — Smart Match Insights

Self-analysis dashboard for FC U Cluj built around four questions the staff actually asks: who played well, where do we lose the ball, who breaks lines, and how do we attack. Wyscout match data + Catapult GPS training files in, grounded answers out.

---

## Prerequisites

- Python 3.10+
- A modern web browser

---

## Setup & Run

### 1. Backend

```bash
cd backend

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install django django-cors-headers google-genai openpyxl

# Run the server
python manage.py runserver
```

The API is available at `http://127.0.0.1:8000`.

### 2. Frontend

Serve the static frontend from any HTTP server:

```bash
cd frontend
python -m http.server 5500
```

Then open `http://127.0.0.1:5500/`. The page calls the backend at `http://127.0.0.1:8000/api/` and falls back to embedded demo data if the API is unreachable.

---

## Environment Variables (Optional)

AI features (match reports, coach brief, cross-insight detector, EXPLICĂ-MI buttons, chat with tools, player summaries) use Google Gemini:

```bash
# macOS / Linux
export GEMINI_API_KEY=your_key_here

# Windows CMD
set GEMINI_API_KEY=your_key_here

# Windows PowerShell
$env:GEMINI_API_KEY="your_key_here"
```

Without a key the AI endpoints return 503 with a clear message — all deterministic analytics still work.

---

## Loading Data

A populated `backend/db.sqlite3` is included. To rebuild from source:

```bash
cd backend
source .venv/bin/activate

# 1. Match stats — 35 Universitatea Cluj fixtures
python manage.py ingest_cluj ../sample_data/all_matches/ --reset

# 2. Real player names from squad roster
python manage.py load_player_names

# 3. GPS / training load — 773 sessions across November + December
python manage.py ingest_training ../players_device_info/
```

---

## What's Inside

| Tab | What it shows |
|-----|--------------|
| **Sezon** | W-D-L, xG for/against, per-match form trend, Top 10 squad scoreboard, ball-loss leaderboard, attacking-mix radar, AI Coach Brief, AI Pattern Detector, EXPLICĂ-MI on every chart |
| **Meci** | Match selector, player scores with 5-component breakdown, ball-loss top, line-breaking runs, attack mix, AI Match Report, **interactive 3D pitch** with player photos and data-driven heat zones (FORM / RISK / xG modes) |
| **Jucători** | Per-player season profile, score evolution, ball-loss donut, attack radar vs squad average, **GPS training section** (calendar, athletic-type classification, distance / HSR / sprint timeline), AI player narrative |
| **AI Chat** | Conversational assistant in Romanian with tool calling — can fetch player details, match details, ball losses, line-breaks, attacking patterns and players-by-role on demand, with an audit accordion showing which tools were called |

---

## Data Scope

- **35 matches** from FC U Cluj's 2024/25 Liga 1 season (aggregated Wyscout player stats per match)
- **29 squad players** with real names, positions, and full season metrics
- **773 GPS sessions** from Catapult devices (November + December 2025) covering 22 players
- **6 backend models**: `Match`, `Player`, `PlayerMatchStats`, `TrainingSession` plus internal Django tables

Everything is scoped strictly to FC U Cluj — opponents only appear as match context, never in the analytics.

---

## Why It Matters

Wyscout gives you the raw data. This tool turns it into the brief a coach actually wants on a Monday morning: who's in form, who's overloaded, what worked in the last win, who to start on Saturday — all with the underlying numbers one click away.
