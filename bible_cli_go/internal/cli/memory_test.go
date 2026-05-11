package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"bible-cli-go/internal/cache"

	nethttp "net/http"
	"net/http/httptest"
)

// ---------------------------------------------------------------------------
// memory upload — argument validation tests (no network required)
// ---------------------------------------------------------------------------

func TestRunMemoryMissingAction(t *testing.T) {
	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory"}, &out, &errBuf)
	if exitCode != 1 {
		t.Fatalf("expected exit 1, got %d", exitCode)
	}
	resp := decodeRunResponse(t, out.String())
	if resp.Error == nil || resp.Error.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS, got %q", out.String())
	}
}

func TestRunMemoryUploadMissingSessionDir(t *testing.T) {
	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "upload"}, &out, &errBuf)
	if exitCode != 1 {
		t.Fatalf("expected exit 1, got %d", exitCode)
	}
	resp := decodeRunResponse(t, out.String())
	if resp.Error == nil || resp.Error.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS, got %q", out.String())
	}
	if !strings.Contains(resp.Error.Message, "session directory") {
		t.Fatalf("expected 'session directory' in message, got %q", resp.Error.Message)
	}
}

func TestRunMemoryUploadNonExistentDir(t *testing.T) {
	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "upload", "/tmp/no-such-dir-for-bible-test"}, &out, &errBuf)
	if exitCode != 1 {
		t.Fatalf("expected exit 1, got %d", exitCode)
	}
	resp := decodeRunResponse(t, out.String())
	if resp.Error == nil || resp.Error.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS, got %q", out.String())
	}
}

func TestRunMemoryUploadInvalidMessageJSON(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "message.json"), []byte("not-json"), 0o644); err != nil {
		t.Fatal(err)
	}
	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "upload", dir}, &out, &errBuf)
	if exitCode != 1 {
		t.Fatalf("expected exit 1 for invalid JSON, got %d", exitCode)
	}
	resp := decodeRunResponse(t, out.String())
	if resp.Error == nil || resp.Error.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS, got %q", out.String())
	}
}

func TestRunMemoryUploadMissingKbIndex(t *testing.T) {
	dir := t.TempDir()
	msg := map[string]any{
		"schema_version": "1.0",
		"session_id":     "test-session-no-kb",
		"requests":       []any{},
	}
	data, _ := json.Marshal(msg)
	if err := os.WriteFile(filepath.Join(dir, "message.json"), data, 0o644); err != nil {
		t.Fatal(err)
	}
	// Ensure env is unset
	t.Setenv("BIBLE_MEMORY_KB_INDEX", "")

	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "upload", dir}, &out, &errBuf)
	if exitCode != 1 {
		t.Fatalf("expected exit 1 for missing kb_index, got %d", exitCode)
	}
	resp := decodeRunResponse(t, out.String())
	if resp.Error == nil || !strings.Contains(resp.Error.Message, "kb_index") {
		t.Fatalf("expected kb_index error, got %q", out.String())
	}
}

func TestRunMemoryUploadAllMissingBaseDir(t *testing.T) {
	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "upload-all"}, &out, &errBuf)
	if exitCode != 1 {
		t.Fatalf("expected exit 1, got %d", exitCode)
	}
	resp := decodeRunResponse(t, out.String())
	if resp.Error == nil || resp.Error.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS, got %q", out.String())
	}
}

func TestRunMemorySearchMissingQuery(t *testing.T) {
	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "search"}, &out, &errBuf)
	if exitCode != 1 {
		t.Fatalf("expected exit 1, got %d", exitCode)
	}
	resp := decodeRunResponse(t, out.String())
	if resp.Error == nil || resp.Error.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS, got %q", out.String())
	}
}

func TestRunMemoryUploadLocalCacheSkip(t *testing.T) {
	dir := t.TempDir()
	msg := map[string]any{
		"schema_version": "1.0",
		"session_id":     "test-session-cache-skip",
		"requests":       []any{},
	}
	data, _ := json.Marshal(msg)
	if err := os.WriteFile(filepath.Join(dir, "message.json"), data, 0o644); err != nil {
		t.Fatal(err)
	}

	// Build meta.json so that meta_hash can be computed.
	metaContent := map[string]any{
		"memory_id": "mem_test-session-cache-skip",
		"title":     "test-session-cache-skip",
		"abstract":  "[空会话]",
	}
	metaData, _ := json.Marshal(metaContent)
	if err := os.WriteFile(filepath.Join(dir, "meta.json"), metaData, 0o644); err != nil {
		t.Fatal(err)
	}

	// Pre-compute the meta_hash the same way the command would.
	hash, err := cache.SHA256File(filepath.Join(dir, "meta.json"))
	if err != nil {
		t.Fatal(err)
	}

	kbIndex := "kb_test"
	if err := cache.SaveCache(dir, cache.MemoryCacheEntry{
		MemoryID:     "mem_test-session-cache-skip",
		KbIndex:      kbIndex,
		MetaHash:     hash,
		UploadStatus: "completed",
		UploadedAt:   time.Now().UTC().Format(time.RFC3339),
	}); err != nil {
		t.Fatal(err)
	}

	t.Setenv("BIBLE_MEMORY_KB_INDEX", kbIndex)

	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "upload", dir}, &out, &errBuf)
	if exitCode != 0 {
		t.Fatalf("expected exit 0 for cache-hit skip, got %d: %s", exitCode, out.String())
	}
	resp := decodeRunResponse(t, out.String())
	if !resp.OK {
		t.Fatalf("expected ok=true for cache-hit skip, got %q", out.String())
	}
	dataMap, ok := resp.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data, got %T", resp.Data)
	}
	if dataMap["status"] != "skipped" {
		t.Fatalf("expected status=skipped, got %v", dataMap["status"])
	}
}

// ---------------------------------------------------------------------------
// memory upload — integration test with fake server
// ---------------------------------------------------------------------------

func TestRunMemoryUploadAccepted(t *testing.T) {
	dir := t.TempDir()
	msg := map[string]any{
		"schema_version": "1.0",
		"session_id":     "test-session-upload-accepted",
		"requests":       []any{},
	}
	data, _ := json.Marshal(msg)
	if err := os.WriteFile(filepath.Join(dir, "message.json"), data, 0o644); err != nil {
		t.Fatal(err)
	}

	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path == "/api/import/memory" && r.Method == nethttp.MethodPost {
			w.WriteHeader(nethttp.StatusAccepted)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"task_id":      "task-test-123",
				"memory_id":    "mem_test-session-upload-accepted",
				"domain":       "MEMORY",
				"status":       "queued",
				"message":      "Memory import accepted.",
			})
			return
		}
		w.WriteHeader(nethttp.StatusNotFound)
	}))
	defer server.Close()

	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)
	t.Setenv("BIBLE_MEMORY_KB_INDEX", "kb_default")

	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "upload", dir}, &out, &errBuf)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d: %s", exitCode, out.String())
	}
	resp := decodeRunResponse(t, out.String())
	if !resp.OK {
		t.Fatalf("expected ok=true, got %q", out.String())
	}

	// Verify cache was written with task_id.
	cacheData, err := os.ReadFile(filepath.Join(dir, ".bible-memory-cache.json"))
	if err != nil {
		t.Fatalf("expected .bible-memory-cache.json to exist: %v", err)
	}
	var cacheEntry map[string]any
	if err := json.Unmarshal(cacheData, &cacheEntry); err != nil {
		t.Fatalf("cache file is not valid JSON: %v", err)
	}
	if cacheEntry["task_id"] != "task-test-123" {
		t.Fatalf("expected task_id=task-test-123 in cache, got %v", cacheEntry["task_id"])
	}
}

func TestRunMemoryStatusMissingIdentifier(t *testing.T) {
	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "status"}, &out, &errBuf)
	if exitCode != 1 {
		t.Fatalf("expected exit 1, got %d", exitCode)
	}
	resp := decodeRunResponse(t, out.String())
	if resp.Error == nil || resp.Error.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS, got %q", out.String())
	}
}

func TestRunMemoryListCallsServer(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path == "/api/search/memory" && r.Method == nethttp.MethodPost {
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{"items": []any{}, "total": 0},
			})
			return
		}
		w.WriteHeader(nethttp.StatusNotFound)
	}))
	defer server.Close()

	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "list"}, &out, &errBuf)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d: %s", exitCode, out.String())
	}
	resp := decodeRunResponse(t, out.String())
	if !resp.OK {
		t.Fatalf("expected ok=true, got %q", out.String())
	}
}

func TestRunMemoryCacheStatusEmptyDir(t *testing.T) {
	dir := t.TempDir()
	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "cache-status", dir}, &out, &errBuf)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d: %s", exitCode, out.String())
	}
	resp := decodeRunResponse(t, out.String())
	if !resp.OK {
		t.Fatalf("expected ok=true, got %q", out.String())
	}
}

func TestRunMemoryUploadAllEmptyDir(t *testing.T) {
	dir := t.TempDir()
	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "upload-all", dir}, &out, &errBuf)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d: %s", exitCode, out.String())
	}
	resp := decodeRunResponse(t, out.String())
	if !resp.OK {
		t.Fatalf("expected ok=true, got %q", out.String())
	}
}

func TestRunMemoryBuildMeta(t *testing.T) {
	dir := t.TempDir()
	msg := map[string]any{
		"schema_version": "1.0",
		"session_id":     "build-meta-test",
		"requests": []any{
			map[string]any{
				"requestId": "req_0",
				"message":   map[string]any{"text": "How does BiBLE work?"},
				"response":  []any{},
			},
		},
	}
	data, _ := json.Marshal(msg)
	if err := os.WriteFile(filepath.Join(dir, "message.json"), data, 0o644); err != nil {
		t.Fatal(err)
	}

	var out, errBuf bytes.Buffer
	exitCode := Run([]string{"memory", "build-meta", dir}, &out, &errBuf)
	if exitCode != 0 {
		t.Fatalf("expected exit 0, got %d: %s", exitCode, out.String())
	}
	resp := decodeRunResponse(t, out.String())
	if !resp.OK {
		t.Fatalf("expected ok=true, got %q", out.String())
	}
	dataMap, ok := resp.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data")
	}
	if dataMap["memory_id"] != "mem_build-meta-test" {
		t.Fatalf("expected memory_id=mem_build-meta-test, got %v", dataMap["memory_id"])
	}
}
