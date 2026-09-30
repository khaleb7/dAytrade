#!/usr/bin/env bash
# Install / start DayTrade hourly scheduler on Linux (this cloud VM).
# Secrets: ~/.daytrade/alpaca.env only — never the Project store.
set -euo pipefail

STORE="${DAYTRADE_STORE:-/cursor/stores/bc-7a9f3369-d383-44f7-b5ec-0d1ac69e76fb}"
SCRIPTS="$STORE/scripts"
ENV_FILE="${DAYTRADE_ENV_FILE:-$HOME/.daytrade/alpaca.env}"
SESSION="${DAYTRADE_TMUX_SESSION:-daytrade-hourly}"
TMUX_CFG="/exec-daemon/tmux.portal.conf"
LOG_DIR="$HOME/.daytrade/logs"
mkdir -p "$(dirname "$ENV_FILE")" "$LOG_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing $ENV_FILE — copy from $SCRIPTS/windows/alpaca.env.example and fill keys." >&2
  exit 1
fi

# Refuse if env file is inside the store
case "$(realpath "$ENV_FILE")" in
  "$(realpath "$STORE")"*) echo "Refusing env file inside Project store: $ENV_FILE" >&2; exit 1 ;;
esac

python3 -m pip install --user -q -r "$SCRIPTS/requirements.txt" tzdata

tmux_bin() {
  if [[ -f "$TMUX_CFG" ]]; then
    tmux -f "$TMUX_CFG" "$@"
  else
    tmux "$@"
  fi
}

# Stop existing session if present
if tmux_bin has-session -t "=$SESSION" 2>/dev/null; then
  echo "Stopping existing tmux session $SESSION"
  tmux_bin kill-session -t "$SESSION" || true
fi

# Launch long-running scheduler (paper submit ON by default)
CMD=(python3 "$SCRIPTS/hourly_scheduler.py"
  --env-file "$ENV_FILE"
  --catch-up
  --phase prep-then-settle
  --proposal-wait-minutes 20
  --continue-on-ingest-error
)

echo "Starting scheduler in tmux session '$SESSION'"
echo "  store=$STORE"
echo "  env=$ENV_FILE"
echo "  log=$LOG_DIR/scheduler.log"

tmux_bin new-session -d -s "$SESSION" -c "$SCRIPTS" -- bash -lc "
  set -a
  # shellcheck disable=SC1090
  source <(grep -v '^#' '$ENV_FILE' | sed 's/^/export /')
  set +a
  exec python3 '$SCRIPTS/hourly_scheduler.py' \
    --env-file '$ENV_FILE' \
    --catch-up \
    --phase prep-then-settle \
    --proposal-wait-minutes 20 \
    --continue-on-ingest-error \
    2>&1 | tee -a '$LOG_DIR/scheduler.log'
"

sleep 1
tmux_bin has-session -t "=$SESSION"
echo "OK — session running. Attach: tmux -f $TMUX_CFG attach -t $SESSION"
echo "Status: $STORE/state/scheduler/status.json"
echo "Logs:   $LOG_DIR/scheduler.log"
