package cli

import (
	"flag"
	"io"

	"bible-cli-go/internal/commands"
	"bible-cli-go/internal/protocol"
)

// parseSkillsFlags parses action-specific flags for skills subcommands.
func parseSkillsFlags(action string, args []string, opts *commands.SkillsCommandOptions) error {
	switch action {
	case "list":
		return parseSkillsListFlags(args, opts)
	case "search":
		return parseSkillsSearchFlags(args, opts)
	case "get":
		return parseSkillsGetFlags(args, opts)
	case "upload":
		return parseSkillsUploadFlags(args, opts)
	case "download":
		return parseSkillsDownloadFlags(args, opts)
	default:
		return nil
	}
}

func parseSkillsListFlags(args []string, opts *commands.SkillsCommandOptions) error {
	fs := flag.NewFlagSet("skills list", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	pagePtr := fs.Int("page", 1, "Page number")
	limitPtr := fs.Int("limit", 20, "Number of results (maps to top_k)")
	tagPtr := fs.String("tag", "", "Filter by tag")

	if err := fs.Parse(args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() > 0 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "skills list does not accept positional arguments.", ExitCode: 1}
	}
	opts.Page = *pagePtr
	opts.Limit = *limitPtr
	opts.Tag = *tagPtr
	return nil
}

func parseSkillsSearchFlags(args []string, opts *commands.SkillsCommandOptions) error {
	fs := flag.NewFlagSet("skills search", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	topKPtr := fs.Int("top-k", 10, "Number of results")
	thresholdPtr := fs.Float64("threshold", 0.0, "Minimum score threshold (client-side filter)")
	tagPtr := fs.String("tag", "", "Filter by tag")

	if err := fs.Parse(args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() < 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "skills search requires a query argument.", ExitCode: 1}
	}
	if fs.NArg() > 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "skills search accepts exactly one positional query argument.", ExitCode: 1}
	}
	opts.Query = fs.Arg(0)
	opts.TopK = *topKPtr
	opts.Threshold = *thresholdPtr
	opts.Tag = *tagPtr
	return nil
}

func parseSkillsGetFlags(args []string, opts *commands.SkillsCommandOptions) error {
	fs := flag.NewFlagSet("skills get", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	contentPtr := fs.Bool("content", false, "Include skill body/content in response")

	if err := fs.Parse(args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() < 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "skills get requires a skill name or id argument.", ExitCode: 1}
	}
	if fs.NArg() > 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "skills get accepts exactly one positional argument.", ExitCode: 1}
	}
	opts.Name = fs.Arg(0)
	opts.Content = *contentPtr
	return nil
}

func parseSkillsUploadFlags(args []string, opts *commands.SkillsCommandOptions) error {
	fs := flag.NewFlagSet("skills upload", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	filePtr := fs.String("file", "", "Absolute path to .skill package file")
	kbIndexPtr := fs.String("kb-index", "", "Knowledge base index")
	vectorModelPtr := fs.String("vector-model", "", "Vector model override")
	waitPtr := fs.Bool("wait", false, "Wait for async task to complete")

	if err := fs.Parse(args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() > 0 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "skills upload does not accept positional arguments (use --file).", ExitCode: 1}
	}
	opts.FilePath = *filePtr
	opts.KbIndex = *kbIndexPtr
	opts.VectorModel = *vectorModelPtr
	opts.Wait = *waitPtr
	return nil
}

func parseSkillsDownloadFlags(args []string, opts *commands.SkillsCommandOptions) error {
	fs := flag.NewFlagSet("skills download", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	storagePathPtr := fs.String("storage-path", "", "Server-side storage path of the skill")
	outputDirPtr := fs.String("output", "", "Local directory to save the downloaded skill (default: ~/.claude/skills/)")
	waitPtr := fs.Bool("wait", false, "Wait for download to complete")

	if err := fs.Parse(args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() > 1 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "skills download accepts at most one positional argument (name_or_id).", ExitCode: 1}
	}
	if fs.NArg() == 1 {
		opts.Name = fs.Arg(0)
	}
	opts.StoragePath = *storagePathPtr
	opts.OutputDir = *outputDirPtr
	opts.Wait = *waitPtr
	return nil
}
