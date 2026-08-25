#!/bin/bash
# Run HNC Tracker + Cloudflare Tunnel
# Usage: bash run.sh

cd "$(dirname "$0")"

# ── Resolve conda base ───────────────────────────────────────────────────────
CONDA_BASE=$(conda info --base 2>/dev/null || echo "$HOME/miniconda3")
ACTIVATE="source $CONDA_BASE/etc/profile.d/conda.sh && conda activate hnc-tracker"

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_DIR="logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$(pwd)/$LOG_DIR/mhealth-$(date +%Y%m%d-%H%M%S).log"

echo "============================================"
echo "  HNC Tracker starting..."
echo "  Logs: $LOG_FILE"
echo "  Run this to get URL after ~60s:"
echo "  tmux capture-pane -t hnc:0.1 -p -S -1000 | grep trycloudflare"
echo "============================================"

# ── Helper: bash + conda activate + command ──────────────────────────────────
activate_pane() {
  local pane=$1
  local cmd=$2
  tmux send-keys -t $pane "bash" Enter
  tmux send-keys -t $pane "$ACTIVATE" Enter
  tmux send-keys -t $pane "$cmd" Enter
}

# ── Launch tmux ──────────────────────────────────────────────────────────────
SESSION="hnc"
tmux kill-session -t $SESSION 2>/dev/null
tmux new-session -d -s $SESSION -x 220 -y 50

# Pane 0 (left): Flask
activate_pane $SESSION:0.0 "python -u app.py 2>&1 | tee $LOG_FILE"

# Pane 1 (top right): Cloudflare Tunnel
# Wait 60s for Flask + VLM to fully load first
tmux split-window -h -t $SESSION:0.0
tmux send-keys -t $SESSION:0.1 "sleep 60 && cloudflared tunnel --url http://localhost:5000" Enter

# Pane 2 (bottom right): live log tail + print URL when ready
tmux split-window -v -t $SESSION:0.1
activate_pane $SESSION:0.2 "sleep 20 && echo '--- PUBLIC URL ---' && tmux capture-pane -t hnc:0.1 -p -S -1000 | grep trycloudflare && echo '--- LOG ---' && tail -f $LOG_FILE"

# Focus Flask pane
tmux select-pane -t $SESSION:0.0

tmux attach -t $SESSION