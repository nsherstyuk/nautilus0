from __future__ import annotations

import json
import sys
import time
import uuid
import asyncio
import atexit
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st
try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from live.dashboard_ipc import append_jsonl, utc_now_iso


def _ensure_event_loop() -> None:
    try:
        asyncio.get_running_loop()
        return
    except RuntimeError:
        pass

    try:
        asyncio.get_event_loop()
        return
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)


def _disconnect_dashboard_ib() -> None:
    try:
        ib = st.session_state.get("ib")
        if ib is not None:
            try:
                ib.disconnect()
            except Exception:
                pass
        st.session_state.pop("ib", None)
    except Exception:
        pass


def _register_exit_cleanup() -> None:
    if st.session_state.get("ib_cleanup_registered"):
        return
    try:
        atexit.register(_disconnect_dashboard_ib)
        st.session_state.ib_cleanup_registered = True
    except Exception:
        pass


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _tail_jsonl(path: Path, max_lines: int = 50) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    # Read only the last ~64KB for safety (good enough for recent commands/acks)
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            read_size = min(size, 65536)
            f.seek(size - read_size)
            data = f.read(read_size).decode("utf-8", errors="ignore")
    except Exception:
        return []

    lines = [ln.strip() for ln in data.splitlines() if ln.strip()]
    lines = lines[-max_lines:]

    out: List[Dict[str, Any]] = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out


def _status_age_seconds(status: Dict[str, Any]) -> Optional[float]:
    try:
        ts = status.get("ts_wall_utc")
        if not ts:
            return None
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return None


def _send_command(ipc_dir: Path, command: str, source: str = "dashboard", notes: str = "") -> str:
    cmd_id = str(uuid.uuid4())
    append_jsonl(
        ipc_dir / "commands.jsonl",
        {
            "cmd_id": cmd_id,
            "ts_wall_utc": utc_now_iso(),
            "command": command,
            "source": source,
            "notes": notes,
        },
    )
    return cmd_id


def _get_ib_connection_params() -> Dict[str, Any]:
    # Best-effort: reuse your existing config loader if available.
    try:
        host_override = str(st.session_state.get("ib_host_override") or "").strip()
        port_override = str(st.session_state.get("ib_port_override") or "").strip()
        client_id_override = str(st.session_state.get("ib_client_id_override") or "").strip()
        account_override = str(st.session_state.get("ib_account_override") or "").strip()

        if host_override and port_override and client_id_override:
            return {
                "host": host_override,
                "port": int(port_override),
                "client_id": int(client_id_override),
                "account": account_override,
            }
    except Exception:
        pass

    try:
        from config.mtf_v2_config import load_mtf_v2_config

        cfg = load_mtf_v2_config()
        return {
            "host": cfg.ib_host,
            "port": int(cfg.ib_port),
            "client_id": int(cfg.ib_client_id) + 50,
            "account": str(cfg.ib_account),
        }
    except Exception:
        return {
            "host": "127.0.0.1",
            "port": 7497,
            "client_id": 999,
            "account": "",
        }


def _get_ib() -> Optional[Any]:
    try:
        _register_exit_cleanup()
        _ensure_event_loop()
        from ib_insync import IB

        if "ib_last_error" not in st.session_state:
            st.session_state.ib_last_error = ""

        if "ib" not in st.session_state:
            st.session_state.ib = IB()
            st.session_state.ib_last_connect_attempt = 0.0

        ib = st.session_state.ib
        params = _get_ib_connection_params()

        # Avoid reconnecting too aggressively
        now = time.time()
        if not ib.isConnected() and now - float(st.session_state.ib_last_connect_attempt) > 5.0:
            st.session_state.ib_last_connect_attempt = now
            try:
                ib.connect(params["host"], params["port"], clientId=params["client_id"], timeout=2)
                st.session_state.ib_last_error = ""
            except Exception as e:
                try:
                    st.session_state.ib_last_error = f"{type(e).__name__}: {e}"
                except Exception:
                    pass

        return ib
    except Exception as e:
        try:
            st.session_state.ib_last_error = f"ib_insync error: {type(e).__name__}: {e}"
        except Exception:
            pass
        return None


def _ib_account_panel() -> None:
    st.subheader("IBKR Account")

    ib = _get_ib()
    params = _get_ib_connection_params()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("IB Connected", "YES" if (ib and ib.isConnected()) else "NO")
    with col2:
        st.write(f"Host: `{params['host']}:{params['port']}`")
    with col3:
        st.write(f"Client ID: `{params['client_id']}`")
    with col4:
        st.write(f"Account: `{params['account']}`" if params["account"] else "Account: (unknown)")

    if not ib or not ib.isConnected():
        last_err = ""
        try:
            last_err = str(st.session_state.get("ib_last_error") or "")
        except Exception:
            last_err = ""

        st.info("IBKR not connected (dashboard side). This does not affect the live runner if it is connected.")
        if last_err:
            st.warning(f"IBKR connect error: `{last_err}`")
        return

    try:
        rows = ib.accountSummary()
        summary = {r.tag: r.value for r in rows}

        colA, colB, colC, colD = st.columns(4)
        with colA:
            st.metric("NetLiquidation", summary.get("NetLiquidation", ""))
        with colB:
            st.metric("AvailableFunds", summary.get("AvailableFunds", ""))
        with colC:
            st.metric("UnrealizedPnL", summary.get("UnrealizedPnL", ""))
        with colD:
            st.metric("RealizedPnL", summary.get("RealizedPnL", ""))
    except Exception:
        st.warning("Failed to read IBKR account summary")

    try:
        positions = ib.positions()
        if positions:
            data = []
            for p in positions:
                data.append(
                    {
                        "symbol": getattr(p.contract, "localSymbol", "") or getattr(p.contract, "symbol", ""),
                        "secType": getattr(p.contract, "secType", ""),
                        "currency": getattr(p.contract, "currency", ""),
                        "position": float(getattr(p, "position", 0.0)),
                        "avgCost": float(getattr(p, "avgCost", 0.0)),
                    }
                )
            st.dataframe(pd.DataFrame(data), use_container_width=True)
        else:
            st.write("No positions")
    except Exception:
        st.warning("Failed to read IBKR positions")


def main() -> None:
    st.set_page_config(page_title="MTF V2 Live Dashboard", layout="wide")

    if st_autorefresh is not None:
        st_autorefresh(interval=1000, key="refresh")
    else:
        st.caption("Auto-refresh disabled: install streamlit-autorefresh to enable.")

    st.title("MTF V2 Live Dashboard")

    params_preview = _get_ib_connection_params()
    with st.sidebar.expander("IBKR (dashboard) connection", expanded=False):
        st.text_input("Host", value=str(params_preview.get("host", "")), key="ib_host_override")
        st.text_input("Port", value=str(params_preview.get("port", "")), key="ib_port_override")
        st.text_input("Client ID", value=str(params_preview.get("client_id", "")), key="ib_client_id_override")
        st.text_input("Account (optional)", value=str(params_preview.get("account", "")), key="ib_account_override")

        if st.button("Force reconnect", use_container_width=True):
            try:
                if "ib" in st.session_state:
                    try:
                        st.session_state.ib.disconnect()
                    except Exception:
                        pass
                st.session_state.pop("ib", None)
                st.session_state.ib_last_connect_attempt = 0.0
                st.session_state.ib_last_error = ""
            except Exception:
                pass

        if st.button("Disconnect IB", use_container_width=True):
            _disconnect_dashboard_ib()

    ipc_dir = Path("logs/live_mtf")
    status_path = ipc_dir / "status.json"

    status = _read_json(status_path) or {}
    age_sec = _status_age_seconds(status)

    top = st.container()
    with top:
        c1, c2, c3, c4, c5 = st.columns(5)

        run_id = status.get("run_id", "")
        paused = bool(status.get("paused", False))
        ib_connected = bool(status.get("connection", {}).get("ib_connected", False))
        bar_age = status.get("connection", {}).get("bar_age_sec", None)

        with c1:
            st.metric("Runner Run ID", run_id or "-")
        with c2:
            st.metric("Runner IB", "CONNECTED" if ib_connected else "DISCONNECTED")
        with c3:
            st.metric("Paused", "YES" if paused else "NO")
        with c4:
            st.metric("Bar Age (sec)", f"{bar_age:.1f}" if isinstance(bar_age, (int, float)) else "-")
        with c5:
            st.metric("Status Age (sec)", f"{age_sec:.1f}" if isinstance(age_sec, (int, float)) else "-")

        if age_sec is None:
            st.warning("No status yet. Start the dashboard-enabled live runner first.")
        elif age_sec > 10:
            st.error("Status is stale. The live runner may be stopped or blocked.")
        else:
            st.success("Status is fresh")

    st.divider()

    # Controls
    st.subheader("Controls")
    b1, b2, b3, b4 = st.columns(4)

    with b1:
        if st.button("PAUSE", use_container_width=True):
            _send_command(ipc_dir, "PAUSE")
    with b2:
        if st.button("RESUME", use_container_width=True):
            _send_command(ipc_dir, "RESUME")
    with b3:
        if st.button("CANCEL ALL", use_container_width=True):
            _send_command(ipc_dir, "CANCEL_ALL")
    with b4:
        if st.button("FLATTEN", use_container_width=True):
            _send_command(ipc_dir, "FLATTEN")

    st.caption("Note: Commands are executed by the live runner (not by this dashboard process).")

    # Strategy panel
    st.divider()
    st.subheader("Strategy")

    strat = status.get("strategy", {})
    last_pred = strat.get("last_prediction", {}) if isinstance(strat, dict) else {}

    colA, colB, colC, colD = st.columns(4)
    with colA:
        st.write(f"Symbol: `{strat.get('symbol', '-')}`")
        st.write(f"Bar Type: `{strat.get('bar_type', '-')}`")
    with colB:
        st.write(f"Warmup Complete: `{strat.get('warmup_complete', False)}`")
        st.write(f"15m Buffer: `{strat.get('buffer_15m_len', '-')}`")
    with colC:
        st.write(f"30m Buffer: `{strat.get('buffer_30m_len', '-')}`")
        st.write(f"Last Bar (UTC): `{strat.get('last_bar_time_utc', '-')}`")
    with colD:
        st.write(f"Pred: `{last_pred.get('pred', '-')}`")
        st.write(f"Conf: `{last_pred.get('confidence', '-')}`")
        st.write(f"Thresh: `{last_pred.get('threshold', '-')}`")

    st.write(f"Last Decision: `{strat.get('last_decision_reason', '')}`")

    # Logs / events
    st.divider()
    st.subheader("Events + Command Acks")

    left, right = st.columns(2)

    with left:
        st.write("Recent Events")
        events = _tail_jsonl(ipc_dir / "events.jsonl", max_lines=50)
        if events:
            st.dataframe(pd.DataFrame(events).tail(50), use_container_width=True)
        else:
            st.write("No events")

    with right:
        st.write("Recent Command Acks")
        acks = _tail_jsonl(ipc_dir / "command_acks.jsonl", max_lines=50)
        if acks:
            df = pd.DataFrame(acks).tail(50)
            st.dataframe(df, use_container_width=True)
        else:
            st.write("No acks")

    st.divider()
    _ib_account_panel()


if __name__ == "__main__":
    main()
