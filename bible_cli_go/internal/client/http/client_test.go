package http

import (
	"encoding/json"
	nethttp "net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"bible-cli-go/internal/config"
	"bible-cli-go/internal/protocol"
)

func TestStatusFallbackToHealthEndpoint(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		switch r.URL.Path {
		case "/api/v1/system/status":
			w.WriteHeader(nethttp.StatusNotFound)
			_ = json.NewEncoder(w).Encode(map[string]any{"detail": "missing"})
		case "/health":
			_ = json.NewEncoder(w).Encode(map[string]any{"status": "ok"})
		default:
			w.WriteHeader(nethttp.StatusNotFound)
		}
	}))
	defer server.Close()

	client := New(config.ClientConfig{BaseURL: server.URL, TimeoutSeconds: 2})
	payload, err := client.Status()
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if payload["status"] != "ok" {
		t.Fatalf("expected status ok, got %v", payload["status"])
	}
}

func TestKnowledgeSearchReturnsEnvelopeResult(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path != "/api/v1/knowledge/search" {
			w.WriteHeader(nethttp.StatusNotFound)
			return
		}
		if got := r.URL.Query().Get("query"); got != "faith" {
			t.Fatalf("expected query faith, got %q", got)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status": "ok",
			"result": map[string]any{"count": 1},
		})
	}))
	defer server.Close()

	client := New(config.ClientConfig{BaseURL: server.URL, TimeoutSeconds: 2})
	payload, err := client.KnowledgeSearch("faith")
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if payload["count"] != float64(1) {
		t.Fatalf("expected count 1, got %v", payload["count"])
	}
}

func TestMapHTTPStatusToCode(t *testing.T) {
	cases := map[int]string{
		nethttp.StatusBadRequest:          "INVALID_ARGS",
		nethttp.StatusUnauthorized:        "UNAUTHENTICATED",
		nethttp.StatusForbidden:           "PERMISSION_DENIED",
		nethttp.StatusNotFound:            "NOT_FOUND",
		nethttp.StatusConflict:            "CONFLICT",
		nethttp.StatusPreconditionFailed:  "FAILED_PRECONDITION",
		nethttp.StatusTooManyRequests:     "RESOURCE_EXHAUSTED",
		nethttp.StatusNotImplemented:      "SEV_NOT_IMPLEMENTED",
		nethttp.StatusServiceUnavailable:  "UNAVAILABLE",
		nethttp.StatusGatewayTimeout:      "TIMEOUT",
		nethttp.StatusInternalServerError: "INTERNAL",
	}

	for input, expected := range cases {
		if got := mapHTTPStatusToCode(input); got != expected {
			t.Fatalf("status %d expected %q, got %q", input, expected, got)
		}
	}
}

func TestErrorEnvelopeMapsToCLIError(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path != "/api/v1/knowledge/list" {
			w.WriteHeader(nethttp.StatusNotFound)
			return
		}
		w.WriteHeader(nethttp.StatusBadRequest)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status": "error",
			"error": map[string]any{
				"code":    "INVALID_ARGUMENT",
				"message": "bad request",
			},
		})
	}))
	defer server.Close()

	client := New(config.ClientConfig{BaseURL: server.URL, TimeoutSeconds: 2})
	_, err := client.KnowledgeList()
	if err == nil {
		t.Fatalf("expected error")
	}
	cliErr, ok := err.(protocol.CLIError)
	if !ok {
		t.Fatalf("expected CLIError, got %T", err)
	}
	if cliErr.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS, got %q", cliErr.Code)
	}
}

func TestErrorEnvelopeFor501ForcesSEVNotImplemented(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path != "/api/v1/knowledge/list" {
			w.WriteHeader(nethttp.StatusNotFound)
			return
		}
		w.WriteHeader(nethttp.StatusNotImplemented)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status": "error",
			"error": map[string]any{
				"code":    "NOT_IMPLEMENTED",
				"message": "not ready",
			},
		})
	}))
	defer server.Close()

	client := New(config.ClientConfig{BaseURL: server.URL, TimeoutSeconds: 2})
	_, err := client.KnowledgeList()
	if err == nil {
		t.Fatalf("expected error")
	}
	cliErr := err.(protocol.CLIError)
	if cliErr.Code != "SEV_NOT_IMPLEMENTED" {
		t.Fatalf("expected SEV_NOT_IMPLEMENTED, got %q", cliErr.Code)
	}
}

func TestTimeoutCompatibilityCodeNormalization(t *testing.T) {
	err := parseErrorPayload(map[string]any{
		"code":    "DEADLINE_EXCEEDED",
		"message": "timed out",
	}, nethttp.StatusGatewayTimeout)

	cliErr := err.(protocol.CLIError)
	if cliErr.Code != "TIMEOUT" {
		t.Fatalf("expected TIMEOUT, got %q", cliErr.Code)
	}
}

func TestHTTPTransportTimeoutMapsToTimeout(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		time.Sleep(1100 * time.Millisecond)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status": "ok",
			"result": map[string]any{"late": true},
		})
	}))
	defer server.Close()

	client := New(config.ClientConfig{BaseURL: server.URL, TimeoutSeconds: 1})
	_, err := client.KnowledgeList()
	if err == nil {
		t.Fatalf("expected timeout error")
	}

	cliErr, ok := err.(protocol.CLIError)
	if !ok {
		t.Fatalf("expected CLIError, got %T", err)
	}
	if cliErr.Code != "TIMEOUT" {
		t.Fatalf("expected TIMEOUT, got %q", cliErr.Code)
	}
}

func TestSearchIncludesSkillAndMemoryHitsWhenEnabled(t *testing.T) {
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
			if r.Method != nethttp.MethodPost {
				t.Fatalf("expected POST for skills search, got %s", r.Method)
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{
					"skills": []any{map[string]any{"name": "skill-a"}},
				},
			})
		case "/api/v1/memory/search":
			if r.Method != nethttp.MethodPost {
				t.Fatalf("expected POST for memory search, got %s", r.Method)
			}
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

	client := New(config.ClientConfig{BaseURL: server.URL, TimeoutSeconds: 2})
	payload, err := client.Search(SearchOptions{
		Query:     "faith",
		TopK:      5,
		EnableHit: true,
		HitTypes:  []string{"skill", "memory"},
	})
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	if _, ok := payload["knowledge"]; !ok {
		t.Fatalf("expected knowledge section in response")
	}
	if _, ok := payload["skill"]; !ok {
		t.Fatalf("expected skill section in response")
	}
	if _, ok := payload["memory"]; !ok {
		t.Fatalf("expected memory section in response")
	}
}

func TestSearchHitFailureDoesNotBreakMainKnowledgeResult(t *testing.T) {
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
			w.WriteHeader(nethttp.StatusInternalServerError)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "error",
				"error": map[string]any{
					"code":    "INTERNAL",
					"message": "skill backend down",
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

	client := New(config.ClientConfig{BaseURL: server.URL, TimeoutSeconds: 2})
	payload, err := client.Search(SearchOptions{
		Query:     "faith",
		TopK:      5,
		EnableHit: true,
		HitTypes:  []string{"skill", "memory"},
	})
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if _, ok := payload["knowledge"]; !ok {
		t.Fatalf("expected knowledge section in response")
	}
	if _, ok := payload["memory"]; !ok {
		t.Fatalf("expected memory section in response")
	}
	if _, ok := payload["skill"]; ok {
		t.Fatalf("did not expect skill section when skill hit fails")
	}

	warningsRaw, ok := payload["hit_warnings"]
	if !ok {
		t.Fatalf("expected hit warnings when skill hit fails")
	}
	warnings, ok := warningsRaw.([]string)
	if !ok {
		t.Fatalf("expected hit_warnings []string, got %T", warningsRaw)
	}
	if len(warnings) == 0 || !strings.Contains(warnings[0], "skill hit failed") {
		t.Fatalf("expected skill failure warning, got %v", warnings)
	}
}
