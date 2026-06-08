package meta

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestPatchPluginMetaJSONForUpload_preservesExtraKeys(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "meta.json")
	raw := map[string]any{
		"session_id":             "sid-1",
		"abstract":               "summary line",
		"overview":               "long overview",
		"primary_request_intent": "do X",
		"key_concepts":           []any{"a", "b"},
	}
	data, err := json.Marshal(raw)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
	msg := []byte(`{"session_id":"sid-1","requests":[]}`)
	patched, err := PatchPluginMetaJSONForUpload(dir, msg)
	if err != nil {
		t.Fatal(err)
	}
	if !patched {
		t.Fatal("expected patch")
	}
	round, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var out map[string]any
	if err := json.Unmarshal(round, &out); err != nil {
		t.Fatal(err)
	}
	if out["memory_id"] != "mem_sid-1" {
		t.Fatalf("memory_id: %v", out["memory_id"])
	}
	if out["title"] == nil || out["title"] == "" {
		t.Fatalf("title: %v", out["title"])
	}
	if out["primary_request_intent"] != "do X" {
		t.Fatalf("lost plugin field: %v", out["primary_request_intent"])
	}
}

func TestPatchPluginMetaJSONForUpload_noOpWhenComplete(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "meta.json")
	raw := map[string]any{
		"memory_id": "mem_x",
		"title":     "t",
		"abstract":  "a",
	}
	data, _ := json.Marshal(raw)
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
	patched, err := PatchPluginMetaJSONForUpload(dir, nil)
	if err != nil {
		t.Fatal(err)
	}
	if patched {
		t.Fatal("expected no patch")
	}
}
