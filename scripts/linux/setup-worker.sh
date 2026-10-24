#!/usr/bin/env bash
# Video Studio worker for the Linux laptop (Ubuntu 24.04). ONE command on the laptop, run again any time to update:
#     curl -fsSL "http://<PC address>:42040/laptop/setup.sh?k=<phone passcode>" | bash
# (or: bash setup-worker.sh  -- it then asks for the PC address and passcode)
# It duplicates the PC's environment (same code from GitHub), CPU only, and runs Video Studio as a user service on port
# 42021, reachable from the home network only with a token. The Newsroom on the PC sends it work when the queue is badly
# backed up. Images: Hugging Face first; ChatGPT / Bing too once you sign in on the laptop (vs-login). Gemini and Google
# Flow are never used here. Talking head: Hugging Face. It never publishes. At the end it reports to the PC by itself.
set -euo pipefail
{   # the whole script is read before it runs (safe with curl | bash)
# system tools first: a personal ~/bin (e.g. a custom tee) must not replace them in this script
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$HOME/.local/bin"
exec > >(/usr/bin/tee -a "$HOME/video-studio-setup.log") 2>&1
DIR="$HOME/video-studio"
CONF="$HOME/.config/video-studio"
REPO="tariq424/video-studio-test"
PC="@@PC@@"; PIN="@@PIN@@"   # filled in by the Newsroom when the script is fetched from it
say() { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
ask() { local v; read -r -p "$1" v </dev/tty; printf '%s' "$v"; }
asks() { local v; read -r -s -p "$1" v </dev/tty; echo >/dev/tty; printf '%s' "$v"; }
case "$PC" in @@*) PC=$(ask "PC address and port (e.g. 192.168.40.150:42040): ");; esac
case "$PIN" in @@*|"") PIN=$(asks "Newsroom phone passcode: ");; esac
T0=$(date +%s)
FROM=${1:-1}   # resume: "bash setup.sh 7" skips the finished steps 1, 2, 5, 6 (code, keys and services always run)
want() { [ "$FROM" -le "$1" ]; }
sudo -v </dev/tty

if want 1; then
say "1/10 system packages (sudo password once)"
sudo -v </dev/tty
sudo apt-get update -qq || true
PKGS="git curl wget gpg jq python3-venv python3-pip python3-dev ffmpeg espeak-ng avahi-daemon libnss3 libatk-bridge2.0-0 libgbm1
      libasound2t64 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libpango-1.0-0 libcairo2 libcups2 libdrm2 fonts-dejavu-core fonts-noto-color-emoji fonts-liberation gh"
command -v node >/dev/null || PKGS="$PKGS nodejs"
command -v npm >/dev/null || PKGS="$PKGS npm"
MISSING=""; for p in $PKGS; do dpkg -s "$p" >/dev/null 2>&1 || MISSING="$MISSING $p"; done
if [ -n "$MISSING" ] && ! sudo apt-get install -y -qq $MISSING >/dev/null 2>&1; then
  echo "   one batch failed (a package conflict on this machine); installing one at a time:"
  FAILED=""; for p in $MISSING; do sudo apt-get install -y -qq "$p" >/dev/null 2>&1 || FAILED="$FAILED $p"; done
  [ -z "$FAILED" ] || echo "   could not install:$FAILED (continuing; the steps that need them will say so)"
fi
echo "   node $(node -v 2>/dev/null || echo missing), npm $(npm -v 2>/dev/null || echo missing), ffmpeg $(command -v ffmpeg >/dev/null && echo ok || echo missing)"
else say "1/10 skipped (resuming from step $FROM)"; fi

if want 2; then
say "2/10 browsers for the image sites (Google Chrome for ChatGPT, Microsoft Edge for Bing)"
if ! command -v google-chrome >/dev/null; then
  wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  sudo apt-get install -y -qq /tmp/chrome.deb >/dev/null; rm -f /tmp/chrome.deb
fi
if ! command -v microsoft-edge >/dev/null; then
  wget -q -O /tmp/edge.deb "https://go.microsoft.com/fwlink?linkid=2149051&brand=M102"
  sudo apt-get install -y -qq /tmp/edge.deb >/dev/null || echo "   (Edge did not install; Bing stays off on the laptop)"; rm -f /tmp/edge.deb
fi
else say "2/10 skipped (resuming from step $FROM)"; fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo /nonexistent)"
if [ -d "$HERE/repo/.git" ]; then   # run from the tarball: the code comes with it, no GitHub sign-in needed
  say "3/10 code from the tarball (no GitHub sign-in)"
  if [ -d "$DIR/.git" ]; then git -C "$DIR" pull -q --ff-only "$HERE/repo" main; else cp -a "$HERE/repo" "$DIR"; fi
  gh auth status >/dev/null 2>&1 || echo "   (optional, later: 'gh auth login' lets the hourly sync pull new code from GitHub by itself)"
else
  say "3/10 GitHub sign-in (the repo is private; a browser code, once)"
  gh auth status >/dev/null 2>&1 || gh auth login --hostname github.com --git-protocol https --web </dev/tty
  gh auth setup-git
  if [ -d "$DIR/.git" ]; then git -C "$DIR" pull -q --ff-only; else gh repo clone "$REPO" "$DIR" -- -q; fi
fi
say "4/10 code: $(git -C "$DIR" log --oneline -1)"

if want 5; then
say "5/10 Python environment (app/env) and packages"
[ -x "$DIR/app/env/bin/python" ] || python3 -m venv "$DIR/app/env"
"$DIR/app/env/bin/pip" install -q --upgrade pip
"$DIR/app/env/bin/pip" install -q -r "$DIR/app/requirements.txt" playwright gradio_client huggingface_hub rembg onnxruntime soundfile
"$DIR/app/env/bin/python" -m playwright install chromium >/dev/null
else say "5/10 skipped (resuming from step $FROM)"; fi

if want 6; then
say "6/10 Kokoro voice (its own env, app/kenv, CPU torch)"
[ -x "$DIR/app/kenv/bin/python" ] || python3 -m venv "$DIR/app/kenv"
"$DIR/app/kenv/bin/pip" install -q --upgrade pip
"$DIR/app/kenv/bin/pip" install -q torch --index-url https://download.pytorch.org/whl/cpu
"$DIR/app/kenv/bin/pip" install -q kokoro soundfile numpy
else say "6/10 skipped (resuming from step $FROM)"; fi

say "7/10 Remotion (the video renderer) and Ollama (local vision check, CPU)"
(cd "$DIR/remotion" && npm ci --silent --no-audit --no-fund && npx --yes remotion browser ensure >/dev/null 2>&1 || true)
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
# ~6 GB, once. Detached (nohup) so a dropped SSH session or closed terminal cannot kill it; a re-run resumes it.
if ollama list 2>/dev/null | grep -q "qwen2.5vl:7b"; then echo "   vision model already downloaded"
else
  nohup bash -c 'for i in 1 2 3 4 5 6 7 8; do ollama pull qwen2.5vl:7b && exit 0; echo "retry $i in 30 s (network/DNS hiccup)"; sleep 30; done; exit 1' > "$HOME/ollama-pull.log" 2>&1 &   # resumes where it stopped
  PULL=$!; echo "   downloading the vision model in the background (log: ~/ollama-pull.log)"
  while kill -0 "$PULL" 2>/dev/null; do printf "\r   %s   " "$(tr '\r' '\n' < "$HOME/ollama-pull.log" | grep -o '[0-9]*%.*' | tail -1 | cut -c1-60)"; sleep 10; done; echo
  ollama list 2>/dev/null | grep -q "qwen2.5vl:7b" || echo "   (the vision model did not finish; run this script again later: it resumes)"
fi

say "8/10 keys (from the PC, home network only) and settings (kept in $CONF, never in git)"
mkdir -p "$CONF" "$HOME/videos/jobs"; chmod 700 "$CONF"
ENVF="$CONF/worker.env"
KEYS=$(curl -fsS -m 15 "http://$PC/laptop/keys?k=$PIN" || echo '{}')
DS=$(printf '%s' "$KEYS" | jq -r '.deepseek_api_key // ""'); HF=$(printf '%s' "$KEYS" | jq -r '.hf_token // ""')
OLD_TOK=$( [ -f "$ENVF" ] && grep ^VS_TOKEN= "$ENVF" | cut -d= -f2 || true)
[ -n "$DS" ] || DS=$( [ -f "$ENVF" ] && grep ^VS_DEEPSEEK_API_KEY= "$ENVF" | cut -d= -f2- || true)
[ -n "$HF" ] || HF=$( [ -f "$ENVF" ] && grep ^VS_HF_TOKEN= "$ENVF" | cut -d= -f2- || true)
[ -n "$DS" ] || DS=$(asks "DeepSeek API key (the PC didn't hand it over): ")
[ -n "$HF" ] || HF=$(asks "Hugging Face token hf_... (the PC didn't hand it over): ")
TOK=${OLD_TOK:-$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)}
umask 077
cat > "$ENVF" <<EOF
VS_DEEPSEEK_API_KEY=$DS
VS_HF_TOKEN=$HF
VS_TOKEN=$TOK
VS_HOST=0.0.0.0
VS_WORKER=elitebook
PORT=42021
VS_RELOAD=0
EOF
umask 022
python3 - "$DIR/settings.json" "$HOME/videos" <<'PY'
import json, sys, os
p, home = sys.argv[1], sys.argv[2]
d = json.load(open(p)) if os.path.exists(p) else {}
signed = [s for s in ("chatgpt", "bing") if os.path.isdir(f"{home}/{s}_profile/Default")]   # vs-login was done
d.update({"jobs_dir": f"{home}/jobs", "imagegen_providers": ["hf"] + signed, "imagegen_rotate": False, "imagegen_per_beat": 1,
          "flow_on": False, "wangp_on_demand": False, "vet_provider": "local", "short_concurrency": 2, "kokoro_online": True,
          "kokoro_device": "cpu", "talking_head": "hf",
          "music_dir": f"{home}/music", "music_generate": False,   # music: the PC's library (vs-sync); no Gemini on the laptop
          "script_provider": d.get("script_provider", "deepseek")})
json.dump(d, open(p, "w"), indent=1)
print("   image services on the laptop:", " -> ".join(d["imagegen_providers"]))
PY

# fonts the captions need (also on a resumed run: emoji icons, an Arial look-alike)
for f in fonts-noto-color-emoji fonts-liberation; do dpkg -s "$f" >/dev/null 2>&1 || sudo apt-get install -y -qq "$f" >/dev/null 2>&1 || echo "   ($f did not install)"; done
say "9/10 helper commands: vs-login (sign in to ChatGPT / Bing once), vs-sync (code + music from the PC now)"
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/vs-login" <<'EOF'
#!/usr/bin/env bash
# vs-login chatgpt | bing : opens the laptop's own profile so you can sign in once; close the window when done.
site=${1:-chatgpt}; prof="$HOME/videos/${site}_profile"; mkdir -p "$prof"
case "$site" in
  chatgpt) google-chrome --user-data-dir="$prof" --no-first-run --new-window https://chatgpt.com/auth/login ;;
  bing)    microsoft-edge --user-data-dir="$prof" --no-first-run --new-window https://www.bing.com/images/create ;;
  *) echo "usage: vs-login chatgpt|bing  (Gemini and Google Flow are not used on the laptop)"; exit 1 ;;
esac
python3 - "$HOME/video-studio/settings.json" "$site" <<'PY'
import json, sys; p, s = sys.argv[1:]; d = json.load(open(p)); l = d.get("imagegen_providers") or ["hf"]
if s not in l: l.append(s)
d["imagegen_providers"] = l; json.dump(d, open(p, "w"), indent=1); print("image services:", " -> ".join(l))
PY
EOF
printf 'PC=%s\nPIN=%s\n' "$PC" "$PIN" > "$CONF/sync.env"; chmod 600 "$CONF/sync.env"
cat > "$HOME/.local/bin/vs-sync" <<'EOF'
#!/usr/bin/env bash
# Hourly: the PC's music library, then the latest code (from the PC; GitHub if signed in).
# Restarts the service only when the code changed, and only once no job is running.
[ -f "$HOME/.config/video-studio/sync.env" ] && . "$HOME/.config/video-studio/sync.env"
D="$HOME/video-studio"; old=$(git -C "$D" rev-parse HEAD); T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
if [ -n "$PC" ] && curl -fsS -m 600 "http://$PC/laptop/music?k=$PIN" -o "$T/m.tgz"; then
  mkdir -p "$HOME/videos/music" && tar xzf "$T/m.tgz" -C "$HOME/videos/music" && echo "music library synced ($(ls "$HOME/videos/music"/hook "$HOME/videos/music"/bed 2>/dev/null | grep -c '\.'))"
fi
if [ -n "$PC" ] && curl -fsS -m 600 "http://$PC/laptop/bundle?k=$PIN" | tar xj -C "$T" && [ -d "$T/vs-laptop/repo/.git" ]; then
  git -C "$D" pull -q --ff-only "$T/vs-laptop/repo" main || { echo "code update failed"; exit 0; }
elif gh auth status >/dev/null 2>&1; then git -C "$D" pull -q --ff-only || exit 0
else exit 0; fi
new=$(git -C "$D" rev-parse HEAD); [ "$old" = "$new" ] && exit 0
git -C "$D" diff --name-only "$old" "$new" | grep -q requirements.txt && "$D/app/env/bin/pip" install -q -r "$D/app/requirements.txt"
git -C "$D" diff --name-only "$old" "$new" | grep -q remotion/package-lock.json && (cd "$D/remotion" && npm ci --silent --no-audit --no-fund)
for i in $(seq 1 120); do curl -s localhost:42021/api/status | grep -q '"current": *"[0-9]' || break; sleep 60; done
systemctl --user restart video-studio.service; echo "updated $old -> $new"
EOF
chmod +x "$HOME/.local/bin/vs-login" "$HOME/.local/bin/vs-sync"

say "10/10 services: Video Studio (on boot), stay awake only while rendering, hourly code sync"
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
cat > "$HOME/.config/systemd/user/video-studio-sync.service" <<EOF
[Unit]
Description=Pull the latest Video Studio code
[Service]
Type=oneshot
ExecStart=$HOME/.local/bin/vs-sync
EOF
cat > "$HOME/.config/systemd/user/video-studio-sync.timer" <<EOF
[Unit]
Description=Hourly Video Studio code + music sync
[Timer]
OnBootSec=10min
OnUnitActiveSec=1h
[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now video-studio.service video-studio-awake.service video-studio-sync.timer
systemctl --user restart video-studio.service
sudo loginctl enable-linger "$USER"   # keeps the services running without a desktop login
for i in $(seq 1 30); do curl -s localhost:42021/api/status >/dev/null && break; sleep 2; done
"$HOME/.local/bin/vs-sync" | sed 's/^/   /' || true   # the music library now (then hourly)

IFACE=$(ip route show default | awk '{print $5; exit}')
NAME="$(hostname).local"; IP=$(hostname -I | awk '{print $1}'); MAC=$(cat /sys/class/net/$IFACE/address)
STATUS=$(curl -s -m5 localhost:42021/api/status | head -c 100)
say "Reporting to the PC ($PC)"
REPLY=$(curl -fsS -m 60 -X POST -H 'Content-Type: application/json' "http://$PC/laptop/register?k=$PIN" \
        -d "{\"name\":\"$NAME\",\"ip\":\"$IP\",\"mac\":\"$MAC\",\"token\":\"$TOK\"}" || echo '{"ok":false}')
echo "   PC says: $REPLY"
say "Done in $(( ($(date +%s) - T0) / 60 )) min"
echo "name: $NAME   ip: $IP   mac: $MAC ($IFACE)"
echo "local check: $STATUS"
echo "Optional: 'vs-login chatgpt' and 'vs-login bing' to add those image services on the laptop (sign in, close the window)."
echo "Log: $HOME/video-studio-setup.log"
echo "Battery tip: BIOS > Advanced > Power Management > Battery Health Manager: 'Maximize my battery health' (caps at ~80%)."
}
