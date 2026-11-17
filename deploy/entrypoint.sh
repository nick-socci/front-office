#!/bin/sh
# Start a Dagster process of the production image (spec 0218, ADR 0133).
#
# `$DAGSTER_HOME/dagster.yaml` is where Dagster reads the instance's settings, and `$DAGSTER_HOME`
# is a volume (the run history lives in it), so the settings are copied in from the image on every
# start: a deploy of a new commit changes them, and a volume restored from elsewhere cannot keep
# old ones.
set -eu
: "${DAGSTER_HOME:?DAGSTER_HOME must name the instance directory}"
cp /app/deploy/dagster.yaml "$DAGSTER_HOME/dagster.yaml"
exec "$@"
