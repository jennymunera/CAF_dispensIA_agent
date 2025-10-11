#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Uso:
  ./deploy.sh <function_app_name> <resource_group> [subscription_id]

Requisitos:
  - Azure CLI (az) con sesión iniciada (az login)
  - Azure Functions Core Tools (func)
  - python3
  - El archivo local.settings.json con los valores a sincronizar

Pasos que ejecuta:
  1. Sincroniza los Application Settings en Azure usando local.settings.json
  2. Publica el código con func azure functionapp publish
  3. Reinicia la Function App
EOF
}

if [[ $# -lt 2 ]]; then
  usage
  exit 1
fi

FUNCTION_APP_NAME="$1"
RESOURCE_GROUP="$2"
SUBSCRIPTION_ID="${3:-}"

for cmd in az func python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "❌ No se encontró '$cmd' en PATH. Instálalo antes de continuar." >&2
    exit 1
  fi
done

# Verificar sesión activa de Azure
if ! az account show >/dev/null 2>&1; then
  echo "❌ No hay sesión activa en Azure. Ejecuta 'az login' e intenta de nuevo." >&2
  exit 1
fi

if [[ -n "$SUBSCRIPTION_ID" ]]; then
  echo "🔄 Seleccionando suscripción '$SUBSCRIPTION_ID'"
  az account set --subscription "$SUBSCRIPTION_ID"
fi

SETTINGS_TMP="$(mktemp)"
trap 'rm -f "$SETTINGS_TMP"' EXIT

echo "📄 Generando payload de Application Settings desde local.settings.json"
python3 <<'PY' >"$SETTINGS_TMP"
import json
import sys
from pathlib import Path

data = json.loads(Path("local.settings.json").read_text(encoding="utf-8"))
values = data.get("Values", {})
# Puedes excluir claves sensibles específicas si es necesario, ej.:
# for key in ("AzureWebJobsStorage",):
#     values.pop(key, None)
json.dump(values, sys.stdout)
PY

echo "🚀 Enviando Application Settings a Azure"
az functionapp config appsettings set \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  --settings @"$SETTINGS_TMP" \
  >/dev/null

echo "🛠️ Publicando Function App '$FUNCTION_APP_NAME'"
func azure functionapp publish "$FUNCTION_APP_NAME"

echo "🔁 Reiniciando Function App"
az functionapp restart \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP_NAME" \
  >/dev/null

echo "✅ Despliegue completado correctamente"
