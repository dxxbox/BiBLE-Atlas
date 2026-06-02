package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

type taskRecord struct {
	TaskID string         `json:"task_id"`
	Status string         `json:"status"`
	Domain string         `json:"domain,omitempty"`
	Tag    string         `json:"tag,omitempty"`
	Result map[string]any `json:"result,omitempty"`
}

type mockServer struct {
	mux       *http.ServeMux
	counter   atomic.Uint64
	mu        sync.RWMutex
	tasks     map[string]taskRecord
	artifacts map[string][]byte
}

func main() {
	addr := flag.String("addr", "127.0.0.1:5555", "listen address")
	flag.Parse()

	server := newMockServer()
	log.Printf("BiBLE Atlas mock server listening on http://%s", *addr)
	log.Printf("Use: export BIBLE_CLI_BASE_URL=http://%s", *addr)
	if err := http.ListenAndServe(*addr, server.mux); err != nil {
		log.Fatal(err)
	}
}

func newMockServer() *mockServer {
	s := &mockServer{
		mux:       http.NewServeMux(),
		tasks:     map[string]taskRecord{},
		artifacts: map[string][]byte{},
	}
	s.routes()
	return s
}

func (s *mockServer) routes() {
	s.mux.HandleFunc("/health", s.health)
	s.mux.HandleFunc("/api/v1/system/status", s.systemStatus)
	s.mux.HandleFunc("/api/v1/system/info", s.systemInfo)
	s.mux.HandleFunc("/api/v1/knowledge/list", s.legacyKnowledgeList)
	s.mux.HandleFunc("/api/control/docs/list", s.knowledgeList)
	s.mux.HandleFunc("/api/search/knowledge-base", s.knowledgeSearch)
	s.mux.HandleFunc("/api/search/memory", s.memorySearch)
	s.mux.HandleFunc("/api/search/skill", s.skillSearch)
	s.mux.HandleFunc("/api/import/knowledge-base", s.importKnowledge)
	s.mux.HandleFunc("/api/import/memory", s.importMemory)
	s.mux.HandleFunc("/api/import/skill", s.importSkill)
	s.mux.HandleFunc("/api/download/memory/file", s.downloadMemoryFile)
	s.mux.HandleFunc("/api/download/memory/batch", s.downloadMemoryBatch)
	s.mux.HandleFunc("/api/download/skill/file", s.downloadSkillFile)
	s.mux.HandleFunc("/api/download/skill/batch", s.downloadSkillBatch)
	s.mux.HandleFunc("/api/download/memory/artifact/", s.memoryArtifact)
	s.mux.HandleFunc("/api/download/skill/artifact/", s.skillArtifact)
	s.mux.HandleFunc("/api/control/admin/tasks/", s.task)
}

func (s *mockServer) health(w http.ResponseWriter, r *http.Request) {
	if !method(w, r, http.MethodGet) {
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "ok",
		"service": "bible-atlas-mock",
		"time":    time.Now().UTC().Format(time.RFC3339),
	})
}

func (s *mockServer) systemStatus(w http.ResponseWriter, r *http.Request) {
	if !method(w, r, http.MethodGet) {
		return
	}
	writeEnvelope(w, map[string]any{"status": "running", "mode": "mock"})
}

func (s *mockServer) systemInfo(w http.ResponseWriter, r *http.Request) {
	if !method(w, r, http.MethodGet) {
		return
	}
	writeEnvelope(w, map[string]any{"name": "BiBLE Atlas Mock", "version": "dev"})
}

func (s *mockServer) legacyKnowledgeList(w http.ResponseWriter, r *http.Request) {
	if !method(w, r, http.MethodGet) {
		return
	}
	writeEnvelope(w, knowledgeListPayload())
}

func (s *mockServer) knowledgeList(w http.ResponseWriter, r *http.Request) {
	if !method(w, r, http.MethodGet) {
		return
	}
	writeEnvelope(w, knowledgeListPayload())
}

func (s *mockServer) knowledgeSearch(w http.ResponseWriter, r *http.Request) {
	s.search(w, r, "KNOWLEDGE_BASE", "knowledge_base")
}

func (s *mockServer) memorySearch(w http.ResponseWriter, r *http.Request) {
	s.search(w, r, "MEMORY", "memory")
}

func (s *mockServer) skillSearch(w http.ResponseWriter, r *http.Request) {
	s.search(w, r, "SKILL", "skill")
}

func (s *mockServer) search(w http.ResponseWriter, r *http.Request, domain string, resultKey string) {
	if !method(w, r, http.MethodPost) {
		return
	}
	var body map[string]any
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "INVALID_ARGUMENT", "invalid JSON body")
		return
	}
	query, _ := body["query"].(string)
	tag, _ := body["tag"].(string)
	if strings.TrimSpace(tag) == "" {
		writeError(w, http.StatusBadRequest, "INVALID_ARGUMENT", "tag is required")
		return
	}
	writeEnvelope(w, map[string]any{
		"domain": domain,
		"tag":    tag,
		"query":  query,
		"total":  1,
		"items": []any{
			map[string]any{
				"id":                    strings.ToLower(domain) + "_mock_1",
				"title":                 "mock result for " + query,
				"score":                 0.99,
				"content":               "This is a mock search result.",
				"related_storage_paths": []string{resultKey + "/mock-artifact"},
			},
		},
	})
}

func (s *mockServer) importKnowledge(w http.ResponseWriter, r *http.Request) {
	s.importDomain(w, r, "KNOWLEDGE_BASE")
}

func (s *mockServer) importMemory(w http.ResponseWriter, r *http.Request) {
	s.importDomain(w, r, "MEMORY")
}

func (s *mockServer) importSkill(w http.ResponseWriter, r *http.Request) {
	s.importDomain(w, r, "SKILL")
}

func (s *mockServer) importDomain(w http.ResponseWriter, r *http.Request, domain string) {
	if !method(w, r, http.MethodPost) {
		return
	}
	if err := r.ParseMultipartForm(64 << 20); err != nil {
		writeError(w, http.StatusBadRequest, "INVALID_ARGUMENT", "invalid multipart form")
		return
	}
	tag := firstFormValue(r, "tag")
	kbIndex := firstFormValue(r, "kb_index")
	if strings.TrimSpace(kbIndex) == "" {
		writeError(w, http.StatusBadRequest, "INVALID_ARGUMENT", "kb_index is required")
		return
	}
	task := s.newTask("import", domain, tag, nil)
	writeJSON(w, http.StatusAccepted, map[string]any{
		"success":  true,
		"task_id":  task.TaskID,
		"domain":   domain,
		"kb_index": kbIndex,
		"tag":      tag,
		"status":   "queued",
	})
}

func (s *mockServer) downloadMemoryFile(w http.ResponseWriter, r *http.Request) {
	s.downloadFile(w, r, "memory")
}

func (s *mockServer) downloadSkillFile(w http.ResponseWriter, r *http.Request) {
	s.downloadFile(w, r, "skill")
}

func (s *mockServer) downloadMemoryBatch(w http.ResponseWriter, r *http.Request) {
	s.downloadBatch(w, r, "memory")
}

func (s *mockServer) downloadSkillBatch(w http.ResponseWriter, r *http.Request) {
	s.downloadBatch(w, r, "skill")
}

func (s *mockServer) downloadFile(w http.ResponseWriter, r *http.Request, domain string) {
	if !method(w, r, http.MethodPost) {
		return
	}
	var body map[string]any
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "INVALID_ARGUMENT", "invalid JSON body")
		return
	}
	storagePath, _ := body["storage_path"].(string)
	if strings.TrimSpace(storagePath) == "" {
		writeError(w, http.StatusBadRequest, "INVALID_ARGUMENT", "storage_path is required")
		return
	}
	name, _ := body["download_name"].(string)
	if strings.TrimSpace(name) == "" {
		name = storagePath[strings.LastIndex(storagePath, "/")+1:]
	}
	task := s.newDownloadTask(domain, name, []byte("mock "+domain+" artifact for "+storagePath+"\n"))
	writeEnvelope(w, map[string]any{"task_id": task.TaskID, "status": "queued", "domain": strings.ToUpper(domain)})
}

func (s *mockServer) downloadBatch(w http.ResponseWriter, r *http.Request, domain string) {
	if !method(w, r, http.MethodPost) {
		return
	}
	var body map[string]any
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "INVALID_ARGUMENT", "invalid JSON body")
		return
	}
	paths, _ := body["storage_paths"].([]any)
	if len(paths) == 0 {
		writeError(w, http.StatusBadRequest, "INVALID_ARGUMENT", "storage_paths is required")
		return
	}
	packageName, _ := body["package_name"].(string)
	if strings.TrimSpace(packageName) == "" {
		packageName = domain + "_bundle.zip"
	}
	task := s.newDownloadTask(domain, packageName, []byte("mock "+domain+" batch artifact\n"))
	writeEnvelope(w, map[string]any{"task_id": task.TaskID, "status": "queued", "domain": strings.ToUpper(domain)})
}

func (s *mockServer) task(w http.ResponseWriter, r *http.Request) {
	taskID := strings.TrimPrefix(r.URL.Path, "/api/control/admin/tasks/")
	if strings.TrimSpace(taskID) == "" {
		writeError(w, http.StatusBadRequest, "INVALID_ARGUMENT", "task_id is required")
		return
	}
	switch r.Method {
	case http.MethodGet:
		s.mu.RLock()
		task, ok := s.tasks[taskID]
		s.mu.RUnlock()
		if !ok {
			task = taskRecord{TaskID: taskID, Status: "completed"}
		}
		task.Status = "completed"
		writeJSON(w, http.StatusOK, task)
	case http.MethodDelete:
		task := taskRecord{TaskID: taskID, Status: "cancelled"}
		s.mu.Lock()
		s.tasks[taskID] = task
		s.mu.Unlock()
		writeEnvelope(w, task)
	default:
		writeError(w, http.StatusMethodNotAllowed, "METHOD_NOT_ALLOWED", "method not allowed")
	}
}

func (s *mockServer) memoryArtifact(w http.ResponseWriter, r *http.Request) {
	s.artifact(w, r, "/api/download/memory/artifact/")
}

func (s *mockServer) skillArtifact(w http.ResponseWriter, r *http.Request) {
	s.artifact(w, r, "/api/download/skill/artifact/")
}

func (s *mockServer) artifact(w http.ResponseWriter, r *http.Request, prefix string) {
	if !method(w, r, http.MethodGet) {
		return
	}
	artifactID := strings.TrimPrefix(r.URL.Path, prefix)
	s.mu.RLock()
	data, ok := s.artifacts[artifactID]
	s.mu.RUnlock()
	if !ok {
		writeError(w, http.StatusNotFound, "DOWNLOAD_ARTIFACT_NOT_FOUND", "artifact not found")
		return
	}
	w.Header().Set("Content-Type", "application/octet-stream")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s.bin"`, artifactID))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(data)
}

func (s *mockServer) newTask(kind string, domain string, tag string, result map[string]any) taskRecord {
	id := fmt.Sprintf("%s_%s_%d", kind, strings.ToLower(domain), s.counter.Add(1))
	task := taskRecord{TaskID: id, Status: "completed", Domain: domain, Tag: tag, Result: result}
	s.mu.Lock()
	s.tasks[id] = task
	s.mu.Unlock()
	return task
}

func (s *mockServer) newDownloadTask(domain string, artifactName string, data []byte) taskRecord {
	artifactID := fmt.Sprintf("artifact_%s_%d", domain, s.counter.Add(1))
	s.mu.Lock()
	s.artifacts[artifactID] = data
	s.mu.Unlock()
	return s.newTask("download", strings.ToUpper(domain), domain, map[string]any{
		"artifact_id":   artifactID,
		"artifact_name": artifactName,
		"content_type":  "application/octet-stream",
		"size_bytes":    len(data),
		"expires_at":    time.Now().UTC().Add(24 * time.Hour).Format(time.RFC3339),
	})
}

func knowledgeListPayload() map[string]any {
	return map[string]any{
		"items": []any{
			map[string]any{"tag": "design", "kb_index": "kb_test", "domain": "KNOWLEDGE_BASE"},
			map[string]any{"tag": "flow", "kb_index": "kb_test", "domain": "KNOWLEDGE_BASE"},
		},
		"total": 2,
	}
}

func firstFormValue(r *http.Request, key string) string {
	values := r.MultipartForm.Value[key]
	if len(values) == 0 {
		return ""
	}
	return values[0]
}

func method(w http.ResponseWriter, r *http.Request, expected string) bool {
	if r.Method == expected {
		return true
	}
	writeError(w, http.StatusMethodNotAllowed, "METHOD_NOT_ALLOWED", "method not allowed")
	_, _ = io.Copy(io.Discard, r.Body)
	return false
}

func writeEnvelope(w http.ResponseWriter, result any) {
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "result": result})
}

func writeError(w http.ResponseWriter, status int, code string, message string) {
	writeJSON(w, status, map[string]any{
		"status": "error",
		"error":  map[string]any{"code": code, "message": message},
	})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
