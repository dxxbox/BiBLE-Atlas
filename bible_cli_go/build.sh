#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${ROOT}/target"
BINARY="${TARGET}/bible"

cd "${ROOT}"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }
info() { echo -e "${YELLOW}[INFO]${NC} $*"; }

# ── vet ──────────────────────────────────────────────────────────────
info "go vet ..."
go vet ./... && pass "vet" || fail "vet failed"

# ── build ─────────────────────────────────────────────────────────────
info "Building binary → ${BINARY}"
mkdir -p "${TARGET}"
go build -o "${BINARY}" ./cmd/bible-cli/ && pass "build → ${BINARY}" || fail "build failed"

# ── test ──────────────────────────────────────────────────────────────
info "Running tests (race detector) ..."
go test ./... -race -count=1 -timeout=120s && pass "all tests" || fail "tests failed"

echo ""
pass "Done. Binary: ${BINARY}"
