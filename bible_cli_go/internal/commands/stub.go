// Package commands – stub.go
//
// Stub mode is activated by setting BIBLE_CLI_STUB_MODE=1 in the environment.
// When active, all commands return pre-canned "stub" responses instead of
// hitting the real server.  This is intentionally designed for integration
// testing between the VS Code plugin and the CLI: the plugin can exercise every
// code-path end-to-end without needing a running Bible server.
//
// Stub responses are intentionally minimal but structurally valid – they match
// the envelope shape that the VS Code extension expects.
//
// When the server IS running, stub mode is ignored unless BIBLE_CLI_STUB_MODE=1
// is explicitly set.  Network / HTTP errors are returned to the caller (no automatic stub).
package commands

import (
	"fmt"
	"os"
	"strings"
	"time"
)

const (
	responseModeServer = "server"
	responseModeStub   = "stub"
)

// isStubMode returns true when BIBLE_CLI_STUB_MODE=1 is set.
func isStubMode() bool {
	v := strings.ToLower(strings.TrimSpace(os.Getenv("BIBLE_CLI_STUB_MODE")))
	return v == "1" || v == "true" || v == "yes"
}

// --- Stub response helpers --------------------------------------------------
// Each helper mirrors the structure returned by the corresponding real API.

// decorateServerResponse marks a successful non-stub payload so callers and
// logs can distinguish real server responses from stub fallbacks.
func decorateServerResponse(payload map[string]any) map[string]any {
	if payload == nil {
		return map[string]any{"stub": false, "response_mode": responseModeServer}
	}
	if _, ok := payload["stub"]; !ok {
		payload["stub"] = false
	}
	if _, ok := payload["response_mode"]; !ok {
		payload["response_mode"] = responseModeServer
	}
	return payload
}

// decorateStubResponse marks a synthetic stub payload with an explicit reason.
func decorateStubResponse(payload map[string]any, reason string) map[string]any {
	if payload == nil {
		payload = map[string]any{}
	}
	payload["stub"] = true
	payload["response_mode"] = responseModeStub
	if strings.TrimSpace(reason) != "" {
		payload["stub_reason"] = reason
	}
	return payload
}

// stubMemoryImport returns a stub import response aligned with the VS Code
// extension SubmitImportResponse (framework v4 §8.1): queued + task_id + session_id.
func stubMemoryImport(kbIndex string, reason string) map[string]any {
	sid := "stub-session-" + generateStubID()
	return decorateStubResponse(map[string]any{
		"task_id":    "stub-task-" + generateStubID(),
		"status":     "queued",
		"kb_index":   kbIndex,
		"tag":        "memory",
		"session_id": sid,
	}, reason)
}

// stubHealth returns a stub health-check response.
func stubHealth() map[string]any {
	return decorateStubResponse(map[string]any{
		"status": "ok",
	}, "stub_mode")
}

// stubMemoryList returns a stub memory listing.
func stubMemoryList(reason string) map[string]any {
	return decorateStubResponse(map[string]any{
		"memories": []any{},
		"total":    0,
		"page":     1,
	}, reason)
}

// stubMemorySearch returns a stub memory search payload matching the extension
// MemorySearchResult: results (MemoryHit[]), total, kb_index, tag (framework v4 §8.1).
func stubMemorySearch(query string, reason string) map[string]any {
	sid := "stub-session-" + generateStubID()
	storage := "stub/memory/" + generateStubID() + ".json"
	hit := map[string]any{
		"session_id":    sid,
		"storage_path":  storage,
		"abstract":      fmt.Sprintf("[STUB] Offline fake hit for plugin integration (query=%q). Not from server.", query),
		"score":         0.99,
		"snippet":       "[STUB] Replace with a running Atlas server for real results.",
		"hit_field":     "abstract",
	}
	return decorateStubResponse(map[string]any{
		"results":  []any{hit},
		"total":    1,
		"kb_index": "memory_main",
		"tag":      "memory",
	}, reason)
}

// stubMemoryStatus returns a stub task-status response.
func stubMemoryStatus(taskID string) map[string]any {
	return decorateStubResponse(map[string]any{
		"task_id": taskID,
		"status":  "completed",
	}, "stub_mode")
}

// generateStubID produces a short pseudo-unique ID based on the current time
// (nanoseconds) for use in stub task IDs.  It is NOT cryptographically secure
// and must only be used for development/integration stubs.
func generateStubID() string {
	ns := time.Now().UnixNano()
	// Use last 8 hex characters of the nanosecond timestamp for brevity.
	full := fmt.Sprintf("%016x", ns)
	if len(full) >= 8 {
		return full[len(full)-8:]
	}
	return full
}
