<p align="center">
  <!-- Replace docs/logo.png with your logo file when you have one -->
  <img src="docs/logo.png" alt="ReCharge Alaska" width="140" />
</p>

<h1 align="center">ReCharge Portal</h1>
<p align="center">
  Next.js + Supabase dashboard for EVSE session data, charts, heatmaps, and XLSX export.<br/>
  Auth-gated per-site access; background jobs keep the database fresh.
</p>

<p align="center">
  <a href="https://nextjs.org/">Next.js</a> •
  <a href="https://supabase.com/">Supabase</a> •
  <a href="https://render.com/">Render</a> •
  <a href="https://www.python.org/">Python</a> •
  <a href="https://plotly.com/javascript/">Plotly</a>
</p>

---

## Overview
The ReCharge Portal is a secure, multi-tenant viewer for EV charging data. Users sign in (OTP email), are granted access to specific **sites**, then filter by UTC date range to view:
- Session table (kWh, max kW, SoC start/end)
- Energy histogram + session-start heatmap
- **Export to XLSX** based on current filters

Data is stored in Postgres (Supabase/Render), and background jobs keep it up-to-date (e.g., `get_token_uc.py`, `fetch_realtime_logs.py`, or ingest from SQLite).

## Architecture (high level)

Browser (Next.js app)  ──>  Next server routes (API)  ──>  Postgres (Supabase/Render)
                             ↑             ↑
                             │             └── Cron/Workers (Python) → insert/update sessions
                             └── Auth (email OTP)

### System Flow Explained

#### 1. Browser (Next.js app)
This is the user-facing dashboard (`app.rechargealaska.net`) where operators and partners log in.  
It runs React components client-side and also server-side rendering for faster loads.  
All user interactions—filters, charts, data exports—happen here.

#### 2. Next.js Server Routes (API)
Server routes act as a secure middle layer between the frontend and the database.  
Examples include:
- `/api/export` – generates XLSX files from filtered data
- `/api/fetch-sessions` – retrieves filtered session data
- `/api/dev-seed` – dev-only route to insert sample sessions

These routes execute on Render’s servers (not client-side) to protect keys and enforce permissions.

#### 3. Postgres (Supabase/Render)
This is the central data store containing:
- `sessions`
- `sites`
- `users`
- (and soon) `site_memberships` for per-site access control.

All charts and exports pull from here.  
When a user filters “Delta / October 2025,” the app queries Postgres for that subset.

#### 4. Auth (Email OTP)
Supabase handles passwordless login via one-time email links.  
After sign-in, the user session includes which sites they can access, restricting visible data to those permissions.

#### 5. Cron / Workers (Python)
Automated scripts like:
- `get_token_uc.py`
- `fetch_realtime_logs.py`
run as background jobs on Render’s Cron system.  
They connect to LynkWell APIs, fetch new telemetry, and insert it into Postgres, ensuring near real-time updates.

---

### Summary Table

| Component | Runs On | Purpose |
|------------|----------|----------|
| **Browser (Next.js app)** | User’s browser | Displays charts, filters, exports |
| **Next.js Server Routes (API)** | Render Web Service | Bridges frontend ↔ database |
| **Postgres (Supabase/Render)** | Cloud DB | Stores sessions, sites, users |
| **Auth (Email OTP)** | Supabase | Controls access per site |
| **Cron / Workers (Python)** | Render Cron Jobs | Keeps data synced automatically |

---

## Tech Stack
- **Frontend**: Next.js (App Router), Tailwind, Plotly
- **Auth/DB**: Supabase (Postgres + RLS) or Render Postgres
- **Exports**: Excel (xlsx) server-side
- **Jobs**: Python scripts for tokens/log ingestion (Render Cron Jobs)

---

## Getting Started (Local Dev)

### Prereqs
- Node 18+ (via nvm recommended)
- npm or pnpm
- (Optional) Python 3.10+ if running ingest/cron scripts locally

### Env Vars
Create `.env.local` in the project root: