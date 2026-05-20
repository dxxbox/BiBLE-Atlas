package http

import (
	"encoding/json"
	nethttp "net/http"
	"net/http/httptest"
	"strings"
	"sync"
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

func TestHealthRequestsHealthEndpointDirectly(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		switch r.URL.Path {
		case "/health":
			_ = json.NewEncoder(w).Encode(map[string]any{"service": "alive"})
		case "/api/v1/system/status":
			t.Fatalf("did not expect /api/v1/system/status for health command")
		default:
			w.WriteHeader(nethttp.StatusNotFound)
		}
	}))
	defer server.Close()

	client := New(config.ClientConfig{BaseURL: server.URL, TimeoutSeconds: 2})
	payload, err := client.Health()
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if payload["service"] != "alive" {
		t.Fatalf("expected service alive, got %v", payload["service"])
	}
}

func TestInfoFallbackToHealthEndpoint(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		switch r.URL.Path {
		case "/api/v1/system/info":
			w.WriteHeader(nethttp.StatusNotFound)
			_ = json.NewEncoder(w).Encode(map[string]any{"detail": "missing"})
		case "/health":
			_ = json.NewEncoder(w).Encode(map[string]any{"service": "alive"})
		default:
			w.WriteHeader(nethttp.StatusNotFound)
		}
	}))
	defer server.Close()

	client := New(config.ClientConfig{BaseURL: server.URL, TimeoutSeconds: 2})
	payload, err := client.Info()
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if payload["service"] != "alive" {
		t.Fatalf("expected fallback /health payload, got %v", payload)
	}
}

func TestKnowledgeSearchReturnsEnvelopeResult(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path != "/api/search/knowledge-base" {
			w.WriteHeader(nethttp.StatusNotFound)
			return
		}
		if r.Method != nethttp.MethodPost {
			t.Fatalf("expected POST, got %s", r.Method)
		}
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body["query"] != "faith" {
			t.Fatalf("expected query faith, got %q", body["query"])
		}
		if body["tag"] != "design" {
			t.Fatalf("expected tag design, got %q", body["tag"])
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status": "ok",
			"result": map[string]any{"count": 1},
		})
	}))
	defer server.Close()

	client := New(config.ClientConfig{BaseURL: server.URL, TimeoutSeconds: 2})
	payload, err := client.KnowledgeSearch(KnowledgeSearchRequest{Query: "faith", Tag: "design"})
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
		case "/api/search/knowledge-base":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{
					"items": []any{map[string]any{"title": "k1"}},
				},
			})
		case "/api/search/skill":
			if r.Method != nethttp.MethodPost {
				t.Fatalf("expected POST for skills search, got %s", r.Method)
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{
					"skills": []any{map[string]any{"name": "skill-a"}},
				},
			})
		case "/api/search/memory":
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
		Query:        "faith",
		TopK:         5,
		EnableHit:    true,
		HitTypes:     []string{"skill", "memory"},
		KnowledgeTag: "design",
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

func TestSearchHitRequestsRunConcurrently(t *testing.T) {
	var (
		mu                sync.Mutex
		skillRequestTime  time.Time
		memoryRequestTime time.Time
	)

	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		switch r.URL.Path {
		case "/api/search/knowledge-base":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{"items": []any{}},
			})
		case "/api/search/skill":
			mu.Lock()
			skillRequestTime = time.Now()
			mu.Unlock()
			time.Sleep(200 * time.Millisecond)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{"skills": []any{}},
			})
		case "/api/search/memory":
			mu.Lock()
			memoryRequestTime = time.Now()
			mu.Unlock()
			time.Sleep(200 * time.Millisecond)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{"items": []any{}},
			})
		default:
			w.WriteHeader(nethttp.StatusNotFound)
		}
	}))
	defer server.Close()

	client := New(config.ClientConfig{BaseURL: server.URL, TimeoutSeconds: 2})
	_, err := client.Search(SearchOptions{
		Query:        "faith",
		TopK:         5,
		EnableHit:    true,
		HitTypes:     []string{"skill", "memory"},
		KnowledgeTag: "design",
	})
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	mu.Lock()
	skillAt := skillRequestTime
	memoryAt := memoryRequestTime
	mu.Unlock()

	if skillAt.IsZero() || memoryAt.IsZero() {
		t.Fatalf("expected both skill and memory search requests to be sent")
	}

	diff := skillAt.Sub(memoryAt)
	if diff < 0 {
		diff = -diff
	}
	if diff > 120*time.Millisecond {
		t.Fatalf("expected hit requests to start concurrently, got start diff %s", diff)
	}
}

func TestSearchHitFailureDoesNotBreakMainKnowledgeResult(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		switch r.URL.Path {
		case "/api/search/knowledge-base":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{
					"items": []any{map[string]any{"title": "k1"}},
				},
			})
		case "/api/search/skill":
			w.WriteHeader(nethttp.StatusInternalServerError)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "error",
				"error": map[string]any{
					"code":    "INTERNAL",
					"message": "skill backend down",
				},
			})
		case "/api/search/memory":
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
		Query:        "faith",
		TopK:         5,
		EnableHit:    true,
		HitTypes:     []string{"skill", "memory"},
		KnowledgeTag: "design",
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
