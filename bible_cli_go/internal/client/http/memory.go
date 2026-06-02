package http

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"net"
	nethttp "net/http"
	"net/textproto"
	"os"
	"time"

	"bible-cli-go/internal/protocol"
)

// MemoryFile describes a single file to include in a multipart import request.
type MemoryFile struct {
	Filename    string
	ContentType string
	Path        string
	FieldName   string
}

// MemoryImportRequest holds all parameters for ImportMemory.
// Files must include exactly one meta.json; message.json is optional.
type MemoryImportRequest struct {
	Files         []MemoryFile
	KbIndex       string
	Tag           string // always "memory"
	VectorModel   string
	ParserContext string
}

// SkillImportRequest holds parameters for ImportSkill.
type SkillImportRequest struct {
	File          MemoryFile
	KbIndex       string
	Tag           string // always "skill"
	VectorModel   string
	ParserContext string
}

// KnowledgeImportRequest holds parameters for ImportKnowledge.
type KnowledgeImportRequest struct {
	Files         []MemoryFile
	ParserScript  *MemoryFile
	KbIndex       string
	Tag           string
	VectorModel   string
	ParserContext string
}

// KnowledgeSearchRequest holds parameters for KnowledgeSearch.
type KnowledgeSearchRequest struct {
	Query      string
	Tag        string
	TopK       int
	SearchType string
}

// MemorySearchRequest holds parameters for MemorySearch.
type MemorySearchRequest struct {
	Query       string
	TopK        int
	Threshold   float64
	SearchType  string
	VectorModel string
	Page        int
	FilterTag   string
	Since       string
}

// SkillSearchRequest holds parameters for SkillSearch.
type SkillSearchRequest struct {
	Query      string
	Tag        string
	SearchType string
	TopK       int
	Threshold  float64
	Page       int
	FilterTag  string
}

// DownloadFileRequest holds parameters for POST /api/download/{domain}/file.
type DownloadFileRequest struct {
	Tag          string
	StoragePath  string
	DownloadName string
}

// DownloadBatchRequest holds parameters for POST /api/download/{domain}/batch.
type DownloadBatchRequest struct {
	Tag             string
	StoragePaths    []string
	PackageName     string
	IncludeMetadata bool
}

// BaseURL returns the configured server base URL.
func (c *Client) BaseURL() string {
	return c.baseURL
}

// MemorySearch calls POST /api/search/memory.
func (c *Client) MemorySearch(req MemorySearchRequest) (map[string]any, error) {
	body := map[string]any{
		"query": req.Query,
		"top_k": req.TopK,
		"tag":   "memory",
	}
	if req.Threshold > 0 {
		body["threshold"] = req.Threshold
	}
	if req.SearchType != "" {
		body["search_type"] = req.SearchType
	}
	if req.VectorModel != "" {
		body["vector_model"] = req.VectorModel
	}
	if req.Page > 0 {
		body["page"] = req.Page
	}
	if req.FilterTag != "" {
		body["filter_tag"] = req.FilterTag
	}
	if req.Since != "" {
		body["since"] = req.Since
	}
	return c.postEnvelope("/api/search/memory", body)
}

// SkillSearch calls POST /api/search/skill.
func (c *Client) SkillSearch(req SkillSearchRequest) (map[string]any, error) {
	body := map[string]any{
		"query": req.Query,
		"top_k": req.TopK,
		"tag":   "skill",
	}
	if req.SearchType != "" {
		body["search_type"] = req.SearchType
	}
	if req.Threshold > 0 {
		body["threshold"] = req.Threshold
	}
	if req.Page > 0 {
		body["page"] = req.Page
	}
	if req.FilterTag != "" {
		body["filter_tag"] = req.FilterTag
	}
	return c.postEnvelope("/api/search/skill", body)
}

// GetTask queries GET /api/control/admin/tasks/{task_id}.
func (c *Client) GetTask(taskID string) (map[string]any, error) {
	payload, _, err := c.getJSON("/api/control/admin/tasks/" + taskID)
	return payload, err
}

// CancelTask cancels a task via DELETE /api/control/admin/tasks/{task_id}.
func (c *Client) CancelTask(taskID string) (map[string]any, error) {
	request, err := nethttp.NewRequest(nethttp.MethodDelete, c.baseURL+"/api/control/admin/tasks/"+taskID, nil)
	if err != nil {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	c.addAuthHeader(request)

	resp, err := c.client.Do(request)
	if err != nil {
		var netErr net.Error
		if errors.As(err, &netErr) && netErr.Timeout() {
			return nil, protocol.CLIError{Code: "TIMEOUT", Message: "HTTP request timed out.", ExitCode: 1}
		}
		return nil, protocol.CLIError{Code: "UNAVAILABLE", Message: "HTTP transport error.", ExitCode: 1}
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to read HTTP response body.", ExitCode: 1}
	}

	var payload map[string]any
	if len(respBody) == 0 {
		payload = map[string]any{}
	} else if err := json.Unmarshal(respBody, &payload); err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Invalid JSON response.", ExitCode: 1}
	}

	if resp.StatusCode >= 400 {
		return nil, errorFromStatus(resp.StatusCode, payload)
	}
	if status, _ := payload["status"].(string); status == "ok" {
		if result, ok := payload["result"].(map[string]any); ok {
			return result, nil
		}
	}
	return payload, nil
}

// PollTask polls GET /api/control/admin/tasks/{task_id} until the task reaches
// a terminal state (completed, failed, or cancelled) or the timeout elapses.
func (c *Client) PollTask(taskID string, interval, timeout time.Duration) (map[string]any, error) {
	deadline := time.Now().Add(timeout)
	for {
		payload, err := c.GetTask(taskID)
		if err != nil {
			return nil, err
		}
		status, _ := payload["status"].(string)
		switch status {
		case "completed", "failed", "cancelled":
			return payload, nil
		}
		if time.Now().After(deadline) {
			return nil, protocol.CLIError{
				Code:     "TIMEOUT",
				Message:  fmt.Sprintf("Task %s did not complete within %s.", taskID, timeout),
				ExitCode: 1,
			}
		}
		time.Sleep(interval)
	}
}

// ImportMemory uploads memory files to POST /api/import/memory.
// Retries on network errors and 5xx with exponential backoff (1s → 4s → 16s).
// Client errors (4xx) are returned immediately without retry.
func (c *Client) ImportMemory(req MemoryImportRequest) (map[string]any, error) {
	if req.Tag == "" {
		req.Tag = "memory"
	}
	return c.postMultipartImport("/api/import/memory", req.Files, req.KbIndex, req.Tag, req.VectorModel, req.ParserContext)
}

// ImportSkill uploads a skill package to POST /api/import/skill.
// Retries on network errors and 5xx with exponential backoff (1s → 4s → 16s).
func (c *Client) ImportSkill(req SkillImportRequest) (map[string]any, error) {
	if req.Tag == "" {
		req.Tag = "skill"
	}
	files := []MemoryFile{req.File}
	return c.postMultipartImport("/api/import/skill", files, req.KbIndex, req.Tag, req.VectorModel, req.ParserContext)
}

// ImportKnowledge uploads knowledge-base files to POST /api/import/knowledge-base.
func (c *Client) ImportKnowledge(req KnowledgeImportRequest) (map[string]any, error) {
	files := make([]MemoryFile, 0, len(req.Files)+1)
	files = append(files, req.Files...)
	if req.ParserScript != nil {
		parserScript := *req.ParserScript
		parserScript.FieldName = "parser_script"
		files = append(files, parserScript)
	}
	return c.postMultipartImport("/api/import/knowledge-base", files, req.KbIndex, req.Tag, req.VectorModel, req.ParserContext)
}

// DownloadFile starts an async download job via POST /api/download/{domain}/file.
func (c *Client) DownloadFile(domain string, req DownloadFileRequest) (map[string]any, error) {
	body := map[string]any{
		"tag":          req.Tag,
		"storage_path": req.StoragePath,
	}
	if req.DownloadName != "" {
		body["download_name"] = req.DownloadName
	}
	return c.postEnvelopeOrPlain("/api/download/"+domain+"/file", body)
}

// DownloadBatch starts an async batch download job via POST /api/download/{domain}/batch.
func (c *Client) DownloadBatch(domain string, req DownloadBatchRequest) (map[string]any, error) {
	body := map[string]any{
		"tag":              req.Tag,
		"storage_paths":    req.StoragePaths,
		"include_metadata": req.IncludeMetadata,
	}
	if req.PackageName != "" {
		body["package_name"] = req.PackageName
	}
	return c.postEnvelopeOrPlain("/api/download/"+domain+"/batch", body)
}

func (c *Client) postEnvelopeOrPlain(path string, requestBody map[string]any) (map[string]any, error) {
	payload, statusCode, err := c.postJSON(path, requestBody)
	if err != nil {
		return nil, err
	}

	status, _ := payload["status"].(string)
	if status == "ok" {
		result, exists := payload["result"]
		if !exists {
			return payload, nil
		}
		if resultObject, ok := result.(map[string]any); ok {
			return resultObject, nil
		}
		return map[string]any{"result": result}, nil
	}
	if status == "error" {
		return nil, parseErrorPayload(payload["error"], statusCode)
	}

	return payload, nil
}

// GetArtifact downloads the artifact binary for a completed download task.
// Returns the raw bytes.
func (c *Client) GetArtifact(domain, artifactID string) ([]byte, error) {
	path := "/api/download/" + domain + "/artifact/" + artifactID
	request, err := nethttp.NewRequest(nethttp.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	c.addAuthHeader(request)

	resp, err := c.client.Do(request)
	if err != nil {
		var netErr net.Error
		if errors.As(err, &netErr) && netErr.Timeout() {
			return nil, protocol.CLIError{Code: "TIMEOUT", Message: "HTTP request timed out.", ExitCode: 1}
		}
		return nil, protocol.CLIError{Code: "UNAVAILABLE", Message: "HTTP transport error.", ExitCode: 1}
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		var payload map[string]any
		_ = json.NewDecoder(resp.Body).Decode(&payload)
		return nil, errorFromStatus(resp.StatusCode, payload)
	}

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to read artifact response.", ExitCode: 1}
	}
	return data, nil
}

func (c *Client) postMultipartImport(apiPath string, files []MemoryFile, kbIndex, tag, vectorModel, parserContext string) (map[string]any, error) {
	backoffs := []time.Duration{1 * time.Second, 4 * time.Second, 16 * time.Second}
	var lastErr error
	for attempt := 0; attempt <= len(backoffs); attempt++ {
		if attempt > 0 {
			time.Sleep(backoffs[attempt-1])
		}
		payload, statusCode, err := c.doMultipartImport(apiPath, files, kbIndex, tag, vectorModel, parserContext)
		if err == nil {
			return payload, nil
		}
		if statusCode >= 400 && statusCode < 500 {
			return nil, err
		}
		lastErr = err
	}
	return nil, lastErr
}

func (c *Client) doMultipartImport(apiPath string, files []MemoryFile, kbIndex, tag, vectorModel, parserContext string) (map[string]any, int, error) {
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)

	for _, f := range files {
		fileData, err := os.ReadFile(f.Path)
		if err != nil {
			return nil, 0, protocol.CLIError{
				Code:     "INVALID_ARGS",
				Message:  fmt.Sprintf("Cannot read file %s: %v", f.Filename, err),
				ExitCode: 1,
			}
		}
		ct := f.ContentType
		if ct == "" {
			ct = "application/json"
		}
		h := make(textproto.MIMEHeader)
		fieldName := f.FieldName
		if fieldName == "" {
			fieldName = "files"
		}
		h.Set("Content-Disposition", fmt.Sprintf(`form-data; name="%s"; filename="%s"`, fieldName, f.Filename))
		h.Set("Content-Type", ct)
		part, err := writer.CreatePart(h)
		if err != nil {
			return nil, 0, protocol.CLIError{Code: "INTERNAL", Message: "Failed to create multipart field.", ExitCode: 1}
		}
		if _, err := part.Write(fileData); err != nil {
			return nil, 0, protocol.CLIError{Code: "INTERNAL", Message: "Failed to write multipart data.", ExitCode: 1}
		}
	}

	if tag != "" {
		if err := writer.WriteField("tag", tag); err != nil {
			return nil, 0, protocol.CLIError{Code: "INTERNAL", Message: "Failed to write tag field.", ExitCode: 1}
		}
	}
	if kbIndex != "" {
		if err := writer.WriteField("kb_index", kbIndex); err != nil {
			return nil, 0, protocol.CLIError{Code: "INTERNAL", Message: "Failed to write kb_index field.", ExitCode: 1}
		}
	}
	if vectorModel != "" {
		if err := writer.WriteField("vector_model", vectorModel); err != nil {
			return nil, 0, protocol.CLIError{Code: "INTERNAL", Message: "Failed to write vector_model field.", ExitCode: 1}
		}
	}
	if parserContext != "" {
		if err := writer.WriteField("parser_context", parserContext); err != nil {
			return nil, 0, protocol.CLIError{Code: "INTERNAL", Message: "Failed to write parser_context field.", ExitCode: 1}
		}
	}

	if err := writer.Close(); err != nil {
		return nil, 0, protocol.CLIError{Code: "INTERNAL", Message: "Failed to finalize multipart body.", ExitCode: 1}
	}

	httpReq, err := nethttp.NewRequest(nethttp.MethodPost, c.baseURL+apiPath, &body)
	if err != nil {
		return nil, 0, protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	httpReq.Header.Set("Content-Type", writer.FormDataContentType())
	c.addAuthHeader(httpReq)

	resp, err := c.client.Do(httpReq)
	if err != nil {
		var netErr net.Error
		if errors.As(err, &netErr) && netErr.Timeout() {
			return nil, 0, protocol.CLIError{Code: "TIMEOUT", Message: "HTTP request timed out.", ExitCode: 1}
		}
		return nil, 0, protocol.CLIError{Code: "UNAVAILABLE", Message: "HTTP transport error.", ExitCode: 1}
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, resp.StatusCode, protocol.CLIError{Code: "INTERNAL", Message: "Failed to read HTTP response body.", ExitCode: 1}
	}

	var payload map[string]any
	if len(respBody) == 0 {
		payload = map[string]any{}
	} else if err := json.Unmarshal(respBody, &payload); err != nil {
		return nil, resp.StatusCode, protocol.CLIError{Code: "INTERNAL", Message: "Invalid JSON response.", ExitCode: 1}
	}

	if resp.StatusCode >= 400 {
		return nil, resp.StatusCode, errorFromStatus(resp.StatusCode, payload)
	}

	return payload, resp.StatusCode, nil
}
