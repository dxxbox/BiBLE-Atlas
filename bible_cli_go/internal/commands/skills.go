package commands

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	clienthttp "bible-cli-go/internal/client/http"
	"bible-cli-go/internal/config"
	"bible-cli-go/internal/protocol"
)

// SkillsCommandOptions aggregates all flags from skills subcommands.
type SkillsCommandOptions struct {
	// ls / list / search
	Page      int
	Limit     int
	Tag       string
	Query     string
	TopK      int
	Threshold float64

	// get
	Name    string
	Content bool

	// upload
	FilePath    string
	KbIndex     string
	VectorModel string
	Wait        bool

	// download
	StoragePath string
	OutputDir   string
}

// SkillsExecute dispatches a skills subcommand.
func (d *Dispatcher) SkillsExecute(action string, opts SkillsCommandOptions) (map[string]any, error) {
	switch action {
	case "list":
		return skillsList(d.client, opts)
	case "search":
		return skillsSearch(d.client, opts)
	case "get":
		return skillsGet(d.client, opts)
	case "upload":
		return skillsUpload(d.client, opts, d.cfg)
	case "download":
		return skillsDownload(d.client, opts)
	default:
		return nil, protocol.NotImplemented("skills " + action)
	}
}

func skillsList(client *clienthttp.Client, opts SkillsCommandOptions) (map[string]any, error) {
	limit := opts.Limit
	if limit <= 0 {
		limit = 20
	}
	req := clienthttp.SkillSearchRequest{
		Query:      "",
		TopK:       limit,
		SearchType: "title",
		Tag:        opts.Tag,
	}
	return client.SkillSearch(req)
}

func skillsSearch(client *clienthttp.Client, opts SkillsCommandOptions) (map[string]any, error) {
	if strings.TrimSpace(opts.Query) == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "query is required for skills search.", ExitCode: 1}
	}
	topK := opts.TopK
	if topK <= 0 {
		topK = 10
	}
	req := clienthttp.SkillSearchRequest{
		Query:      opts.Query,
		TopK:       topK,
		Threshold:  opts.Threshold,
		SearchType: "keyword",
		Tag:        opts.Tag,
	}
	return client.SkillSearch(req)
}

func skillsGet(client *clienthttp.Client, opts SkillsCommandOptions) (map[string]any, error) {
	name := strings.TrimSpace(opts.Name)
	if name == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "skill name or id is required.", ExitCode: 1}
	}
	req := clienthttp.SkillSearchRequest{
		Query:      name,
		TopK:       1,
		SearchType: "keyword",
	}
	result, err := client.SkillSearch(req)
	if err != nil {
		return nil, err
	}
	if !opts.Content {
		return result, nil
	}
	// With --content, return the body/content field of the first hit if available.
	if items, ok := extractListItems(result); ok && len(items) > 0 {
		first := items[0]
		if content, ok := first["body"].(string); ok && content != "" {
			first["content"] = content
		}
		return first, nil
	}
	return result, nil
}

func skillsUpload(client *clienthttp.Client, opts SkillsCommandOptions, cfg config.ClientConfig) (map[string]any, error) {
	fp := strings.TrimSpace(opts.FilePath)
	if fp == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "--file is required for skills upload.", ExitCode: 1}
	}
	if !strings.HasSuffix(strings.ToLower(fp), ".skill") {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "Invalid skill package: file must have .skill extension.", ExitCode: 1}
	}
	if _, err := os.Stat(fp); os.IsNotExist(err) {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: fmt.Sprintf("File not found: %s", fp), ExitCode: 1}
	}

	kbIndex := resolveKbIndex(opts.KbIndex, cfg)
	vectorModel := resolveVectorModel(opts.VectorModel, cfg)

	req := clienthttp.SkillImportRequest{
		File: clienthttp.MemoryFile{
			Filename:    filepath.Base(fp),
			Path:        fp,
			ContentType: "application/octet-stream",
		},
		KbIndex:     kbIndex,
		Tag:         "skill",
		VectorModel: vectorModel,
	}

	payload, err := client.ImportSkill(req)
	if err != nil {
		return nil, err
	}

	if opts.Wait {
		taskID, _ := payload["task_id"].(string)
		if taskID != "" {
			return client.PollTask(taskID, 3*time.Second, 5*time.Minute)
		}
	}

	return payload, nil
}

func skillsDownload(client *clienthttp.Client, opts SkillsCommandOptions) (map[string]any, error) {
	storagePath := strings.TrimSpace(opts.StoragePath)
	if storagePath == "" && strings.TrimSpace(opts.Name) != "" {
		storagePath = opts.Name
	}
	if storagePath == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "Provide a skill name/id or --storage-path for download.", ExitCode: 1}
	}

	downloadReq := clienthttp.DownloadFileRequest{
		Tag:         "skill",
		StoragePath: storagePath,
	}
	payload, err := client.DownloadFile("skill", downloadReq)
	if err != nil {
		return nil, err
	}

	taskID, _ := payload["task_id"].(string)
	if taskID == "" {
		return payload, nil
	}

	// Poll for completion.
	finalPayload, err := client.PollTask(taskID, 3*time.Second, 5*time.Minute)
	if err != nil {
		return nil, err
	}

	// If there's an artifact_id, download the binary.
	result, _ := finalPayload["result"].(map[string]any)
	artifactID, _ := result["artifact_id"].(string)
	if artifactID == "" {
		return finalPayload, nil
	}

	data, err := client.GetArtifact("skill", artifactID)
	if err != nil {
		return nil, err
	}

	outputDir := strings.TrimSpace(opts.OutputDir)
	if outputDir == "" {
		home, _ := os.UserHomeDir()
		outputDir = filepath.Join(home, ".claude", "skills")
	}
	if err := os.MkdirAll(outputDir, 0o755); err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Cannot create output directory: " + err.Error(), ExitCode: 1}
	}

	filename := filepath.Base(storagePath)
	if !strings.HasSuffix(filename, ".skill") {
		filename += ".skill"
	}
	destPath := filepath.Join(outputDir, filename)
	if err := os.WriteFile(destPath, data, 0o644); err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: "Failed to write skill file: " + err.Error(), ExitCode: 1}
	}

	return map[string]any{
		"status":      "downloaded",
		"output_path": destPath,
	}, nil
}

// extractListItems tries to get items from common server response shapes.
func extractListItems(payload map[string]any) ([]map[string]any, bool) {
	for _, key := range []string{"items", "results", "hits", "data"} {
		if raw, ok := payload[key]; ok {
			if list, ok := raw.([]any); ok {
				items := make([]map[string]any, 0, len(list))
				for _, item := range list {
					if m, ok := item.(map[string]any); ok {
						items = append(items, m)
					}
				}
				return items, true
			}
		}
	}
	return nil, false
}
