package cli

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
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

func standardSkillPackage(t *testing.T, skillName string) []byte {
	t.Helper()

	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	manifest, err := zw.Create(skillName + "/SKILLS.md")
	if err != nil {
		t.Fatalf("failed to create skill manifest: %v", err)
	}
	if _, err := manifest.Write([]byte("# " + skillName + "\n")); err != nil {
		t.Fatalf("failed to write skill manifest: %v", err)
	}
	script, err := zw.Create(skillName + "/api.py")
	if err != nil {
		t.Fatalf("failed to create skill script: %v", err)
	}
	if _, err := script.Write([]byte("def run():\n    return \"ok\"\n")); err != nil {
		t.Fatalf("failed to write skill script: %v", err)
	}
	if err := zw.Close(); err != nil {
		t.Fatalf("failed to close skill package: %v", err)
	}
	return buf.Bytes()
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
	help := out.String()
	expectedLines := []string{
		"bible knowledge import --file <path> [--file <path>] --kb-index <index> --tag <tag> [--wait]",
		"bible memory upload <session_dir> --kb-index <index> [--skip-if-exists] [--wait]",
		"bible memory upload-all <base_dir> --kb-index <index> [--workers N]",
		"bible skills upload --file <path.skill|skill_dir> --kb-index <index> [--wait]",
		`bible memory save --input '{"title":"...","messages":[...]}' --kb-index <index> [--wait]`,
		`bible session save --input '{"title":"...","messages":[...]}' --kb-index <index> [--wait]  (deprecated: use 'memory save')`,
		"Note: --kb-index <index> may also be supplied by BIBLE_MEMORY_KB_INDEX or config.",
	}
	for _, line := range expectedLines {
		if !strings.Contains(help, line) {
			t.Fatalf("expected help output to contain %q, got %q", line, help)
		}
	}
	if strings.Contains(help, "[--kb-index <index>]") {
		t.Fatalf("expected kb-index not to be marked optional, got %q", help)
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

func TestRunSkillsListPassesPageAndFilterTag(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path != "/api/search/skill" {
			w.WriteHeader(nethttp.StatusNotFound)
			return
		}
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body["query"] != "*" {
			t.Fatalf("expected wildcard list query, got %v", body["query"])
		}
		if body["page"] != float64(3) {
			t.Fatalf("expected page=3, got %v", body["page"])
		}
		if body["filter_tag"] != "agent" {
			t.Fatalf("expected filter_tag=agent, got %v", body["filter_tag"])
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status": "ok",
			"result": map[string]any{"items": []any{}},
		})
	}))
	defer server.Close()
	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"skills", "list", "--page", "3", "--tag", "agent"}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d: %s", exitCode, out.String())
	}
}

func TestRunSkillsUploadPackagesDirectory(t *testing.T) {
	tmpDir := t.TempDir()
	skillDir := filepath.Join(tmpDir, "code-reviewer")
	if err := os.MkdirAll(filepath.Join(skillDir, "examples"), 0o755); err != nil {
		t.Fatalf("failed to create skill directory: %v", err)
	}
	if err := os.WriteFile(filepath.Join(skillDir, "SKILLS.md"), []byte("# Code Reviewer\n"), 0o644); err != nil {
		t.Fatalf("failed to write SKILLS.md: %v", err)
	}
	if err := os.WriteFile(filepath.Join(skillDir, "examples", "note.md"), []byte("example"), 0o644); err != nil {
		t.Fatalf("failed to write nested skill file: %v", err)
	}

	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path != "/api/import/skill" {
			w.WriteHeader(nethttp.StatusNotFound)
			return
		}
		if r.Method != nethttp.MethodPost {
			t.Fatalf("expected POST, got %s", r.Method)
		}
		if err := r.ParseMultipartForm(32 << 20); err != nil {
			t.Fatalf("failed to parse multipart form: %v", err)
		}
		if got := r.MultipartForm.Value["kb_index"]; len(got) != 1 || got[0] != "rrm" {
			t.Fatalf("expected kb_index rrm, got %v", got)
		}
		if got := r.MultipartForm.Value["tag"]; len(got) != 1 || got[0] != "skill" {
			t.Fatalf("expected tag skill, got %v", got)
		}

		files := r.MultipartForm.File["files"]
		if len(files) != 1 {
			t.Fatalf("expected one uploaded file, got %v", files)
		}
		if files[0].Filename != "code-reviewer.skill" {
			t.Fatalf("expected packaged skill filename, got %q", files[0].Filename)
		}

		uploaded, err := files[0].Open()
		if err != nil {
			t.Fatalf("failed to open uploaded skill package: %v", err)
		}
		defer uploaded.Close()
		data, err := io.ReadAll(uploaded)
		if err != nil {
			t.Fatalf("failed to read uploaded skill package: %v", err)
		}
		zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
		if err != nil {
			t.Fatalf("expected uploaded skill package to be a zip: %v", err)
		}
		entries := map[string]bool{}
		for _, f := range zr.File {
			entries[f.Name] = true
		}
		if !entries["code-reviewer/SKILLS.md"] {
			t.Fatalf("expected zip to contain code-reviewer/SKILLS.md, got %v", entries)
		}
		if !entries["code-reviewer/examples/note.md"] {
			t.Fatalf("expected zip to contain nested skill file, got %v", entries)
		}

		_ = json.NewEncoder(w).Encode(map[string]any{
			"task_id": "skill-import-1",
			"status":  "queued",
		})
	}))
	defer server.Close()
	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"skills", "upload", "--file", skillDir, "--kb-index", "rrm"}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d, stdout=%q, stderr=%q", exitCode, out.String(), err.String())
	}
	response := decodeRunResponse(t, out.String())
	if !response.OK {
		t.Fatalf("expected ok=true response, got %q", out.String())
	}
	dataMap, ok := response.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data payload, got %T", response.Data)
	}
	if dataMap["task_id"] != "skill-import-1" {
		t.Fatalf("expected task id in response, got %v", dataMap)
	}
}

func TestRunSkillsUploadMissingKbIndex(t *testing.T) {
	tmpDir := t.TempDir()
	skillPath := filepath.Join(tmpDir, "code-reviewer.skill")
	if err := os.WriteFile(skillPath, standardSkillPackage(t, "code-reviewer"), 0o644); err != nil {
		t.Fatalf("failed to write skill package: %v", err)
	}
	t.Setenv("BIBLE_MEMORY_KB_INDEX", "")

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"skills", "upload", "--file", skillPath}, &out, &err)
	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d, stdout=%q, stderr=%q", exitCode, out.String(), err.String())
	}
	response := decodeRunResponse(t, out.String())
	if response.OK {
		t.Fatalf("expected ok=false response, got %q", out.String())
	}
	if response.Error == nil || response.Error.Code != "INVALID_ARGS" || !strings.Contains(response.Error.Message, "kb_index") {
		t.Fatalf("expected INVALID_ARGS kb_index error, got %q", out.String())
	}
	if err.Len() != 0 {
		t.Fatalf("expected empty stderr, got %q", err.String())
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

func TestRunMemoryListPassesFilters(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path != "/api/search/memory" {
			w.WriteHeader(nethttp.StatusNotFound)
			return
		}
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body["query"] != "*" {
			t.Fatalf("expected wildcard list query, got %v", body["query"])
		}
		if body["page"] != float64(2) {
			t.Fatalf("expected page=2, got %v", body["page"])
		}
		if body["filter_tag"] != "meeting" {
			t.Fatalf("expected filter_tag=meeting, got %v", body["filter_tag"])
		}
		if body["since"] != "2026-05-01" {
			t.Fatalf("expected since=2026-05-01, got %v", body["since"])
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status": "ok",
			"result": map[string]any{"items": []any{}},
		})
	}))
	defer server.Close()
	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"memory", "list", "--page", "2", "--tag", "meeting", "--since", "2026-05-01"}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d: %s", exitCode, out.String())
	}
}

func TestRunKnowledgeImportAccepted(t *testing.T) {
	tmpDir := t.TempDir()
	docPath := filepath.Join(tmpDir, "design.md")
	if err := os.WriteFile(docPath, []byte("# design"), 0o644); err != nil {
		t.Fatalf("failed to write test doc: %v", err)
	}

	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path != "/api/import/knowledge-base" {
			w.WriteHeader(nethttp.StatusNotFound)
			return
		}
		if r.Method != nethttp.MethodPost {
			t.Fatalf("expected POST, got %s", r.Method)
		}
		if err := r.ParseMultipartForm(32 << 20); err != nil {
			t.Fatalf("failed to parse multipart form: %v", err)
		}
		if got := r.MultipartForm.Value["kb_index"]; len(got) != 1 || got[0] != "kb_design" {
			t.Fatalf("expected kb_index kb_design, got %v", got)
		}
		if got := r.MultipartForm.Value["tag"]; len(got) != 1 || got[0] != "design" {
			t.Fatalf("expected tag design, got %v", got)
		}
		if files := r.MultipartForm.File["files"]; len(files) != 1 || files[0].Filename != "design.md" {
			t.Fatalf("expected one design.md file, got %v", files)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"task_id": "knowledge-import-1",
			"status":  "queued",
		})
	}))
	defer server.Close()
	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"knowledge", "import", "--file", docPath, "--kb-index", "kb_design", "--tag", "design"}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d, stdout=%q, stderr=%q", exitCode, out.String(), err.String())
	}
	response := decodeRunResponse(t, out.String())
	if !response.OK {
		t.Fatalf("expected ok=true response, got %q", out.String())
	}
	dataMap, ok := response.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data payload, got %T", response.Data)
	}
	if dataMap["task_id"] != "knowledge-import-1" {
		t.Fatalf("expected task id in response, got %v", dataMap)
	}
}

func TestRunKnowledgeImportRequiresFile(t *testing.T) {
	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"knowledge", "import", "--kb-index", "kb_design", "--tag", "design"}, &out, &err)
	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
	response := decodeRunResponse(t, out.String())
	if response.Error == nil || response.Error.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS, got %q", out.String())
	}
}

func TestRunMemoryDownloadWritesArtifact(t *testing.T) {
	outputDir := t.TempDir()
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		switch r.URL.Path {
		case "/api/download/memory/file":
			if r.Method != nethttp.MethodPost {
				t.Fatalf("expected POST for memory download, got %s", r.Method)
			}
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body["tag"] != "memory" {
				t.Fatalf("expected tag memory, got %v", body["tag"])
			}
			if body["storage_path"] != "memory-1" {
				t.Fatalf("expected storage_path memory-1, got %v", body["storage_path"])
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{"status": "queued", "task_id": "task-memory-download"},
			})
		case "/api/control/admin/tasks/task-memory-download":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "completed",
				"result": map[string]any{"artifact_id": "artifact-memory"},
			})
		case "/api/download/memory/artifact/artifact-memory":
			_, _ = w.Write([]byte("memory artifact"))
		default:
			w.WriteHeader(nethttp.StatusNotFound)
		}
	}))
	defer server.Close()
	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"memory", "download", "--output", outputDir, "memory-1"}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d, stdout=%q, stderr=%q", exitCode, out.String(), err.String())
	}
	response := decodeRunResponse(t, out.String())
	if !response.OK {
		t.Fatalf("expected ok=true response, got %q", out.String())
	}
	dataMap, ok := response.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data payload, got %T", response.Data)
	}
	outputPath, _ := dataMap["output_path"].(string)
	if outputPath == "" {
		t.Fatalf("expected output_path in response, got %v", dataMap)
	}
	content, readErr := os.ReadFile(outputPath)
	if readErr != nil {
		t.Fatalf("failed to read downloaded artifact: %v", readErr)
	}
	if string(content) != "memory artifact" {
		t.Fatalf("unexpected artifact content %q", string(content))
	}
}

func TestRunMemoryBatchDownloadWritesArtifact(t *testing.T) {
	outputDir := t.TempDir()
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		switch r.URL.Path {
		case "/api/download/memory/batch":
			if r.Method != nethttp.MethodPost {
				t.Fatalf("expected POST for memory batch download, got %s", r.Method)
			}
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			paths, ok := body["storage_paths"].([]any)
			if !ok || len(paths) != 2 {
				t.Fatalf("expected two storage_paths, got %v", body["storage_paths"])
			}
			if body["package_name"] != "memories.zip" {
				t.Fatalf("expected package_name memories.zip, got %v", body["package_name"])
			}
			if body["include_metadata"] != true {
				t.Fatalf("expected include_metadata=true, got %v", body["include_metadata"])
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{"status": "queued", "task_id": "task-memory-batch"},
			})
		case "/api/control/admin/tasks/task-memory-batch":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "completed",
				"result": map[string]any{
					"artifact_id":   "artifact-batch",
					"artifact_name": "memories.zip",
				},
			})
		case "/api/download/memory/artifact/artifact-batch":
			_, _ = w.Write([]byte("memory zip"))
		default:
			w.WriteHeader(nethttp.StatusNotFound)
		}
	}))
	defer server.Close()
	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{
		"memory", "download",
		"--storage-path", "memory-a",
		"--storage-path", "memory-b",
		"--package-name", "memories.zip",
		"--include-metadata",
		"--output", outputDir,
	}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d, stdout=%q, stderr=%q", exitCode, out.String(), err.String())
	}
	response := decodeRunResponse(t, out.String())
	if !response.OK {
		t.Fatalf("expected ok=true response, got %q", out.String())
	}
	dataMap, ok := response.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data payload, got %T", response.Data)
	}
	outputPath, _ := dataMap["output_path"].(string)
	if filepath.Base(outputPath) != "memories.zip" {
		t.Fatalf("expected memories.zip output, got %q", outputPath)
	}
	content, readErr := os.ReadFile(outputPath)
	if readErr != nil {
		t.Fatalf("failed to read downloaded artifact: %v", readErr)
	}
	if string(content) != "memory zip" {
		t.Fatalf("unexpected artifact content %q", string(content))
	}
}

func TestRunSkillsBatchDownloadWritesArtifact(t *testing.T) {
	outputDir := t.TempDir()
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		switch r.URL.Path {
		case "/api/download/skill/batch":
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			paths, ok := body["storage_paths"].([]any)
			if !ok || len(paths) != 2 {
				t.Fatalf("expected two storage_paths, got %v", body["storage_paths"])
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{"status": "queued", "task_id": "task-skill-batch"},
			})
		case "/api/control/admin/tasks/task-skill-batch":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "completed",
				"result": map[string]any{
					"artifact_id":   "skill-batch",
					"artifact_name": "skills.zip",
				},
			})
		case "/api/download/skill/artifact/skill-batch":
			_, _ = w.Write([]byte("skill zip"))
		default:
			w.WriteHeader(nethttp.StatusNotFound)
		}
	}))
	defer server.Close()
	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{
		"skills", "download",
		"--storage-path", "skill-a.skill",
		"--storage-path", "skill-b.skill",
		"--output", outputDir,
	}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d, stdout=%q, stderr=%q", exitCode, out.String(), err.String())
	}
	response := decodeRunResponse(t, out.String())
	if !response.OK {
		t.Fatalf("expected ok=true response, got %q", out.String())
	}
	dataMap, ok := response.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data payload, got %T", response.Data)
	}
	outputPath, _ := dataMap["output_path"].(string)
	if filepath.Base(outputPath) != "skills.zip" {
		t.Fatalf("expected skills.zip output, got %q", outputPath)
	}
}

func TestRunSkillsDownloadAcceptsFlagsAfterName(t *testing.T) {
	outputDir := t.TempDir()
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		switch r.URL.Path {
		case "/api/download/skill/file":
			if r.Method != nethttp.MethodPost {
				t.Fatalf("expected POST for skill download, got %s", r.Method)
			}
			var body map[string]any
			_ = json.NewDecoder(r.Body).Decode(&body)
			if body["tag"] != "skill" {
				t.Fatalf("expected tag skill, got %v", body["tag"])
			}
			if body["storage_path"] != "sct-reviewer" {
				t.Fatalf("expected storage_path sct-reviewer, got %v", body["storage_path"])
			}
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{"status": "queued", "task_id": "task-skill-download"},
			})
		case "/api/control/admin/tasks/task-skill-download":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "completed",
				"result": map[string]any{"artifact_id": "skill-artifact"},
			})
		case "/api/download/skill/artifact/skill-artifact":
			_, _ = w.Write(standardSkillPackage(t, "sct-reviewer"))
		default:
			w.WriteHeader(nethttp.StatusNotFound)
		}
	}))
	defer server.Close()
	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"skills", "download", "sct-reviewer", "--output", outputDir}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d, stdout=%q, stderr=%q", exitCode, out.String(), err.String())
	}
	response := decodeRunResponse(t, out.String())
	if !response.OK {
		t.Fatalf("expected ok=true response, got %q", out.String())
	}
	dataMap, ok := response.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data payload, got %T", response.Data)
	}
	outputPath, _ := dataMap["output_path"].(string)
	if filepath.Base(outputPath) != "sct-reviewer" {
		t.Fatalf("expected sct-reviewer output directory, got %q", outputPath)
	}
	content, readErr := os.ReadFile(filepath.Join(outputPath, "SKILLS.md"))
	if readErr != nil {
		t.Fatalf("failed to read downloaded skill manifest: %v", readErr)
	}
	if !strings.Contains(string(content), "# sct-reviewer") {
		t.Fatalf("unexpected skill manifest content %q", string(content))
	}
	if _, readErr := os.ReadFile(filepath.Join(outputPath, "api.py")); readErr != nil {
		t.Fatalf("failed to read downloaded skill script: %v", readErr)
	}
}

func TestRunMemoryDownloadRequiresIdentifier(t *testing.T) {
	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"memory", "download"}, &out, &err)
	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
	response := decodeRunResponse(t, out.String())
	if response.Error == nil || response.Error.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS, got %q", out.String())
	}
}

func TestRunTaskGet(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path != "/api/control/admin/tasks/task-1" {
			w.WriteHeader(nethttp.StatusNotFound)
			return
		}
		if r.Method != nethttp.MethodGet {
			t.Fatalf("expected GET, got %s", r.Method)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"task_id": "task-1", "status": "completed"})
	}))
	defer server.Close()
	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"task", "get", "task-1"}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d, stdout=%q, stderr=%q", exitCode, out.String(), err.String())
	}
	response := decodeRunResponse(t, out.String())
	if !response.OK {
		t.Fatalf("expected ok=true response, got %q", out.String())
	}
	dataMap, ok := response.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data payload, got %T", response.Data)
	}
	if dataMap["status"] != "completed" {
		t.Fatalf("expected completed task, got %v", dataMap)
	}
}

func TestRunTaskCancel(t *testing.T) {
	server := httptest.NewServer(nethttp.HandlerFunc(func(w nethttp.ResponseWriter, r *nethttp.Request) {
		if r.URL.Path != "/api/control/admin/tasks/task-2" {
			w.WriteHeader(nethttp.StatusNotFound)
			return
		}
		if r.Method != nethttp.MethodDelete {
			t.Fatalf("expected DELETE, got %s", r.Method)
		}
		_ = json.NewEncoder(w).Encode(map[string]any{
			"status": "ok",
			"result": map[string]any{"task_id": "task-2", "status": "cancelled"},
		})
	}))
	defer server.Close()
	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"task", "cancel", "task-2"}, &out, &err)
	if exitCode != 0 {
		t.Fatalf("expected exit code 0, got %d, stdout=%q, stderr=%q", exitCode, out.String(), err.String())
	}
	response := decodeRunResponse(t, out.String())
	if !response.OK {
		t.Fatalf("expected ok=true response, got %q", out.String())
	}
	dataMap, ok := response.Data.(map[string]any)
	if !ok {
		t.Fatalf("expected object data payload, got %T", response.Data)
	}
	if dataMap["status"] != "cancelled" {
		t.Fatalf("expected cancelled task, got %v", dataMap)
	}
}

func TestRunTaskRequiresID(t *testing.T) {
	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"task", "get"}, &out, &err)
	if exitCode != 1 {
		t.Fatalf("expected exit code 1, got %d", exitCode)
	}
	response := decodeRunResponse(t, out.String())
	if response.Error == nil || response.Error.Code != "INVALID_ARGS" {
		t.Fatalf("expected INVALID_ARGS, got %q", out.String())
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
		case "/api/search/knowledge-base":
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "ok",
				"result": map[string]any{
					"items": []any{map[string]any{"title": "k1"}},
				},
			})
		case "/api/search/skill":
			w.WriteHeader(nethttp.StatusServiceUnavailable)
			_ = json.NewEncoder(w).Encode(map[string]any{
				"status": "error",
				"error": map[string]any{
					"code":    "UNAVAILABLE",
					"message": "skill service down",
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

	t.Setenv("BIBLE_CLI_BASE_URL", server.URL)

	var out bytes.Buffer
	var err bytes.Buffer
	exitCode := Run([]string{"search", "--query", "faith", "--enable-hit", "--knowledge-tag", "design"}, &out, &err)
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
