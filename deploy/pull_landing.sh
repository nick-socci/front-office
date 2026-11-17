#!/usr/bin/env bash
# Pull a copy of the production landing zone (spec 0218, ADR 0137, R4.2 and R5.1).
#
# usage: pull_landing.sh SOURCE DESTINATION [extra rsync options, e.g. -n]
#
# The NAS runs it hourly: SOURCE `front-office@mothership:./` (its key is restricted to
# `rrsync -ro` on the landing zone, so the path is relative to it). The laptop runs it by hand:
# SOURCE `mothership:data/raw/`, never while a build reads the copy.
#
# A landing zone only ever gains captures (ADR 0014), so the pull adds and never deletes:
# `--ignore-existing`, no `--delete`, and `*.tmp-*` (a capture being written) left out. An option
# that deletes is refused. After a good run it writes `last_pull_ok` beside the destination, so a
# pull that has failed for days shows as a stale file (R5.4).
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: $0 SOURCE DESTINATION [extra rsync options]" >&2
  exit 2
fi
source_path=$1
destination=$2
shift 2

for option in "$@"; do
  case "$option" in
    --delete*|--remove-source-files|--del)
      echo "refused: a landing zone is never deleted from ($option)" >&2
      exit 2
      ;;
  esac
done

mkdir -p "$destination"

rsync --archive --ignore-existing --exclude '*.tmp-*' "$@" "$source_path" "$destination/"

# A dry run copies nothing and must not mark a pull good: `--dry-run`, `-n`, or `n` inside a
# cluster of short options such as `-an` or `-nv`.
for option in "$@"; do
  case "$option" in
    --dry-run) exit 0 ;;
    --*) ;;
    -*n*) exit 0 ;;
  esac
done
date -u +%Y-%m-%dT%H:%M:%SZ > "$(dirname "$(realpath "$destination")")/last_pull_ok"
