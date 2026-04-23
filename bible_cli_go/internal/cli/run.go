package cli

import (
	"flag"
	"fmt"
	"io"
	"os"
	"strings"

	clienthttp "bible-cli-go/internal/client/http"
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
	searchOptions := clienthttp.SearchOptions{
		TopK:      5,
		EnableHit: false,
		HitTypes:  []string{"skill", "memory"},
	}

	switch command {
	case "health":
		if len(args) > 1 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "health does not accept subcommands.", ExitCode: 1})
		}
	case "search":
		fs := flag.NewFlagSet("search", flag.ContinueOnError)
		fs.SetOutput(io.Discard)
		queryPtr := fs.String("query", "", "Search query")
		topKPtr := fs.Int("top-k", 5, "Top k results")
		enableHitPtr := fs.Bool("enable-hit", false, "Enable hit search")
		hitTypesPtr := fs.String("hit-types", "skill,memory", "Comma-separated hit types: skill,memory")
		if err := fs.Parse(args[1:]); err != nil {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1})
		}
		if fs.NArg() > 0 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "search does not accept positional arguments.", ExitCode: 1})
		}
		if strings.TrimSpace(*queryPtr) == "" {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "--query is required for search.", ExitCode: 1})
		}
		if *topKPtr <= 0 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "--top-k must be greater than 0.", ExitCode: 1})
		}
		hitTypes, hitTypeErr := parseHitTypes(*hitTypesPtr)
		if hitTypeErr != nil {
			return fail(stdout, stderr, protocol.WrapAsCLIError(hitTypeErr))
		}
		searchOptions = clienthttp.SearchOptions{
			Query:     *queryPtr,
			TopK:      *topKPtr,
			EnableHit: *enableHitPtr,
			HitTypes:  hitTypes,
		}
	case "system", "knowledge", "memory", "skills":
		if len(args) < 2 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: fmt.Sprintf("Missing action for '%s'.", command), ExitCode: 1})
		}
		action = normalizeActionAlias(command, args[1])

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
	var (
		response map[string]any
		err      error
	)
	if command == "search" {
		response, err = dispatcher.Search(searchOptions)
	} else {
		response, err = dispatcher.Handle(command, action, query)
	}
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
	fmt.Fprintln(w, "  bible health")
	fmt.Fprintln(w, "  bible search --query <string> [--top-k <int>] [--enable-hit] [--hit-types skill,memory]")
	fmt.Fprintln(w, "  bible system status|info")
	fmt.Fprintln(w, "  bible knowledge list")
	fmt.Fprintln(w, "  bible knowledge search [query]")
	fmt.Fprintln(w, "  bible memory show")
	fmt.Fprintln(w, "  bible skills list")
}

func parseHitTypes(raw string) ([]string, error) {
	defaultTypes := []string{"skill", "memory"}
	if strings.TrimSpace(raw) == "" {
		return defaultTypes, nil
	}

	supported := map[string]struct{}{
		"skill":  {},
		"memory": {},
	}
	seen := map[string]struct{}{}
	types := []string{}
	for _, item := range strings.Split(raw, ",") {
		value := strings.ToLower(strings.TrimSpace(item))
		if value == "" {
			continue
		}
		if _, ok := supported[value]; !ok {
			return nil, protocol.CLIError{
				Code:     "INVALID_ARGS",
				Message:  fmt.Sprintf("Unsupported hit type '%s'. Supported values: skill,memory.", value),
				ExitCode: 1,
			}
		}
		if _, exists := seen[value]; exists {
			continue
		}
		seen[value] = struct{}{}
		types = append(types, value)
	}
	if len(types) == 0 {
		return defaultTypes, nil
	}
	return types, nil
}

func normalizeActionAlias(command string, action string) string {
	normalizedAction := strings.ToLower(strings.TrimSpace(action))
	if normalizedAction == "" {
		return action
	}

	commandAliases := map[string]map[string]string{
		"knowledge": {
			"list":   "list",
			"ls":     "list",
			"search": "search",
		},
		"memory": {
			"show":   "show",
			"list":   "list",
			"ls":     "list",
			"search": "search",
		},
		"skills": {
			"list": "list",
			"ls":   "list",
		},
	}

	aliases, ok := commandAliases[command]
	if !ok {
		return normalizedAction
	}
	canonical, exists := aliases[normalizedAction]
	if !exists {
		return normalizedAction
	}
	return canonical
}
