"""RTH half-hour scheduler for Alpaca paper consensus (Windows-friendly).

Runs America/New_York ticks every 30 minutes from 09:30–15:30 on NYSE days.
Designed to stay alive on a Windows box (Task Scheduler → this process).

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

from hour_bucket import (
    RTH_TICKS,
    as_of_iso,
    bucket_for,
    is_rth_consensus_tick,
    next_rth_tick as hb_next_rth_tick,
    parse_hour_bucket,
    slot_key,
)
from paths import SCRIPTS, STATE, STORE_ROOT, hourly_dir
from trading_calendar import is_trading_day

try:
    from discord_notify import notify as discord_notify
except Exception:  # noqa: BLE001
    def discord_notify(*_a: Any, **_k: Any) -> bool:  # type: ignore[misc]
        return False

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

ET_NAME = "America/New_York"
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


def next_rth_tick(after: Optional[datetime] = None) -> Tuple[date, int, int, datetime, str, str]:
    """Next consensus tick (day, hour, minute, when_et, bucket, slot)."""
    return hb_next_rth_tick(after)


def run_tick(
    day: date,
    hour: int,
    minute: int = 0,
    *,
    phase: str,
    submit: bool,
    continue_on_ingest_error: bool,
    python: str,
    extra_args: Optional[List[str]] = None,
) -> int:
    bucket = bucket_for(day, hour, minute)
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
    proc = subprocess.run(cmd, cwd=str(SCRIPTS), env=env)
    return int(proc.returncode)


def proposals_ready(day: date, hour: int, minute: int = 0) -> bool:
    from paths import active_agent_ids

    d = hourly_dir(day.isoformat(), slot_key(hour, minute))
    aids = active_agent_ids()
    if not aids:
        return False
    return all((d / f"{a}.json").exists() for a in aids)


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
        help="For prep-then-settle: minutes to wait for A1.json before settle (0=skip wait; default 20)",
    )
    p.add_argument(
        "--submit",
        action="store_true",
        default=True,
        help="Pass --submit on settle/full (default ON for paper account)",
    )
    p.add_argument(
        "--dry-run",
        "--no-submit",
        dest="dry_run",
        action="store_true",
        help="Skip Alpaca paper orders (opt-in dry-run)",
    )
    p.add_argument("--continue-on-ingest-error", action="store_true")
    p.add_argument("--env-file", type=Path, help="Path to alpaca.env OUTSIDE the Project store")
    p.add_argument("--python", default=sys.executable, help="Python executable for child ticks")
    p.add_argument("--catch-up", action="store_true", help="If started mid-hour in RTH, run current hour once")
    args = p.parse_args(argv)
    if getattr(args, "dry_run", False):
        args.submit = False

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

    def do_phases(day: date, hour: int, minute: int = 0) -> int:
        phase = args.phase
        status = {
            "bucket": bucket_for(day, hour, minute),
            "slot": slot_key(hour, minute),
            "as_of": as_of_iso(day, hour, minute),
            "phase_mode": phase,
            "started_at": now_et().isoformat(),
            "submit": bool(args.submit),
            "cadence": "30m",
        }
        write_scheduler_status(status)

        if phase == "prep-then-settle":
            rc = run_tick(
                day,
                hour,
                minute,
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
                if proposals_ready(day, hour, minute):
                    break
                status["waiting_for_proposals"] = True
                status["deadline"] = deadline.isoformat()
                write_scheduler_status(status)
                time.sleep(15)
            if not proposals_ready(day, hour, minute):
                status["settle_skipped"] = "proposals_missing"
                status["finished_at"] = now_et().isoformat()
                write_scheduler_status(status)
                print("[scheduler] settle skipped — proposals not ready", flush=True)
                discord_notify(
                    f"Issue · settle skipped · {bucket_for(day, hour, minute)}",
                    "proposals_missing",
                    kind="issue",
                    ok=False,
                )
                return 0
            rc2 = run_tick(
                day,
                hour,
                minute,
                phase="settle",
                submit=args.submit,
                continue_on_ingest_error=args.continue_on_ingest_error,
                python=args.python,
            )
            status["settle_rc"] = rc2
            status["finished_at"] = now_et().isoformat()
            write_scheduler_status(status)
            if hour == 15 and minute == 30:
                try:
                    discord_notify(
                        f"Day-end analysis · {day.isoformat()}",
                        "Building day-end brief…",
                        kind="day_end",
                    )
                    r = subprocess.run(
                        [args.python, str(SCRIPTS / "day_end_analysis.py"), "--date", day.isoformat()],
                        cwd=str(SCRIPTS),
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    brief = (r.stdout or r.stderr or f"exit {r.returncode}")[:500]
                    discord_notify(
                        f"Day-end done · {day.isoformat()}",
                        brief,
                        kind="day_end",
                        ok=r.returncode == 0,
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"[scheduler] day-end analysis failed: {e}", flush=True)
                    discord_notify(
                        f"Day-end failed · {day.isoformat()}",
                        str(e),
                        kind="issue",
                        ok=False,
                    )
            return rc2

        rc = run_tick(
            day,
            hour,
            minute,
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
        day, hour, minute, slot, _ = parse_hour_bucket(args.hour)
        if not is_rth_consensus_tick(day, hour, minute):
            print(f"[scheduler] warning: {args.hour} outside RTH consensus ticks", flush=True)
        return do_phases(day, hour, minute)

    if args.catch_up:
        n = now_et()
        now_mins = n.hour * 60 + n.minute
        best = None
        if is_trading_day(n.date()):
            for h, m in RTH_TICKS:
                tick_mins = h * 60 + m
                if tick_mins <= now_mins < tick_mins + 25:
                    best = (h, m)
        if best:
            print(f"[scheduler] catch-up tick {best[0]:02d}:{best[1]:02d}", flush=True)
            rc = do_phases(n.date(), best[0], best[1])
            if force_once:
                return rc

    if force_once:
        day, hour, minute, tick, bucket, slot = next_rth_tick()
        n = now_et()
        now_mins = n.hour * 60 + n.minute
        if is_trading_day(n.date()):
            for h, m in RTH_TICKS:
                if h * 60 + m <= now_mins <= h * 60 + m + 2:
                    print(f"[scheduler] --once on-tick → {bucket_for(n.date(), h, m)}", flush=True)
                    return do_phases(n.date(), h, m)
        print(f"[scheduler] --once waiting for {tick.isoformat()} …", flush=True)
        sleep_until(tick)
        return do_phases(day, hour, minute)

    # Long-running loop
    print("[scheduler] loop started (30m RTH ticks; Ctrl+C to stop)", flush=True)
    while True:
        day, hour, minute, tick, bucket, slot = next_rth_tick()
        write_scheduler_status(
            {
                "next_tick": tick.isoformat(),
                "bucket": bucket,
                "slot": slot,
                "mode": "loop",
                "cadence": "30m",
                "updated_at": now_et().isoformat(),
            }
        )
        print(f"[scheduler] next tick {tick.isoformat()} ({bucket})", flush=True)
        sleep_until(tick)
        time.sleep(1)
        try:
            do_phases(day, hour, minute)
        except Exception as e:  # noqa: BLE001
            print(f"[scheduler] tick error: {e}", file=sys.stderr, flush=True)
            write_scheduler_status(
                {
                    "error": str(e),
                    "bucket": bucket,
                    "slot": slot,
                    "at": now_et().isoformat(),
                }
            )
            discord_notify(
                f"Issue · loop · {bucket}",
                str(e),
                kind="issue",
                ok=False,
            )
        time.sleep(2)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[scheduler] stopped", flush=True)
        raise SystemExit(130)
