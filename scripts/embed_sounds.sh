#!/usr/bin/env bash
# Re-build all obfuscated sound modules from the sounds/ folder.
#
# Convention: a file at ``sounds/<slot>.wav`` becomes
# ``src/flamechat/ui/_<slot>_data.py``. A number suffix like
# ``sounds/typing1.wav`` maps to the ``typing_1`` slot, and sounds.py
# auto-discovers all ``_typing_*_data`` modules for random playback.
#
# Usage:
#   ./scripts/embed_sounds.sh
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"

if [[ ! -d sounds ]]; then
    echo "No sounds/ folder found at $(pwd)/sounds" >&2
    exit 1
fi

shopt -s nullglob
found=0
for wav in sounds/*.wav sounds/*.WAV; do
    name="$(basename "$wav" .wav)"
    name="$(basename "$name" .WAV)"
    # Insert underscore before trailing digit(s): typing1 -> typing_1
    slot="$(echo "$name" | sed -E 's/([A-Za-z])([0-9]+)$/\1_\2/' | tr '[:upper:]' '[:lower:]')"
    echo "→ $wav  ⇒  slot '$slot'"
    "$PY" scripts/embed_wav.py "$wav" "$slot"
    found=$((found + 1))
done

if [[ $found -eq 0 ]]; then
    echo "No WAV files found in sounds/" >&2
    exit 1
fi

echo ""
echo "Embedded $found sound(s). Restart FlameChat to pick up the new bundles."
