package commands

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	clienthttp "bible-cli-go/internal/client/http"
	"bible-cli-go/internal/cache"
	"bible-cli-go/internal/config"
	"bible-cli-go/internal/meta"
	"bible-cli-go/internal/protocol"
)

// SessionCommandOptions aggregates all flags from session subcommands.
type SessionCommandOptions struct {
	// list
	Limit int
	UID   string

	// get
	ID string

	// save
	Input   string
	KbIndex string
	Wait    bool
}

// SessionExecute dispatches a session subcommand.
func (d *Dispatcher) SessionExecute(action string, opts SessionCommandOptions) (map[string]any, error) {
	switch action {
	case "list":
		return sessionList(d.client, opts)
	case "get":
		return sessionGet(d.client, opts)
	case "save":
		return sessionSave(d.client, opts, d.cfg)
	default:
		return nil, protocol.NotImplemented("session " + action)
	}
}

func sessionList(client *clienthttp.Client, opts SessionCommandOptions) (map[string]any, error) {
	limit := opts.Limit
	if limit <= 0 {
		limit = 10
	}
	req := clienthttp.MemorySearchRequest{
		Query:      "",
		TopK:       limit,
		SearchType: "title",
	}
	return client.MemorySearch(req)
}

func sessionGet(client *clienthttp.Client, opts SessionCommandOptions) (map[string]any, error) {
	id := strings.TrimSpace(opts.ID)
	if id == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "--id is required for session get.", ExitCode: 1}
	}
	req := clienthttp.MemorySearchRequest{
		Query:      id,
		TopK:       1,
		SearchType: "keyword",
	}
	return client.MemorySearch(req)
}

func sessionSave(client *clienthttp.Client, opts SessionCommandOptions, cfg config.ClientConfig) (map[string]any, error) {
	inputStr := strings.TrimSpace(opts.Input)
	if inputStr == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "--input is required for session save.", ExitCode: 1}
	}

	var input meta.SessionMessages
	if err := json.Unmarshal([]byte(inputStr), &input); err != nil {
		return nil, protocol.CLIError{
			Code:    "INVALID_ARGS",
			Message: "Invalid --input JSON: " + err.Error(),
			ExitCode: 1,
		}
	}
	if len(input.Messages) == 0 {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "--input must contain at least one message.", ExitCode: 1}
	}

	// Generate a session ID from timestamp.
	sessionID := fmt.Sprintf("session_%d", time.Now().UnixNano())

	// Create a temp directory for this session.
	tmpDir, err := os.MkdirTemp("", "bible_session_*")
	if err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to create temp dir: " + err.Error(), ExitCode: 1}
	}
	defer os.RemoveAll(tmpDir)

	// Build and write message.json.
	msgBytes, err := meta.BuildMessageJSONFromMessages(sessionID, input.Messages)
	if err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to build message.json: " + err.Error(), ExitCode: 1}
	}
	msgPath := filepath.Join(tmpDir, "message.json")
	if err := os.WriteFile(msgPath, msgBytes, 0o644); err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to write message.json: " + err.Error(), ExitCode: 1}
	}

	// Build meta.json.
	buildOpts := meta.BuildOptions{
		TitleOverride:    input.Title,
		AbstractTruncate: true,
	}
	m, err := meta.BuildMetaFromMessageJSON(msgPath, tmpDir, buildOpts)
	if err != nil {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if err := meta.WriteMetaJSON(tmpDir, m); err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to write meta.json: " + err.Error(), ExitCode: 1}
	}

	// Resolve kb_index.
	kbIndex := resolveKbIndex(opts.KbIndex, cfg)
	if kbIndex == "" {
		return nil, protocol.CLIError{
			Code:    "INVALID_ARGS",
			Message: "kb_index is required. Provide --kb-index flag or set BIBLE_MEMORY_KB_INDEX environment variable.",
			ExitCode: 1,
		}
	}

	metaPath := filepath.Join(tmpDir, "meta.json")
	files := []clienthttp.MemoryFile{
		{Filename: "meta.json", Path: metaPath, ContentType: "application/json"},
		{Filename: "message.json", Path: msgPath, ContentType: "application/json"},
	}

	importReq := clienthttp.MemoryImportRequest{
		Files:   files,
		KbIndex: kbIndex,
		Tag:     "memory",
	}

	payload, err := client.ImportMemory(importReq)
	if err != nil {
		return nil, err
	}

	taskID, _ := payload["task_id"].(string)
	if opts.Wait && taskID != "" {
		return client.PollTask(taskID, 3*time.Second, 5*time.Minute)
	}

	// Persist minimal cache in a permanent location keyed by memory_id.
	if taskID != "" {
		metaHash, _ := cache.SHA256File(metaPath)
		cacheDir := filepath.Join(os.TempDir(), "bible_memory_cache")
		_ = os.MkdirAll(cacheDir, 0o755)
		entry := cache.MemoryCacheEntry{
			MemoryID:     m.MemoryID,
			KbIndex:      kbIndex,
			MetaHash:     metaHash,
			TaskID:       taskID,
			UploadStatus: "accepted",
			UploadedAt:   time.Now().UTC().Format(time.RFC3339),
			ServerURL:    client.BaseURL(),
		}
		_ = cache.SaveCache(cacheDir, entry)
	}

	return payload, nil
}
