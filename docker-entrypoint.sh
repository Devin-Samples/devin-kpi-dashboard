#!/bin/sh
# Generate the synthetic demo DB when no API key is configured.
if [ -z "$DEVIN_API_KEY" ]; then
    python -m devin_kpi demo-data || true
fi
exec "$@"
