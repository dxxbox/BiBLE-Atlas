package cli

import (
	"flag"
	"fmt"
	"io"
	"os"

	"bible-cli-go/internal/commands"
	"bible-cli-go/internal/config"
	"bible-cli-go/internal/protocol"
)

func Run(args []string, stdout io.Writer, stderr io.Writer) int {
	if len(args) == 0 {
		printHelp(stdout)
		return 0
	}

	command := args[0]
	action := ""
	query := ""

	switch command {
	case "health":
		if len(args) > 1 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "health does not accept subcommands.", ExitCode: 1})
		}
	case "system", "knowledge", "memory", "skills":
		if len(args) < 2 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: fmt.Sprintf("Missing action for '%s'.", command), ExitCode: 1})
		}
		action = args[1]

		if command == "knowledge" && action == "search" {
			fs := flag.NewFlagSet("knowledge search", flag.ContinueOnError)
			fs.SetOutput(io.Discard)
			if err := fs.Parse(args[2:]); err != nil {
				return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1})
			}
			if fs.NArg() > 0 {
				query = fs.Arg(0)
			}
			if fs.NArg() > 1 {
				return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "knowledge search accepts at most one optional query argument.", ExitCode: 1})
			}
		} else if len(args) > 2 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "Unexpected extra arguments.", ExitCode: 1})
		}
	case "help", "--help", "-h":
		printHelp(stdout)
		return 0
	default:
		return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: fmt.Sprintf("Unknown command '%s'.", command), ExitCode: 1})
	}

	cfg := config.LoadResolvedConfig().ClientConfig
	dispatcher := commands.NewDispatcher(cfg)
	response, err := dispatcher.Handle(command, action, query)
	if err != nil {
		return fail(stdout, stderr, protocol.WrapAsCLIError(err))
	}

	if err := protocol.PrintSuccess(stdout, response); err != nil {
		return fail(stdout, stderr, protocol.CLIError{Code: "INTERNAL", Message: "Failed to serialize command output.", ExitCode: 1})
	}
	return 0
}

func fail(stdout io.Writer, stderr io.Writer, err protocol.CLIError) int {
	if printErr := protocol.PrintFailure(stdout, err.Code, err.Message); printErr != nil {
		protocol.PrintCLIError(stderr, protocol.CLIError{Code: "INTERNAL", Message: "Failed to serialize command output.", ExitCode: 1})
		return 1
	}

	if os.Getenv("BIBLE_CLI_LEGACY_STDERR") == "1" {
		protocol.PrintCLIError(stderr, err)
	}

	return err.ExitCode
}

func printHelp(w io.Writer) {
	fmt.Fprintln(w, "Bible CLI command line interface.")
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Usage:")
	fmt.Fprintln(w, "  bs health")
	fmt.Fprintln(w, "  bs system status|info")
	fmt.Fprintln(w, "  bs knowledge list")
	fmt.Fprintln(w, "  bs knowledge search [query]")
	fmt.Fprintln(w, "  bs memory show")
	fmt.Fprintln(w, "  bs skills list")
}
