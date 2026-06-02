package cli

import (
	"flag"
	"io"

	"bible-cli-go/internal/commands"
	"bible-cli-go/internal/protocol"
)

// parseSessionFlags parses action-specific flags for session subcommands.
func parseSessionFlags(action string, args []string, opts *commands.SessionCommandOptions) error {
	switch action {
	case "list":
		return parseSessionListFlags(args, opts)
	case "get":
		return parseSessionGetFlags(args, opts)
	case "save":
		return parseSessionSaveFlags(args, opts)
	default:
		return nil
	}
}

func parseSessionListFlags(args []string, opts *commands.SessionCommandOptions) error {
	fs := flag.NewFlagSet("session list", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	limitPtr := fs.Int("limit", 10, "Number of sessions to return")
	uidPtr := fs.String("uid", "", "Filter by user ID (reserved)")

	if err := parseFlagSet(fs, args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() > 0 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "session list does not accept positional arguments.", ExitCode: 1}
	}
	opts.Limit = *limitPtr
	opts.UID = *uidPtr
	return nil
}

func parseSessionGetFlags(args []string, opts *commands.SessionCommandOptions) error {
	fs := flag.NewFlagSet("session get", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	idPtr := fs.String("id", "", "Session ID to retrieve")

	if err := parseFlagSet(fs, args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() > 0 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "session get does not accept positional arguments (use --id).", ExitCode: 1}
	}
	opts.ID = *idPtr
	return nil
}

func parseSessionSaveFlags(args []string, opts *commands.SessionCommandOptions) error {
	fs := flag.NewFlagSet("session save", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	inputPtr := fs.String("input", "", `JSON string: {"title":"...","messages":[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]}`)
	kbIndexPtr := fs.String("kb-index", "", "Knowledge base index")
	waitPtr := fs.Bool("wait", false, "Wait for async task to complete")

	if err := parseFlagSet(fs, args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() > 0 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "session save does not accept positional arguments.", ExitCode: 1}
	}
	opts.Input = *inputPtr
	opts.KbIndex = *kbIndexPtr
	opts.Wait = *waitPtr
	return nil
}
