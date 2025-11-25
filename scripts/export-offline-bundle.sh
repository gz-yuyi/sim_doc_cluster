#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/export-offline-bundle.sh <output-dir>

拉取最新镜像并导出离线包，包含：
- images/sim-doc-cluster-images.tar
- docker-compose.yml
- .env.example
- offline-deploy.md
EOF
  exit 1
}

log() {
  echo "[offline-bundle] $*"
}

require_file() {
  local path="$1"
  local name="$2"
  if [[ ! -f "$path" ]]; then
    echo "Missing required file: $name ($path)" >&2
    exit 1
  fi
}

OUTPUT_DIR="${1:-}"
[[ -z "$OUTPUT_DIR" ]] && usage

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"
ENV_SAMPLE="$PROJECT_ROOT/.env.example"
DOC_FILE="$PROJECT_ROOT/docs/offline-deploy.md"

require_file "$COMPOSE_FILE" "docker-compose.yml"
require_file "$ENV_SAMPLE" ".env.example"
require_file "$DOC_FILE" "docs/offline-deploy.md"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker command not found. Please install Docker first." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose plugin is required (try upgrading Docker Desktop / CLI)." >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR/images"

log "Collecting images from docker-compose.yml"
mapfile -t IMAGES < <(cd "$PROJECT_ROOT" && docker compose -f "$COMPOSE_FILE" config --images | sort -u)

if [[ ${#IMAGES[@]} -eq 0 ]]; then
  echo "No images found in docker-compose.yml" >&2
  exit 1
fi

log "Pulling latest images"
for image in "${IMAGES[@]}"; do
  log "Pulling $image"
  docker pull "$image"
done

ARCHIVE_PATH="$OUTPUT_DIR/images/sim-doc-cluster-images.tar"
log "Saving images to $ARCHIVE_PATH"
docker save "${IMAGES[@]}" -o "$ARCHIVE_PATH"

log "Copying docker-compose.yml"
cp "$COMPOSE_FILE" "$OUTPUT_DIR/docker-compose.yml"

log "Copying .env.example"
cp "$ENV_SAMPLE" "$OUTPUT_DIR/.env.example"

log "Copying offline-deploy.md"
cp "$DOC_FILE" "$OUTPUT_DIR/offline-deploy.md"

if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$ARCHIVE_PATH" > "$OUTPUT_DIR/images/sim-doc-cluster-images.sha256"
  log "Wrote checksum to images/sim-doc-cluster-images.sha256"
elif command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "$ARCHIVE_PATH" > "$OUTPUT_DIR/images/sim-doc-cluster-images.sha256"
  log "Wrote checksum to images/sim-doc-cluster-images.sha256"
else
  log "sha256sum/shasum not found; skipping checksum"
fi

log "Done. Bundle is ready at $OUTPUT_DIR"
