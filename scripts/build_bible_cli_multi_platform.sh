#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CLI_DIR="${REPO_ROOT}/bible_cli_go"
DIST_DIR="${CLI_DIR}/dist"
PACKAGE_DIR="${DIST_DIR}/packages"

if [[ -n "${BIBLE_CLI_VERSION:-}" ]]; then
  VERSION="${BIBLE_CLI_VERSION}"
elif git -C "${REPO_ROOT}" describe --tags --exact-match >/dev/null 2>&1; then
  VERSION="$(git -C "${REPO_ROOT}" describe --tags --exact-match)"
else
  SHORT_SHA="$(git -C "${REPO_ROOT}" rev-parse --short HEAD)"
  VERSION="dev-${SHORT_SHA}"
fi

mkdir -p "${DIST_DIR}"
mkdir -p "${PACKAGE_DIR}"
cd "${CLI_DIR}"

echo "==> Building native binary"
go build -buildvcs=false -o "${DIST_DIR}/bible" ./cmd/bible-cli

echo "==> Cross-building target platforms"
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -buildvcs=false -o "${DIST_DIR}/bible_linux_amd64" ./cmd/bible-cli
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -buildvcs=false -o "${DIST_DIR}/bible_linux_arm64" ./cmd/bible-cli
GOOS=darwin GOARCH=amd64 CGO_ENABLED=0 go build -buildvcs=false -o "${DIST_DIR}/bible_darwin_amd64" ./cmd/bible-cli
GOOS=darwin GOARCH=arm64 CGO_ENABLED=0 go build -buildvcs=false -o "${DIST_DIR}/bible_darwin_arm64" ./cmd/bible-cli
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 go build -buildvcs=false -o "${DIST_DIR}/bible_windows_amd64.exe" ./cmd/bible-cli
GOOS=windows GOARCH=arm64 CGO_ENABLED=0 go build -buildvcs=false -o "${DIST_DIR}/bible_windows_arm64.exe" ./cmd/bible-cli

echo "==> Generating compatibility copies (bible-cli-go*)"
cp -f "${DIST_DIR}/bible" "${DIST_DIR}/bible-cli-go"
cp -f "${DIST_DIR}/bible_linux_amd64" "${DIST_DIR}/bible-cli-go_linux_amd64"
cp -f "${DIST_DIR}/bible_linux_arm64" "${DIST_DIR}/bible-cli-go_linux_arm64"
cp -f "${DIST_DIR}/bible_darwin_amd64" "${DIST_DIR}/bible-cli-go_darwin_amd64"
cp -f "${DIST_DIR}/bible_darwin_arm64" "${DIST_DIR}/bible-cli-go_darwin_arm64"
cp -f "${DIST_DIR}/bible_windows_amd64.exe" "${DIST_DIR}/bible-cli-go_windows_amd64.exe"
cp -f "${DIST_DIR}/bible_windows_arm64.exe" "${DIST_DIR}/bible-cli-go_windows_arm64.exe"

echo "==> Packaging archives with version: ${VERSION}"
rm -f "${PACKAGE_DIR}"/bible_"${VERSION}"_*

tar -C "${DIST_DIR}" -czf "${PACKAGE_DIR}/bible_${VERSION}_linux_amd64.tar.gz" bible_linux_amd64
tar -C "${DIST_DIR}" -czf "${PACKAGE_DIR}/bible_${VERSION}_linux_arm64.tar.gz" bible_linux_arm64
tar -C "${DIST_DIR}" -czf "${PACKAGE_DIR}/bible_${VERSION}_darwin_amd64.tar.gz" bible_darwin_amd64
tar -C "${DIST_DIR}" -czf "${PACKAGE_DIR}/bible_${VERSION}_darwin_arm64.tar.gz" bible_darwin_arm64
(
  cd "${DIST_DIR}"
  zip -q -j "${PACKAGE_DIR}/bible_${VERSION}_windows_amd64.zip" bible_windows_amd64.exe
  zip -q -j "${PACKAGE_DIR}/bible_${VERSION}_windows_arm64.zip" bible_windows_arm64.exe
)

echo "==> Build completed. Artifacts:"
ls -lh "${DIST_DIR}"/bible*
echo "==> Versioned packages:"
ls -lh "${PACKAGE_DIR}"/bible_"${VERSION}"_*
