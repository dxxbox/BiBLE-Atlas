#!/usr/bin/env bash
#
# build_all.sh — 一键编译 BiBLE Atlas 指定或全部模块
#
# 用法见: ./build_all.sh --help
#
# 产物输出到 release/ 目录（无参时与原先一致；单模块时仅生成该模块相关产物）
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="${REPO_ROOT}/release"
LOG_DIR="${RELEASE_DIR}/logs"
BUILD_START=$(date '+%Y-%m-%d %H:%M:%S')

SKIP_TEST=false
VERBOSE=false
RUN_PYTHON=false
RUN_CLI=false
RUN_VSCODE=false
RUN_OC=false
HAVE_MODULE_PICK=false

usage() {
  cat <<'EOF'
BiBLE Atlas — build_all.sh

用法:
  ./build_all.sh [选项] [模块…]

无模块参数时: 编译全部模块（Python 服务端、Go CLI、VSCode 扩展、OpenClaw 插件），
              并执行各自回归测试（可用 --skip-test 跳过测试）。

模块参数（可多个，将依次执行所选模块）:
  --python, --server   Python 服务端 (bible/)：uv sync、ruff、mypy、uv build、pytest tests/
  --cli                Go 命令行 (bible_cli_go/)：go vet、go build、go test
  --vscode             VSCode 扩展 (bible_vscode/)：npm、tsc、打包 vsix
  --oc, --openclaw     OpenClaw 插件 (bible-oc-plugin/)：npm、typecheck、build、vitest

通用选项:
  --skip-test          跳过各模块的测试步骤，仅编译 / 打包
  --verbose            更详细输出（例如 pytest 不使用 -q）
  -h, --help           显示本说明并退出

示例:
  ./build_all.sh --cli                    # 仅构建 CLI 并跑 go test
  ./build_all.sh --python --skip-test     # 仅 Python 包与静态检查，不跑 pytest
  ./build_all.sh --vscode --oc            # 仅扩展与插件
  ./build_all.sh --verbose                # 全量构建且 pytest 详细输出

说明:
  · 模块日志仍写入 release/logs/（文件名与全量构建一致，未执行的步骤不产生对应日志）。
  · ruff / mypy 失败在全量与 --python 下均为「提示」，不单独阻断脚本（与原先一致）。
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help)
      usage
      exit 0
      ;;
    --skip-test)
      SKIP_TEST=true
      ;;
    --verbose)
      VERBOSE=true
      ;;
    --python | --server)
      RUN_PYTHON=true
      HAVE_MODULE_PICK=true
      ;;
    --cli)
      RUN_CLI=true
      HAVE_MODULE_PICK=true
      ;;
    --vscode)
      RUN_VSCODE=true
      HAVE_MODULE_PICK=true
      ;;
    --oc | --openclaw)
      RUN_OC=true
      HAVE_MODULE_PICK=true
      ;;
    *)
      echo "未知参数: $1" >&2
      echo "使用 ./build_all.sh --help 查看用法。" >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "${HAVE_MODULE_PICK}" == false ]]; then
  RUN_PYTHON=true
  RUN_CLI=true
  RUN_VSCODE=true
  RUN_OC=true
fi

# ── 颜色 ──────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

pass()    { echo -e "${GREEN}[PASS]${NC} $*"; }
fail()    { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
info()    { echo -e "${YELLOW}[INFO]${NC} $*"; }
section() { echo -e "\n${CYAN}${BOLD}══════════════════════════════════════════${NC}"; echo -e "${CYAN}${BOLD}  $*${NC}"; echo -e "${CYAN}${BOLD}══════════════════════════════════════════${NC}"; }

# run_log LOGFILE CMD... — 输出同时打印到终端并收集到日志文件
run_log() {
  local logfile="$1"; shift
  "$@" 2>&1 | tee "${logfile}"
  return "${PIPESTATUS[0]}"
}

FAILED_MODULES=()
LINT_MSGS=()
LINT_LOGS=()

PYTHON_TEST_RESULT="—"
GO_TEST_RESULT="—"
OC_TEST_RESULT="—"

rm -rf "${RELEASE_DIR}"
mkdir -p "${RELEASE_DIR}" "${LOG_DIR}"

GIT_BRANCH=$(git -C "${REPO_ROOT}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
GIT_COMMIT=$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_DIRTY=$(git -C "${REPO_ROOT}" diff --quiet 2>/dev/null && echo "clean" || echo "dirty")

# ══════════════════════════════════════════════════════════════════════
# Python 服务端 (bible)
# ══════════════════════════════════════════════════════════════════════
if [[ "${RUN_PYTHON}" == true ]]; then
  section "Python 服务器端 (bible) — 环境准备"
  cd "${REPO_ROOT}"
  info "uv sync --extra test --extra dev ..."
  if run_log "${LOG_DIR}/00-uv-sync.log" uv sync --extra test --extra dev; then
    pass "uv sync"
  else
    warn "uv sync 出现问题，继续编译..."
  fi

  section "Python 服务器端 (bible) — 检查与构建"
  cd "${REPO_ROOT}"

  info "ruff check ..."
  if run_log "${LOG_DIR}/01-ruff-check.log" uv run ruff check bible/; then
    pass "ruff check"
  else
    LINT_MSGS+=("ruff check — $(grep '^Found' "${LOG_DIR}/01-ruff-check.log" 2>/dev/null | head -1 || echo "see log")")
    LINT_LOGS+=("${LOG_DIR}/01-ruff-check.log")
  fi

  info "mypy ..."
  if run_log "${LOG_DIR}/02-mypy.log" uv run mypy bible/; then
    pass "mypy"
  else
    LINT_MSGS+=("mypy — $(grep '^Found' "${LOG_DIR}/02-mypy.log" 2>/dev/null | tail -1 || echo "see log")")
    LINT_LOGS+=("${LOG_DIR}/02-mypy.log")
  fi

  info "uv build ..."
  if run_log "${LOG_DIR}/03-uv-build.log" uv build --out-dir "${RELEASE_DIR}"; then
    pass "Python 服务器端 → release/"
  else
    fail "Python 服务器端编译失败"
  fi

  PYTHON_TEST_RESULT="skipped"
  if [[ "${SKIP_TEST}" == false ]]; then
    info "pytest ..."
    pytest_args=(tests/ -x)
    [[ "${VERBOSE}" == false ]] && pytest_args+=(-q)
    if run_log "${LOG_DIR}/04-pytest.log" uv run pytest "${pytest_args[@]}"; then
      pass "Python tests"
      PYTHON_TEST_RESULT="passed"
    else
      warn "Python 测试有失败"
      FAILED_MODULES+=("python-tests")
      PYTHON_TEST_RESULT="failed"
    fi
  fi
fi

# ══════════════════════════════════════════════════════════════════════
# Go CLI (bible_cli_go)
# ══════════════════════════════════════════════════════════════════════
if [[ "${RUN_CLI}" == true ]]; then
  section "Go CLI (bible_cli_go)"

  CLI_GO_DIR="${REPO_ROOT}/bible_cli_go"
  cd "${CLI_GO_DIR}"

  info "go vet ..."
  if run_log "${LOG_DIR}/05-go-vet.log" go vet ./...; then
    pass "go vet"
  else
    fail "go vet 失败"
  fi

  info "go build → release/bible"
  if run_log "${LOG_DIR}/06-go-build.log" go build -o "${RELEASE_DIR}/bible" ./cmd/bible-cli/; then
    pass "Go CLI → release/bible"
  else
    fail "Go CLI 编译失败"
  fi

  GO_TEST_RESULT="skipped"
  if [[ "${SKIP_TEST}" == false ]]; then
    info "go test ..."
    if run_log "${LOG_DIR}/07-go-test.log" go test ./... -race -count=1 -timeout=120s; then
      pass "Go tests"
      GO_TEST_RESULT="passed"
    else
      warn "Go 测试有失败"
      FAILED_MODULES+=("go-tests")
      GO_TEST_RESULT="failed"
    fi
  fi
fi

# ══════════════════════════════════════════════════════════════════════
# VSCode 扩展 (bible_vscode)
# ══════════════════════════════════════════════════════════════════════
if [[ "${RUN_VSCODE}" == true ]]; then
  section "VSCode 扩展 (bible_vscode)"

  VSCODE_DIR="${REPO_ROOT}/bible_vscode"
  cd "${VSCODE_DIR}"

  info "npm install ..."
  if run_log "${LOG_DIR}/08-vscode-npm-install.log" npm install --no-audit --no-fund; then
    pass "npm install"
  else
    fail "npm install 失败 (bible_vscode)"
  fi

  info "tsc --noEmit ..."
  if run_log "${LOG_DIR}/09-vscode-typecheck.log" npx tsc --noEmit; then
    pass "tsc --noEmit"
  else
    warn "TypeScript 有类型错误"
    FAILED_MODULES+=("vscode-typecheck")
  fi

  info "esbuild + vsce package → release/bible-vscode.vsix"
  if run_log "${LOG_DIR}/10-vscode-package.log" bash -c "cd '${VSCODE_DIR}' && npm run package && npx --yes @vscode/vsce@latest package --no-dependencies --skip-license -o '${RELEASE_DIR}/bible-vscode.vsix'"; then
    pass "VSIX → release/bible-vscode.vsix"
  else
    fail "VSIX 打包失败"
  fi
fi

# ══════════════════════════════════════════════════════════════════════
# OpenClaw 插件 (bible-oc-plugin)
# ══════════════════════════════════════════════════════════════════════
if [[ "${RUN_OC}" == true ]]; then
  section "OpenClaw 插件 (bible-oc-plugin)"

  OC_DIR="${REPO_ROOT}/bible-oc-plugin"
  cd "${OC_DIR}"

  info "npm install ..."
  if run_log "${LOG_DIR}/11-oc-npm-install.log" npm install --no-audit --no-fund; then
    pass "npm install"
  else
    fail "npm install 失败 (bible-oc-plugin)"
  fi

  info "typecheck ..."
  if run_log "${LOG_DIR}/12-oc-typecheck.log" npm run typecheck; then
    pass "typecheck"
  else
    warn "TypeScript 有类型错误"
    FAILED_MODULES+=("oc-plugin-typecheck")
  fi

  info "tsc build → dist/"
  if run_log "${LOG_DIR}/13-oc-build.log" npm run build; then
    pass "tsc build"
  else
    fail "bible-oc-plugin 编译失败"
  fi

  info "Copying dist → release/bible-oc-plugin/"
  mkdir -p "${RELEASE_DIR}/bible-oc-plugin"
  cp -r "${OC_DIR}/dist/"* "${RELEASE_DIR}/bible-oc-plugin/"
  cp "${OC_DIR}/package.json" "${RELEASE_DIR}/bible-oc-plugin/"
  cp "${OC_DIR}/openclaw.plugin.json" "${RELEASE_DIR}/bible-oc-plugin/" 2>/dev/null || true
  pass "OpenClaw 插件 → release/bible-oc-plugin/"

  OC_TEST_RESULT="skipped"
  if [[ "${SKIP_TEST}" == false ]]; then
    info "vitest ..."
    if run_log "${LOG_DIR}/14-oc-test.log" npm run test; then
      pass "vitest tests"
      OC_TEST_RESULT="passed"
    else
      warn "OpenClaw 插件测试有失败"
      FAILED_MODULES+=("oc-plugin-tests")
      OC_TEST_RESULT="failed"
    fi
  fi
fi

# ══════════════════════════════════════════════════════════════════════
# 生成 BUILD_INFO.md
# ══════════════════════════════════════════════════════════════════════

BUILD_END=$(date '+%Y-%m-%d %H:%M:%S')

BIBLE_SIZE=$(du -h "${RELEASE_DIR}/bible" 2>/dev/null | cut -f1 || echo "N/A")
VSIX_SIZE=$(du -h "${RELEASE_DIR}/bible-vscode.vsix" 2>/dev/null | cut -f1 || echo "N/A")
WHL_NAME=$(basename "${RELEASE_DIR}"/bible_atlas-*.whl 2>/dev/null || echo "N/A")
WHL_SIZE=$(du -h "${RELEASE_DIR}"/bible_atlas-*.whl 2>/dev/null | cut -f1 || echo "N/A")
SDIST_NAME=$(basename "${RELEASE_DIR}"/bible_atlas-*.tar.gz 2>/dev/null || echo "N/A")
SDIST_SIZE=$(du -h "${RELEASE_DIR}"/bible_atlas-*.tar.gz 2>/dev/null | cut -f1 || echo "N/A")
OC_SIZE=$(du -sh "${RELEASE_DIR}/bible-oc-plugin" 2>/dev/null | cut -f1 || echo "N/A")

PYTHON_VER=$(python3 --version 2>/dev/null || echo "N/A")
GO_VER=$(go version 2>/dev/null | awk '{print $3}' || echo "N/A")
NODE_VER=$(node --version 2>/dev/null || echo "N/A")

cat > "${RELEASE_DIR}/BUILD_INFO.md" <<BUILDEOF
# BiBLE Atlas — Build Info

> 由 \`build_all.sh\` 自动生成

## 构建环境

| 项目 | 值 |
|------|-----|
| 构建时间 | ${BUILD_START} → ${BUILD_END} |
| Git 分支 | \`${GIT_BRANCH}\` |
| Git 提交 | \`${GIT_COMMIT}\` (${GIT_DIRTY}) |
| Python | ${PYTHON_VER} |
| Go | ${GO_VER} |
| Node.js | ${NODE_VER} |

## 产物清单

### 1. Go CLI — \`bible\`

| | |
|---|---|
| 文件 | \`bible\` |
| 大小 | ${BIBLE_SIZE} |
| 说明 | BiBLE Atlas 命令行工具（当前平台原生二进制） |
| 源码 | \`bible_cli_go/\` |
| 测试 | ${GO_TEST_RESULT} |

**用途：** 提供 \`bible health\`、\`bible memory search/upload\`、\`bible knowledge\`、\`bible skills\` 等子命令，供终端和 IDE 插件调用与 Atlas 服务端交互。

**安装：** 将 \`bible\` 复制到 \`\$PATH\` 中的目录即可使用。

---

### 2. VSCode 扩展 — \`bible-vscode.vsix\`

| | |
|---|---|
| 文件 | \`bible-vscode.vsix\` |
| 大小 | ${VSIX_SIZE} |
| 说明 | Bible Atlas 的 VSCode/Cursor 扩展包 |
| 源码 | \`bible_vscode/\` |

**用途：** 在 VSCode/Cursor 中提供 memory 搜索、保存当前对话、任务状态查看等功能；注册 LM Tools 和 Chat Participant，支持 AI 助手直接调用 Bible Atlas。

**安装：**
\`\`\`bash
code --install-extension bible-vscode.vsix --force
# 或 Cursor
cursor --install-extension bible-vscode.vsix --force
\`\`\`

---

### 3. OpenClaw 插件 — \`bible-oc-plugin/\`

| | |
|---|---|
| 目录 | \`bible-oc-plugin/\` |
| 大小 | ${OC_SIZE} |
| 说明 | Bible Atlas 的 OpenClaw 平台插件（Context Engine） |
| 源码 | \`bible-oc-plugin/\` (项目根) |
| 测试 | ${OC_TEST_RESULT} |

**用途：** 为 OpenClaw 平台提供会话记忆自动召回、memory/knowledge/skill 工具注册、生命周期 hooks，通过 HTTP 与 Atlas 服务端通信。

**安装：**
\`\`\`bash
openclaw plugins install ./bible-oc-plugin --force
openclaw bible setup --base-url http://127.0.0.1:5555 --write
\`\`\`

---

### 4. Python 服务端包

| | |
|---|---|
| Wheel | \`${WHL_NAME}\` (${WHL_SIZE}) |
| Sdist | \`${SDIST_NAME}\` (${SDIST_SIZE}) |
| 说明 | BiBLE Atlas 服务端（FastAPI + OpenSearch + Celery） |
| 源码 | \`bible/\` |
| 测试 | ${PYTHON_TEST_RESULT} |

**用途：** 提供 RESTful API 服务，管理 memory/knowledge/skill 的导入、检索和异步任务调度。

**安装：**
\`\`\`bash
pip install ${WHL_NAME}
# 启动服务
python -m bible.main
\`\`\`

## 构建日志

所有编译过程的完整日志收集在 \`logs/\` 目录：

\`\`\`
$(ls -1 "${LOG_DIR}/"*.log 2>/dev/null | while read -r f; do printf "logs/%-35s %s\n" "$(basename "$f")" "$(du -h "$f" | cut -f1)"; done)
\`\`\`
BUILDEOF

# ══════════════════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════════════════
section "构建完成"

echo ""
echo "release/ 目录内容:"
echo "──────────────────────────────────────"
(cd "${RELEASE_DIR}" && find . -maxdepth 2 -not -path './logs*' -not -name '.gitkeep' -not -name '.gitignore' | sort | while read -r f; do
  if [[ -f "$f" ]]; then
    printf "  %-45s %s\n" "$f" "$(du -h "$f" | cut -f1)"
  elif [[ -d "$f" && "$f" != "." ]]; then
    printf "  %-45s %s\n" "$f/" ""
  fi
done)
echo "──────────────────────────────────────"
echo ""
echo -e "  ${DIM}构建日志:  release/logs/ ($(ls "${LOG_DIR}/"*.log 2>/dev/null | wc -l) 个文件)${NC}"
echo -e "  ${DIM}产物介绍:  release/BUILD_INFO.md${NC}"
echo ""

if [[ ${#LINT_MSGS[@]} -gt 0 ]]; then
  echo -e "${DIM}代码质量提示（不影响编译；日志路径在各条下一行，可 Ctrl+点击打开）:${NC}"
  for i in "${!LINT_MSGS[@]}"; do
    echo -e "  ${DIM}·${NC} ${LINT_MSGS[$i]}"
    echo "${LINT_LOGS[$i]}"
  done
  echo ""
fi

if [[ ${#FAILED_MODULES[@]} -gt 0 ]]; then
  echo -e "${RED}${BOLD}✗ 以下步骤失败:${NC}"
  for m in "${FAILED_MODULES[@]}"; do
    echo -e "  ${RED}•${NC} ${m}"
  done
  echo ""
  echo -e "${YELLOW}请修复失败项后再提交。${NC}"
  exit 1
else
  if [[ "${RUN_PYTHON}" == true && "${RUN_CLI}" == true && "${RUN_VSCODE}" == true && "${RUN_OC}" == true ]]; then
    pass "所有模块编译 & 测试通过！"
  else
    pass "所选模块编译 & 测试通过！"
  fi
  echo -e "${GREEN}${BOLD}  可以放心提交。${NC}"
fi
