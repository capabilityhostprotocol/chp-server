#!/usr/bin/env bash
# Guided CHP node installer — choose how deep to go. Seeds a minimal governed venv, shows (honestly,
# for THIS device) what each tier can actually provide, then provisions the chosen tier's system
# prerequisites through the governed + EVIDENCED capability chp.adapters.host.bootstrap (via
# install-host.sh --bootstrap) and installs the host + the tier's adapters.
#
#   ./guided-install.sh                      # interactive: pick a tier
#   ./guided-install.sh --tier assurance --inference [--yes] [--dry-run] [install-host.sh opts]
#
# Tiers (cumulative): node → containment → assurance.  --inference adds a sovereign LLM backend.
# The feasibility preview is a PURE plan (no installs, no evidence); the real provision is the
# governed, hash-chained CHP evidence recorded by `chp-server onboard` inside install-host.sh.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
STATE="$HOME/.chp-host"; VENV="$STATE/venv"

TIER=""; INFERENCE=0; YES=0; DRY=0; PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --tier) TIER="$2"; shift 2 ;;
    --inference) INFERENCE=1; shift ;;
    --yes) YES=1; shift ;;
    --dry-run) DRY=1; shift ;;
    *) PASS+=("$1"); shift ;;
  esac
done
inf_flag=""; [ "$INFERENCE" = 1 ] && inf_flag="--inference"
say() { printf '==> %s\n' "$*"; }

command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 >= 3.11 required." >&2; exit 1; }

# --- seed a minimal governed venv so the pure planner + governed onboarding are available ---
say "Seeding a governed venv ($VENV) with chp-server + chp-adapter-host …"
mkdir -p "$STATE"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet chp-server chp-adapter-host
PLAN="$VENV/bin/chp-server onboard --plan"   # pure cross-OS feasibility — no installs, no evidence

# --- show each tier's feasibility on THIS device (pure plan, no side effects, no evidence) ---
say "What this device can support (detected):"
for t in node containment assurance; do
  printf "  [%s]\n" "$t"
  $PLAN --tier "$t" $inf_flag 2>/dev/null | sed 's/^/    /' | grep -vE '^    host:'
done

# --- choose a tier (interactive unless --tier) ---
if [ -z "$TIER" ]; then
  echo ""; echo "How deep do you want to go?"
  echo "  1) node         — governed host + adapters only"
  echo "  2) containment  — + OpenShell/OpenCell shared-kernel cells"
  echo "  3) assurance    — + hardware runtime assurance (microVM + W4 TPM, where supported)"
  printf "Select [1-3] (default 1): "
  read -r choice || choice=1
  case "${choice:-1}" in 2) TIER=containment ;; 3) TIER=assurance ;; *) TIER=node ;; esac
  printf "Also install a sovereign LLM backend (ollama)? [y/N]: "
  read -r yn || yn=n
  case "$yn" in y|Y) INFERENCE=1; inf_flag="--inference" ;; esac
fi
say "Chosen tier: $TIER${inf_flag:+ +inference}"

# --- the concrete plan for the chosen tier (pure) ---
PLAN_TXT="$($PLAN --tier "$TIER" $inf_flag)"
say "Plan for this device:"
printf '%s\n' "$PLAN_TXT" | sed 's/^/    /'

# --- confirm (the governed, evidenced provision happens inside install-host.sh --bootstrap) ---
NSTEPS="$(printf '%s\n' "$PLAN_TXT" | grep -c 'will install :' || true)"
if [ "$NSTEPS" -gt 0 ] && [ "$YES" != 1 ] && [ "$DRY" != 1 ]; then
  printf "Install %s system prerequisite(s) for tier '%s' (governed + evidenced)? [y/N]: " "$NSTEPS" "$TIER"
  read -r ok || ok=n; case "$ok" in y|Y) ;; *) echo "aborted."; exit 1 ;; esac
fi

# --- adapters to serve for the chosen tier (merge with any the operator passed through) ---
ADAPTERS=()
case "$TIER" in containment|assurance) ADAPTERS+=(safety audit) ;; esac
HOST_ARGS=(${ADAPTERS[@]+"${ADAPTERS[@]}"} ${PASS[@]+"${PASS[@]}"})

# --- hand off to install-host.sh: it installs the tier's adapters, provisions the prereqs via the
# governed, evidenced `chp-server onboard --no-serve`, and installs the persistent service. ---
inst_flags=(--bootstrap "$TIER")
[ "$INFERENCE" = 1 ] && inst_flags+=(--inference)
[ "$DRY" = 1 ] && inst_flags+=(--dry-run)

echo ""
if [ "${#HOST_ARGS[@]}" -eq 0 ]; then
  say "No adapters named for the '$TIER' tier (install-host.sh needs ≥1 to serve). The venv + the"
  say "governed provisioning are ready — re-run naming adapters, e.g.:  guided-install.sh --tier $TIER safety audit"
elif [ "$DRY" = 1 ]; then
  say "[dry-run] would run: install-host.sh ${inst_flags[*]} ${HOST_ARGS[*]}"
elif [ -x "$HERE/install-host.sh" ]; then
  say "Installing the governed host + adapters (prereqs provisioned + evidenced) …"
  "$HERE/install-host.sh" "${inst_flags[@]}" "${HOST_ARGS[@]}"
else
  say "install-host.sh not found beside this script — run: install-host.sh ${inst_flags[*]} ${HOST_ARGS[*]}"
fi
say "Done. Tier '$TIER' provisioned to the extent this device supports it."
