#!/usr/bin/env bash
# Update the installed ALPHA checkout to a release tag, check it, and go back by itself on failure.
#
# Usage: scripts/update.sh [--to TAG] [--check-only] [--service NAME] [--no-restart]
#   --to TAG        install this tag (default: the newest r* tag on origin)
#   --check-only    change nothing; run the smoke check on the version that is installed now
#   --service NAME  the user service to restart and check (default: alpha-workstation.service)
#   --no-restart    do not restart or check the service
#
# Steps: install the tag with every locked environment (root, each worker folder that holds a
# uv.lock, the web app), restart the service, run the smoke check. When any step fails, the
# checkout returns to the last good commit, which is kept in .update/last-good.
# Exit 0: done or already current. Exit 1: failed and returned to the last good version.
# Exit 2: failed and the return failed too. Needs git and uv (and npm for the web app); no sudo.
# It does not use the Python environment it replaces: it is plain bash.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
service='alpha-workstation.service'
target=''
check_only=0
restart=1
unit_found=0
notes_base='https://github.com/Project-alpha-research/Project-ALPHA/releases/tag'

say() { printf 'update: %s\n' "$*"; }
fail() { printf 'update: %s\n' "$*" >&2; }

while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        --to) [ "$#" -ge 2 ] || { fail 'Option --to needs a tag, for example --to r2026.11.24.5.'; exit 2; }
              target="$2"; shift ;;
        --check-only) check_only=1 ;;
        --service) [ "$#" -ge 2 ] || { fail 'Option --service needs a name.'; exit 2; }
                   service="$2"; shift ;;
        --no-restart) restart=0 ;;
        *) fail "Unknown option: $1. Run scripts/update.sh --help."; exit 2 ;;
    esac
    shift
done

cd "$root"
state_dir="$root/.update"

unit_exists() { systemctl --user cat "$service" >/dev/null 2>&1; }

unit_env() { # value of one Environment= variable of the unit, or nothing
    systemctl --user show -p Environment --value "$service" 2>/dev/null |
        tr ' ' '\n' | sed -n "s/^$1=//p" | head -1
}

current_label() {
    git describe --tags --exact-match 2>/dev/null || git rev-parse --short HEAD
}

install_here() { # install the checked-out version: root, every worker with a lock, the web app
    uv sync --locked || { fail 'The root environment did not install.'; return 1; }
    local lock folder
    for lock in "$root"/workers/*/uv.lock; do
        [ -e "$lock" ] || continue
        folder="$(dirname -- "$lock")"
        say "Installing the worker environment ${folder##*/}."
        (cd "$folder" && uv sync --locked) || { fail "The worker environment ${folder##*/} did not install."; return 1; }
    done
    if [ -f "$root/apps/alpha-web/frontend/package-lock.json" ]; then
        say 'Building the web app.'
        (cd "$root/apps/alpha-web/frontend" && npm ci && npm run build) || { fail 'The web app did not build.'; return 1; }
    fi
}

restart_service() {
    if [ "$restart" = 0 ]; then
        say 'Service restart skipped (--no-restart).'
        return 0
    fi
    if ! unit_exists; then
        say "Service $service does not exist here: restart skipped."
        return 0
    fi
    systemctl --user restart "$service" || { fail "The service $service did not restart."; return 1; }
    unit_found=1
}

check_service() {
    local port pid listeners waited=0
    port="$(unit_env ALPHA_WEB_PORT)"
    port="${port:-8801}"
    while [ "$waited" -lt 30 ]; do
        pid="$(systemctl --user show -p MainPID --value "$service" 2>/dev/null || true)"
        listeners="$(ss -ltnp "sport = :$port" 2>/dev/null || true)"
        if systemctl --user is-active --quiet "$service" && [ -n "$pid" ] && [ "$pid" != 0 ]; then
            case "$listeners" in *"pid=$pid,"*) break ;; esac
        fi
        sleep 1
        waited=$((waited + 1))
    done
    if [ "$waited" -ge 30 ]; then
        fail "The service $service is not active and listening on port $port after 30 seconds."
        return 1
    fi
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://127.0.0.1:$port/" || true)"
    case "$code" in
        2??|3??) ;;
        *) fail "The Workstation page on port $port answered with status ${code:-none}."; return 1 ;;
    esac
    say "Checked: the service is active and the Workstation answers on port $port."
}

smoke_check() {
    "$root/.venv/bin/alpha" --help >/dev/null 2>&1 || { fail 'The command "alpha --help" failed.'; return 1; }
    "$root/.venv/bin/alpha" next >/dev/null 2>&1 || { fail 'The command "alpha next" failed.'; return 1; }
    local lock folder
    for lock in "$root"/workers/*/uv.lock; do
        [ -e "$lock" ] || continue
        folder="$(dirname -- "$lock")"
        [ -d "$folder/.venv" ] || { fail "The worker ${folder##*/} has no environment (.venv)."; return 1; }
    done
    if [ "$unit_found" = 1 ] || { [ "$check_only" = 1 ] && [ "$restart" = 1 ] && unit_exists; }; then
        check_service || return 1
    fi
    local data="${ALPHA_DATA_DIR:-}"
    if [ -z "$data" ] && unit_exists; then data="$(unit_env ALPHA_DATA_DIR)"; fi
    if [ -z "$data" ] && [ -d "$root/data" ]; then data="$root/data"; fi
    if [ -n "$data" ] && [ -d "$data" ]; then
        # `alpha data coverage` only reads. --metadata-only skips the slow file check.
        ALPHA_DATA_DIR="$data" "$root/.venv/bin/alpha" data coverage --metadata-only >/dev/null 2>&1 ||
            { fail 'The command "alpha data coverage" failed on the data home.'; return 1; }
        say 'Checked: the data home can be read.'
    else
        say 'Data home check skipped: no data home found (set ALPHA_DATA_DIR).'
    fi
}

return_to_last_good() {
    local good="$1"
    say "Going back to the last good version ${good:0:12}."
    git checkout --detach "$good" >/dev/null 2>&1 && install_here && restart_service && smoke_check
}

if [ "$check_only" = 1 ]; then
    say "Checking the installed version $(current_label)."
    if smoke_check; then
        say "The installed version $(current_label) is healthy."
        exit 0
    fi
    fail "The installed version $(current_label) is not healthy."
    exit 1
fi

# a. refuse an unsafe start
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    fail 'This checkout has uncommitted changes to tracked files. Commit or undo them, then run again.'
    exit 1
fi
free_kb="$(df -Pk "$root" | awk 'NR==2 {print $4}')"
if [ "${free_kb:-0}" -lt 3145728 ]; then
    fail 'Less than 3 GB of disk is free. Free some space, then run again.'
    exit 1
fi

# b. record the way back and pick the target
git fetch --tags --force origin >/dev/null 2>&1 || { fail 'Could not fetch tags from origin.'; exit 1; }
if [ -z "$target" ]; then
    target="$(git tag -l 'r*' --sort=-version:refname | head -1)"
    [ -n "$target" ] || { fail 'There is no release tag (r*) on origin yet.'; exit 1; }
fi
target_commit="$(git rev-parse -q --verify "refs/tags/$target^{commit}")" ||
    { fail "The tag $target does not exist."; exit 1; }
good="$(git rev-parse HEAD)"
from="$(current_label)"
if [ "$good" = "$target_commit" ]; then
    say "Already at $target. Nothing to do."
    exit 0
fi
mkdir -p "$state_dir"
printf '%s\n' "$good" >"$state_dir/last-good"
say "from $from to $target"

# c to e. install, restart, check
say "Installing $target."
if git checkout --detach "$target_commit" >/dev/null 2>&1 && install_here && restart_service && smoke_check; then
    # g. success
    git rev-parse HEAD >"$state_dir/last-good"
    say "Installed now: $target."
    say 'Checked: alpha runs, the worker environments exist, and the data home and the service work as shown above.'
    say "Release notes: $notes_base/$target"
    exit 0
fi

# f. failure: go back
fail "The update to $target failed."
if return_to_last_good "$good"; then
    fail "Returned to the last good version $from."
    exit 1
fi
fail "The return failed too. Last good commit: $good. Run: git checkout --detach $good, then scripts/update.sh --check-only."
exit 2
