package fixtures_test

import (
	"testing"

	"bible-cli-go/internal/fixtures"
)

func TestMemorySearchTestDataTopKTrimsResults(t *testing.T) {
	m, err := fixtures.MemorySearchTestData("q", 1, "")
	if err != nil {
		t.Fatal(err)
	}
	results, ok := m["results"].([]any)
	if !ok || len(results) != 1 {
		t.Fatalf("expected 1 result after topK=1, got %v", m["results"])
	}
	if m["total"] != float64(1) {
		t.Fatalf("expected total 1, got %v", m["total"])
	}
}

func TestMemorySearchTestDataFilterTag(t *testing.T) {
	m, err := fixtures.MemorySearchTestData("x", 5, "custom")
	if err != nil {
		t.Fatal(err)
	}
	if m["tag"] != "custom" {
		t.Fatalf("tag: %v", m["tag"])
	}
}
