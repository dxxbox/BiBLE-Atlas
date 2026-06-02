package cli

import (
	"flag"
	"io"
	"strings"

	"bible-cli-go/internal/commands"
	"bible-cli-go/internal/protocol"
)

// parseMemoryFlags parses action-specific flags from args and populates opts.
func parseMemoryFlags(action string, args []string, opts *commands.MemoryCommandOptions) error {
	switch action {
	case "upload":
		return parseMemoryUploadFlags(args, opts)
	case "upload-all":
		return parseMemoryUploadAllFlags(args, opts)
	case "build-meta":
		return parseMemoryBuildMetaFlags(args, opts)
	case "status":
		return parseMemoryStatusFlags(args, opts)
	case "list":
		return parseMemoryListFlags(args, opts)
	case "search":
		return parseMemorySearchFlags(args, opts)
	case "cache-status":
		return parseMemoryCacheStatusFlags(args, opts)
	case "download":
		return parseMemoryDownloadFlags(args, opts)
	default:
		// Unknown actions pass through; MemoryExecute will return NotImplemented.
		return nil
	}
}

func parseMemoryUploadFlags(args []string, opts *commands.MemoryCommandOptions) error {
	fs := flag.NewFlagSet("memory upload", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	kbIndexPtr := fs.String("kb-index", "", "Knowledge base index (overrides BIBLE_MEMORY_KB_INDEX env and config)")
	vectorModelPtr := fs.String("vector-model", "", "Vector model override")
	taskIDsPtr := fs.String("task-ids", "", "Comma-separated task IDs to embed in meta.json")
	featureTagsPtr := fs.String("feature-tags", "", "Comma-separated feature tags")
	domainTagsPtr := fs.String("domain-tags", "", "Comma-separated domain tags")
	skipPtr := fs.Bool("skip-if-exists", true, "Skip if session already uploaded with same meta content")
	waitPtr := fs.Bool("wait", false, "Wait for async task to complete before exiting")
	outputPtr := fs.String("output", "json", "Output format: json|table")

	if err := parseFlagSet(fs, args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() < 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "memory upload requires a session directory argument.", ExitCode: 1}
	}
	if fs.NArg() > 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "memory upload accepts exactly one positional argument (session_dir).", ExitCode: 1}
	}
	opts.SessionDir = fs.Arg(0)
	opts.KbIndex = *kbIndexPtr
	opts.VectorModel = *vectorModelPtr
	opts.TaskIDs = splitCSV(*taskIDsPtr)
	opts.FeatureTags = splitCSV(*featureTagsPtr)
	opts.DomainTags = splitCSV(*domainTagsPtr)
	opts.SkipIfExists = *skipPtr
	opts.Wait = *waitPtr
	opts.Output = *outputPtr
	return nil
}

func parseMemoryUploadAllFlags(args []string, opts *commands.MemoryCommandOptions) error {
	fs := flag.NewFlagSet("memory upload-all", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	kbIndexPtr := fs.String("kb-index", "", "Knowledge base index")
	vectorModelPtr := fs.String("vector-model", "", "Vector model override")
	skipPtr := fs.Bool("skip-if-exists", true, "Skip sessions already uploaded with same meta content")
	waitPtr := fs.Bool("wait", false, "Wait for each task to complete before proceeding")
	workersPtr := fs.Int("workers", 3, "Number of concurrent upload workers")

	if err := parseFlagSet(fs, args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() < 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "memory upload-all requires a base directory argument.", ExitCode: 1}
	}
	if fs.NArg() > 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "memory upload-all accepts exactly one positional argument (base_dir).", ExitCode: 1}
	}
	opts.BaseDir = fs.Arg(0)
	opts.KbIndex = *kbIndexPtr
	opts.VectorModel = *vectorModelPtr
	opts.SkipIfExists = *skipPtr
	opts.Wait = *waitPtr
	opts.Workers = *workersPtr
	return nil
}

func parseMemoryBuildMetaFlags(args []string, opts *commands.MemoryCommandOptions) error {
	fs := flag.NewFlagSet("memory build-meta", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	taskIDsPtr := fs.String("task-ids", "", "Comma-separated task IDs to embed in meta.json")
	featureTagsPtr := fs.String("feature-tags", "", "Comma-separated feature tags")
	domainTagsPtr := fs.String("domain-tags", "", "Comma-separated domain tags")

	if err := parseFlagSet(fs, args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() < 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "memory build-meta requires a session directory argument.", ExitCode: 1}
	}
	if fs.NArg() > 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "memory build-meta accepts exactly one positional argument (session_dir).", ExitCode: 1}
	}
	opts.SessionDir = fs.Arg(0)
	opts.TaskIDs = splitCSV(*taskIDsPtr)
	opts.FeatureTags = splitCSV(*featureTagsPtr)
	opts.DomainTags = splitCSV(*domainTagsPtr)
	return nil
}

func parseMemoryStatusFlags(args []string, opts *commands.MemoryCommandOptions) error {
	fs := flag.NewFlagSet("memory status", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	memoryIDPtr := fs.String("memory-id", "", "Look up task_id from local cache by memory_id")
	cacheDirPtr := fs.String("cache-dir", "", "Session directory containing .bible-memory-cache.json")

	if err := parseFlagSet(fs, args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() > 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "memory status accepts at most one positional argument (task_id).", ExitCode: 1}
	}
	if fs.NArg() == 1 {
		opts.TaskID = fs.Arg(0)
	}
	opts.MemoryID = *memoryIDPtr
	opts.CacheDir = *cacheDirPtr
	return nil
}

func parseMemoryListFlags(args []string, opts *commands.MemoryCommandOptions) error {
	fs := flag.NewFlagSet("memory list", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	pagePtr := fs.Int("page", 1, "Page number")
	limitPtr := fs.Int("limit", 20, "Number of results per page")
	tagPtr := fs.String("tag", "", "Filter by tag")
	sincePtr := fs.String("since", "", "Filter by date (ISO 8601)")

	if err := parseFlagSet(fs, args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() > 0 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "memory list does not accept positional arguments.", ExitCode: 1}
	}
	opts.Page = *pagePtr
	opts.Limit = *limitPtr
	opts.Tag = *tagPtr
	opts.Since = *sincePtr
	return nil
}

func parseMemorySearchFlags(args []string, opts *commands.MemoryCommandOptions) error {
	fs := flag.NewFlagSet("memory search", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	topKPtr := fs.Int("top-k", 5, "Number of results to return")
	thresholdPtr := fs.Float64("threshold", 0.0, "Minimum similarity score threshold")
	searchTypePtr := fs.String("search-type", "", "Search type: keyword|title|text|vector|hybrid")

	if err := parseFlagSet(fs, args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() < 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "memory search requires a query argument.", ExitCode: 1}
	}
	if fs.NArg() > 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "memory search accepts exactly one positional query argument.", ExitCode: 1}
	}
	opts.Query = fs.Arg(0)
	opts.TopK = *topKPtr
	opts.Threshold = *thresholdPtr
	opts.SearchType = *searchTypePtr
	return nil
}

func parseMemoryCacheStatusFlags(args []string, opts *commands.MemoryCommandOptions) error {
	fs := flag.NewFlagSet("memory cache-status", flag.ContinueOnError)
	fs.SetOutput(io.Discard)

	if err := parseFlagSet(fs, args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() > 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "memory cache-status accepts at most one positional argument (base_dir).", ExitCode: 1}
	}
	if fs.NArg() == 1 {
		opts.BaseDir = fs.Arg(0)
	}
	return nil
}

func parseMemoryDownloadFlags(args []string, opts *commands.MemoryCommandOptions) error {
	fs := flag.NewFlagSet("memory download", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	var storagePaths multiStringFlag
	fs.Var(&storagePaths, "storage-path", "Server-side storage path of the memory artifact; repeat for batch download")
	outputDirPtr := fs.String("output", "", "Local directory to save the downloaded memory artifact (default: ~/.bible/memory/)")
	downloadNamePtr := fs.String("download-name", "", "Optional local download filename")
	packageNamePtr := fs.String("package-name", "", "ZIP package name for batch download")
	includeMetadataPtr := fs.Bool("include-metadata", false, "Include metadata manifest for batch download")
	waitPtr := fs.Bool("wait", false, "Wait for download to complete")

	if err := parseFlagSet(fs, args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() > 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "memory download accepts at most one positional argument (memory_id).", ExitCode: 1}
	}
	if fs.NArg() == 1 {
		opts.MemoryID = fs.Arg(0)
	}
	opts.StoragePaths = storagePaths
	opts.OutputDir = *outputDirPtr
	opts.DownloadName = *downloadNamePtr
	opts.PackageName = *packageNamePtr
	opts.IncludeMetadata = *includeMetadataPtr
	opts.Wait = *waitPtr
	return nil
}

// splitCSV splits a comma-separated string into a trimmed, non-empty slice.
func splitCSV(s string) []string {
	if strings.TrimSpace(s) == "" {
		return nil
	}
	var result []string
	for _, part := range strings.Split(s, ",") {
		if v := strings.TrimSpace(part); v != "" {
			result = append(result, v)
		}
	}
	return result
}
