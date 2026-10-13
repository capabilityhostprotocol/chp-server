#!/usr/bin/env bash
# install-host.sh — bring up a governed CHP host on any Unix host (Linux or macOS):
# create a venv, install chp-server + the adapters you name, serve them, and install a
# persistent (restart-on-boot) service. Public stack only — chp-server + chp-core +
# chp-adapter-* — with NO private-product dependency.
#
#   ./install-host.sh safety audit [http filesystem ...] [--port P] [--bind ADDR]
#                     [--no-service] [--runtime-assurance] [--dry-run]
#   ./install-host.sh --all             # serve every adapter already installed in the venv
#
# Windows: the same host runs under Python on Windows; register a Scheduled Task that runs
# `venv\Scripts\python serve_adapters.py <adapters> --port P` at boot + logon (see README).
#
# Prereqs: python3 >= 3.11. A Linux system service needs sudo; without it, falls back to a
# `systemd --user` service with lingering.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
OS="$(uname -s)"; ARCH="$(uname -m)"
STATE="$HOME/.chp-host"
PORT=8800; BIND="0.0.0.0"; STORE="$STATE/chp-host.sqlite"
INSTALL_SERVICE=1; RUNTIME_ASSURANCE=0; DRY_RUN=0; BOOTSTRAP=""; INFERENCE=0
ADAPTERS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --bind) BIND="$2"; shift 2 ;;
    --store) STORE="$2"; shift 2 ;;
    --no-service) INSTALL_SERVICE=0; shift ;;
    --runtime-assurance) RUNTIME_ASSURANCE=1; shift ;;
    --bootstrap) BOOTSTRAP="$2"; shift 2 ;;   # node|containment|assurance — provision system prereqs
    --inference) INFERENCE=1; shift ;;         # also provision a sovereign LLM backend (ollama)
    --dry-run) DRY_RUN=1; shift ;;
    --all) ADAPTERS=(ALL); shift ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *) ADAPTERS+=("$1"); shift ;;
  esac
done
[ ${#ADAPTERS[@]} -gt 0 ] || { echo "usage: install-host.sh <adapter...> [--port P] [opts]" >&2; exit 2; }

say() { printf '==> %s\n' "$*"; }
say "CHP host install — $OS/$ARCH, adapters: ${ADAPTERS[*]}, port $PORT"

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 >= 3.11 required." >&2; exit 1; }
python3 -c 'import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)' \
  || { echo "ERROR: need python3 >= 3.11 (found $(python3 -V 2>&1))." >&2; exit 1; }
case "$OS" in Linux|Darwin) ;; *) echo "ERROR: $OS unsupported; see README for Windows." >&2; exit 2;; esac

# System prerequisites for a tier (Docker, gVisor, Kata, tpm2-tools, …) are provisioned AFTER the
# venv exists, by the governed, evidenced capability `chp.adapters.host.bootstrap` via
# `chp-server onboard --no-serve` — NOT by a hand-rolled ledger. That capability detects the host,
# plans per-OS, runs each step hardened, RE-DETECTS to verify installs actually took, fails closed
# honestly, and records every phase as signed, SHA256-chained CHP ExecutionEvidence (replayable via
# `chp-server replay`). See the post-install step below.

# pip targets: chp-server + chp-adapter-<name> for each named adapter (--all installs none extra and
# serves whatever is already present in the venv). A --bootstrap tier also needs chp-adapter-host,
# which carries the governed provisioning capability.
PKGS=(chp-server)
[ -n "$BOOTSTRAP" ] && PKGS+=(chp-adapter-host)
if [ "${ADAPTERS[0]}" != ALL ]; then for a in "${ADAPTERS[@]}"; do PKGS+=("chp-adapter-$a"); done; fi

inf_flag=""; [ "$INFERENCE" = 1 ] && inf_flag="--inference"

if [ "$DRY_RUN" = 1 ]; then
  say "[dry-run] venv: $STATE/venv"
  say "[dry-run] pip install ${PKGS[*]}"
  [ -n "$BOOTSTRAP" ] && say "[dry-run] provision (evidenced): chp-server onboard --tier $BOOTSTRAP $inf_flag --dry-run --no-serve"
  say "[dry-run] serve: python serve_adapters.py ${ADAPTERS[*]/ALL/} --port $PORT --bind $BIND"
  [ "$INSTALL_SERVICE" = 1 ] && say "[dry-run] install $OS persistent service"
else
  say "Creating venv + installing from PyPI …"
  mkdir -p "$STATE"
  python3 -m venv "$STATE/venv"
  "$STATE/venv/bin/pip" install --quiet --upgrade pip
  "$STATE/venv/bin/pip" install --quiet "${PKGS[@]}"
  cp "$HERE/serve_adapters.py" "$STATE/serve_adapters.py"
  say "Installed $("$STATE/venv/bin/pip" list 2>/dev/null | grep -ciE 'chp-') chp packages."
  # Provision the tier's SYSTEM prerequisites through the governed, EVIDENCED capability (no
  # hand-rolled ledger). --no-serve: the persistent service below is what serves. The record is
  # inspectable per environment via `chp-server replay` against the onboard store.
  if [ -n "$BOOTSTRAP" ]; then
    say "Provisioning tier '$BOOTSTRAP'$inf_flag (governed + evidenced via chp.adapters.host.bootstrap) …"
    "$STATE/venv/bin/chp-server" onboard --tier "$BOOTSTRAP" $inf_flag --no-serve \
      --store "$STATE/onboard.sqlite" 2>&1 | sed 's/^/    /' \
      || say "provision reported a non-ok outcome — inspect: chp-server replay against $STATE/onboard.sqlite"
  fi
fi

SERVE_ARGS=""; [ "${ADAPTERS[0]}" != ALL ] && SERVE_ARGS="${ADAPTERS[*]}"
EXEC="$STATE/venv/bin/python $STATE/serve_adapters.py $SERVE_ARGS --port $PORT --bind $BIND --store $STORE"

install_service_linux() {
  local unit
  unit=$(cat <<UNIT
[Unit]
Description=CHP governed host (chp-server + adapters)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=$USER
ExecStart=$EXEC
Restart=on-failure
RestartSec=10
[Install]
WantedBy=multi-user.target
UNIT
)
  if sudo -n true 2>/dev/null || [ "$(id -u)" = 0 ] || sudo true 2>/dev/null; then
    printf '%s\n' "$unit" | sudo tee /etc/systemd/system/chp-host.service >/dev/null
    sudo systemctl daemon-reload; sudo systemctl enable --now chp-host
    say "Installed system service 'chp-host' (systemctl status chp-host)."
  else
    mkdir -p "$HOME/.config/systemd/user"
    printf '%s\n' "${unit/WantedBy=multi-user.target/WantedBy=default.target}" \
      > "$HOME/.config/systemd/user/chp-host.service"
    systemctl --user daemon-reload; systemctl --user enable --now chp-host
    loginctl enable-linger "$USER" 2>/dev/null || true
    say "No sudo — installed 'systemd --user' service with lingering."
  fi
}
install_service_macos() {
  local dst="$HOME/Library/LaunchAgents/com.chp.host.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$dst" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.chp.host</string>
  <key>ProgramArguments</key><array>
    <string>/bin/sh</string><string>-c</string><string>$EXEC</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/chp-host.log</string>
  <key>StandardErrorPath</key><string>/tmp/chp-host.log</string>
</dict></plist>
PLIST
  launchctl unload "$dst" 2>/dev/null || true
  launchctl load "$dst"
  say "Installed launchd agent 'com.chp.host' (logs: /tmp/chp-host.log)."
}
verify_up() {
  sleep 2
  python3 - "$PORT" <<'PY' || echo "    (not listening yet — check service logs)"
import socket,sys
s=socket.socket(); s.settimeout(2)
try: s.connect(("127.0.0.1",int(sys.argv[1]))); print(f"    host listening on 127.0.0.1:{sys.argv[1]} — up")
except Exception: sys.exit(1)
PY
}
if [ "$INSTALL_SERVICE" = 1 ] && [ "$DRY_RUN" = 0 ]; then
  say "Installing the persistent service …"
  case "$OS" in Linux) install_service_linux;; Darwin) install_service_macos;; esac
  verify_up
fi

runtime_assurance_report() {
  say "Runtime-assurance (CHP Safety) readiness"
  if [ "$OS" = Linux ]; then
    { [ -e /dev/tpm0 ] || [ -e /dev/tpmrm0 ]; } && echo "    TPM: present -> W4 possible" || echo "    TPM: ABSENT -> no W4"
    [ -e /dev/kvm ] && echo "    KVM: present -> own-kernel microVM possible" || echo "    KVM: ABSENT -> no microVM"
    command -v docker >/dev/null 2>&1 && echo "    docker: present" || echo "    docker: absent"
    echo "    Full hardening: chp-safety/docs/NUC_SETUP.md (a CHP Safety concern)."
  else
    echo "    $OS has no TPM/KVM parity; W4 + own-kernel microVM need Linux hardware (honest limit)."
  fi
}
[ "$RUNTIME_ASSURANCE" = 1 ] && runtime_assurance_report || true
echo
say "Done. Governed host on :$PORT. Try:  curl -s http://127.0.0.1:$PORT/server"
