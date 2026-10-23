#!/usr/bin/env bash
# Video Studio worker for the Linux laptop (Ubuntu 24.04). Run once, then again any time to update:
#     bash setup-worker.sh
# It duplicates the PC's environment (same code from GitHub), CPU only, and runs Video Studio as a user service on
# port 42021, reachable from the home network only with a token. The Newsroom on the PC sends it work when the queue is
# badly backed up. Images: Hugging Face only (no browser sign-ins on this machine). It never publishes.
set -euo pipefail
DIR="$HOME/video-studio"
CONF="$HOME/.config/video-studio"
REPO="tariq424/video-studio-test"
say() { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }

say "1/8 system packages (sudo password once)"
sudo apt-get update -qq
sudo apt-get install -y -qq git curl python3-venv python3-pip python3-dev ffmpeg espeak-ng nodejs npm avahi-daemon \
  libnss3 libatk-bridge2.0-0 libgbm1 libasound2t64 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libpango-1.0-0 \
  libcairo2 libcups2 libdrm2 fonts-dejavu-core >/dev/null
command -v gh >/dev/null || sudo apt-get install -y -qq gh >/dev/null

say "2/8 GitHub sign-in (the repo is private; a browser code flow, once)"
gh auth status >/dev/null 2>&1 || gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git

say "3/8 code"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull -q --ff-only; else gh repo clone "$REPO" "$DIR" -- -q; fi

say "4/8 Python environment (app/env) and packages"
python3 -m venv "$DIR/app/env"
"$DIR/app/env/bin/pip" install -q --upgrade pip
"$DIR/app/env/bin/pip" install -q -r "$DIR/app/requirements.txt" playwright gradio_client rembg onnxruntime soundfile
"$DIR/app/env/bin/python" -m playwright install chromium >/dev/null

say "5/8 Kokoro voice (its own env, app/kenv, CPU torch)"
python3 -m venv "$DIR/app/kenv"
"$DIR/app/kenv/bin/pip" install -q --upgrade pip
"$DIR/app/kenv/bin/pip" install -q torch --index-url https://download.pytorch.org/whl/cpu
"$DIR/app/kenv/bin/pip" install -q kokoro soundfile numpy

say "6/8 Remotion (the video renderer) and Ollama (local vision check for stock clips and images, CPU)"
(cd "$DIR/remotion" && npm ci --silent --no-audit --no-fund)
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5vl:7b   # ~6 GB, once

say "7/8 settings and keys (kept in $CONF, never in git)"
mkdir -p "$CONF" "$HOME/videos/jobs"; chmod 700 "$CONF"
ENVF="$CONF/worker.env"
if [ ! -f "$ENVF" ]; then
  read -rsp "DeepSeek API key (writes the scripts): " DS; echo
  read -rsp "Hugging Face token (hf_..., images): " HF; echo
  TOK=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)
  cat > "$ENVF" <<EOF
VS_DEEPSEEK_API_KEY=$DS
VS_HF_TOKEN=$HF
VS_TOKEN=$TOK
VS_HOST=0.0.0.0
VS_WORKER=elitebook
PORT=42021
VS_RELOAD=0
EOF
  chmod 600 "$ENVF"
fi
python3 - "$DIR/settings.json" "$HOME/videos/jobs" <<'PY'
import json, sys, os
p, jobs = sys.argv[1], sys.argv[2]
d = json.load(open(p)) if os.path.exists(p) else {}
d.update({"jobs_dir": jobs, "imagegen_providers": ["hf"], "imagegen_rotate": False, "imagegen_per_beat": 1,
          "flow_on": False, "wangp_on_demand": False, "vet_provider": "local", "short_concurrency": 2, "kokoro_online": True, "kokoro_device": "cpu",
          "script_provider": d.get("script_provider", "deepseek")})
json.dump(d, open(p, "w"), indent=1)
PY

say "8/8 service (starts on boot; blocks sleep only while a job renders)"
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/video-studio.service" <<EOF
[Unit]
Description=Video Studio worker (port 42021)
After=network-online.target
[Service]
EnvironmentFile=$ENVF
WorkingDirectory=$DIR/app
ExecStart=$DIR/app/env/bin/python -u server.py
Restart=on-failure
RestartSec=10
[Install]
WantedBy=default.target
EOF
cat > "$HOME/.config/systemd/user/video-studio-awake.service" <<EOF
[Unit]
Description=Keep the laptop awake while Video Studio renders
After=video-studio.service
[Service]
ExecStart=/bin/bash -c 'while true; do if curl -s localhost:42021/api/status | grep -q "\"current\": *\"[0-9]"; then systemd-inhibit --what=sleep:idle --why="Video Studio is rendering" sleep 120; else sleep 60; fi; done'
Restart=always
[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now video-studio.service video-studio-awake.service
sudo loginctl enable-linger "$USER"   # keeps the service running without a desktop login
sleep 6

IFACE=$(ip route show default | awk '{print $5; exit}')
echo
say "Done. Send Claude these lines:"
echo "name:  $(hostname).local"
echo "ip:    $(hostname -I | awk '{print $1}')"
echo "mac:   $(cat /sys/class/net/$IFACE/address) ($IFACE)"
echo "token: $(grep ^VS_TOKEN= "$ENVF" | cut -d= -f2)"
echo "check: $(curl -s localhost:42021/api/status | head -c 120)"
echo
echo "Battery tip: BIOS > Advanced > Power Management > Battery Health Manager: 'Maximize my battery health' (caps at ~80%)."
