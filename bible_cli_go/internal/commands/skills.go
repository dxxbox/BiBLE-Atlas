package commands

import (
	"archive/zip"
	"bytes"
	"fmt"
	"io"
	"io/fs"
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
	StoragePath     string
	StoragePaths    []string
	OutputDir       string
	PackageName     string
	IncludeMetadata bool
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
		Query:      "*",
		TopK:       limit,
		SearchType: "title",
		Tag:        opts.Tag,
		Page:       opts.Page,
		FilterTag:  opts.Tag,
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

	uploadFile, cleanup, err := prepareSkillUploadFile(fp)
	if err != nil {
		return nil, err
	}
	defer cleanup()

	kbIndex := resolveKbIndex(opts.KbIndex, cfg)
	if kbIndex == "" {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  "kb_index is required. Provide --kb-index flag or set BIBLE_MEMORY_KB_INDEX environment variable.",
			ExitCode: 1,
		}
	}
	vectorModel := resolveVectorModel(opts.VectorModel, cfg)

	req := clienthttp.SkillImportRequest{
		File:        uploadFile,
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

func prepareSkillUploadFile(path string) (clienthttp.MemoryFile, func(), error) {
	info, err := os.Stat(path)
	if os.IsNotExist(err) {
		return clienthttp.MemoryFile{}, func() {}, protocol.CLIError{Code: "INVALID_ARGS", Message: fmt.Sprintf("File not found: %s", path), ExitCode: 1}
	}
	if err != nil {
		return clienthttp.MemoryFile{}, func() {}, protocol.CLIError{Code: "INVALID_ARGS", Message: fmt.Sprintf("Cannot access skill package: %v", err), ExitCode: 1}
	}

	if info.IsDir() {
		return packageSkillDirectory(path)
	}
	if !strings.HasSuffix(strings.ToLower(path), ".skill") {
		return clienthttp.MemoryFile{}, func() {}, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  "Invalid skill package: provide a .skill file or a directory containing SKILLS.md.",
			ExitCode: 1,
		}
	}
	if _, err := validateSkillPackageFile(path); err != nil {
		return clienthttp.MemoryFile{}, func() {}, err
	}

	return clienthttp.MemoryFile{
		Filename:    filepath.Base(path),
		Path:        path,
		ContentType: "application/octet-stream",
	}, func() {}, nil
}

func packageSkillDirectory(dir string) (clienthttp.MemoryFile, func(), error) {
	manifestPath := filepath.Join(dir, "SKILLS.md")
	if info, err := os.Stat(manifestPath); os.IsNotExist(err) {
		return clienthttp.MemoryFile{}, func() {}, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  "Invalid skill directory: SKILLS.md is required at the directory root.",
			ExitCode: 1,
		}
	} else if err != nil {
		return clienthttp.MemoryFile{}, func() {}, protocol.CLIError{Code: "INVALID_ARGS", Message: fmt.Sprintf("Cannot access SKILLS.md: %v", err), ExitCode: 1}
	} else if info.IsDir() {
		return clienthttp.MemoryFile{}, func() {}, protocol.CLIError{Code: "INVALID_ARGS", Message: "Invalid skill directory: SKILLS.md must be a file.", ExitCode: 1}
	}

	baseName := filepath.Base(filepath.Clean(dir))
	tmp, err := os.CreateTemp("", baseName+"-*.skill")
	if err != nil {
		return clienthttp.MemoryFile{}, func() {}, protocol.CLIError{Code: "INTERNAL", Message: "Failed to create temporary skill package: " + err.Error(), ExitCode: 1}
	}
	tmpPath := tmp.Name()
	cleanup := func() { _ = os.Remove(tmpPath) }

	if err := writeSkillZip(tmp, dir, baseName); err != nil {
		_ = tmp.Close()
		cleanup()
		return clienthttp.MemoryFile{}, func() {}, err
	}
	if err := tmp.Close(); err != nil {
		cleanup()
		return clienthttp.MemoryFile{}, func() {}, protocol.CLIError{Code: "INTERNAL", Message: "Failed to finalize temporary skill package: " + err.Error(), ExitCode: 1}
	}

	return clienthttp.MemoryFile{
		Filename:    baseName + ".skill",
		Path:        tmpPath,
		ContentType: "application/zip",
	}, cleanup, nil
}

func writeSkillZip(dest *os.File, dir, topDir string) error {
	zw := zip.NewWriter(dest)
	if err := filepath.WalkDir(dir, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if d.IsDir() {
			return nil
		}
		if d.Type()&os.ModeSymlink != 0 {
			return protocol.CLIError{Code: "INVALID_ARGS", Message: "Invalid skill directory: symlinks are not supported in skill packages.", ExitCode: 1}
		}

		rel, err := filepath.Rel(dir, path)
		if err != nil {
			return err
		}
		if rel == "." {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		header, err := zip.FileInfoHeader(info)
		if err != nil {
			return err
		}
		header.Name = filepath.ToSlash(filepath.Join(topDir, rel))
		header.Method = zip.Deflate

		part, err := zw.CreateHeader(header)
		if err != nil {
			return err
		}
		src, err := os.Open(path)
		if err != nil {
			return err
		}
		defer src.Close()
		_, err = io.Copy(part, src)
		return err
	}); err != nil {
		_ = zw.Close()
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "Failed to package skill directory: " + err.Error(), ExitCode: 1}
	}
	if err := zw.Close(); err != nil {
		return protocol.CLIError{Code: "INTERNAL", Message: "Failed to write temporary skill package: " + err.Error(), ExitCode: 1}
	}
	return nil
}

func validateSkillPackageFile(path string) (string, error) {
	zr, err := zip.OpenReader(path)
	if err != nil {
		return "", protocol.CLIError{Code: "INVALID_ARGS", Message: ".skill file must be a valid zip package", ExitCode: 1}
	}
	defer zr.Close()

	files := make([]*zip.File, 0, len(zr.File))
	files = append(files, zr.File...)
	return validateSkillPackageEntries(files)
}

func validateSkillPackageData(data []byte) (string, []*zip.File, error) {
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return "", nil, protocol.CLIError{Code: "INVALID_ARGS", Message: ".skill file must be a valid zip package", ExitCode: 1}
	}
	files := make([]*zip.File, 0, len(zr.File))
	files = append(files, zr.File...)
	topDir, err := validateSkillPackageEntries(files)
	if err != nil {
		return "", nil, err
	}
	return topDir, files, nil
}

func validateSkillPackageEntries(files []*zip.File) (string, error) {
	topDirs := map[string]struct{}{}
	hasManifest := false

	for _, file := range files {
		rawName := filepath.ToSlash(file.Name)
		if strings.HasPrefix(rawName, "/") || filepath.IsAbs(rawName) {
			return "", protocol.CLIError{Code: "INVALID_ARGS", Message: "Invalid skill package: unsafe zip path.", ExitCode: 1}
		}
		name := strings.TrimSuffix(rawName, "/")
		if name == "" {
			continue
		}
		clean := filepath.ToSlash(filepath.Clean(name))
		if strings.HasPrefix(clean, "../") || clean == ".." || filepath.IsAbs(clean) {
			return "", protocol.CLIError{Code: "INVALID_ARGS", Message: "Invalid skill package: unsafe zip path.", ExitCode: 1}
		}
		parts := strings.Split(clean, "/")
		if len(parts) < 2 {
			if file.FileInfo().IsDir() {
				topDirs[parts[0]] = struct{}{}
				continue
			}
			return "", protocol.CLIError{Code: "INVALID_ARGS", Message: "Invalid skill package: files must live under a single top-level directory.", ExitCode: 1}
		}
		topDirs[parts[0]] = struct{}{}
		if len(parts) == 2 && parts[1] == "SKILLS.md" && !file.FileInfo().IsDir() {
			hasManifest = true
		}
		if file.FileInfo().Mode()&os.ModeSymlink != 0 {
			return "", protocol.CLIError{Code: "INVALID_ARGS", Message: "Invalid skill package: symlinks are not supported.", ExitCode: 1}
		}
	}

	if len(topDirs) != 1 {
		return "", protocol.CLIError{Code: "INVALID_ARGS", Message: "Invalid skill package: package must contain exactly one top-level directory.", ExitCode: 1}
	}
	var topDir string
	for dir := range topDirs {
		topDir = dir
	}
	if !hasManifest {
		return "", protocol.CLIError{Code: "INVALID_ARGS", Message: "Invalid skill package: package must contain <skill-name>/SKILLS.md.", ExitCode: 1}
	}
	return topDir, nil
}

func skillsDownload(client *clienthttp.Client, opts SkillsCommandOptions) (map[string]any, error) {
	storagePath := strings.TrimSpace(opts.StoragePath)
	if storagePath == "" && strings.TrimSpace(opts.Name) != "" {
		storagePath = opts.Name
	}

	storagePaths := normalizedStoragePaths(opts.StoragePaths)
	if storagePath != "" {
		storagePaths = append([]string{storagePath}, storagePaths...)
	}
	if len(storagePaths) == 0 {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "Provide a skill name/id or --storage-path for download.", ExitCode: 1}
	}

	var (
		payload map[string]any
		err     error
	)
	if len(storagePaths) == 1 {
		downloadReq := clienthttp.DownloadFileRequest{
			Tag:         "skill",
			StoragePath: storagePaths[0],
		}
		payload, err = client.DownloadFile("skill", downloadReq)
	} else {
		downloadReq := clienthttp.DownloadBatchRequest{
			Tag:             "skill",
			StoragePaths:    storagePaths,
			PackageName:     opts.PackageName,
			IncludeMetadata: opts.IncludeMetadata,
		}
		payload, err = client.DownloadBatch("skill", downloadReq)
	}
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

	if len(storagePaths) == 1 {
		installDir, err := installSkillPackage(data, outputDir)
		if err != nil {
			return nil, err
		}
		return map[string]any{
			"status":      "downloaded",
			"output_path": installDir,
		}, nil
	}

	filename := artifactName(finalPayload)
	if filename == "" {
		filename = strings.TrimSpace(opts.PackageName)
	}
	if filename == "" {
		filename = filepath.Base(storagePaths[0])
	}
	if len(storagePaths) == 1 && !strings.HasSuffix(filename, ".skill") {
		filename += ".skill"
	} else if len(storagePaths) > 1 && filepath.Ext(filename) == "" {
		filename += ".zip"
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

func installSkillPackage(data []byte, outputDir string) (string, error) {
	topDir, files, err := validateSkillPackageData(data)
	if err != nil {
		return "", err
	}
	destRoot := filepath.Clean(outputDir)
	installDir := filepath.Join(destRoot, topDir)
	for _, file := range files {
		name := strings.TrimSuffix(filepath.ToSlash(file.Name), "/")
		if name == "" {
			continue
		}
		clean := filepath.ToSlash(filepath.Clean(name))
		targetPath := filepath.Join(destRoot, filepath.FromSlash(clean))
		if !isWithinDirectory(destRoot, targetPath) {
			return "", protocol.CLIError{Code: "INVALID_ARGS", Message: "Invalid skill package: unsafe zip path.", ExitCode: 1}
		}
		if file.FileInfo().IsDir() {
			if err := os.MkdirAll(targetPath, 0o755); err != nil {
				return "", protocol.CLIError{Code: "INTERNAL", Message: "Failed to create skill directory: " + err.Error(), ExitCode: 1}
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(targetPath), 0o755); err != nil {
			return "", protocol.CLIError{Code: "INTERNAL", Message: "Failed to create skill directory: " + err.Error(), ExitCode: 1}
		}
		src, err := file.Open()
		if err != nil {
			return "", protocol.CLIError{Code: "INTERNAL", Message: "Failed to read skill package: " + err.Error(), ExitCode: 1}
		}
		content, err := io.ReadAll(src)
		_ = src.Close()
		if err != nil {
			return "", protocol.CLIError{Code: "INTERNAL", Message: "Failed to read skill package: " + err.Error(), ExitCode: 1}
		}
		if err := os.WriteFile(targetPath, content, file.FileInfo().Mode().Perm()); err != nil {
			return "", protocol.CLIError{Code: "INTERNAL", Message: "Failed to write skill file: " + err.Error(), ExitCode: 1}
		}
	}
	return installDir, nil
}

func isWithinDirectory(root, path string) bool {
	rel, err := filepath.Rel(root, path)
	if err != nil {
		return false
	}
	return rel == "." || (!strings.HasPrefix(rel, ".."+string(filepath.Separator)) && rel != "..")
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
