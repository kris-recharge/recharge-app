#!/usr/bin/env python3
# Version: 3.1 — Major release (Render-ready, UI polish)
# app.py — ReCharge Alaska viewer (Streamlit, Python 3.9)
#
# Patch (2025-10-03): Fix NameError by ensuring status_df and auth_df_display are
# defined in tabs[1] and tabs[2] before being used in the export tab.
# Patch (2025-08-21): Fix TypeError ("Expected numeric dtype, got object instead")
# when computing hvb_volts. Root cause: Series dtype 'object' from string/None
# values causing .round() to reject. Solution: coerce to numeric with pandas,
# compute via numpy.divide with a boolean mask, and only round after ensuring
# float dtype. Also guards against divide-by-zero/inf and keeps Int64 (nullable).

from pathlib import Path
from typing import Dict, Optional, Tuple, List, Callable
from datetime import time as dtime

import numpy as np
import pandas as pd
import streamlit as st
from io import BytesIO

from plotly.subplots import make_subplots
import plotly.graph_objects as go

# ---- Dynamic DB engine: Render/Postgres, Supabase, or SQLite --------------
import os
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import URL
import sqlite3

# Default DB: live next to this app, under ./database/lynkwell_data.db
APP_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE_PATH = APP_DIR / "database" / "lynkwell_data.db"

def get_engine(db_path: str):
    """Return a SQLAlchemy engine, preferring the Render Postgres URL if available.
    Priority now:
      1. RENDER_DB_URL or DATABASE_URL (Render-hosted Postgres)
      2. local SQLite file at `db_path`
    Supabase is intentionally not used here anymore — we keep auth in Supabase but
    read OCPP/meters from Render.
    """
    render_db_url = os.environ.get("RENDER_DB_URL") or os.environ.get("DATABASE_URL")
    if render_db_url:
        try:
            return create_engine(render_db_url)
        except Exception as e:
            # If Render URL is set but broken, fall back to SQLite so the UI still loads
            print(f"[db] failed to connect to Render Postgres, falling back to SQLite: {e}")
    sqlite_url = URL.create("sqlite", database=str(db_path))
    return create_engine(sqlite_url)

# ---- Optional: AgGrid for true row-click selection ------------------------
try:
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode
    AGGRID_AVAILABLE = True
except Exception:
    AGGRID_AVAILABLE = False

# ---- Excel engine detection -------------------------------------------------
try:
    import xlsxwriter
    EXCEL_ENGINE = "xlsxwriter"
    __XLSXWRITER_IMPORTED = xlsxwriter  # silence pyflakes: bind the module
except Exception:
    EXCEL_ENGINE = "openpyxl"
    _XLSXWRITER_IMPORTED = None

# ---- Timezone helpers (py39 safe) ------------------------------------------
try:
    from zoneinfo import ZoneInfo
    AK = ZoneInfo("America/Anchorage")
    UTC = ZoneInfo("UTC")
except Exception:  # pragma: no cover
    import pytz
    AK = pytz.timezone("America/Anchorage")
    UTC = pytz.UTC

# ---- Friendly EVSE names ----------------------------------------------------
EVSE_NAME_MAP: Dict[str, str] = {
    "as_cnIGqQ0DoWdFCo7zSrN01": "ARG - Left",
    "as_c8rCuPHDd7sV1ynHBVBiq": "ARG - Right",
    "as_5Oo7sRlINKDmiFm8tNXFB": "Cantwell",
    "as_LYHe6mZTRKiFfziSNJFvJ": "Glennallen",
    "as_xTUHfTKoOvKSfYZhhdlhT": "Delta - Left",
    "as_oXoa7HXphUu5riXsSW253": "Delta - Right",
    "CEA": "CEA",
}

# Dynamic EVSE map from DB (station_id -> name)
ASSET_NAME_MAP: Dict[str, str] = {}

@st.cache_data(show_spinner=False)
def load_assets_map(db_file: str, _mtime: float) -> Dict[str, str]:
    if not Path(db_file).exists():
        return {}
    try:
        with sqlite3.connect(db_file) as con:
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='assets'")
            if not cur.fetchone():
                return {}
            cur.execute("SELECT asset_id, name FROM assets")
            rows = cur.fetchall()
            return {str(a): (str(n) if n is not None else str(a)) for a, n in rows}
    except Exception:
        return {}

 # Best-friendly resolver: prefer site-friendly static names, then dynamic asset names, then raw id
def friendly_evse_dynamic(sid: str) -> str:
    sid = str(sid)
    # 1) Prefer curated site-friendly names
    if sid in EVSE_NAME_MAP and EVSE_NAME_MAP[sid]:
        return EVSE_NAME_MAP[sid]
    # 2) Fall back to runtime asset names (may be hardware model labels)
    if sid in ASSET_NAME_MAP and ASSET_NAME_MAP[sid]:
        return ASSET_NAME_MAP[sid]
    # 3) Raw id
    return sid

def friendly_evse(sid: str) -> str:
    return friendly_evse_dynamic(sid)

# ---- Connector type map (by friendly site name) -----------------------------
CONNECTOR_TYPE_MAP: Dict[str, Dict[int, str]] = {
    "Delta - Left":  {1: "CHAdeMO", 2: "CCS"},
    "Delta - Right": {1: "CHAdeMO", 2: "CCS"},
    "Glennallen":    {1: "NACS",    2: "CCS"},
    "ARG - Left":    {1: "NACS",    2: "CCS"},
    "ARG - Right":   {1: "CCS",     2: "CCS"},
    "CEA":           {1: "CCS",     2: "CCS"},
}

def connector_type_for(site_name: str, connector_id: Optional[object]) -> str:
    try:
        cid = int(pd.to_numeric(connector_id, errors="coerce")) if connector_id is not None else None
    except Exception:
        cid = None
    if not site_name or cid is None:
        return ""
    site_map = CONNECTOR_TYPE_MAP.get(str(site_name), {})
    return site_map.get(cid, "")

# ---- Tritium error-code platform mapping (by friendly site name) ----------
# Used to decide which error dictionary to use when enriching status rows.
# Delta sites use RT50 codes; ARG sites use RTM codes.
PLATFORM_MAP: Dict[str, str] = {
    "Delta - Left": "RT50",
    "Delta - Right": "RT50",
    "ARG - Left": "RTM",
    "ARG - Right": "RTM",
    # Sites without Tritium (e.g., Glennallen ABB Terra184) intentionally omitted
}

# ---- Paths / default DB -----------------------------------------------------
# Make paths relative to THIS file so it works the same on Mac and on Render.
BASE = Path(__file__).resolve().parent
DEFAULT_DB = BASE / "database" / "lynkwell_data.db"
# keep logo next to the app, or adjust to BASE / "assets" / "...png"
LOGO_PATH = BASE / "ReCharge Logo_REVA.png"

# ---- DB cache-buster: use DB file mtime to invalidate caches -------------
def _db_mtime(path: str) -> float:
    try:
        return float(Path(path).stat().st_mtime)
    except Exception:
        return 0.0

# ---- Streamlit config & session keys ---------------------------------------
st.set_page_config(page_title="ReCharge Alaska — LynkWell Viewer", layout="wide")
# ---- Tab styling: rectangular buttons, bold active, even spacing -----------
st.markdown(
    """
    <style>
    /* space tabs evenly across the header row */
    .stTabs [data-baseweb="tab-list"] {
        display: flex;
        justify-content: space-between;
        gap: 12px;
    }
    /* make each tab look like a rectangular button */
    .stTabs [data-baseweb="tab"] {
        background-color: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.15);
        height: 40px;
        padding: 6px 16px;
        border-radius: 5px; /* ~1/8 of 40px */
        margin: 0;
        transition: box-shadow 120ms ease, transform 120ms ease, filter 120ms ease, background-color 120ms ease, border-color 120ms ease;
    }
    /* remove the default underline/highlight bar */
    .stTabs [data-baseweb="tab-highlight"] {
        background: transparent !important;
        height: 0px !important;
    }
    /* active tab: bolder with a subtle accent background/border (default blue) */
    .stTabs [aria-selected="true"] {
        font-weight: 700 !important;
        border-color: rgba(13,110,253,0.55) !important;
        background-color: rgba(13,110,253,0.18) !important;
    }
    /* subtle hover glow */
    .stTabs [data-baseweb="tab"]:hover {
        filter: brightness(1.06);
        box-shadow: 0 0 0 2px rgba(13,110,253,0.18) inset;
        transform: translateY(-0.5px);
    }
    /* inactive tabs: normal weight */
    .stTabs [aria-selected="false"] {
        font-weight: 400 !important;
    }

    /* ---------- Per-tab color accents ---------- */
    /* 1) Charge Sessions (red accent when active; redish hover) */
    .stTabs [data-baseweb="tab"]:nth-child(1)[aria-selected="true"] {
        border-color: rgba(220,53,69,0.55) !important;       /* bootstrap danger */
        background-color: rgba(220,53,69,0.18) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(1):hover {
        box-shadow: 0 0 0 2px rgba(220,53,69,0.22) inset;
    }

    /* 2) Status History (green accent when active; greenish hover) */
    .stTabs [data-baseweb="tab"]:nth-child(2)[aria-selected="true"] {
        border-color: rgba(25,135,84,0.55) !important;        /* bootstrap success */
        background-color: rgba(25,135,84,0.18) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(2):hover {
        box-shadow: 0 0 0 2px rgba(25,135,84,0.22) inset;
    }

    /* 4) Data Export (blue accent explicit; bluish hover) */
    .stTabs [data-baseweb="tab"]:nth-child(4)[aria-selected="true"] {
        border-color: rgba(253,126,20,0.65) !important;
        background-color: rgba(253,126,20,0.22) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(4):hover {
        box-shadow: 0 0 0 2px rgba(253,126,20,0.24) inset;
    }
    /* 5) Data Export (blue accent explicit; bluish hover) */
    .stTabs [data-baseweb="tab"]:nth-child(5)[aria-selected="true"] {
        border-color: rgba(13,110,253,0.55) !important;
        background-color: rgba(13,110,253,0.18) !important;
    }
    .stTabs [data-baseweb="tab"]:nth-child(5):hover {
        box-shadow: 0 0 0 2px rgba(13,110,253,0.22) inset;
    }
    /* ---------- Small badge for headers ---------- */
    .rca-badge {
        display: inline-block;
        margin-left: 8px;
        padding: 2px 8px;
        font-size: 11px;
        line-height: 16px;
        border-radius: 10px;
        background: rgba(255,255,255,0.08);
        border: 1px solid rgba(255,255,255,0.20);
        vertical-align: middle;
        user-select: none;
        white-space: nowrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
if "status_df_key" not in st.session_state:
    st.session_state["status_df_key"] = 0
if "meter_plot_counter" not in st.session_state:
    st.session_state["meter_plot_counter"] = 0

# ---- Sidebar (UNCHANGED) ----------------------------------------------------
with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), use_container_width=True)
    st.title("Data Source & Time Range")

    db_path = st.text_input("SQLite DB path", value=str(DEFAULT_DB))
    if os.path.exists(db_path):
        st.caption(f"✅ DB found at: {db_path}")
    else:
        st.caption(f"❌ DB NOT FOUND at: {db_path}")

    # Load names from DB assets table and build combined list for dropdown
    ASSET_NAME_MAP = load_assets_map(db_path, _db_mtime(db_path))
    ALL_NAME_MAP = {**EVSE_NAME_MAP, **ASSET_NAME_MAP}
    unique_evse_names = sorted(set(ALL_NAME_MAP.values()))

    # Multi-select EVSEs (leave empty for ALL)
    evse_picks = st.multiselect(
        "EVSE (optional, multi)",
        options=unique_evse_names,
        default=[],
        help="Pick one or more sites; leave empty for all."
    )
    # Build name→id maps (dynamic overrides static if both exist)
    NAME_TO_ID = {**{v: k for k, v in EVSE_NAME_MAP.items()}, **{v: k for k, v in ASSET_NAME_MAP.items()}}
    selected_evse_ids = [NAME_TO_ID[n] for n in evse_picks if n in NAME_TO_ID]

    # Fleet filter no longer needed — show everything by default
    FLEET_IDS = set()
    fleet_only = False

    # Default window: last 7 days ending at current AKDT hour
    now_ak = pd.Timestamp.now(tz=AK)
    _start_default_date = (now_ak - pd.Timedelta(days=7)).date()
    _end_default_date = now_ak.date()
    _current_hour = int(now_ak.hour)

    start_date = st.date_input("Start date (AKDT)", value=_start_default_date)
    start_hour = st.selectbox("Start hour (24h AKDT)", options=list(range(24)), index=_current_hour, format_func=lambda h: f"{h:02d}:00")
    end_date = st.date_input("End date (AKDT)", value=_end_default_date)
    end_hour = st.selectbox("End hour (24h AKDT)", options=list(range(24)), index=_current_hour, format_func=lambda h: f"{h:02d}:00")

# ---- Time conversion --------------------------------------------------------
def akdt_range_to_utc_iso(start_date, start_hour, end_date, end_hour) -> Tuple[str, str]:
    s = pd.Timestamp.combine(start_date, dtime(hour=int(start_hour), minute=0)).tz_localize(AK).astimezone(UTC)
    e = pd.Timestamp.combine(end_date, dtime(hour=int(end_hour), minute=59)).tz_localize(AK).astimezone(UTC)
    return s.isoformat(), e.isoformat()

start_utc_iso, end_utc_iso = akdt_range_to_utc_iso(start_date, start_hour, end_date, end_hour)

# ---- DB helpers -------------------------------------------------------------
def table_list(db_file: str, _mtime: float) -> List[str]:
    """Return current table names for the active DB file."""
    try:
        engine = get_engine(db_file)
        insp = inspect(engine)
        return sorted(insp.get_table_names())
    except Exception as e:
        st.write(f"(debug) table_list: inspector could not read tables from engine — {e}")
        return []

@st.cache_data(show_spinner=False)
def read_range(db_file: str, table: str, start_iso: str, end_iso: str, evse_id: Optional[str], _mtime: float) -> pd.DataFrame:
    engine = get_engine(db_file)
    where = ["timestamp >= :start AND timestamp <= :end"]
    params: Dict = {"start": start_iso, "end": end_iso}
    if evse_id:
        where.append("station_id = :evse_id")
        params["evse_id"] = evse_id
    sql = f"SELECT * FROM {table} WHERE {' AND '.join(where)} ORDER BY timestamp ASC"
    try:
        df = pd.read_sql(sql, engine, params=params)
    except Exception:
        df = pd.DataFrame()
    return df

# ---- Helper: Load and normalize CEA OCPP samples to meter schema ----
@st.cache_data(show_spinner=False)
def read_cea_samples(db_file: str, start_iso: str, end_iso: str, _mtime: float) -> pd.DataFrame:
    """
    Load CEA OCPP samples and normalize columns so they blend into the main meter
    pipeline. Expected table: `cea_ocpp_samples` with at least:
      - timestamp_utc (ISO8601)
      - station_id (string, e.g., 'CEA')
      - connector_id (int)
      - current_import_a, current_offered_a
      - energy_import_wh, power_import_w
      - soc_percent, voltage_v
    Returns a DataFrame with canonical columns used by the app:
      timestamp, station_id, connector_id, power_w, energy_wh, soc,
      amperage_import, offered_current_a, hvb_volts
    """
    engine = get_engine(db_file)
    try:
        df = pd.read_sql(
            """
            SELECT *
            FROM cea_ocpp_samples
            WHERE timestamp_utc >= :start AND timestamp_utc <= :end
            ORDER BY timestamp_utc ASC
            """,
            engine,
            params={"start": start_iso, "end": end_iso},
        )
    except Exception:
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    out = pd.DataFrame()
    # Timestamp: normalize to the canonical column name used elsewhere
    if "timestamp_utc" in df.columns:
        out["timestamp"] = pd.to_datetime(df["timestamp_utc"], errors="coerce", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        # Ensure a clean Z form (optional cosmetic)
        out["timestamp"] = out["timestamp"].str.replace(r"\+0000$", "+00:00", regex=True)
    elif "timestamp" in df.columns:
        out["timestamp"] = df["timestamp"].astype(str)
    else:
        # No timestamp — nothing usable
        return pd.DataFrame()

    # Identity columns
    if "station_id" in df.columns:
        out["station_id"] = df["station_id"].astype(str)
    else:
        out["station_id"] = "CEA"

    if "connector_id" in df.columns:
        out["connector_id"] = pd.to_numeric(df["connector_id"], errors="coerce")

    # Transaction/session identity (needed for session summaries)
    if "transaction_id" in df.columns:
        out["transaction_id"] = df["transaction_id"].astype(str)
    elif "session_id" in df.columns:
        out["transaction_id"] = df["session_id"].astype(str)

    # Metric mappings (defensive if missing)
    if "power_import_w" in df.columns:
        out["power_w"] = pd.to_numeric(df["power_import_w"], errors="coerce")
    if "energy_import_wh" in df.columns:
        out["energy_wh"] = pd.to_numeric(df["energy_import_wh"], errors="coerce")
    if "soc_percent" in df.columns:
        out["soc"] = pd.to_numeric(df["soc_percent"], errors="coerce")
    if "current_import_a" in df.columns:
        out["amperage_import"] = pd.to_numeric(df["current_import_a"], errors="coerce")
    if "current_offered_a" in df.columns:
        out["offered_current_a"] = pd.to_numeric(df["current_offered_a"], errors="coerce")
    if "requested_current_a" in df.columns:
        out["requested_current_a"] = pd.to_numeric(df["requested_current_a"], errors="coerce")
    if "voltage_v" in df.columns:
        out["hvb_volts"] = pd.to_numeric(df["voltage_v"], errors="coerce")

    # Carry optional action/type/source if present (won’t affect plotting)
    for extra in ["action", "type", "source", "protocol"]:
        if extra in df.columns:
            out[extra] = df[extra]

    # Tag EVSE name later via add_evse_name_col; return normalized
    return out
def _candidate_tables(avail: List[str], include_terms: List[str], exclude_terms: List[str] = None) -> List[str]:
    exclude_terms = exclude_terms or []
    out = []
    for t in avail:
        tl = t.lower()
        if all(term in tl for term in include_terms) and not any(ex in tl for ex in exclude_terms):
            out.append(t)
    out.sort(key=lambda x: (0 if "realtime" in x.lower() else 1, x))
    return out

@st.cache_data(show_spinner=False)
def load_connectivity_events(db_file: str, start_iso: str, end_iso: str, _mtime: float) -> pd.DataFrame:
    avail = table_list(db_file, _mtime)
    events = []

    # --- Explicit fast path: known table 'realtime_websocket' (and archive) ---
    for ws_table in ["realtime_websocket", "realtime_websocket_archive"]:
        if ws_table in avail:
            try:
                with sqlite3.connect(db_file) as con:
                    q = f"SELECT * FROM {ws_table} WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp ASC"
                    base = pd.read_sql_query(q, con, params=[start_iso, end_iso])
                if not base.empty:
                    # Normalize event labels to our 'Connectivity' column
                    df_ws = base.copy()
                    evt_lc = {c.lower(): c for c in df_ws.columns}
                    if "event" in evt_lc:
                        ev = df_ws[evt_lc["event"]].astype(str).str.upper()
                        df_ws["Connectivity"] = np.where(ev.str.contains("DISCONNECT"), "websocket DISCONNECT", "websocket CONNECT")
                    else:
                        # If no 'event' column for some reason, skip this table
                        df_ws = pd.DataFrame()
                    if not df_ws.empty:
                        events.append(df_ws)
            except Exception:
                pass

    # --- Heuristic paths (keep existing behavior) ---
    if not events:
        # Case A: separate connect / disconnect tables
        connect_tables = _candidate_tables(avail, ["websocket", "connect"], ["disconnect"])
        disconnect_tables = _candidate_tables(avail, ["websocket", "disconnect"])
        # Also consider short 'ws' prefix
        connect_tables += _candidate_tables(avail, ["ws", "connect"], ["disconnect"])
        disconnect_tables += _candidate_tables(avail, ["ws", "disconnect"])

        for ct in connect_tables:
            df = read_range(db_file, ct, start_iso, end_iso, None, _mtime)
            if not df.empty:
                df = df.copy()
                df["Connectivity"] = "websocket CONNECT"
                events.append(df)
        for dt in disconnect_tables:
            df = read_range(db_file, dt, start_iso, end_iso, None, _mtime)
            if not df.empty:
                df = df.copy()
                df["Connectivity"] = "websocket DISCONNECT"
                events.append(df)

    if not events:
        # Case B: single table with an 'event'/'action'/'status' column (e.g., 'realtime_websocket' variants)
        candidates = _candidate_tables(avail, ["websocket"]) + _candidate_tables(avail, ["ws"])
        seen = set()
        for t in candidates:
            if t in seen:
                continue
            seen.add(t)
            df = read_range(db_file, t, start_iso, end_iso, None, _mtime)
            if df.empty:
                continue
            cols_lc = {c.lower(): c for c in df.columns}
            evt_col = cols_lc.get("event") or cols_lc.get("action") or cols_lc.get("status")
            if not evt_col:
                continue
            dff = df.copy()
            ev = dff[evt_col].astype(str).str.upper()
            mask = ev.str.contains("CONNECT") | ev.str.contains("DISCONNECT")
            dff = dff[mask].copy()
            if dff.empty:
                continue
            dff["Connectivity"] = np.where(
                ev.loc[dff.index].str.contains("DISCONNECT"),
                "websocket DISCONNECT",
                "websocket CONNECT",
            )
            events.append(dff)

    if not events:
        return pd.DataFrame(columns=["timestamp", "station_id", "Connectivity"])

    out = pd.concat(events, ignore_index=True, sort=False)

    # Normalize key columns if variants exist
    cols = {c.lower(): c for c in out.columns}
    # station id variants
    for cand in ["station_id", "evse_id", "asset_id", "station"]:
        if cand in cols:
            if cand != "station_id":
                out = out.rename(columns={cols[cand]: "station_id"})
            break
    # timestamp variants
    for cand in ["timestamp", "time", "ts", "created_at"]:
        if cand in cols:
            if cand != "timestamp":
                out = out.rename(columns={cols[cand]: "timestamp"})
            break

    # Keep only essentials
    keep = [c for c in ["timestamp", "station_id", "Connectivity"] if c in out.columns]
    return out[keep].copy()

# ---- Tritium error-code dictionary helpers --------------------------------
ERROR_TABLE = "tritium_error_codes"  # columns: platform, code, impact, description

@st.cache_data(show_spinner=False)
def error_code_table_exists(db_file: str, _mtime: float) -> bool:
    if not Path(db_file).exists():
        return False
    engine = get_engine(db_file)
    try:
        insp = inspect(engine)
        return ERROR_TABLE in insp.get_table_names()
    except Exception:
        return False

def ensure_error_code_table(db_file: str) -> None:
    engine = get_engine(db_file)
    with engine.begin() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ERROR_TABLE} (
              platform TEXT NOT NULL,
              code TEXT NOT NULL,
              impact TEXT,
              description TEXT,
              PRIMARY KEY (platform, code)
            )
            """
        )
        try:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{ERROR_TABLE}_platform_code ON {ERROR_TABLE}(platform, code)")
        except Exception:
            pass

@st.cache_data(show_spinner=False)
def get_error_codes_df(db_file: str, _mtime: float) -> pd.DataFrame:
    if not error_code_table_exists(db_file, _mtime):
        return pd.DataFrame(columns=["platform","code","impact","description"])
    engine = get_engine(db_file)
    try:
        return pd.read_sql(
            f"SELECT platform, code, impact, description FROM {ERROR_TABLE}", engine
        )
    except Exception:
        return pd.DataFrame(columns=["platform","code","impact","description"])

# ---- Flexible Excel sheet reader for error code import ----
def _read_sheet_flexible(xls: pd.ExcelFile, sheet_name: str) -> pd.DataFrame:
    """
    Read an Excel sheet even if the header row isn't the first row.
    Heuristic: scan the first 20 rows to find a row that contains
    both a 'code' and a 'description' cell (case-insensitive),
    then re-read using that row as the header.
    """
    try:
        tmp = pd.read_excel(xls, sheet_name=sheet_name, header=None, nrows=20)
        header_row = None
        for i in range(min(len(tmp), 20)):
            row_vals = tmp.iloc[i].astype(str).str.strip().str.lower().tolist()
            if any("code" in v for v in row_vals) and any(("description" in v) or ("desc" in v) for v in row_vals):
                header_row = i
                break
        if header_row is not None:
            return pd.read_excel(xls, sheet_name=sheet_name, header=header_row)
        return pd.read_excel(xls, sheet_name=sheet_name)
    except Exception:
        return pd.read_excel(xls, sheet_name=sheet_name)

def upsert_error_codes_from_excel(db_file: str, file_like) -> Tuple[int, int]:
    """Load Tritium error codes from the uploaded Excel (two sheets) and upsert into DB.
    Returns (inserted_or_updated_rows, total_rows_discovered_across_sheets).
    This version is tolerant to sheet/column name variants and logs what it found.
    """
    ensure_error_code_table(db_file)

    xls = pd.ExcelFile(file_like)

    # Helper: fuzzy column finder by keyword
    def _find_col(cols, *keywords):
        cols_lc = {str(c).strip().lower(): c for c in cols}
        # exact
        for kw in keywords:
            if kw in cols_lc:
                return cols_lc[kw]
        # contains any
        for name_lc, orig in cols_lc.items():
            if any(kw in name_lc for kw in keywords):
                return orig
        return None

    # Relaxed sheet detection
    sheet_for = {"RT50": None, "RTM": None}
    for s in xls.sheet_names:
        sl = s.strip().lower()
        if "rt50" in sl:
            sheet_for["RT50"] = s
        if ("rtm" in sl) or ("rtm75" in sl):
            sheet_for["RTM"] = s

    frames = []
    total_seen = 0
    for platform, sheet in sheet_for.items():
        if not sheet:
            continue
        df = _read_sheet_flexible(xls, sheet)
        if df is None or df.empty:
            continue
        total_seen += len(df)

        code_col = _find_col(df.columns, "code", "error code", "fault code")
        impact_col = _find_col(df.columns, "impact", "severity", "impact class", "impact level")
        desc_col = _find_col(df.columns, "description", "desc", "details", "fault description", "error description")

        if not code_col or not desc_col:
            # Skip sheet if key columns missing
            continue

        # Build normalized frame
        out = pd.DataFrame({
            "platform": platform,
            "code": df[code_col].astype(str).str.strip(),
            "impact": (df[impact_col].astype(str).str.strip().str[0].str.upper() if impact_col else ""),
            "description": df[desc_col].astype(str).str.strip(),
        })

        # Drop rows that look like repeated headers or blank codes
        out = out[out["code"].astype(str).str.strip().str.lower() != "code"]
        out = out[out["description"].astype(str).str.strip().str.lower() != "description"]
        out = out[out["code"].astype(str).str.strip() != ""]

        # Normalize impact strictly to N/L/H
        out.loc[~out["impact"].isin(["N", "L", "H"]), "impact"] = ""
        out = out.dropna(subset=["code"])
        out = out.loc[out["code"].astype(str).str.len() > 0]

        frames.append(out)

    if not frames:
        return (0, total_seen)

    all_rows = pd.concat(frames, ignore_index=True)

    engine = get_engine(db_file)
    with engine.begin() as conn:
        for r in all_rows.itertuples(index=False):
            conn.execute(
                f"""
                INSERT INTO {ERROR_TABLE}(platform, code, impact, description)
                VALUES (:platform, :code, :impact, :description)
                ON CONFLICT(platform, code) DO UPDATE SET
                  impact=excluded.impact,
                  description=excluded.description
                """,
                {"platform": r.platform, "code": r.code, "impact": r.impact, "description": r.description},
            )

    return (len(all_rows), total_seen)

def add_akdt(df: pd.DataFrame, ts_col: str = "timestamp") -> pd.DataFrame:
    if ts_col not in df.columns:
        return df
    out = df.copy()

    # Normalize to string and trim; normalize 'Z' to '+00:00' just in case
    s = out[ts_col].astype(str).str.strip()
    s = s.replace({"": np.nan, "None": np.nan})
    s_norm = s.str.replace("Z", "+00:00", regex=False)

    # First pass: ISO8601 (and anything pandas can parse) → UTC
    out["ts_utc"] = pd.to_datetime(s_norm, utc=True, errors="coerce")

    # Second pass: fix rows still NaT by trying epoch microseconds/milliseconds/seconds (numeric or numeric-strings)
    nat = out["ts_utc"].isna()
    if nat.any():
        num = pd.to_numeric(out.loc[nat, ts_col], errors="coerce")
        has_num = num.notna()
        if has_num.any():
            us_mask = num > 1e14
            ms_mask = (~us_mask) & (num > 1e12)
            s_mask  = (~us_mask) & (~ms_mask) & (num >= 1e9)
            if us_mask.any():
                out.loc[nat[nat].index[us_mask.values], "ts_utc"] = pd.to_datetime(num[us_mask], unit="us", utc=True, errors="coerce")
            if ms_mask.any():
                out.loc[nat[nat].index[ms_mask.values], "ts_utc"] = pd.to_datetime(num[ms_mask], unit="ms", utc=True, errors="coerce")
            if s_mask.any():
                out.loc[nat[nat].index[s_mask.values],  "ts_utc"] = pd.to_datetime(num[s_mask],  unit="s",  utc=True, errors="coerce")

    # Third pass: very defensive — try parsing without utc then localize to UTC
    nat = out["ts_utc"].isna()
    if nat.any():
        try:
            tmp = pd.to_datetime(out.loc[nat, ts_col], errors="coerce")
            # If timezone-naive, assume UTC
            if tmp.notna().any():
                # If tz-aware, convert; else localize to UTC
                tzaware = pd.api.types.is_datetime64tz_dtype(tmp)
                if tzaware:
                    out.loc[nat, "ts_utc"] = tmp.dt.tz_convert(UTC)
                else:
                    out.loc[nat, "ts_utc"] = tmp.dt.tz_localize(UTC)
        except Exception:
            pass

    # AKDT timezone and a printable string for tables
    out["AKDT_dt"] = out["ts_utc"].dt.tz_convert(AK)
    # Human string used in some views (Y-m-d HH:MM:SS)
    out["AKDT"] = out["AKDT_dt"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return out

def add_evse_name_col(df: pd.DataFrame, col: str = "station_id") -> pd.DataFrame:
    if col not in df.columns:
        return df
    out = df.copy()
    out["EVSE"] = out[col].map(friendly_evse_dynamic)
    return out

def add_hvb_volts(df: pd.DataFrame, power_col="power_w", amps_col="amperage_import", out_col="hvb_volts") -> pd.DataFrame:
    out = df.copy()
    if power_col in out.columns and amps_col in out.columns:
        p = pd.to_numeric(out[power_col], errors="coerce")
        a = pd.to_numeric(out[amps_col], errors="coerce")
        valid = (p.notna()) & (a.notna()) & (p > 0) & (a > 0)
        result = np.full(len(out), np.nan, dtype="float64")
        # compute only on valid indices
        result[valid.values] = (p[valid] / a[valid]).astype("float64").values
        hv = pd.Series(result, index=out.index, dtype="float64")
        out[out_col] = hv.round(0).astype("Int64")
    return out

# Normalize a dataframe to include robust time columns and friendly EVSE name
# Adds/overwrites: ts_utc, AKDT_dt, AKDT, EVSE
def ensure_evse_and_time(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = add_akdt(df, ts_col="timestamp")
    out = add_evse_name_col(out, col="station_id")
    return out

# Excel-safe: drop timezone info from any timezone-aware datetime columns

def strip_tz_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    for c in out.columns:
        try:
            if pd.api.types.is_datetime64tz_dtype(out[c]):
                # keep wall-clock values, remove tz
                out[c] = out[c].dt.tz_convert(None)
        except Exception:
            pass
    return out

# Helper: Convert a datetime-like Series to Anchorage tz and make it tz-naive for Excel export.
def to_ak_naive(dt_like: pd.Series) -> pd.Series:
    """
    Ensure a datetime-like Series is converted to Anchorage time (AK) and made timezone-naive
    for Excel export. If the input is timezone-aware, it will be converted from its tz to AK.
    If the input is timezone-naive, we assume it represents UTC and convert to AK.
    """
    ser = pd.to_datetime(dt_like, errors="coerce")
    try:
        if pd.api.types.is_datetime64tz_dtype(ser):
            ser = ser.dt.tz_convert(AK)
        else:
            # Treat naive datetimes as UTC by default, then convert to AK
            ser = ser.dt.tz_localize(UTC).dt.tz_convert(AK)
        # Strip tz for Excel-friendly naive datetimes while preserving AK wall-clock
        return ser.dt.tz_localize(None)
    except Exception:
        return ser

# Build a map: transaction_id -> first id_tag seen in authorize table (within window)
@st.cache_data(show_spinner=False)
def build_auth_id_map(db_file: str, start_iso: str, end_iso: str, evse_id: Optional[str], _mtime: float) -> Dict[str, str]:
    try:
        avail = table_list(db_file, _mtime)
        a_table = "realtime_authorize" if "realtime_authorize" in avail else ("authorize" if "authorize" in avail else None)
        if not a_table:
            return {}
        adf = read_range(db_file, a_table, start_iso, end_iso, evse_id, _db_mtime(db_path))
        if adf is None or adf.empty:
            return {}
        if "transaction_id" in adf.columns and "id_tag" in adf.columns:
            grp = adf.dropna(subset=["transaction_id", "id_tag"]).copy()
            grp["transaction_id"] = grp["transaction_id"].astype(str)
            return grp.groupby("transaction_id")["id_tag"].first().to_dict()
        return {}
    except Exception:
        return {}

# Build maps for auth artifacts keyed by common session keys
@st.cache_data(show_spinner=False)
def build_auth_maps(db_file: str, start_iso: str, end_iso: str, evse_id: Optional[str], _mtime: float) -> Tuple[Dict[str, str], Dict[str, str]]:
    id_map: Dict[str, str] = {}
    vid_map: Dict[str, str] = {}
    try:
        avail = table_list(db_file, _mtime)
        a_table = "realtime_authorize" if "realtime_authorize" in avail else ("authorize" if "authorize" in avail else None)
        if not a_table:
            return id_map, vid_map
        adf = read_range(db_file, a_table, start_iso, end_iso, evse_id, _db_mtime(db_path))
        if adf is None or adf.empty:
            return id_map, vid_map
        # Normalize column casing for VID
        cols = {c.lower(): c for c in adf.columns}
        vid_col = cols.get("vid")
        idtag_col = cols.get("id_tag")
        # Try mapping by most reliable keys first
        for key in ["transaction_id", "session_id", "session"]:
            if key in adf.columns:
                tmp = adf.copy()
                tmp[key] = tmp[key].astype(str)
                if idtag_col:
                    m = tmp.dropna(subset=[key, idtag_col]).groupby(key)[idtag_col].first().to_dict()
                    # only set if not already set by a stronger key
                    for k, v in m.items():
                        id_map.setdefault(str(k), str(v))
                if vid_col:
                    m = tmp.dropna(subset=[key, vid_col]).groupby(key)[vid_col].first().to_dict()
                    for k, v in m.items():
                        vid_map.setdefault(str(k), str(v))
        return id_map, vid_map
    except Exception:
        return id_map, vid_map

# Helper: Streamlit dialog (fallback inline if st.dialog missing)
def open_dialog(title: str, body: Callable[[], None]) -> None:
    if hasattr(st, "dialog"):
        @st.dialog(title)  # type: ignore[attr-defined]
        def _dlg() -> None:
            body()
        _dlg()
    else:
        st.info(f"(Dialog not supported in this Streamlit version) — {title}")
        body()

# ---- Diagnostics drawer -----------------------------------------------------
with st.expander("🧰 Diagnostics", expanded=False):
    st.write(f"**DB:** `{db_path}`")
    # runtime DB source visibility (helps confirm Render picked up env vars)
    _env_render = os.environ.get("RENDER_DB_URL") or os.environ.get("DATABASE_URL")
    _env_supabase = os.environ.get("SUPABASE_DB_URL")
    st.caption(f"RENDER_DB_URL seen: {'yes' if _env_render else 'no'}")
    st.caption(f"SUPABASE_DB_URL seen: {'yes' if _env_supabase else 'no'}")
    chosen = os.environ.get("RENDER_DB_URL") or os.environ.get("DATABASE_URL") or f"sqlite:///{db_path}"
    st.caption(f"DB engine in use: {('Render/DATABASE_URL' if (os.environ.get('RENDER_DB_URL') or os.environ.get('DATABASE_URL')) else 'SQLite')} -> {chosen}")
    tl = table_list(db_path, _db_mtime(db_path))
    if tl:
        st.write("Tables found:", ", ".join(tl))
        def mmc(table):
            try:
                engine = get_engine(db_path)
                with engine.connect() as con:
                    res = con.execute(f"SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM {table}")
                    c, mn, mx = res.fetchone()
                st.write(f"**{table}**: count={c} min={mn} max={mx}")
            except Exception:
                pass
        for t in [
            "realtime_meter_values",
            "meter_values",
            "realtime_status_notifications",
            "status_notifications",
            "realtime_authorize",
            "realtime_websocket"
        ]:
            if t in tl: 
                mmc(t)
    else:
        st.warning("DB file not found or no tables.")

# ---- Tabs -------------------------------------------------------------------
tabs = st.tabs(["Charging Sessions", "Status History", "Connectivity", "⬇Data Export"])

# ============================================================================ #
# 1) Meter Data (Session History)
# ============================================================================ #
with tabs[0]:

    # Use multi-select EVSE filter (selected_evse_ids from sidebar)
    evse_id = None  # keep DB query broad; filter after read using selected_evse_ids
    evse_ids_set = set(str(x) for x in selected_evse_ids) if 'selected_evse_ids' in locals() else set()

    avail = table_list(db_path, _db_mtime(db_path))
    meter_table = "realtime_meter_values" if "realtime_meter_values" in avail else ("meter_values" if "meter_values" in avail else None)

    if not meter_table:
        st.info("No meter tables found.")
    else:
        mdf = read_range(db_path, meter_table, start_utc_iso, end_utc_iso, evse_id, _db_mtime(db_path))
        # --- Also pull CEA samples in the same window and normalize to meter schema ---
        cea_df = pd.DataFrame()
        try:
            cea_df = read_cea_samples(db_path, start_utc_iso, end_utc_iso, _db_mtime(db_path))
        except Exception:
            cea_df = pd.DataFrame()
        if not cea_df.empty:
            # Apply sidebar EVSE filter (if any)
            if 'evse_ids_set' in locals() and len(evse_ids_set) > 0:
                cea_df = cea_df[cea_df["station_id"].astype(str).isin(evse_ids_set)]
            # Apply fleet filter (include CEA by default since we added it to EVSE_NAME_MAP)
            if fleet_only:
                cea_df = cea_df[cea_df["station_id"].astype(str).isin(FLEET_IDS)]

        # Apply filters to LynkWell data first
        if 'evse_ids_set' in locals() and len(evse_ids_set) > 0:
            mdf = mdf[mdf["station_id"].astype(str).isin(evse_ids_set)]
        if fleet_only:
            mdf = mdf[mdf["station_id"].astype(str).isin(FLEET_IDS)]

        # Combine LynkWell and CEA (align columns; concat if either is non-empty)
        combined_sources = []
        if not mdf.empty:
            combined_sources.append(mdf.copy())
        if not cea_df.empty:
            combined_sources.append(cea_df.copy())

        if not combined_sources:
            st.info("No meter data in this window.")
            df = pd.DataFrame()
            session_summary = pd.DataFrame()
        else:
            mdf = pd.concat(combined_sources, ignore_index=True, sort=False)

            # Normalize time + EVSE naming, and compute hvb_volts if needed
            mdf = add_akdt(mdf, "timestamp")
            mdf = add_evse_name_col(mdf, "station_id")
            # For rows without hvb_volts but with power/amps, compute it
            mdf = add_hvb_volts(mdf)

            df = mdf  # for export and downstream

            # --- Build session summary (robust for LynkWell + CEA) ---------------------
            # Normalize keys so CEA sessions appear downstream
            try:
                work = df.copy()

                # Ensure UTC datetime for grouping
                if "ts_utc" not in work.columns:
                    s = work["timestamp"].astype(str).str.replace("Z", "+00:00", regex=False)
                    work["ts_utc"] = pd.to_datetime(s, errors="coerce", utc=True)

                # Normalize transaction_id to real NaN for blanks and odd strings
                if "transaction_id" in work.columns:
                    tid = work["transaction_id"].astype(str).str.strip()
                    tid = tid.replace({"": np.nan, "None": np.nan, "none": np.nan,
                                       "NaN": np.nan, "nan": np.nan, "NULL": np.nan, "null": np.nan})
                    work["transaction_id"] = tid
                else:
                    work["transaction_id"] = np.nan

                # Keep only rows that belong to a session
                work = work.dropna(subset=["transaction_id", "ts_utc"]).copy()

                # Coerce numerics we aggregate
                for col in ["energy_wh", "power_w", "soc", "amperage_import", "offered_current_a", "hvb_volts", "connector_id"]:
                    if col in work.columns:
                        work[col] = pd.to_numeric(work[col], errors="coerce")

                grp = work.groupby(["station_id", "transaction_id"], dropna=False)
                session_summary = grp.agg(
                    start_utc=("ts_utc", "min"),
                    end_utc=("ts_utc", "max"),
                    start_soc=("soc", lambda s: pd.to_numeric(s, errors="coerce").dropna().iloc[0] if s.notna().any() else np.nan),
                    end_soc=("soc", "max"),
                    energy_wh=("energy_wh", "max"),
                    max_power_w=("power_w", "max"),
                    connector_id=("connector_id", lambda s: pd.to_numeric(s, errors="coerce").dropna().iloc[-1] if s.notna().any() else np.nan),
                ).reset_index()

                # Duration (minutes) and display times in AKDT
                session_summary["Duration (min)"] = (session_summary["end_utc"] - session_summary["start_utc"]).dt.total_seconds() / 60.0
                session_summary["Date/Time (AKDT)"] = session_summary["start_utc"].dt.tz_convert(AK).dt.strftime("%Y-%m-%d %H:%M:%S")
                session_summary["Stop Time (AKDT)"] = session_summary["end_utc"].dt.tz_convert(AK).dt.strftime("%Y-%m-%d %H:%M:%S")

                # Friendly names and connector type
                session_summary["Location"] = session_summary["station_id"].map(friendly_evse_dynamic)
                session_summary["Connector Type"] = session_summary.apply(
                    lambda r: connector_type_for(r["Location"], r.get("connector_id")), axis=1
                )

                # Convert power/energy to kW/kWh and SoC to 0-1 scale with 2 decimals
                session_summary["Max Power kW"] = (pd.to_numeric(session_summary["max_power_w"], errors="coerce") / 1000.0).round(2)
                session_summary["Energy kWh"] = (pd.to_numeric(session_summary["energy_wh"], errors="coerce") / 1000.0).round(2)
                session_summary["Start SoC"] = (pd.to_numeric(session_summary["start_soc"], errors="coerce") / 100.0).round(2)
                session_summary["End SoC"] = (pd.to_numeric(session_summary["end_soc"], errors="coerce") / 100.0).round(2)

                session_summary = session_summary.rename(columns={"transaction_id": "Transaction ID"})
                session_summary = session_summary[
                    [
                        "Date/Time (AKDT)", "Stop Time (AKDT)", "Location", "Transaction ID",
                        "Connector Type", "Max Power kW", "Energy kWh", "Duration (min)",
                        "Start SoC", "End SoC"
                    ]
                ].sort_values("Date/Time (AKDT)", ascending=False)
            except Exception:
                # If anything goes wrong, keep a safe empty frame to avoid downstream KeyErrors
                session_summary = pd.DataFrame(
                    columns=[
                        "Date/Time (AKDT)", "Stop Time (AKDT)", "Location", "Transaction ID",
                        "Connector Type", "Max Power kW", "Energy kWh", "Duration (min)",
                        "Start SoC", "End SoC", "Stop Time (AKDT)"
                    ]
                )
            # --- Normalize keys so CEA sessions appear downstream -----------------
            # transaction_id can come through as "", "None", "nan" (string) etc. Normalize to real NaN.
            if "transaction_id" in df.columns:
                df["transaction_id"] = df["transaction_id"].astype(str).str.strip()
                df.loc[df["transaction_id"].isin(["", "None", "none", "NaN", "nan", "NULL", "null"]), "transaction_id"] = np.nan

            # connector_id should be numeric for grouping/labeling; keep NaN if not parseable.
            if "connector_id" in df.columns:
                df["connector_id"] = pd.to_numeric(df["connector_id"], errors="coerce")
            id_tag_map, vid_map = build_auth_maps(db_path, start_utc_iso, end_utc_iso, evse_id, _db_mtime(db_path))

            # Load authorize rows for timestamp proximity matching (to backfill id_tag/VID)
            auth_df = pd.DataFrame()
            if "realtime_authorize" in avail or "authorize" in avail:
                a_tbl = "realtime_authorize" if "realtime_authorize" in avail else "authorize"
                auth_df = read_range(db_path, a_tbl, start_utc_iso, end_utc_iso, evse_id, _db_mtime(db_path))
                if not auth_df.empty and 'evse_ids_set' in locals() and len(evse_ids_set) > 0:
                    auth_df = auth_df[auth_df["station_id"].astype(str).isin(evse_ids_set)]
                if fleet_only and not auth_df.empty:
                    auth_df = auth_df[auth_df["station_id"].astype(str).isin(FLEET_IDS)]
                if not auth_df.empty:
                    auth_df = add_akdt(auth_df, "timestamp")
                    # Normalize column naming for VID casing
                    if "vid" in auth_df.columns and "VID" not in auth_df.columns:
                        auth_df = auth_df.rename(columns={"vid": "VID"})
                    # Ensure comparable dtypes
                    if "connector_id" in auth_df.columns:
                        auth_df["connector_id"] = pd.to_numeric(auth_df["connector_id"], errors="coerce")

            # Make authorize rows available to Export tab even without an Activation tab
            st.session_state["auth_df_display"] = auth_df.copy() if auth_df is not None else pd.DataFrame()
            
            # --- Session summary (one row per transaction_id) ---
            def _build_session_summary(df: pd.DataFrame) -> pd.DataFrame:
                """
                Build one row per charging transaction with:
                  - Date/Time (AKDT) (start)
                  - Stop Time (AKDT)
                  - Location (friendly EVSE name)
                  - Transaction ID
                  - Connector Type (CHAdeMO / CCS / NACS from map)
                  - Max Power kW
                  - Energy kWh (max(energy_wh)-min(energy_wh))
                  - Duration (min)
                  - ID Tag (VID only: 'VID:<hex>' if vehicle VID was read; else blank)
                """
                txn_col = next((c for c in ["transaction_id", "session_id", "session"] if c in df.columns), None)
                if not txn_col:
                    return pd.DataFrame()

                work = df.copy()
                # Coerce numerics we use
                for c in ["energy_wh", "power_w", "soc", "connector_id"]:
                    if c in work.columns:
                        work[c] = pd.to_numeric(work[c], errors="coerce")

                # Sort for stable grouping
                work = work.sort_values([txn_col, "timestamp"], kind="mergesort")
                # Robust time columns
                work = add_akdt(work, "timestamp")

                g = work.groupby(txn_col, sort=True)

                # --- Determine display start as the earliest MeterValue in the session ---
                # Per requirement: session "start" is the first MeterValue timestamp, not the Authorize or
                # the first high-power moment. Use the earliest sample we have.
                first_any_utc = g["ts_utc"].min()
                last_utc      = g["ts_utc"].max()
                # Fallback to raw strings if any NaT snuck in
                if "timestamp" in work.columns:
                    raw_min = pd.to_datetime(g["timestamp"].min(), utc=True, errors="coerce")
                    raw_max = pd.to_datetime(g["timestamp"].max(), utc=True, errors="coerce")
                    first_any_utc = first_any_utc.fillna(raw_min)
                    last_utc      = last_utc.fillna(raw_max)
                active_start_utc = first_any_utc

                # Display times in AKDT
                first_dt = active_start_utc.dt.tz_convert(AK)
                last_dt  = last_utc.dt.tz_convert(AK)

                # Friendly display strings
                try:
                    ts_fmt = first_dt.dt.strftime("%-m/%-d/%y %H:%M:%S")
                except Exception:
                    ts_fmt = first_dt.dt.strftime("%m/%d/%y %H:%M:%S")
                try:
                    stop_fmt = last_dt.dt.strftime("%-m/%-d/%y %H:%M:%S")
                except Exception:
                    stop_fmt = last_dt.dt.strftime("%m/%d/%y %H:%M:%S")

                # Connector & location
                connector_num = g["connector_id"].agg(
                    lambda s: (s.mode().iloc[0] if s.dropna().mode().shape[0]
                               else (s.dropna().iloc[0] if s.dropna().shape[0] else np.nan))
                )
                location = (g["EVSE"].first() if "EVSE" in work.columns
                            else (g["station_id"].first() if "station_id" in work.columns
                                  else pd.Series("(unknown)", index=first_dt.index)))

                # Session stats
                emax = pd.to_numeric(g["energy_wh"].max(), errors="coerce") if "energy_wh" in work.columns else pd.Series(np.nan, index=first_dt.index)
                emin = pd.to_numeric(g["energy_wh"].min(), errors="coerce") if "energy_wh" in work.columns else pd.Series(np.nan, index=first_dt.index)
                energy_kwh = ((emax - emin).clip(lower=0) / 1000.0).round(2)
                max_power_kw = (pd.to_numeric(g["power_w"].max(), errors="coerce") / 1000.0).round(2) if "power_w" in work.columns else pd.Series(np.nan, index=first_dt.index)

                # ---------- VID-only matching from auth_df (vectorized with asof joins) ----------
                # Build a VID-only series by finding the nearest prior VID read per session start.
                # Strategy: try same station & connector within 60s → 5min, then relax to station-only within 30min.
                # Result is normalized to 'VID:<hex>' or blank if none.
                # Ensure we have station_first available for the left frame
                station_first = (g["station_id"].first() if "station_id" in work.columns else pd.Series(index=first_dt.index, dtype="object"))

                def _normalize_vid_string(v: object) -> str:
                    if v is None or (isinstance(v, float) and np.isnan(v)):
                        return ""
                    s = str(v).strip()
                    if not s:
                        return ""
                    if s.lower().startswith("vid:"):
                        return "VID:" + s.split(":", 1)[1]
                    return "VID:" + s

                if auth_df is not None and not auth_df.empty and "ts_utc" in auth_df.columns:
                    auth = auth_df.copy()
                    # Ensure both sides of merge_asof use timezone-aware UTC datetimes
                    if "ts_utc" in auth.columns:
                        auth["ts_utc"] = pd.to_datetime(auth["ts_utc"], utc=True, errors="coerce")
                    # Build a unified VID column: from explicit VID or from id_tag like 'VID:abcd...'
                    auth["vid_norm"] = ""
                    if "VID" in auth.columns:
                        auth.loc[auth["VID"].notna(), "vid_norm"] = auth.loc[auth["VID"].notna(), "VID"].astype(str)
                    if "id_tag" in auth.columns:
                        _id = auth["id_tag"].astype(str)
                        mask = _id.str.match(r"^\s*VID\s*:\s*[A-Fa-f0-9]+\s*$", na=False)
                        auth.loc[mask, "vid_norm"] = _id.loc[mask].str.extract(r"VID\s*:\s*([A-Fa-f0-9]+)", expand=False)
                    # Normalize prefix exactly to 'VID:' and drop blanks
                    auth["vid_norm"] = auth["vid_norm"].apply(_normalize_vid_string)
                    auth = auth[auth["vid_norm"].astype(str).str.len() > 0].copy()

                    if not auth.empty:
                        if "connector_id" in auth.columns:
                            auth["connector_id"] = pd.to_numeric(auth["connector_id"], errors="coerce")
                        auth = auth.sort_values("ts_utc")

                        left = pd.DataFrame({
                            "k": first_dt.index,
                            "start_utc": active_start_utc.values,
                            "station_id": station_first.values if len(station_first) else [""] * len(first_dt),
                            "connector_id": connector_num.values,
                        }).sort_values("start_utc")
                        left["start_utc"] = pd.to_datetime(left["start_utc"], utc=True, errors="coerce")

                        def _asof_by_station_and_connector(cand: pd.DataFrame, tol: str) -> pd.DataFrame:
                            return pd.merge_asof(
                                left,
                                cand.sort_values("ts_utc")["ts_utc station_id connector_id vid_norm".split()],
                                left_on="start_utc",
                                right_on="ts_utc",
                                by=["station_id", "connector_id"],
                                direction="backward",
                                tolerance=pd.Timedelta(tol),
                            )

                        def _asof_by_station_only(cand: pd.DataFrame, tol: str) -> pd.DataFrame:
                            return pd.merge_asof(
                                left,
                                cand.sort_values("ts_utc")["ts_utc station_id vid_norm".split()],
                                left_on="start_utc",
                                right_on="ts_utc",
                                by=["station_id"],
                                direction="backward",
                                tolerance=pd.Timedelta(tol),
                            )

                        # Pass 1: require same connector within 60s, then 5min
                        if "connector_id" in auth.columns:
                            res = _asof_by_station_and_connector(auth, "60s")
                            miss = res["vid_norm"].isna()
                            if miss.any():
                                res2 = _asof_by_station_and_connector(auth, "5min")
                                res.loc[miss, "vid_norm"] = res2.loc[miss, "vid_norm"]
                        else:
                            # If no connector in auth table, start with station-only 60s
                            res = _asof_by_station_only(auth, "60s")
                            miss = res["vid_norm"].isna()
                            if miss.any():
                                res2 = _asof_by_station_only(auth, "5min")
                                res.loc[miss, "vid_norm"] = res2.loc[miss, "vid_norm"]

                        # Pass 2: relax to station-only within 30min for remaining
                        miss = res["vid_norm"].isna()
                        if miss.any():
                            res3 = _asof_by_station_only(auth, "30min")
                            res.loc[miss, "vid_norm"] = res3.loc[miss, "vid_norm"]

                        vid_series = pd.Series(
                            res.set_index("k")["vid_norm"].fillna("").astype(str).replace("nan", ""),
                            index=first_dt.index,
                            dtype="object",
                        )
                    else:
                        vid_series = pd.Series([""] * len(first_dt), index=first_dt.index, dtype="object")
                else:
                    vid_series = pd.Series([""] * len(first_dt), index=first_dt.index, dtype="object")

                # Connector type label from site + connector number
                conn_type_series = pd.Series(
                    [
                        connector_type_for(
                            location.loc[k] if k in location.index else "",
                            connector_num.loc[k] if k in connector_num.index else None,
                        )
                        for k in first_dt.index
                    ],
                    index=first_dt.index,
                    dtype="object",
                )

                # Compute Start/End SoC (first non-zero, and max per session)
                if "soc" in work.columns:
                    def _first_nonzero(series: pd.Series) -> float:
                        s = pd.to_numeric(series, errors="coerce")
                        nz = s[s > 0]
                        return float(nz.iloc[0]) if len(nz) > 0 else np.nan
                    start_soc = (g["soc"].apply(_first_nonzero).astype(float) / 100.0).round(2)
                    end_soc = (pd.to_numeric(g["soc"].max(), errors="coerce").astype(float) / 100.0).round(2)
                else:
                    start_soc = pd.Series(np.nan, index=first_dt.index, dtype="float")
                    end_soc = pd.Series(np.nan, index=first_dt.index, dtype="float")

                out = pd.DataFrame({
                    "Date/Time (AKDT)": ts_fmt,
                    "Stop Time (AKDT)": stop_fmt,
                    "Location": location,
                    "Transaction ID": first_dt.index.astype(str),
                    "Connector #": connector_num,
                    "Connector Type": conn_type_series,
                    "Max Power kW": pd.to_numeric(max_power_kw, errors="coerce"),
                    "Energy kWh": pd.to_numeric(energy_kwh, errors="coerce"),
                    "Duration (min)": ((last_dt - first_dt).dt.total_seconds() / 60.0).round(2),
                    "SoC Start": (start_soc * 100.0).round(0),
                    "SoC End": (end_soc * 100.0).round(0),
                    "ID Tag": vid_series,   # VID only; blank if none
                    "_start": first_dt,
                    "_end": last_dt,
                }).reset_index(drop=True)

                # Ensure display start string derived from _start
                try:
                    dt_series = out["_start"].dt.tz_convert(AK)
                    try:
                        out["Date/Time (AKDT)"] = dt_series.dt.strftime("%-m/%-d/%y %H:%M:%S")
                    except Exception:
                        out["Date/Time (AKDT)"] = dt_series.dt.strftime("%m/%d/%y %H:%M:%S")
                except Exception:
                    pass

                return out

            session_summary = _build_session_summary(mdf)
            # --- Ensure session_summary always has the standard columns (even if empty) ---
            # --- Ensure session_summary always has the standard columns (even if empty) ---
            _summary_cols = [
                "Date/Time (AKDT)", "Stop Time (AKDT)", "Location", "Transaction ID",
                "Connector #", "Connector Type", "Max Power kW", "Energy kWh", "Duration (min)",
                "SoC Start", "SoC End", "ID Tag", "_start", "_end"
            ]
            if session_summary is None or session_summary.empty:
                session_summary = pd.DataFrame(columns=_summary_cols)
            else:
                # Backfill any missing columns to avoid KeyErrors downstream
                for _c in _summary_cols:
                    if _c not in session_summary.columns:
                        session_summary[_c] = pd.Series([np.nan] * len(session_summary))
                # Ensure column order for consistency
                session_summary = session_summary[_summary_cols + [c for c in session_summary.columns if c not in _summary_cols]]
                # 🔽 Force newest → oldest by the real datetime
                session_summary = session_summary.sort_values("_start", ascending=False, kind="mergesort").reset_index(drop=True)
                # ---- Make latest session summary available to Export tab (with cache-busting) ----
                st.session_state["export_session_summary"] = session_summary.copy()
                st.session_state["export_context"] = {
                    "start": start_utc_iso,
                    "end": end_utc_iso,
                    "evse_ids": list(selected_evse_ids),
                    "fleet_only": bool(fleet_only),
                    "db_mtime": _db_mtime(db_path),
                }

            # === Session History table (one row per transaction) ===
            if session_summary.empty:
                st.info("No charging sessions (no transaction_id) in this window.")
                x_range_override = None
                txn_filter = None
            else:
                x_range_override = None
                txn_filter = None

                # Prefer AgGrid (true row-click selection). Fallback to data_editor if not installed.
                if AGGRID_AVAILABLE:
                    tbl = session_summary[[
                        "Date/Time (AKDT)", "Stop Time (AKDT)", "Location",
                        "Connector #", "Connector Type", "Max Power kW", "Energy kWh", "Duration (min)",
                        "SoC Start", "SoC End", "ID Tag",
                        "_start", "_end"
                    ]].copy()
                    tbl = tbl.sort_values("_start", ascending=False, kind="mergesort")

                    gob = GridOptionsBuilder.from_dataframe(tbl)
                    gob.configure_default_column(
                        filter=True,
                        sortable=True,
                        resizable=True,
                        flex=1,
                        minWidth=110,
                        tooltipField=None,
                    )
                    # numeric formatting
                    gob.configure_column("Max Power kW", type=["numericColumn"], valueFormatter="x.toFixed(2)")
                    gob.configure_column("Energy kWh", type=["numericColumn"], valueFormatter="x.toFixed(2)")
                    gob.configure_column("Duration (min)", type=["numericColumn"], valueFormatter="x.toFixed(2)")
                    gob.configure_column("SoC Start", type=["numericColumn"], valueFormatter="x.toFixed(0)")
                    gob.configure_column("SoC End", type=["numericColumn"], valueFormatter="x.toFixed(0)")
                    # tooltips for long text columns, with explicit widths for start/stop time
                    gob.configure_column("Date/Time (AKDT)", headerTooltip="Session start time in Alaska time", width=190)
                    gob.configure_column("Stop Time (AKDT)", headerTooltip="Session stop time in Alaska time", width=190)
                    gob.configure_column("Location", headerTooltip="Site / charger name")
                    gob.configure_column("ID Tag", headerTooltip="VID:... if vehicle ID was read")

                    # Single-row click selection
                    gob.configure_selection(
                        selection_mode="single",
                        use_checkbox=False,
                    )
                    gob.configure_column("_start", hide=True, sort="desc")
                    gob.configure_column("_end", hide=True)
                    gob.configure_column("Connector #", type=["numericColumn"], maxWidth=120)
                    gob.configure_column("Connector Type", maxWidth=140)
                    # The following numeric columns are already formatted above; keep maxWidth for layout
                    gob.configure_column("Max Power kW", maxWidth=140)
                    gob.configure_column("Energy kWh", maxWidth=140)
                    gob.configure_column("Duration (min)", maxWidth=160)

                    grid = AgGrid(
                        tbl,
                        gridOptions=gob.build(),
                        update_mode=GridUpdateMode.SELECTION_CHANGED,
                        fit_columns_on_grid_load=True,
                        height=320,
                        allow_unsafe_jscode=False,
                    )
                    try:
                        grid_table = grid["data"]  # trigger autosize in frontend
                    except Exception:
                        pass

                    sel = grid.get("selected_rows", [])

                    # Normalize selection to a single row dict
                    row_dict = None
                    if isinstance(sel, list):
                        if len(sel) > 0:
                            row_dict = sel[0]
                    elif isinstance(sel, pd.DataFrame):
                        if not sel.empty:
                            row_dict = sel.iloc[0].to_dict()

                    if row_dict is not None:
                        start_pad = pd.to_datetime(row_dict.get("_start")) - pd.Timedelta(minutes=10)
                        end_pad = pd.to_datetime(row_dict.get("_end")) + pd.Timedelta(minutes=10)
                        x_range_override = (start_pad, end_pad)
                        txn_filter = str(row_dict.get("Transaction ID"))
                else:
                    # Fallback: checkbox-in-table + button
                    tbl = session_summary[[
                        "Date/Time (AKDT)", "Stop Time (AKDT)", "Location",
                        "Connector #", "Connector Type", "Max Power kW", "Energy kWh", "Duration (min)",
                        "SoC Start", "SoC End", "ID Tag",
                        "_start", "_end"
                    ]].copy()
                    tbl = tbl.sort_values("_start", ascending=False, kind="mergesort")
                    tbl.insert(0, "Zoom", False)

                    edited = st.data_editor(
                        tbl,
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "Zoom": st.column_config.CheckboxColumn(
                                "Zoom",
                                help="Check a row and press the button below to zoom the chart to that session",
                                default=False,
                            ),
                            "Date/Time (AKDT)": st.column_config.TextColumn("Date/Time (AKDT)"),
                            "Stop Time (AKDT)": st.column_config.TextColumn("Stop Time (AKDT)"),
                            "Location": st.column_config.TextColumn("Location"),
                            "Connector #": st.column_config.NumberColumn("Connector #"),
                            "Connector Type": st.column_config.TextColumn("Connector Type"),
                            "Max Power kW": st.column_config.NumberColumn("Max Power kW", format="%.2f"),
                            "Energy kWh": st.column_config.NumberColumn("Energy kWh", format="%.2f"),
                            "Duration (min)": st.column_config.NumberColumn("Duration (min)", format="%.2f"),
                            "SoC Start": st.column_config.NumberColumn("SoC Start", format="%d%%"),
                            "SoC End": st.column_config.NumberColumn("SoC End", format="%d%%"),
                            "ID Tag": st.column_config.TextColumn("ID Tag"),
                            "_start": st.column_config.DatetimeColumn("_start", disabled=True),
                            "_end": st.column_config.DatetimeColumn("_end", disabled=True),
                        },
                        disabled=["Date/Time (AKDT)", "Stop Time (AKDT)", "Location", "Connector #", "Connector Type", "Max Power kW", "Energy kWh", "Duration (min)", "SoC Start", "SoC End", "ID Tag", "_start", "_end"],
                        key="session_summary_editor",
                    )

                    # Determine single selection via checkbox (first checked wins)
                    sel_rows = (
                        edited.index[edited["Zoom"]].tolist()
                        if isinstance(edited, pd.DataFrame) and "Zoom" in edited.columns
                        else []
                    )

                    if len(sel_rows) > 1:
                        st.info("Multiple rows checked — using the first one.")
                        sel_rows = sel_rows[:1]

                    cols_zoom = st.columns([1, 3])
                    with cols_zoom[0]:
                        if st.button("🔍 Zoom to selected", key="zoom_selected"):
                            if sel_rows:
                                i = sel_rows[0]
                                row = edited.loc[i]
                                start_pad = pd.to_datetime(row["_start"], errors="coerce") - pd.Timedelta(minutes=10)
                                end_pad = pd.to_datetime(row["_end"], errors="coerce") + pd.Timedelta(minutes=10)
                                x_range_override = (start_pad, end_pad)
                                txn_filter = str(row["Transaction ID"])
                            else:
                                st.warning("Check one row first.")
                    with cols_zoom[1]:
                        with st.expander("Or pick a single session from a list"):
                            _ordered = session_summary.sort_values("_start", ascending=False, kind="mergesort")
                            sel_label_map = {
                                f"{r['Date/Time (AKDT)']} — {r['Location']} — {r['Transaction ID']}": i
                                for i, r in _ordered.iterrows()
                            }
                            sel_key = st.selectbox(
                                "Select a session to zoom",
                                options=list(sel_label_map.keys()),
                                index=0,
                            ) if sel_label_map else None

                            if sel_key and st.button("🔎 Zoom..."):
                                i = sel_label_map[sel_key]
                                row = session_summary.loc[i]
                                start_pad = pd.to_datetime(row["_start"]) - pd.Timedelta(minutes=10)
                                end_pad = pd.to_datetime(row["_end"]) + pd.Timedelta(minutes=10)
                                x_range_override = (start_pad, end_pad)
                                txn_filter = str(row["Transaction ID"])
            
            # ---------- Interactive Plot (Time Series) ----------
            plot_src = mdf.copy()
            sess_col = next((c for c in ["transaction_id", "session_id", "session"] if c in plot_src.columns), None)
            if sess_col and txn_filter:
                plot_src = plot_src[plot_src[sess_col].astype(str) == str(txn_filter)]

            # Metric mapping
            metric_map = {}

            if "soc" in plot_src.columns:
                metric_map["State of Charge %"] = ("soc", 1.0, 0)

            if "power_w" in plot_src.columns:
                metric_map["Power kW"] = ("power_w", 1 / 1000.0, 3)

            if "energy_wh" in plot_src.columns:
                metric_map["Energy kWh"] = ("energy_wh", 1 / 1000.0, 3)

            if "offered_current_a" in plot_src.columns:
                metric_map["Offered Amps"] = ("offered_current_a", 1.0, 1)

            if "requested_current_a" in plot_src.columns:
                metric_map["Requested Amps"] = ("requested_current_a", 1.0, 1)

            if "amperage_import" in plot_src.columns:
                metric_map["Amps (import)"] = ("amperage_import", 1.0, 1)

            if "hvb_volts" in plot_src.columns:
                metric_map["HVB Volts"] = ("hvb_volts", 1.0, 0)

            st.subheader("Charging Session Detail")
            st.markdown('<span class="rca-badge">sorted newest first</span>', unsafe_allow_html=True)
            if metric_map:
                # Default to ALL available metrics selected
                default_y = list(metric_map.keys())
                y_choices = st.multiselect("Y-axis fields", options=list(metric_map.keys()), default=default_y)
                if y_choices:
                    plot_df = pd.DataFrame({"Time": plot_src.get("AKDT_dt", pd.to_datetime(plot_src["AKDT"], errors="coerce"))})
                    for label in y_choices:
                        col, scale, rnd = metric_map[label]
                        plot_df[label] = (pd.to_numeric(plot_src[col], errors="coerce") * scale).round(rnd)
                    # Layout toggle
                    layout_choice = st.radio(
                        "Chart layout",
                        ["Single pane (multi-axis)", "Stacked subplots"],
                        index=0,  # default to Single pane (multi y-axis)
                        horizontal=True,
                        key="chart_layout_choice",
                    )

                    if layout_choice == "Single pane (multi-axis)":
                        # Build a multi-axis figure where each selected metric gets its own y-axis.
                        # Axes alternate sides (left/right) after the first axis and include readable tick scales.
                        fig = go.Figure()

                        # Determine counts for alternating axes
                        n_metrics = len(y_choices)
                        n_extra = max(n_metrics - 1, 0)

                        # After the first (left) axis, alternate: right, left, right, ...
                        left_indices = []
                        right_indices = []
                        for i in range(1, n_metrics):
                            if i % 2 == 1:
                                right_indices.append(i)
                            else:
                                left_indices.append(i)

                        # Geometry for axis placement (keep full-width domain, use small interior bands)
                        left_band = 0.06      # portion inside [0,1] reserved for extra LEFT axes
                        right_band = 0.06     # portion inside [0,1] reserved for extra RIGHT axes

                        left_start = left_band
                        left_end = 0.0
                        left_n = max(len(left_indices), 1)
                        left_step = (left_start - left_end) / left_n

                        right_start = 1.0 - right_band
                        right_end = 1.0
                        right_n = max(len(right_indices), 1)
                        right_step = (right_end - right_start) / right_n

                        # Keep the plot x-domain at full width; let automargins handle titles/ticks
                        domain_begin = 0.0
                        domain_end = 1.0
                        dynamic_l_margin = 40
                        dynamic_r_margin = 40

                        fig.update_layout(
                            hovermode="x unified",
                            legend_title="Metric",
                            xaxis=dict(title="Time (AKDT)", domain=[float(domain_begin), float(domain_end)], showspikes=True),
                            margin=dict(l=int(dynamic_l_margin), r=int(dynamic_r_margin)),
                        )
                        fig.update_xaxes(rangeslider_visible=True)

                        for i, label in enumerate(y_choices):
                            col, scale, rnd = metric_map[label]
                            yvals = plot_df[label]

                            if i == 0:
                                # First metric uses the default LEFT axis: trace.yaxis="y", layout key "yaxis"
                                trace_axis_name = "y"
                                layout_axis_key = "yaxis"
                                fig.add_trace(
                                    go.Scatter(
                                        x=plot_df["Time"],
                                        y=yvals,
                                        name=label,
                                        mode="lines",
                                        hovertemplate=f"{label}: %{{y:.{rnd}f}}<extra></extra>",
                                    )
                                )
                                fig.update_layout(
                                    **{
                                        layout_axis_key: dict(
                                            title=dict(text=label, font=dict(size=12)),
                                            side="left",
                                            anchor="x",
                                            zeroline=False,
                                            showgrid=True,
                                            showticklabels=True,
                                            ticks="outside",
                                            ticklen=3,
                                            tickfont=dict(size=10),
                                            ticklabelstandoff=6,
                                            automargin=True,
                                            autorange=True,
                                        )
                                    }
                                )
                            else:
                                # Subsequent metrics alternate between RIGHT and LEFT axes.
                                # For traces, the axis names are y2, y3, ...; for layout they are yaxis2, yaxis3, ...
                                idx = i + 1
                                trace_axis_name = f"y{idx}"
                                layout_axis_key = f"yaxis{idx}"

                                fig.add_trace(
                                    go.Scatter(
                                        x=plot_df["Time"],
                                        y=yvals,
                                        name=label,
                                        mode="lines",
                                        yaxis=trace_axis_name,
                                        hovertemplate=f"{label}: %{{y:.{rnd}f}}<extra></extra>",
                                    )
                                )

                                # Decide side and position
                                if i % 2 == 1:
                                    slot = right_indices.index(i)
                                    pos = right_start + slot * right_step
                                    side = "right"
                                else:
                                    slot = left_indices.index(i)
                                    pos = left_start - slot * left_step
                                    side = "left"

                                fig.update_layout(
                                    **{
                                        layout_axis_key: dict(
                                            title=dict(text=label, font=dict(size=12), standoff=6),
                                            anchor="free",
                                            overlaying="y",
                                            side=side,
                                            position=float(min(max(pos, 0.01), 0.99)),  # keep within [0,1)
                                            showgrid=False,
                                            showticklabels=True,
                                            ticks="outside",
                                            ticklen=3,
                                            tickfont=dict(size=10),
                                            nticks=5,
                                            ticklabelstandoff=6,
                                            automargin=True,
                                            zeroline=False,
                                            autorange=True,
                                        )
                                    }
                                )

                        # Respect zoom to a chosen session
                        if x_range_override is not None:
                            fig.update_xaxes(range=[pd.to_datetime(x_range_override[0]), pd.to_datetime(x_range_override[1])])

                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        # One subplot per metric with its own y-axis/title
                        rows = len(y_choices)
                        fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.05)
                        for i, label in enumerate(y_choices, start=1):
                            fig.add_trace(
                                go.Scatter(x=plot_df["Time"], y=plot_df[label], name=label, mode="lines"),
                                row=i, col=1
                            )
                            fig.update_yaxes(title_text=label, row=i, col=1)
                        fig.update_layout(hovermode="x unified", showlegend=False)
                        fig.update_xaxes(title_text="Time (AKDT)", rangeslider_visible=True, row=rows, col=1)
                        if x_range_override is not None:
                            fig.update_xaxes(range=[pd.to_datetime(x_range_override[0]), pd.to_datetime(x_range_override[1])], row=rows, col=1)
                        st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No plottable metrics available for this selection.")

            # ---------- Heatmap: Session Starts by Day/Hour ----------
            st.subheader("Session Start Density (by Day & Hour)")
            if session_summary is not None and not session_summary.empty:
                # We need the true start times and per-session duration
                starts = pd.to_datetime(session_summary["_start"], errors="coerce").dropna()
                durs = pd.to_numeric(session_summary.get("Duration (min)"), errors="coerce")

                if not starts.empty:
                    # Build base frame for day/hour
                    base = pd.DataFrame({
                        "dow": starts.dt.dayofweek,  # Monday=0 .. Sunday=6
                        "hour": starts.dt.hour,
                        "dur": durs.values if durs is not None and len(durs) == len(starts) else np.nan,
                    })

                    # Week order: Sun → Sat (pandas dayofweek is Mon=0..Sun=6)
                    day_labels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
                    order_idx = [6, 0, 1, 2, 3, 4, 5]  # reorder rows to start with Sunday

                    # --- Heatmap 1: Count per day/hour (blue) ---
                    ct1 = pd.crosstab(base["dow"], base["hour"]).reindex(range(7), fill_value=0)
                    ct1 = ct1.loc[order_idx]  # Sun-first
                    ct1 = ct1.reindex(columns=range(24), fill_value=0)
                    ct1.index = day_labels

                    z1 = ct1.values.astype(float)
                    z1_max = float(np.nanmax(z1)) if z1.size else 0.0

                    # Inline labels (blank for zeros)
                    _vals1 = ct1.values.astype("int64")
                    _text1 = np.where(_vals1 == 0, "", _vals1.astype(str))

                    fig_hm1 = go.Figure(
                        data=go.Heatmap(
                            z=z1,
                            x=list(range(24)),
                            y=list(ct1.index),
                            colorscale=[[0.0, "#ffffff"], [1.0, "#0d6efd"]],
                            zmin=0,
                            zmax=max(z1_max, 1.0),
                            colorbar=dict(title="Sessions"),
                            text=_text1,
                            texttemplate="%{text}",
                            textfont=dict(color="black", size=12),
                            hovertemplate="Day: %{y}&lt;br&gt;Hour: %{x}&lt;br&gt;Sessions: %{z:.0f}&lt;extra&gt;&lt;/extra&gt;",
                            showscale=True,
                        )
                    )
                    fig_hm1.update_traces(xgap=1, ygap=1)
                    fig_hm1.update_layout(
                        title="Session starts per hour/day",
                        xaxis=dict(title="Hour (0–23)"),
                        yaxis=dict(
                            title="Day of Week",
                            categoryorder="array",
                            categoryarray=day_labels,
                            autorange="reversed",  # Sunday at the top
                        ),
                    )
                    st.plotly_chart(fig_hm1, use_container_width=True)

                    # Two-line gap
                    st.markdown("<br><br>", unsafe_allow_html=True)

                    # --- Heatmap 2: Average duration (minutes) per day/hour (red) ---
                    grp = base.groupby(["dow", "hour"], dropna=False)["dur"].mean()
                    grid = (
                        grp.unstack(level=1)
                           .reindex(index=range(7), columns=range(24))
                    )
                    ct2 = grid.loc[order_idx].fillna(0.0)
                    ct2.index = day_labels

                    z2 = ct2.values.astype(float)
                    z2_max = float(np.nanmax(z2)) if z2.size else 0.0

                    # Inline text: one decimal when >0, blank when 0
                    _text2 = np.where(z2 <= 0.0, "", np.round(z2, 1).astype(str))

                    fig_hm2 = go.Figure(
                        data=go.Heatmap(
                            z=z2,
                            x=list(range(24)),
                            y=list(ct2.index),
                            colorscale=[[0.0, "#ffffff"], [1.0, "#dc3545"]],  # red scale
                            zmin=0,
                            zmax=max(z2_max, 1.0),
                            colorbar=dict(title="Avg minutes"),
                            text=_text2,
                            texttemplate="%{text}",
                            textfont=dict(color="black", size=12),
                            hovertemplate="Day: %{y}&lt;br&gt;Hour: %{x}&lt;br&gt;Avg duration: %{z:.1f} min&lt;extra&gt;&lt;/extra&gt;",
                            showscale=True,
                        )
                    )
                    fig_hm2.update_traces(xgap=1, ygap=1)
                    fig_hm2.update_layout(
                        title="Average session duration (minutes) by day/hour",
                        xaxis=dict(title="Hour (0–23)"),
                        yaxis=dict(
                            title="Day of Week",
                            categoryorder="array",
                            categoryarray=day_labels,
                            autorange="reversed",  # Sunday at the top
                        ),
                    )
                    st.plotly_chart(fig_hm2, use_container_width=True)

                else:
                    st.info("No session starts in the selected window.")
            else:
                st.info("No sessions in the selected window.")
            


# ============================================================================ #
# 2) Status Notifications Tab - RE-INSERTED to define status_df (AKDT + sorting)
# ============================================================================ #
with tabs[1]:
    st.header("Status History")
    st.markdown('<span class="rca-badge">sorted newest first</span>', unsafe_allow_html=True)

    avail = table_list(db_path, _db_mtime(db_path))
    status_table = (
        "realtime_status_notifications"
        if "realtime_status_notifications" in avail
        else ("status_notifications" if "status_notifications" in avail else None)
    )

    if not status_table:
        st.info("No status tables found.")
        status_df = pd.DataFrame()  # Define for downstream export
    else:
        # Pull the chosen table for the selected window
        status_df = read_range(
            db_path, status_table, start_utc_iso, end_utc_iso, None, _db_mtime(db_path)
        )

        if status_df.empty:
            st.info("No status data in this window.")
        else:
            # Normalize time columns to UTC -> AKDT helpers
            status_df = add_akdt(status_df, "timestamp")
            # Friendly EVSE name column
            status_df = add_evse_name_col(status_df, "station_id")

            # Ensure an AKDT label column for display; keep tz-aware for sort
            if "AKDT" in status_df.columns:
                status_df = status_df.rename(columns={"AKDT": "Date/Time (UTC)"})
            else:
                if "AKDT_dt" in status_df.columns:
                    try:
                        status_df["Date/Time (UTC)"] = status_df["AKDT_dt"].dt.tz_convert(AK).dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        status_df["Date/Time (UTC)"] = status_df["AKDT_dt"].dt.strftime("%Y-%m-%d %H:%M:%S")

            # Apply sidebar filters (if any)
            if 'selected_evse_ids' in locals() and selected_evse_ids:
                _set = set(str(x) for x in selected_evse_ids)
                status_df = status_df[status_df["station_id"].astype(str).isin(_set)]
            if fleet_only:
                status_df = status_df[status_df["station_id"].astype(str).isin(FLEET_IDS)]

            # Sort newest -> oldest by the true datetime
            if "AKDT_dt" in status_df.columns:
                status_df = status_df.sort_values("AKDT_dt", ascending=False, kind="mergesort")
            else:
                # Fallback: build AKDT_dt from timestamp
                ts = pd.to_datetime(
                    status_df["timestamp"].astype(str).str.replace("Z", "+00:00", regex=False),
                    utc=True,
                    errors="coerce",
                ).dt.tz_convert(AK)
                status_df = status_df.assign(AKDT_dt=ts).sort_values("AKDT_dt", ascending=False, kind="mergesort")

            # --- Tritium code enrichment (Impact/Description) BEFORE rendering ---
            try:
                codes_df = get_error_codes_df(db_path, _db_mtime(db_path))
                sdf = status_df.copy()
                # Platform by site; unknown sites won't join
                sdf["Platform"] = sdf["EVSE"].map(PLATFORM_MAP).fillna("") if "EVSE" in sdf.columns else ""
                # Normalize vendor code to digits-only string for joining
                if "vendor_error_code" in sdf.columns:
                    v = sdf["vendor_error_code"].astype(str)
                    sdf["code_key"] = v.str.extract(r"(\d+)", expand=False).fillna("")
                else:
                    sdf["code_key"] = ""
                if not codes_df.empty:
                    rename_map = {"code": "code_key", "platform": "Platform"}
                    codes_norm = codes_df.rename(columns={k: v for k, v in rename_map.items() if k in codes_df.columns}).copy()
                    need = ["Platform", "code_key", "impact", "description"]
                    keep = [c for c in need if c in codes_norm.columns]
                    enriched = sdf.merge(codes_norm[keep], on=["Platform", "code_key"], how="left")
                else:
                    enriched = sdf
                # Keep enriched for display/export; maintain UTC label we chose above
                status_df = enriched.rename(columns={"AKDT": "Date/Time (UTC)"})
            except Exception:
                # If enrichment fails for any reason, keep the base frame
                status_df = status_df

            # Pick columns to show (only those that exist) — include Impact/Description
            display_cols_pref = [
                "Date/Time (UTC)", "EVSE", "station_id", "connector_id",
                "status", "error_code", "vendor_error_code", "info", "vendor_id",
                "impact", "description",
            ]
            display_cols = [c for c in display_cols_pref if c in status_df.columns]

            # Render table
            try:
                if AGGRID_AVAILABLE:
                    gob = GridOptionsBuilder.from_dataframe(status_df[display_cols])
                    gob.configure_default_column(filter=True, sortable=True, resizable=True, flex=1, minWidth=110)
                    gob.configure_column("Date/Time (UTC)", sort="desc")
                    AgGrid(status_df[display_cols], gridOptions=gob.build(), fit_columns_on_grid_load=True, height=320)
                else:
                    st.dataframe(status_df[display_cols], use_container_width=True)
            except Exception:
                st.dataframe(status_df[display_cols], use_container_width=True)

# ============================================================================ #
# 4) Connectivity Tab (WebSocket CONNECT/DISCONNECT)
# ============================================================================ #
with tabs[2]:
    st.header("Connectivity")
    st.markdown('<span class="rca-badge">sorted newest first</span>', unsafe_allow_html=True)

    # Load events defensively
    conn_df = load_connectivity_events(db_path, start_utc_iso, end_utc_iso, _db_mtime(db_path))
    if conn_df.empty:
        st.info("No websocket CONNECT/DISCONNECT events found in this window.")
        connectivity_view = pd.DataFrame()
    else:
        # EVSE + time columns, then filter
        conn_df = ensure_evse_and_time(conn_df)
        if 'evse_ids_set' in locals() and len(evse_ids_set) > 0:
            conn_df = conn_df[conn_df["station_id"].astype(str).isin(evse_ids_set)]
        if fleet_only:
            conn_df = conn_df[conn_df["station_id"].astype(str).isin(FLEET_IDS)]

        if conn_df.empty:
            st.info("No websocket events after filters.")
            connectivity_view = pd.DataFrame()
        else:
            # Compute duration: for each CONNECT, time since previous DISCONNECT for same EVSE
            # Example sequence (newest at top in UI, but we compute on ASC time):
            # ... DISCONNECT @ t0, CONNECT @ t1  => duration = t1 - t0 (minutes) on the CONNECT row
            # If sequence has CONNECT followed by CONNECT (no prior DISCONNECT), duration = NaN
            conn_df = conn_df.sort_values(["station_id", "ts_utc"], kind="mergesort")

            def _duration_since_prev_disconnect(group: pd.DataFrame) -> pd.Series:
                g = group.copy()
                ts = g["ts_utc"]
                evt = g["Connectivity"].astype(str).str.upper()
                prev_ts = ts.shift(1)
                prev_evt = evt.shift(1)
                dur_min = np.where(
                    evt.str.contains("CONNECT") & prev_evt.str.contains("DISCONNECT"),
                    (ts - prev_ts).dt.total_seconds() / 60.0,
                    np.nan,
                )
                return pd.Series(dur_min, index=g.index, dtype="float")

            conn_df["Duration_min"] = conn_df.groupby("station_id", group_keys=False).apply(_duration_since_prev_disconnect)

            # Build display frame
            try:
                display_dt = conn_df["AKDT_dt"].dt.tz_convert(AK).dt.strftime("%-m/%-d/%y %H:%M:%S")
            except Exception:
                display_dt = conn_df["AKDT_dt"].dt.tz_convert(AK).dt.strftime("%m/%d/%y %H:%M:%S")

            connectivity_view = pd.DataFrame({
                "Date/Time (AKDT)": display_dt,
                "EVSE": conn_df["EVSE"],
                "Connectivity": conn_df["Connectivity"],
                "Duration": conn_df["Duration_min"].round(2),
                "_akdt_dt": conn_df["AKDT_dt"],
            }).sort_values("_akdt_dt", ascending=False, kind="mergesort")
            # Render
            st.dataframe(connectivity_view.drop(columns=["_akdt_dt"], errors="ignore"), use_container_width=True)

# ============================================================================ #
# 5) Data Export Tab - CORRECTED BLOCK (Fixing NameErrors and Excel Date Format)
# ============================================================================ #
with tabs[3]:
    st.header("Data Export")
    auth_df_display = st.session_state.get("auth_df_display", pd.DataFrame())
    # Use the latest summary prepared in the Sessions tab to avoid stale exports
    exp_summary = st.session_state.get("export_session_summary")
    if exp_summary is None or (isinstance(exp_summary, pd.DataFrame) and exp_summary.empty):
        st.info("No prepared session summary found. Visit the 'Charging Sessions' tab once for this window, then return here to export.")
        st.stop()
    # Work on a copy so we don't mutate session state
    session_summary = exp_summary.copy()
    _exp_ctx = st.session_state.get("export_context", {})
    if _exp_ctx:
        st.caption(f"Export window: {_exp_ctx.get('start','')} → {_exp_ctx.get('end','')} | mtime={_exp_ctx.get('db_mtime','')}")
    # Mirror EVSE selection in export (informational)
    if 'evse_picks' in locals() and evse_picks:
        st.markdown(f"_Export limited to:_ **{', '.join(evse_picks)}**")
    else:
        st.markdown("_Export includes **all EVSEs** in the selected time window._")
    st.write("Export all available data from the current time range (Main Data, Summary, Status, Auth)")

    # --- DataFrames for Export ---
    
    # 1. Prepare Main Data (df)
    df_main_export = strip_tz_for_excel(df.copy())
    
    # 2. Prepare Summary Data (session_summary)
    # Use the native datetime columns (_start, _end) and rename them for the sheet
    # Build the Summary export from the prepared session_summary (already newest→oldest upstream),
    # then re-enforce sorting here in case the user changed the view.
    _df_sum = session_summary.copy()

    # Hard sort by the real datetime so newest is on top in the sheet
    if "_start" in _df_sum.columns:
        _df_sum = _df_sum.sort_values("_start", ascending=False, kind="mergesort")

    # Construct the export frame (defensive: some cols may not exist)
    desired_cols = [
        "Date/Time (AKDT)", "Stop Time (AKDT)", "Location", "Transaction ID",
        "Connector #", "Connector Type", "Max Power kW", "Energy kWh", "Duration (min)",
        "SoC Start", "SoC End", "ID Tag", "_start", "_end",
    ]
    present_cols = [c for c in desired_cols if c in _df_sum.columns]
    df_summary_export = _df_sum[present_cols].copy()

    # Force Anchorage local time for the two display columns regardless of source tz
    if "_start" in df_summary_export.columns:
        df_summary_export["Date/Time (AKDT)"] = to_ak_naive(df_summary_export["_start"])
    if "_end" in df_summary_export.columns:
        df_summary_export["Stop Time (AKDT)"] = to_ak_naive(df_summary_export["_end"])

    # Strip tz info from any leftover tz-aware columns
    df_summary_export = strip_tz_for_excel(df_summary_export)

    # Final column order for Excel (and drop the helper columns)
    _df_cols_final = [
        "Date/Time (AKDT)", "Stop Time (AKDT)", "Location", "Transaction ID",
        "Connector #", "Connector Type", "Max Power kW", "Energy kWh", "Duration (min)",
        "SoC Start", "SoC End", "ID Tag",
    ]
    # keep only the ones that were actually present
    df_summary_export = df_summary_export[[c for c in _df_cols_final if c in df_summary_export.columns]]

    # 3. Prepare Status Data (status_df)
    df_status_export = status_df.copy()
    # Remove duplicated column names to avoid pandas indexing errors during assignment
    if not df_status_export.empty:
        # If a previous string-formatted column exists, drop it safely
        if "Date/Time (AKDT)" in df_status_export.columns:
            # also collapse duplicate names, if any
            df_status_export = df_status_export.loc[:, ~df_status_export.columns.duplicated()]
            df_status_export = df_status_export.drop(columns=["Date/Time (AKDT)"], errors="ignore")
        # Prefer native datetime for Excel; keep tz for now and strip later
        if "AKDT_dt" in df_status_export.columns:
            df_status_export["Date/Time (AKDT)"] = df_status_export["AKDT_dt"]
        # Strip timezone info for Excel export compatibility
        df_status_export = strip_tz_for_excel(df_status_export)
    
    # 4. Prepare Auth Data 
    df_auth_export = pd.DataFrame()
    if not auth_df_display.empty:
        df_auth_export = strip_tz_for_excel(auth_df_display.copy())
    
    # 5. Prepare Connectivity Data
    df_conn_export = pd.DataFrame()
    try:
        if 'connectivity_view' in locals() and isinstance(connectivity_view, pd.DataFrame) and not connectivity_view.empty:
            tmp = connectivity_view.copy()
            if "_akdt_dt" in tmp.columns:
                tmp["Date/Time (AKDT)"] = to_ak_naive(tmp["_akdt_dt"])
            df_conn_export = tmp[["Date/Time (AKDT)", "EVSE", "Connectivity", "Duration"]].copy()
    except Exception:
        df_conn_export = pd.DataFrame()

    # --- Write to Excel ---
    excel_buf = BytesIO()
    with pd.ExcelWriter(excel_buf, engine=EXCEL_ENGINE) as writer:
        # --- Write Summary FIRST ---
        df_summary_export.to_excel(
            writer,
            sheet_name="Summary",
            index=False,
            columns=[c for c in df_summary_export.columns if not c.startswith("_")]
        )
        # Then Main Data
        df_main_export.to_excel(writer, sheet_name="Main Data", index=False)
        # Build Status export with selected/renamed columns
        status_selected = pd.DataFrame()
        if not df_status_export.empty:
            # Ensure a native datetime for Date/Time (AKDT)
            if "AKDT_dt" in df_status_export.columns:
                df_status_export["Date/Time (AKDT)"] = df_status_export["AKDT_dt"]
            status_cols = [
                ("Date/Time (AKDT)", "Date/Time (AKDT)"),
                ("EVSE", "EVSE"),
                ("status", "Status"),
                ("error_code", "Error_Code"),
                ("vendor_error_code", "Vendor Error Code"),
                ("connector_id", "Connector_id"),
                ("id", "ID"),
                ("impact", "Impact"),
                ("description", "Description"),
            ]
            keep_cols = [c for c, _ in status_cols if c in df_status_export.columns]
            status_selected = df_status_export[keep_cols].rename(columns=dict(status_cols))
            status_selected = strip_tz_for_excel(status_selected)
            status_selected.to_excel(writer, sheet_name="Status", index=False)
        # Auth (optional)
        if not df_auth_export.empty:
            df_auth_export.to_excel(writer, sheet_name="Auth", index=False)

        # Connectivity (optional)
        if not df_conn_export.empty:
            df_conn_export.to_excel(writer, sheet_name="Connectivity", index=False)

        # --- Formatting (xlsxwriter only) ---
        try:
            if EXCEL_ENGINE == "xlsxwriter":
                workbook = writer.book
                date_fmt = workbook.add_format({"num_format": "m/d/yy hh:mm:ss"})
                # Summary A, B are datetimes
                if "Summary" in writer.sheets:
                    ws = writer.sheets["Summary"]
                    ws.set_column("A:A", 20, date_fmt)
                    ws.set_column("B:B", 20, date_fmt)
                    num2_fmt = workbook.add_format({"num_format": "0.00"})
                    # Start SoC (I) and End SoC (J) as numeric with 2 decimals
                    ws.set_column("I:J", 12, num2_fmt)
                # Status A is datetime
                if "Status" in writer.sheets:
                    ws = writer.sheets["Status"]
                    ws.set_column("A:A", 20, date_fmt)
                # Connectivity A is datetime; Duration (D) uses 2 decimals
                if "Connectivity" in writer.sheets:
                    ws = writer.sheets["Connectivity"]
                    ws.set_column("A:A", 20, date_fmt)
                    num2_fmt = workbook.add_format({"num_format": "0.00"})
                    ws.set_column("D:D", 12, num2_fmt)
        except Exception:
            pass

    # ---- Download button for Excel export ----
    excel_buf.seek(0)
    excel_bytes = excel_buf.getvalue()
    export_fname = f"RCA_export_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.xlsx"

    st.download_button(
        label="Export all (xlsx)",
        data=excel_bytes,
        file_name=export_fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=False,
        key=f"export_all_xlsx_{abs(hash((start_utc_iso, end_utc_iso, evse_id or '(all)', bool(fleet_only)))) % 10**8}",
    )