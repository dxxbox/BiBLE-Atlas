package commands

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"bible-cli-go/internal/cache"
	clienthttp "bible-cli-go/internal/client/http"
	"bible-cli-go/internal/config"
	"bible-cli-go/internal/logger"
	"bible-cli-go/internal/meta"
	"bible-cli-go/internal/protocol"
)

// MemoryCommandOptions aggregates all flags from memory subcommands.
type MemoryCommandOptions struct {
	// upload / upload-all
	SessionDir   string
	BaseDir      string
	KbIndex      string
	VectorModel  string
	TaskIDs      []string
	FeatureTags  []string
	DomainTags   []string
	SkipIfExists bool
	Wait         bool
	Output       string
	Workers      int

	// status
	TaskID   string
	MemoryID string
	CacheDir string
	// SessionID is a deprecated alias; kept for backward compat with --session-id flag.
	SessionID string

	// list
	Page  int
	Limit int
	Tag   string
	Since string

	// search
	Query      string
	TopK       int
	Threshold  float64
	SearchType string
	// TestMode: set when any standalone `--test` / `-test` appears in memory
	// subcommand args (peeled in cli.parseMemoryFlags before per-action FlagSet).
	TestMode bool

	// import
	SourceFile string
	MetaFile   string

	// download
	StoragePath     string
	StoragePaths    []string
	OutputDir       string
	DownloadName    string
	PackageName     string
	IncludeMetadata bool
}

// MemoryExecute dispatches a memory subcommand.
func (d *Dispatcher) MemoryExecute(action string, opts MemoryCommandOptions) (map[string]any, error) {
	switch action {
	case "upload":
		return memoryUpload(d.client, opts, d.cfg)
	case "upload-all":
		return memoryUploadAll(d.client, opts, d.cfg)
	case "build-meta":
		return memoryBuildMeta(opts)
	case "status":
		return memoryStatus(d.client, opts)
	case "list":
		return memoryList(d.client, opts)
	case "search":
		return runMemorySearch(d.client, opts)
	case "cache-status":
		return memoryCacheStatus(opts)
	case "download":
		return memoryDownload(d.client, opts)
	case "import":
		return memoryImport(d.client, opts, d.cfg)
	default:
		return nil, protocol.NotImplemented("memory " + action)
	}
}

// resolveKbIndex returns the kb_index to use, checking flag → env → config.
func resolveKbIndex(flagValue string, cfg config.ClientConfig) string {
	if strings.TrimSpace(flagValue) != "" {
		return strings.TrimSpace(flagValue)
	}
	if v := strings.TrimSpace(os.Getenv("BIBLE_MEMORY_KB_INDEX")); v != "" {
		return v
	}
	return strings.TrimSpace(cfg.Memory.Upload.KbIndex)
}

// resolveVectorModel returns the vector_model to use, checking flag → env → config.
func resolveVectorModel(flagValue string, cfg config.ClientConfig) string {
	if strings.TrimSpace(flagValue) != "" {
		return strings.TrimSpace(flagValue)
	}
	if v := strings.TrimSpace(os.Getenv("BIBLE_MEMORY_VECTOR_MODEL")); v != "" {
		return v
	}
	return strings.TrimSpace(cfg.Memory.Upload.VectorModel)
}

func memoryUpload(client *clienthttp.Client, opts MemoryCommandOptions, cfg config.ClientConfig) (map[string]any, error) {
	sessionDir := opts.SessionDir
	if strings.TrimSpace(sessionDir) == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "session_dir is required.", ExitCode: 1}
	}

	if _, err := os.Stat(sessionDir); os.IsNotExist(err) {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  fmt.Sprintf("Session directory does not exist: %s", sessionDir),
			ExitCode: 1,
		}
	}

	msgPath := filepath.Join(sessionDir, "message.json")
	metaPath := filepath.Join(sessionDir, "meta.json")

	// Validate message.json exists and is parseable.
	if _, err := os.Stat(msgPath); os.IsNotExist(err) {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  fmt.Sprintf("message.json not found in %s", sessionDir),
			ExitCode: 1,
		}
	}

	// Validate message.json is valid JSON.
	rawMsg, err := os.ReadFile(msgPath)
	if err != nil {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "Cannot read message.json: " + err.Error(), ExitCode: 1}
	}
	var msgCheck map[string]any
	if err := unmarshalJSON(rawMsg, &msgCheck); err != nil {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "message.json is not valid JSON: " + err.Error(), ExitCode: 1}
	}

	// Build meta.json if it does not exist.
	if _, err := os.Stat(metaPath); os.IsNotExist(err) {
		buildOpts := meta.BuildOptions{
			TaskIDs:          opts.TaskIDs,
			FeatureTags:      opts.FeatureTags,
			DomainTags:       opts.DomainTags,
			AbstractTruncate: cfg.Memory.Upload.AbstractTruncate,
		}
		m, err := meta.BuildMetaFromMessageJSON(msgPath, sessionDir, buildOpts)
		if err != nil {
			return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
		}
		if err := meta.WriteMetaJSON(sessionDir, m); err != nil {
			return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to write meta.json: " + err.Error(), ExitCode: 1}
		}
	}

	// Validate required meta fields.
	m, err := meta.LoadMetaJSON(sessionDir)
	if err != nil {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if m == nil {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "meta.json is missing.", ExitCode: 1}
	}
	// Plugin meta.json (VS Code MemoryMeta) often has session_id + abstract but no memory_id/title.
	patched, err := meta.PatchPluginMetaJSONForUpload(sessionDir, rawMsg)
	if err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to patch meta.json: " + err.Error(), ExitCode: 1}
	}
	if patched {
		m, err = meta.LoadMetaJSON(sessionDir)
		if err != nil {
			return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
		}
		if m == nil {
			return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "meta.json is missing.", ExitCode: 1}
		}
	}
	if strings.TrimSpace(m.MemoryID) == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "meta.json is missing required field: memory_id", ExitCode: 1}
	}
	if strings.TrimSpace(m.Title) == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "meta.json is missing required field: title", ExitCode: 1}
	}
	if strings.TrimSpace(m.Abstract) == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "meta.json is missing required field: abstract", ExitCode: 1}
	}

	// Resolve kb_index.
	kbIndex := resolveKbIndex(opts.KbIndex, cfg)
	if kbIndex == "" {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  "kb_index is required. Provide --kb-index flag or set BIBLE_MEMORY_KB_INDEX environment variable.",
			ExitCode: 1,
		}
	}

	// Compute meta_hash for idempotency.
	metaHash, err := cache.SHA256File(metaPath)
	if err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to hash meta.json: " + err.Error(), ExitCode: 1}
	}

	// Local cache skip check.
	if opts.SkipIfExists {
		cached, err := cache.LoadCache(sessionDir)
		if err == nil && cached != nil &&
			cached.MetaHash == metaHash &&
			cached.KbIndex == kbIndex &&
			cached.UploadStatus == "completed" {
			return map[string]any{
				"status":    "skipped",
				"memory_id": cached.MemoryID,
				"task_id":   cached.TaskID,
				"reason":    "already uploaded with same meta content",
			}, nil
		}
	}

	// IDE test mode: same envelope as successful POST /api/import/memory, no HTTP.
	if opts.TestMode {
		logger.Info("memory.upload.test", map[string]any{"session_dir": sessionDir, "kb_index": kbIndex})
		taskID := fmt.Sprintf("test-upload-task-%d", time.Now().UnixNano())
		payload := map[string]any{
			"task_id":   taskID,
			"status":    "accepted",
			"memory_id": m.MemoryID,
			"kb_index":  kbIndex,
			"tag":       "memory",
		}
		if sid, ok := sessionIDFromMessageJSON(rawMsg); ok && sid != "" {
			payload["session_id"] = sid
		}
		entry := cache.MemoryCacheEntry{
			MemoryID:     m.MemoryID,
			KbIndex:      kbIndex,
			MetaHash:     metaHash,
			TaskID:       taskID,
			UploadStatus: "accepted",
			UploadedAt:   time.Now().UTC().Format(time.RFC3339),
			ServerURL:    client.BaseURL(),
		}
		_ = cache.SaveCache(sessionDir, entry)
		if opts.Wait && taskID != "" {
			logger.Info("memory.upload.test.skip_poll", map[string]any{"task_id": taskID})
		}
		return payload, nil
	}

	vectorModel := resolveVectorModel(opts.VectorModel, cfg)

	// Build file list: meta.json is required; message.json is optional attachment.
	files := []clienthttp.MemoryFile{
		{Filename: "meta.json", Path: metaPath, ContentType: "application/json"},
	}
	if _, err := os.Stat(msgPath); err == nil {
		files = append(files, clienthttp.MemoryFile{
			Filename:    "message.json",
			Path:        msgPath,
			ContentType: "application/json",
		})
	}

	importReq := clienthttp.MemoryImportRequest{
		Files:       files,
		KbIndex:     kbIndex,
		Tag:         "memory",
		VectorModel: vectorModel,
	}

	payload, err := client.ImportMemory(importReq)
	if err != nil {
		return nil, err
	}

	taskID, _ := payload["task_id"].(string)
	uploadStatus := "accepted"
	if s, ok := payload["status"].(string); ok && s != "" {
		uploadStatus = s
	}

	// Persist cache.
	entry := cache.MemoryCacheEntry{
		MemoryID:     m.MemoryID,
		KbIndex:      kbIndex,
		MetaHash:     metaHash,
		TaskID:       taskID,
		UploadStatus: uploadStatus,
		UploadedAt:   time.Now().UTC().Format(time.RFC3339),
		ServerURL:    client.BaseURL(),
	}
	_ = cache.SaveCache(sessionDir, entry)

	// Optionally poll for completion.
	if opts.Wait && taskID != "" {
		finalPayload, pollErr := client.PollTask(taskID, 3*time.Second, 5*time.Minute)
		if pollErr != nil {
			return nil, pollErr
		}
		if finalStatus, ok := finalPayload["status"].(string); ok {
			entry.UploadStatus = finalStatus
			_ = cache.SaveCache(sessionDir, entry)
		}
		return finalPayload, nil
	}

	return payload, nil
}

// memoryImport implements `bible memory import`.
//
// Unlike `memory upload` which expects a session directory with a pre-existing
// message.json / meta.json layout, `memory import` accepts explicit file paths.
// This is the entry-point used by the VS Code plugin's chat-export strategy:
//
//	bible memory import \
//	  --source-file /tmp/bible-vscode/<id>/source.json \
//	  --meta-file   /tmp/bible-vscode/<id>/meta.json   \
//	  --kb-index    memory_main                         \
//	  --tag         memory
//
// Stub mode:
//   - When BIBLE_CLI_STUB_MODE=1 is set the server is never contacted and a
//     pre-canned "accepted" response is returned immediately.
//   Network / HTTP errors are returned to the caller (no automatic stub).
func memoryImport(client *clienthttp.Client, opts MemoryCommandOptions, cfg config.ClientConfig) (map[string]any, error) {
	sourceFile := strings.TrimSpace(opts.SourceFile)
	metaFile := strings.TrimSpace(opts.MetaFile)

	logger.Info("memory.import.start", map[string]any{
		"source_file": sourceFile,
		"meta_file":   metaFile,
		"kb_index":    opts.KbIndex,
		"tag":         opts.Tag,
	})

	// --- Input validation ---------------------------------------------------

	if sourceFile == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "--source-file is required.", ExitCode: 1}
	}
	if metaFile == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "--meta-file is required.", ExitCode: 1}
	}
	if _, err := os.Stat(sourceFile); os.IsNotExist(err) {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  fmt.Sprintf("source-file does not exist: %s", sourceFile),
			ExitCode: 1,
		}
	}
	if _, err := os.Stat(metaFile); os.IsNotExist(err) {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  fmt.Sprintf("meta-file does not exist: %s", metaFile),
			ExitCode: 1,
		}
	}

	kbIndex := resolveKbIndex(opts.KbIndex, cfg)
	if kbIndex == "" {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  "kb_index is required. Provide --kb-index flag or set BIBLE_MEMORY_KB_INDEX env variable.",
			ExitCode: 1,
		}
	}

	tag := strings.TrimSpace(opts.Tag)
	if tag == "" {
		tag = "memory"
	}

	// IDE test mode: accepted import envelope, no HTTP (no stub_* markers).
	if opts.TestMode {
		logger.Info("memory.import.test", map[string]any{"kb_index": kbIndex})
		rawMeta, err := os.ReadFile(metaFile)
		if err != nil {
			return nil, protocol.CLIError{Code: "INTERNAL", Message: err.Error(), ExitCode: 1}
		}
		var mf map[string]any
		_ = json.Unmarshal(rawMeta, &mf)
		sessionID, _ := mf["session_id"].(string)
		memoryID, _ := mf["memory_id"].(string)
		taskID := fmt.Sprintf("test-import-task-%d", time.Now().UnixNano())
		out := map[string]any{
			"task_id":  taskID,
			"status":   "accepted",
			"kb_index": kbIndex,
			"tag":      tag,
		}
		if sessionID != "" {
			out["session_id"] = sessionID
		}
		if memoryID != "" {
			out["memory_id"] = memoryID
		}
		return out, nil
	}

	// --- Stub mode shortcut -------------------------------------------------
	// Return immediately without touching the network when explicitly requested.
	if isStubMode() {
		logger.Info("memory.import.stub", map[string]any{
			"reason":   "BIBLE_CLI_STUB_MODE=1",
			"kb_index": kbIndex,
		})
		return stubMemoryImport(kbIndex, "stub_mode"), nil
	}

	// --- Real server call ---------------------------------------------------

	vectorModel := resolveVectorModel(opts.VectorModel, cfg)

	// Assemble the multipart payload: meta.json is mandatory, source (message)
	// is sent as message.json so the server-side parser recognises it.
	files := []clienthttp.MemoryFile{
		{Filename: "meta.json", Path: metaFile, ContentType: "application/json"},
		{Filename: "message.json", Path: sourceFile, ContentType: "application/json"},
	}

	importReq := clienthttp.MemoryImportRequest{
		Files:       files,
		KbIndex:     kbIndex,
		Tag:         tag,
		VectorModel: vectorModel,
	}

	logger.Debug("memory.import.http", map[string]any{
		"kb_index":     kbIndex,
		"tag":          tag,
		"vector_model": vectorModel,
	})

	payload, err := client.ImportMemory(importReq)
	if err != nil {
		logger.Error("memory.import.error", map[string]any{"error": err.Error()})
		return nil, err
	}

	logger.Info("memory.import.ok", map[string]any{
		"task_id":  payload["task_id"],
		"status":   payload["status"],
		"kb_index": kbIndex,
	})
	return decorateServerResponse(payload), nil
}

func memoryUploadAll(client *clienthttp.Client, opts MemoryCommandOptions, cfg config.ClientConfig) (map[string]any, error) {
	baseDir := opts.BaseDir
	if strings.TrimSpace(baseDir) == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "base_dir is required.", ExitCode: 1}
	}
	if _, err := os.Stat(baseDir); os.IsNotExist(err) {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  fmt.Sprintf("Base directory does not exist: %s", baseDir),
			ExitCode: 1,
		}
	}

	// Find subdirectories containing message.json.
	var sessionDirs []string
	entries, err := os.ReadDir(baseDir)
	if err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Cannot read base directory: " + err.Error(), ExitCode: 1}
	}
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		msgPath := filepath.Join(baseDir, e.Name(), "message.json")
		if _, err := os.Stat(msgPath); err == nil {
			sessionDirs = append(sessionDirs, filepath.Join(baseDir, e.Name()))
		}
	}

	if len(sessionDirs) == 0 {
		return map[string]any{"uploaded": 0, "skipped": 0, "failed": 0, "sessions": []any{}}, nil
	}

	workers := opts.Workers
	if workers <= 0 {
		workers = 3
	}

	type result struct {
		dir  string
		data map[string]any
		err  error
	}

	jobs := make(chan string, len(sessionDirs))
	results := make(chan result, len(sessionDirs))

	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for dir := range jobs {
				singleOpts := opts
				singleOpts.SessionDir = dir
				data, err := memoryUpload(client, singleOpts, cfg)
				results <- result{dir: dir, data: data, err: err}
			}
		}()
	}

	for _, dir := range sessionDirs {
		jobs <- dir
	}
	close(jobs)

	wg.Wait()
	close(results)

	uploaded, skipped, failed := 0, 0, 0
	var sessions []map[string]any
	for r := range results {
		entry := map[string]any{"session_dir": r.dir}
		if r.err != nil {
			failed++
			entry["status"] = "failed"
			entry["error"] = r.err.Error()
		} else {
			status, _ := r.data["status"].(string)
			if status == "skipped" {
				skipped++
			} else {
				uploaded++
			}
			entry["status"] = status
			if taskID, ok := r.data["task_id"].(string); ok {
				entry["task_id"] = taskID
			}
		}
		sessions = append(sessions, entry)
	}

	return map[string]any{
		"uploaded": uploaded,
		"skipped":  skipped,
		"failed":   failed,
		"sessions": sessions,
	}, nil
}

// memoryBuildMeta constructs meta.json from message.json without uploading.
func memoryBuildMeta(opts MemoryCommandOptions) (map[string]any, error) {
	sessionDir := opts.SessionDir
	if strings.TrimSpace(sessionDir) == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "session_dir is required.", ExitCode: 1}
	}
	if _, err := os.Stat(sessionDir); os.IsNotExist(err) {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  fmt.Sprintf("Session directory does not exist: %s", sessionDir),
			ExitCode: 1,
		}
	}

	msgPath := filepath.Join(sessionDir, "message.json")
	if _, err := os.Stat(msgPath); os.IsNotExist(err) {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  fmt.Sprintf("message.json not found in %s", sessionDir),
			ExitCode: 1,
		}
	}

	buildOpts := meta.BuildOptions{
		TitleOverride:    opts.Query, // reuse Query field for --title override
		TaskIDs:          opts.TaskIDs,
		FeatureTags:      opts.FeatureTags,
		DomainTags:       opts.DomainTags,
		AbstractTruncate: true,
	}
	m, err := meta.BuildMetaFromMessageJSON(msgPath, sessionDir, buildOpts)
	if err != nil {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}

	if err := meta.WriteMetaJSON(sessionDir, m); err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to write meta.json: " + err.Error(), ExitCode: 1}
	}

	return map[string]any{
		"memory_id": m.MemoryID,
		"title":     m.Title,
		"abstract":  m.Abstract,
		"meta_path": filepath.Join(sessionDir, "meta.json"),
	}, nil
}

func memoryStatus(client *clienthttp.Client, opts MemoryCommandOptions) (map[string]any, error) {
	taskID := opts.TaskID
	if taskID == "" && opts.MemoryID == "" && opts.CacheDir == "" && opts.SessionID == "" {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  "Provide a task_id, --memory-id, or --cache-dir to look up task status.",
			ExitCode: 1,
		}
	}

	// Resolve task_id from local cache if needed.
	if taskID == "" {
		lookupDir := opts.CacheDir
		if lookupDir == "" {
			lookupDir = "."
		}
		cached, err := cache.LoadCache(lookupDir)
		if err != nil {
			return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "Cannot read cache: " + err.Error(), ExitCode: 1}
		}
		if cached == nil {
			return nil, protocol.CLIError{Code: "NOT_FOUND", Message: "No cache entry found in " + lookupDir, ExitCode: 1}
		}
		if opts.MemoryID != "" && cached.MemoryID != opts.MemoryID {
			return nil, protocol.CLIError{
				Code:     "NOT_FOUND",
				Message:  fmt.Sprintf("Cache entry memory_id=%s does not match requested %s", cached.MemoryID, opts.MemoryID),
				ExitCode: 1,
			}
		}
		taskID = cached.TaskID
		if taskID == "" {
			return map[string]any{
				"memory_id":     cached.MemoryID,
				"upload_status": cached.UploadStatus,
				"uploaded_at":   cached.UploadedAt,
				"note":          "no task_id in cache; upload may not have reached server",
			}, nil
		}
	}

	if opts.TestMode && strings.TrimSpace(taskID) != "" {
		logger.Info("memory.status.test", map[string]any{"task_id": taskID})
		return map[string]any{
			"task_id":  taskID,
			"status":   "completed",
			"progress": 100,
		}, nil
	}

	return client.GetTask(taskID)
}

func memoryList(client *clienthttp.Client, opts MemoryCommandOptions) (map[string]any, error) {
	limit := opts.Limit
	if limit <= 0 {
		limit = 20
	}
	if opts.TestMode {
		listTag := strings.TrimSpace(opts.Tag)
		if listTag == "" {
			listTag = "memory"
		}
		logger.Info("memory.list.test", map[string]any{"tag": listTag})
		return map[string]any{
			"results":  []any{},
			"total":    0,
			"kb_index": "memory_main",
			"tag":      listTag,
		}, nil
	}
	req := clienthttp.MemorySearchRequest{
		Query:      "*",
		TopK:       limit,
		SearchType: "title",
		Page:       opts.Page,
		FilterTag:  opts.Tag,
		Since:      opts.Since,
	}
	if isStubMode() {
		logger.Info("memory.list.stub", map[string]any{"reason": "BIBLE_CLI_STUB_MODE=1"})
		return stubMemoryList("stub_mode"), nil
	}
	payload, err := client.MemorySearch(req)
	if err != nil {
		return payload, err
	}
	return decorateServerResponse(payload), nil
}

func memoryDownload(client *clienthttp.Client, opts MemoryCommandOptions) (map[string]any, error) {
	storagePath := strings.TrimSpace(opts.StoragePath)
	if storagePath == "" && strings.TrimSpace(opts.MemoryID) != "" {
		storagePath = opts.MemoryID
	}

	storagePaths := normalizedStoragePaths(opts.StoragePaths)
	if storagePath != "" {
		storagePaths = append([]string{storagePath}, storagePaths...)
	}
	if len(storagePaths) == 0 {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "Provide a memory id or --storage-path for download.", ExitCode: 1}
	}

	if opts.TestMode {
		return memoryDownloadTestMode(opts, storagePaths)
	}

	var (
		payload map[string]any
		err     error
	)
	if len(storagePaths) == 1 {
		downloadReq := clienthttp.DownloadFileRequest{
			Tag:          "memory",
			StoragePath:  storagePaths[0],
			DownloadName: opts.DownloadName,
		}
		payload, err = client.DownloadFile("memory", downloadReq)
	} else {
		downloadReq := clienthttp.DownloadBatchRequest{
			Tag:             "memory",
			StoragePaths:    storagePaths,
			PackageName:     opts.PackageName,
			IncludeMetadata: opts.IncludeMetadata,
		}
		payload, err = client.DownloadBatch("memory", downloadReq)
	}
	if err != nil {
		return nil, err
	}

	taskID, _ := payload["task_id"].(string)
	if taskID == "" {
		return payload, nil
	}

	finalPayload, err := client.PollTask(taskID, 3*time.Second, 5*time.Minute)
	if err != nil {
		return nil, err
	}

	result, _ := finalPayload["result"].(map[string]any)
	artifactID, _ := result["artifact_id"].(string)
	if artifactID == "" {
		return finalPayload, nil
	}

	data, err := client.GetArtifact("memory", artifactID)
	if err != nil {
		return nil, err
	}

	outputDir := strings.TrimSpace(opts.OutputDir)
	if outputDir == "" {
		home, _ := os.UserHomeDir()
		outputDir = filepath.Join(home, ".bible", "memory")
	}
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Cannot create output directory: " + err.Error(), ExitCode: 1}
	}

	filename := artifactName(finalPayload)
	if filename == "" {
		filename = strings.TrimSpace(opts.DownloadName)
	}
	if filename == "" {
		filename = strings.TrimSpace(opts.PackageName)
	}
	if filename == "" {
		filename = filepath.Base(storagePaths[0])
	}
	if filename == "." || filename == string(filepath.Separator) || filename == "" {
		filename = artifactID
	}
	if filepath.Ext(filename) == "" {
		filename += ".zip"
	}
	destPath := filepath.Join(outputDir, filename)
	if err := os.WriteFile(destPath, data, 0o644); err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to write memory file: " + err.Error(), ExitCode: 1}
	}

	return map[string]any{
		"status":      "downloaded",
		"output_path": destPath,
	}, nil
}

// memoryDownloadTestMode writes a minimal bible-chat-v1 JSON without contacting
// the server. Return shape matches a successful integrated download.
func memoryDownloadTestMode(opts MemoryCommandOptions, storagePaths []string) (map[string]any, error) {
	outputDir := strings.TrimSpace(opts.OutputDir)
	if outputDir == "" {
		home, _ := os.UserHomeDir()
		outputDir = filepath.Join(home, ".bible", "memory")
	}
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Cannot create output directory: " + err.Error(), ExitCode: 1}
	}

	filename := strings.TrimSpace(opts.DownloadName)
	if filename == "" {
		filename = strings.TrimSpace(opts.PackageName)
	}
	if filename == "" {
		filename = filepath.Base(storagePaths[0])
	}
	if filename == "." || filename == string(filepath.Separator) || filename == "" {
		filename = "test-download"
	}
	if filepath.Ext(filename) == "" {
		if len(storagePaths) > 1 {
			filename += ".zip"
		} else {
			filename += ".json"
		}
	}
	destPath := filepath.Join(outputDir, filename)

	body := []byte(`{"source_format":"bible-chat-v1","session_id":"test-download","exported_at":"1970-01-01T00:00:00Z","turns":[]}`)
	if err := os.WriteFile(destPath, body, 0o644); err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to write memory file: " + err.Error(), ExitCode: 1}
	}
	logger.Info("memory.download.test", map[string]any{"output_path": destPath})
	return map[string]any{
		"status":      "downloaded",
		"output_path": destPath,
	}, nil
}

func memoryCacheStatus(opts MemoryCommandOptions) (map[string]any, error) {
	baseDir := opts.BaseDir
	if strings.TrimSpace(baseDir) == "" {
		baseDir = "."
	}
	if _, err := os.Stat(baseDir); os.IsNotExist(err) {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  fmt.Sprintf("Directory does not exist: %s", baseDir),
			ExitCode: 1,
		}
	}

	entries, err := os.ReadDir(baseDir)
	if err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Cannot read directory: " + err.Error(), ExitCode: 1}
	}

	var sessions []map[string]any
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		dir := filepath.Join(baseDir, e.Name())
		msgPath := filepath.Join(dir, "message.json")
		metaPath := filepath.Join(dir, "meta.json")
		if _, err := os.Stat(msgPath); os.IsNotExist(err) {
			continue
		}

		entry := map[string]any{
			"session_dir": dir,
		}

		cached, err := cache.LoadCache(dir)
		if err != nil || cached == nil {
			entry["cache_status"] = "no_cache"
			sessions = append(sessions, entry)
			continue
		}

		entry["memory_id"] = cached.MemoryID
		entry["task_id"] = cached.TaskID
		entry["upload_status"] = cached.UploadStatus
		entry["uploaded_at"] = cached.UploadedAt

		// Check for content drift.
		if _, statErr := os.Stat(metaPath); statErr == nil {
			currentHash, hashErr := cache.SHA256File(metaPath)
			if hashErr == nil && cached.MetaHash != "" && currentHash != cached.MetaHash {
				entry["cache_status"] = "stale"
			} else {
				entry["cache_status"] = cached.UploadStatus
			}
		} else {
			entry["cache_status"] = cached.UploadStatus
		}

		sessions = append(sessions, entry)
	}

	if sessions == nil {
		sessions = []map[string]any{}
	}
	return map[string]any{"sessions": sessions}, nil
}

// sessionIDFromMessageJSON returns session_id from bible-chat-v1 message.json when present.
func sessionIDFromMessageJSON(raw []byte) (string, bool) {
	var mj map[string]any
	if err := json.Unmarshal(raw, &mj); err != nil {
		return "", false
	}
	s, ok := mj["session_id"].(string)
	if !ok {
		return "", false
	}
	s = strings.TrimSpace(s)
	if s == "" {
		return "", false
	}
	return s, true
}

// unmarshalJSON validates that data is valid JSON by attempting to decode into v.
func unmarshalJSON(data []byte, v any) error {
	return json.Unmarshal(data, v)
}
