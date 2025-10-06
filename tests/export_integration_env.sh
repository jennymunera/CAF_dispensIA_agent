#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

_read_setting() {
    local key="$1"
    python3 - <<'PY' "$ROOT_DIR" "$key"
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
key = sys.argv[2]

settings_path = root / "local.settings.json"
if settings_path.exists():
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        value = data.get("Values", {}).get(key)
        if value:
            print(value)
    except json.JSONDecodeError:
        pass
PY
}

export DOCUMENTS_BASE_PATH="${DOCUMENTS_BASE_PATH:-basedocuments}"
export RAW_DOCUMENTS_FOLDER="${RAW_DOCUMENTS_FOLDER:-raw}"
export RESULTS_FOLDER="${RESULTS_FOLDER:-results}"
export DEFAULT_AGENT_PROMPT_FILE="${DEFAULT_AGENT_PROMPT_FILE:-agente_extractor.txt}"
export DEFAULT_CHAINED_PROMPT_FILE="${DEFAULT_CHAINED_PROMPT_FILE:-agente_clasificador.txt}"

export INTEGRATION_TESTS=true

: "${TEST_STORAGE_CONNECTION_STRING:=$(_read_setting AZURE_STORAGE_CONNECTION_STRING)}"
export TEST_STORAGE_CONNECTION_STRING

export TEST_STORAGE_CONTAINER="${TEST_STORAGE_CONTAINER:-dispensia-documents}"
export TEST_PROJECT_ID="${TEST_PROJECT_ID:-basedocuments/CFA007671}"
export TEST_FUNCTION_BASE_URL="${TEST_FUNCTION_BASE_URL:-http://localhost:7071/api}"
export TEST_FUNCTION_KEY="${TEST_FUNCTION_KEY:-}" # usar la function key si aplica
export TEST_ROUTER_QUEUE_NAME="${TEST_ROUTER_QUEUE_NAME:-dispensas-router-in}"

: "${TEST_SERVICE_BUS_CONNECTION:=$(_read_setting SERVICE_BUS_CONNECTION)}"
export TEST_SERVICE_BUS_CONNECTION

export TEST_MODEL="${TEST_MODEL:-gpt-5-mini}"
export TEST_RESULTS_TIMEOUT="${TEST_RESULTS_TIMEOUT:-300}"
export TEST_TARGET_BLOB="${TEST_TARGET_BLOB:-raw/EED-048.PDF}"

echo "Variables de integración cargadas. Ajusta las que queden vacías antes de ejecutar las pruebas." >&2
