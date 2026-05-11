package cli

import (
	"bytes"
	"encoding/json"
	"fmt"
	nethttp "net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

type runResponse struct {
	OK    bool `json:"ok"`
	Data  any  `json:"data"`
	Error *struct {
		Code    string `json:"code"`
		Message string `json:"message"`
	} `json:"error"`
}

type goldenExpectation struct {
	ExitCode  int    `json:"exit_code"`
	OK        bool   `json:"ok"`
	ErrorCode string `json:"error_code"`
}

func decodeRunResponse(t *testing.T, raw string) runResponse {
	t.Helper()

	var parsed runResponse
	if err := json.Unmarshal([]byte(raw), &parsed); err != nil {
		t.Fatalf("expected valid response json, got %q: %v", raw, err)
	}
	return parsed
}

func loadGoldenExpectation(t *testing.T, fileName string) goldenExpectation {
	t.Helper()

	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatalf("failed to locate test file path")
	}

	goldenPath := filepath.Join(filepath.Dir(thisFile), "..", "..", "testdata", "golden", fileName)
	content, err := os.ReadFile(goldenPath)
	if err != nil {
		t.Fatalf("failed to read golden file %q: %v", goldenPath, err)
	}

	var expected goldenExpectation
	if err := json.Unmarshal(content, &expected); err != nil {
		t.Fatalf("failed to parse golden file %q: %v", goldenPath, err)
	}

	return expected
}

func TestRunHelpWithoutArgs(t *testing.T) {
	var out bytes.Buffer
	var err bytes.Buffer

	exitCode := Run([]string{}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d", exitCode)
	}
	if !strings.Contains(out.String(), "Usage:") {
		t.Fatalf("expected help output, got %q", out.String())
	}
	if err.Len() != 0 {
		t.Fatalf("expected empty stderr, got %q", err.String())
	}
}

func TestRunUnknownCommand(t *testing.T) {
	var out bytes.Buffer
	var err bytes.Buffer

	exitCode := Run([]string{"unknown"}, &out, &err)
	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
	response := decodeRunResponse(t, out.String())
	if response.OK {
		t.Fatalf("expected ok=false response, got %q", out.String())
	}
	if response.Error == nil || response.Error.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS error code, got %q", out.String())
	}
	if err.Len() != 0 {
		t.Fatalf("expected empty stderr by default, got %q", err.String())
	}
}

func TestRunKnowledgeSearchWithTooManyArgs(t *testing.T) {
	var out bytes.Buffer
	var err bytes.Buffer

	exitCode := Run([]string{"knowledge", "search", "a", "b"}, &out, &err)
	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
	response := decodeRunResponse(t, out.String())
	if response.Error == nil || !strings.Contains(response.Error.Message, "at most one optional query") {
		t.Fatalf("expected query arity error, got %q", out.String())
	}
	if err.Len() != 0 {
		t.Fatalf("expected empty stderr by default, got %q", err.String())
	}
}

func TestRunHealthSuccess(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		switch r.URL.Path {
		case "/health":
			_ = json.NewEncoder(w).Encode(map[string]any{"service": "up"})
		case "/api/v1/system/status":
			t.Fatalf("did not expect /api/v1/system/status for health command")
		default:
			w.WriteHeader(nethttp.StatusNotFound)
		}
	}))
	defer server.Close()

	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer

	exitCode := Run([]string{"health"}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d, stderr=%q", exitCode, err.String())
	}
	response := decodeRunResponse(t, out.String())
	if !response.OK {
		t.Fatalf("expected ok=true response, got %q", out.String())
	}
	dataMap, ok := response.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data payload, got %T", response.Data)
	}
	if fmt.Sprintf("%v", dataMap["service"]) != "up" {
		t.Fatalf("expected service=up in data, got %q", out.String())
	}
	if err.Len() != 0 {
		t.Fatalf("expected empty stderr, got %q", err.String())
	}
}

func TestRunSkillsUnknownActionNotImplemented(t *testing.T) {
	var out bytes.Buffer
	var err bytes.Buffer

	exitCode := Run([]string{"skills", "frobnicate"}, &out, &err)
	if exitCode != 3 {
		t.Fatalf("expected exit code 3, got %d", exitCode)
	}
	response := decodeRunResponse(t, out.String())
	if response.Error == nil || response.Error.Code != "CLI_NOT_IMPLEMENTED" {
		t.Fatalf("expected CLI_NOT_IMPLEMENTED response, got %q", out.String())
	}
	if err.Len() != 0 {
		t.Fatalf("expected empty stderr by default, got %q", err.String())
	}
}

func TestRunSkillsLsAliasNormalizesToList(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path == "/api/search/skill" && r.Method == nethttp.MethodPost {
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

	var out bytes.Buffer
	var err bytes.Buffer

	exitCode := Run([]string{"skills", "ls"}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0 (ls alias → list → server call), got %d: %s", exitCode, out.String())
	}
	response := decodeRunResponse(t, out.String())
	if !response.OK {
		t.Fatalf("expected ok=true, got %q", out.String())
	}
}

func TestRunKnowledgeLsAliasMapsToKnowledgeList(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		switch r.URL.Path {
		case "/api/v1/knowledge/list":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{"count": 1},
			})
		default:
			w.WriteHeader(nethttp.StatusNotFound)
		}
	}))
	defer server.Close()

	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"knowledge", "ls"}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d", exitCode)
	}
	response := decodeRunResponse(t, out.String())
	if !response.OK {
		t.Fatalf("expected ok=true response, got %q", out.String())
	}
	dataMap, ok := response.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data payload, got %T", response.Data)
	}
	if dataMap["count"] != float64(1) {
		t.Fatalf("expected count 1, got %v", dataMap["count"])
	}
}

func TestRunSearchRequiresQueryFlag(t *testing.T) {
	var out bytes.Buffer
	var err bytes.Buffer

	exitCode := Run([]string{"search"}, &out, &err)
	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
	response := decodeRunResponse(t, out.String())
	if response.Error == nil || response.Error.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS response, got %q", out.String())
	}
}

func TestRunSearchEnableHitReturnsKnowledgeAndMemoryWhenSkillFails(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		switch r.URL.Path {
		case "/api/v1/knowledge/search":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{
					"items": []any{map[string]any{"title": "k1"}},
				},
			})
		case "/api/v1/skills/search":
			w.WriteHeader(nethttp.StatusServiceUnavailable)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "error",
				"error": map[string]any{
					"code":    "UNAVAILABLE",
					"message": "skill service down",
				},
			})
		case "/api/v1/memory/search":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{
					"items": []any{map[string]any{"memory_id": "m1"}},
				},
			})
		default:
			w.WriteHeader(nethttp.StatusNotFound)
		}
	}))
	defer server.Close()

	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"search", "--query", "faith", "--enable-hit"}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d, stderr=%q", exitCode, err.String())
	}

	response := decodeRunResponse(t, out.String())
	if !response.OK {
		t.Fatalf("expected ok=true response, got %q", out.String())
	}
	dataMap, ok := response.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data payload, got %T", response.Data)
	}
	if _, exists := dataMap["knowledge"]; !exists {
		t.Fatalf("expected knowledge payload in search response")
	}
	if _, exists := dataMap["memory"]; !exists {
		t.Fatalf("expected memory payload in search response")
	}
	if _, exists := dataMap["skill"]; exists {
		t.Fatalf("did not expect skill payload when skill hit fails")
	}
}

func TestRunLegacyStderrCompatibility(t *testing.T) {
	t.Setenv("BIBLE_CLI_LEGACY_STDERR", "1")

	var out bytes.Buffer
	var err bytes.Buffer

	exitCode := Run([]string{"unknown"}, &out, &err)
	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
	if !strings.Contains(out.String(), "\"ok\":false") {
		t.Fatalf("expected json error payload on stdout, got %q", out.String())
	}
	if !strings.Contains(err.String(), "Error[INVALID_ARGS]") {
		t.Fatalf("expected legacy stderr output, got %q", err.String())
	}
}

func TestRunGoldenScenarios(t *testing.T) {
	t.Run("success", func(t *testing.T) {
		expected := loadGoldenExpectation(t, "success.json")

		server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
			if r.URL.Path == "/health" {
				_ = json.NewEncoder(w).Encode(map[string]any{"service": "up"})
				return
			}
			w.WriteHeader(nethttp.StatusNotFound)
		}))
		defer server.Close()
		t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

		var out bytes.Buffer
		var err bytes.Buffer
		exitCode := Run([]string{"health"}, &out, &err)
		response := decodeRunResponse(t, out.String())

		if exitCode != expected.ExitCode {
			t.Fatalf("expected exit code %d, got %d", expected.ExitCode, exitCode)
		}
		if response.OK != expected.OK {
			t.Fatalf("expected ok=%v, got %v", expected.OK, response.OK)
		}
		if err.Len() != 0 {
			t.Fatalf("expected empty stderr, got %q", err.String())
		}
	})

	t.Run("invalid args", func(t *testing.T) {
		expected := loadGoldenExpectation(t, "invalid-args.json")

		var out bytes.Buffer
		var err bytes.Buffer
		exitCode := Run([]string{"unknown"}, &out, &err)
		response := decodeRunResponse(t, out.String())

		if exitCode != expected.ExitCode {
			t.Fatalf("expected exit code %d, got %d", expected.ExitCode, exitCode)
		}
		if response.OK != expected.OK {
			t.Fatalf("expected ok=%v, got %v", expected.OK, response.OK)
		}
		if response.Error == nil || response.Error.Code != expected.ErrorCode {
			t.Fatalf("expected error code %q, got %q", expected.ErrorCode, out.String())
		}
		if err.Len() != 0 {
			t.Fatalf("expected empty stderr, got %q", err.String())
		}
	})

	t.Run("404", func(t *testing.T) {
		expected := loadGoldenExpectation(t, "not-found-404.json")

		server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
			w.WriteHeader(nethttp.StatusNotFound)
			_ = json.NewEncoder(w).Encode(map[string]any{"detail": "missing"})
		}))
		defer server.Close()
		t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

		var out bytes.Buffer
		var err bytes.Buffer
		exitCode := Run([]string{"knowledge", "list"}, &out, &err)
		response := decodeRunResponse(t, out.String())

		if exitCode != expected.ExitCode {
			t.Fatalf("expected exit code %d, got %d", expected.ExitCode, exitCode)
		}
		if response.OK != expected.OK {
			t.Fatalf("expected ok=%v, got %v", expected.OK, response.OK)
		}
		if response.Error == nil || response.Error.Code != expected.ErrorCode {
			t.Fatalf("expected error code %q, got %q", expected.ErrorCode, out.String())
		}
		if err.Len() != 0 {
			t.Fatalf("expected empty stderr, got %q", err.String())
		}
	})

	t.Run("5xx", func(t *testing.T) {
		expected := loadGoldenExpectation(t, "server-5xx.json")

		server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
			w.WriteHeader(nethttp.StatusInternalServerError)
			_ = json.NewEncoder(w).Encode(map[string]any{"detail": "server exploded"})
		}))
		defer server.Close()
		t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

		var out bytes.Buffer
		var err bytes.Buffer
		exitCode := Run([]string{"knowledge", "list"}, &out, &err)
		response := decodeRunResponse(t, out.String())

		if exitCode != expected.ExitCode {
			t.Fatalf("expected exit code %d, got %d", expected.ExitCode, exitCode)
		}
		if response.OK != expected.OK {
			t.Fatalf("expected ok=%v, got %v", expected.OK, response.OK)
		}
		if response.Error == nil || response.Error.Code != expected.ErrorCode {
			t.Fatalf("expected error code %q, got %q", expected.ErrorCode, out.String())
		}
		if err.Len() != 0 {
			t.Fatalf("expected empty stderr, got %q", err.String())
		}
	})

	t.Run("timeout", func(t *testing.T) {
		expected := loadGoldenExpectation(t, "timeout.json")

		server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
			time.Sleep(1100 * time.Millisecond)
			w.WriteHeader(nethttp.StatusOK)
			_ = json.NewEncoder(w).Encode(map[string]any{"status": "ok", "result": map[string]any{"late": true}})
		}))
		defer server.Close()
		t.Setenv("BIBLE_CLI_BASE_URL", server.URL)
		t.Setenv("BIBLE_CLI_TIMEOUT_SECONDS", "1")

		var out bytes.Buffer
		var err bytes.Buffer
		exitCode := Run([]string{"knowledge", "list"}, &out, &err)
		response := decodeRunResponse(t, out.String())

		if exitCode != expected.ExitCode {
			t.Fatalf("expected exit code %d, got %d", expected.ExitCode, exitCode)
		}
		if response.OK != expected.OK {
			t.Fatalf("expected ok=%v, got %v", expected.OK, response.OK)
		}
		if response.Error == nil || response.Error.Code != expected.ErrorCode {
			t.Fatalf("expected error code %q, got %q", expected.ErrorCode, out.String())
		}
		if err.Len() != 0 {
			t.Fatalf("expected empty stderr, got %q", err.String())
		}
	})

	t.Run("cli not implemented", func(t *testing.T) {
		expected := loadGoldenExpectation(t, "cli-not-implemented.json")

		var out bytes.Buffer
		var err bytes.Buffer
		// Use an unknown action on a known command to trigger CLI_NOT_IMPLEMENTED.
		exitCode := Run([]string{"skills", "frobnicate"}, &out, &err)
		response := decodeRunResponse(t, out.String())

		if exitCode != expected.ExitCode {
			t.Fatalf("expected exit code %d, got %d", expected.ExitCode, exitCode)
		}
		if response.OK != expected.OK {
			t.Fatalf("expected ok=%v, got %v", expected.OK, response.OK)
		}
		if response.Error == nil || response.Error.Code != expected.ErrorCode {
			t.Fatalf("expected error code %q, got %q", expected.ErrorCode, out.String())
		}
		if err.Len() != 0 {
			t.Fatalf("expected empty stderr, got %q", err.String())
		}
	})
}
