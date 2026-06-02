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
		return memorySearch(d.client, opts)
	case "cache-status":
		return memoryCacheStatus(opts)
	case "download":
		return memoryDownload(d.client, opts)
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

	return client.GetTask(taskID)
}

func memoryList(client *clienthttp.Client, opts MemoryCommandOptions) (map[string]any, error) {
	limit := opts.Limit
	if limit <= 0 {
		limit = 20
	}
	req := clienthttp.MemorySearchRequest{
		Query:      "*",
		TopK:       limit,
		SearchType: "title",
		Page:       opts.Page,
		FilterTag:  opts.Tag,
		Since:      opts.Since,
	}
	return client.MemorySearch(req)
}

func memorySearch(client *clienthttp.Client, opts MemoryCommandOptions) (map[string]any, error) {
	if strings.TrimSpace(opts.Query) == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "query is required for memory search.", ExitCode: 1}
	}
	topK := opts.TopK
	if topK <= 0 {
		topK = 5
	}
	req := clienthttp.MemorySearchRequest{
		Query:      opts.Query,
		TopK:       topK,
		Threshold:  opts.Threshold,
		SearchType: opts.SearchType,
	}
	return client.MemorySearch(req)
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

// unmarshalJSON validates that data is valid JSON by attempting to decode into v.
func unmarshalJSON(data []byte, v any) error {
	return json.Unmarshal(data, v)
}
