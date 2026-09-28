"""RTH hourly scheduler for Alpaca paper consensus (Windows-friendly).

Runs America/New_York ticks at :00 for hours 10–15 on NYSE trading days.
Designed to stay alive on a Windows box (Task Scheduler → this process, or
per-hour scheduled tasks calling --once).

Secrets: load from environment, or a local env file outside the Project store
(default candidate: %USERPROFILE%\\.daytrade\\alpaca.env). Never writes keys
into the store.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hour_bucket import as_of_iso, is_rth_consensus_hour
from paths import SCRIPTS, STATE, STORE_ROOT, hourly_dir
from trading_calendar import is_trading_day, next_trading_day

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

ET_NAME = "America/New_York"
RTH_HOURS = (10, 11, 12, 13, 14, 15)
DEFAULT_ENV_CANDIDATES = [
    Path(os.environ.get("DAYTRADE_ENV_FILE", "")),
    Path.home() / ".daytrade" / "alpaca.env",
    Path.home() / "daytrade" / "alpaca.env",
]


def et_tz():
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo unavailable; use Python 3.9+ (and pip install tzdata on Windows)")
    try:
        return ZoneInfo(ET_NAME)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Cannot load {ET_NAME}. On Windows: pip install tzdata. Underlying: {e}"
        ) from e


def now_et() -> datetime:
    return datetime.now(tz=et_tz())


def load_dotenv(path: Path) -> Dict[str, str]:
    """Minimal KEY=VALUE loader (no export into os until applied)."""
    out: Dict[str, str] = {}
    if not path or not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip("'").strip('"')
        if k:
            out[k] = v
    return out


def apply_env_file(path: Optional[Path] = None) -> Optional[Path]:
    candidates = [path] if path else DEFAULT_ENV_CANDIDATES
    for p in candidates:
        if not p or str(p) in ("", "."):
            continue
        # Refuse loading env files from inside the Project store (secrets policy)
        try:
            p.resolve().relative_to(STORE_ROOT.resolve())
            print(f"refusing env file inside Project store: {p}", file=sys.stderr)
            continue
        except ValueError:
            pass
        loaded = load_dotenv(p)
        if not loaded:
            continue
        for k, v in loaded.items():
            if k.startswith("APCA_") or k.startswith("DAYTRADE_"):
                os.environ.setdefault(k, v)
        return p
    return None


def next_rth_tick(after: Optional[datetime] = None) -> Tuple[date, int, datetime]:
    """Next consensus tick (day, hour_et, aware datetime at :00 ET)."""
    tz = et_tz()
    cur = (after or now_et()).astimezone(tz)
    # Start search at current ET calendar day
    d = cur.date()
    for _ in range(20):  # enough to clear long weekends
        if is_trading_day(d):
            for h in RTH_HOURS:
                tick = datetime(d.year, d.month, d.day, h, 0, 0, tzinfo=tz)
                if tick > cur:
                    return d, h, tick
        d = next_trading_day(d)
    raise RuntimeError("could not find next RTH tick")


def bucket_for(day: date, hour: int) -> str:
    return f"{day.isoformat()}T{hour:02d}"


def run_tick(
    day: date,
    hour: int,
    *,
    phase: str,
    submit: bool,
    continue_on_ingest_error: bool,
    python: str,
    extra_args: Optional[List[str]] = None,
) -> int:
    bucket = bucket_for(day, hour)
    cmd = [
        python,
        str(SCRIPTS / "run_hourly.py"),
        "--hour",
        bucket,
        "--phase",
        phase,
        "--reconcile",
    ]
    if submit:
        cmd.append("--submit")
    else:
        cmd.append("--dry-run")
    if continue_on_ingest_error:
        cmd.append("--continue-on-ingest-error")
    if extra_args:
        cmd.extend(extra_args)
    print(f"[scheduler] running: {' '.join(cmd)}", flush=True)
    env = os.environ.copy()
    # Ensure scripts/ is importable when invoked as subprocess cwd
    proc = subprocess.run(cmd, cwd=str(SCRIPTS), env=env)
    return int(proc.returncode)


def proposals_ready(day: date, hour: int) -> bool:
    d = hourly_dir(day.isoformat(), hour)
    return all((d / f"{a}.json").exists() for a in ("A1", "A2", "A3", "A4", "A5"))


def write_scheduler_status(payload: Dict[str, Any]) -> Path:
    path = STATE / "scheduler" / "status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def sleep_until(target: datetime, *, wake_every_sec: int = 30) -> None:
    """Sleep until target, waking periodically so the process stays responsive."""
    while True:
        now = now_et()
        remaining = (target - now).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(wake_every_sec, max(1.0, remaining)))


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="DayTrade RTH hourly scheduler (Windows-ready)")
    p.add_argument("--once", action="store_true", help="Run the next due tick (or --hour) and exit")
    p.add_argument("--hour", help="Force a specific bucket YYYY-MM-DDTHH (implies --once)")
    p.add_argument(
        "--phase",
        choices=["prep", "settle", "full", "prep-then-settle"],
        default="prep-then-settle",
        help="prep=packs only; settle=consensus; full=one-shot; prep-then-settle=prep, wait, settle",
    )
    p.add_argument(
        "--proposal-wait-minutes",
        type=int,
        default=20,
        help="For prep-then-settle: minutes to wait for A1–A5.json before settle (0=skip wait)",
    )
    p.add_argument("--submit", action="store_true", help="Pass --submit on settle/full (default dry-run)")
    p.add_argument("--continue-on-ingest-error", action="store_true")
    p.add_argument("--env-file", type=Path, help="Path to alpaca.env OUTSIDE the Project store")
    p.add_argument("--python", default=sys.executable, help="Python executable for child ticks")
    p.add_argument("--catch-up", action="store_true", help="If started mid-hour in RTH, run current hour once")
    args = p.parse_args(argv)

    used_env = apply_env_file(args.env_file)
    if used_env:
        print(f"[scheduler] loaded env from {used_env}", flush=True)
    else:
        print("[scheduler] no external env file loaded (using process environment)", flush=True)

    if not os.environ.get("APCA_API_KEY_ID"):
        print(
            "[scheduler] warning: APCA_API_KEY_ID unset — reconcile/submit will fail until set",
            file=sys.stderr,
            flush=True,
        )

    force_once = bool(args.once or args.hour)

    def do_phases(day: date, hour: int) -> int:
        phase = args.phase
        status = {
            "bucket": bucket_for(day, hour),
            "as_of": as_of_iso(day, hour),
            "phase_mode": phase,
            "started_at": now_et().isoformat(),
            "submit": bool(args.submit),
        }
        write_scheduler_status(status)

        if phase == "prep-then-settle":
            rc = run_tick(
                day,
                hour,
                phase="prep",
                submit=False,
                continue_on_ingest_error=args.continue_on_ingest_error,
                python=args.python,
            )
            status["prep_rc"] = rc
            write_scheduler_status(status)
            if rc != 0:
                return rc
            deadline = now_et() + timedelta(minutes=max(0, args.proposal_wait_minutes))
            while args.proposal_wait_minutes > 0 and now_et() < deadline:
                if proposals_ready(day, hour):
                    break
                status["waiting_for_proposals"] = True
                status["deadline"] = deadline.isoformat()
                write_scheduler_status(status)
                time.sleep(15)
            if not proposals_ready(day, hour):
                status["settle_skipped"] = "proposals_missing"
                status["finished_at"] = now_et().isoformat()
                write_scheduler_status(status)
                print("[scheduler] settle skipped — proposals not ready", flush=True)
                return 0
            rc2 = run_tick(
                day,
                hour,
                phase="settle",
                submit=args.submit,
                continue_on_ingest_error=args.continue_on_ingest_error,
                python=args.python,
            )
            status["settle_rc"] = rc2
            status["finished_at"] = now_et().isoformat()
            write_scheduler_status(status)
            return rc2

        rc = run_tick(
            day,
            hour,
            phase=phase,
            submit=args.submit and phase in ("settle", "full"),
            continue_on_ingest_error=args.continue_on_ingest_error,
            python=args.python,
        )
        status["rc"] = rc
        status["finished_at"] = now_et().isoformat()
        write_scheduler_status(status)
        return rc

    if args.hour:
        from hour_bucket import parse_hour_bucket

        day, hour, _ = parse_hour_bucket(args.hour)
        if not is_rth_consensus_hour(day, hour):
            print(f"[scheduler] warning: {args.hour} outside RTH consensus hours", flush=True)
        return do_phases(day, hour)

    if args.catch_up:
        n = now_et()
        if is_trading_day(n.date()) and n.hour in RTH_HOURS and n.minute < 55:
            print(f"[scheduler] catch-up current hour {n.hour}", flush=True)
            rc = do_phases(n.date(), n.hour)
            if force_once:
                return rc

    if force_once:
        day, hour, tick = next_rth_tick()
        # --once without --hour: if we're past a tick that just started (<2 min), run it;
        # else wait for next? For Task Scheduler firing at :00, run "this hour" if on the hour.
        n = now_et()
        if is_trading_day(n.date()) and n.hour in RTH_HOURS and n.minute <= 2:
            day, hour = n.date(), n.hour
            print(f"[scheduler] --once on-the-hour → {bucket_for(day, hour)}", flush=True)
            return do_phases(day, hour)
        print(f"[scheduler] --once waiting for {tick.isoformat()} …", flush=True)
        sleep_until(tick)
        return do_phases(day, hour)

    # Long-running loop
    print("[scheduler] loop started (Ctrl+C to stop)", flush=True)
    while True:
        day, hour, tick = next_rth_tick()
        write_scheduler_status(
            {
                "next_tick": tick.isoformat(),
                "bucket": bucket_for(day, hour),
                "mode": "loop",
                "updated_at": now_et().isoformat(),
            }
        )
        print(f"[scheduler] next tick {tick.isoformat()} ({bucket_for(day, hour)})", flush=True)
        sleep_until(tick)
        # small pad so clock is firmly on the hour
        time.sleep(1)
        try:
            do_phases(day, hour)
        except Exception as e:  # noqa: BLE001
            print(f"[scheduler] tick error: {e}", file=sys.stderr, flush=True)
            write_scheduler_status(
                {
                    "error": str(e),
                    "bucket": bucket_for(day, hour),
                    "at": now_et().isoformat(),
                }
            )
        # advance past this tick
        time.sleep(2)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[scheduler] stopped", flush=True)
        raise SystemExit(130)
