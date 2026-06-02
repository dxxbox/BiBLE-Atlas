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
	tag := ""
	searchOptions := clienthttp.SearchOptions{
		TopK:      5,
		EnableHit: false,
		HitTypes:  []string{"skill", "memory"},
	}
	var memoryOpts commands.MemoryCommandOptions
	var skillsOpts commands.SkillsCommandOptions
	var sessionOpts commands.SessionCommandOptions
	var knowledgeOpts commands.KnowledgeCommandOptions
	var taskOpts commands.TaskCommandOptions

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
		knowledgeTagPtr := fs.String("knowledge-tag", "", "Tag for knowledge-base search (v4); omit to skip knowledge results")
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
			Query:        *queryPtr,
			TopK:         *topKPtr,
			EnableHit:    *enableHitPtr,
			HitTypes:     hitTypes,
			KnowledgeTag: *knowledgeTagPtr,
		}
	case "memory":
		if len(args) < 2 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "Missing action for 'memory'.", ExitCode: 1})
		}
		action = normalizeActionAlias(command, args[1])
		switch action {
		case "get", "save":
			if err := parseSessionFlags(action, args[2:], &sessionOpts); err != nil {
				return fail(stdout, stderr, protocol.WrapAsCLIError(err))
			}
		default:
			if err := parseMemoryFlags(action, args[2:], &memoryOpts); err != nil {
				return fail(stdout, stderr, protocol.WrapAsCLIError(err))
			}
		}
	case "skills":
		if len(args) < 2 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "Missing action for 'skills'.", ExitCode: 1})
		}
		action = normalizeActionAlias(command, args[1])
		if err := parseSkillsFlags(action, args[2:], &skillsOpts); err != nil {
			return fail(stdout, stderr, protocol.WrapAsCLIError(err))
		}
	case "session":
		if len(args) < 2 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "Missing action for 'session'.", ExitCode: 1})
		}
		action = normalizeActionAlias(command, args[1])
		if err := parseSessionFlags(action, args[2:], &sessionOpts); err != nil {
			return fail(stdout, stderr, protocol.WrapAsCLIError(err))
		}
	case "task":
		if len(args) < 2 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "Missing action for 'task'.", ExitCode: 1})
		}
		action = normalizeActionAlias(command, args[1])
		if len(args) < 3 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "task_id is required.", ExitCode: 1})
		}
		if len(args) > 3 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "task accepts exactly one task_id argument.", ExitCode: 1})
		}
		taskOpts.TaskID = args[2]
	case "system", "knowledge":
		if len(args) < 2 {
			return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: fmt.Sprintf("Missing action for '%s'.", command), ExitCode: 1})
		}
		action = normalizeActionAlias(command, args[1])

		if command == "knowledge" && action == "search" {
			fs := flag.NewFlagSet("knowledge search", flag.ContinueOnError)
			fs.SetOutput(io.Discard)
			tagPtr := fs.String("tag", "", "Knowledge base tag (required for v4 search)")
			if err := fs.Parse(args[2:]); err != nil {
				return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1})
			}
			if fs.NArg() > 0 {
				query = fs.Arg(0)
			}
			if fs.NArg() > 1 {
				return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "knowledge search accepts at most one optional query argument.", ExitCode: 1})
			}
			tag = strings.TrimSpace(*tagPtr)
			if tag == "" {
				return fail(stdout, stderr, protocol.CLIError{Code: "INVALID_ARGS", Message: "--tag is required for knowledge search.", ExitCode: 1})
			}
		} else if command == "knowledge" && action == "import" {
			if err := parseKnowledgeImportFlags(args[2:], &knowledgeOpts); err != nil {
				return fail(stdout, stderr, protocol.WrapAsCLIError(err))
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
	switch command {
	case "search":
		response, err = dispatcher.Search(searchOptions)
	case "memory":
		if action == "get" || action == "save" {
			response, err = dispatcher.SessionExecute(action, sessionOpts)
		} else {
			response, err = dispatcher.MemoryExecute(action, memoryOpts)
		}
	case "skills":
		response, err = dispatcher.SkillsExecute(action, skillsOpts)
	case "session":
		response, err = dispatcher.SessionExecute(action, sessionOpts)
	case "knowledge":
		response, err = dispatcher.KnowledgeExecute(action, query, tag, knowledgeOpts)
	case "task":
		response, err = dispatcher.TaskExecute(action, taskOpts)
	default:
		response, err = dispatcher.Handle(command, action, query, tag)
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
	fmt.Fprintln(w, "  bible search --query <string> [--top-k <int>] [--enable-hit] [--hit-types skill,memory] [--knowledge-tag <tag>]")
	fmt.Fprintln(w, "  bible system status|info")
	fmt.Fprintln(w, "  bible knowledge list|search --tag <tag> [query]")
	fmt.Fprintln(w, "  bible knowledge import --file <path> [--file <path>] --kb-index <index> --tag <tag> [--wait]")
	fmt.Fprintln(w, "  bible memory upload <session_dir> --kb-index <index> [--skip-if-exists] [--wait]")
	fmt.Fprintln(w, "  bible memory upload-all <base_dir> --kb-index <index> [--workers N]")
	fmt.Fprintln(w, "  bible memory build-meta <session_dir>")
	fmt.Fprintln(w, "  bible memory status [task_id] [--memory-id ID] [--cache-dir DIR]")
	fmt.Fprintln(w, "  bible memory list [--limit N] [--tag TAG] [--since DATE]")
	fmt.Fprintln(w, "  bible memory search <query> [--top-k N]")
	fmt.Fprintln(w, "  bible memory download <memory_id> [--storage-path PATH ...] [--package-name NAME] [--output DIR]")
	fmt.Fprintln(w, "  bible memory cache-status [base_dir]")
	fmt.Fprintln(w, "  bible skills list [--limit N] [--tag TAG]")
	fmt.Fprintln(w, "  bible skills search <query> [--top-k N]")
	fmt.Fprintln(w, "  bible skills get <name_or_id> [--content]")
	fmt.Fprintln(w, "  bible skills upload --file <path.skill|skill_dir> --kb-index <index> [--wait]")
	fmt.Fprintln(w, "  bible skills download <name_or_id> [--storage-path PATH ...] [--package-name NAME] [--output DIR]")
	fmt.Fprintln(w, "  bible task get|status|cancel <task_id>")
	fmt.Fprintln(w, "  bible memory get --id <memory-id>")
	fmt.Fprintln(w, `  bible memory save --input '{"title":"...","messages":[...]}' --kb-index <index> [--wait]`)
	fmt.Fprintln(w, "  bible session list [--limit N]       (deprecated: use 'memory list')")
	fmt.Fprintln(w, "  bible session get --id <session-id>  (deprecated: use 'memory get')")
	fmt.Fprintln(w, `  bible session save --input '{"title":"...","messages":[...]}' --kb-index <index> [--wait]  (deprecated: use 'memory save')`)
	fmt.Fprintln(w)
	fmt.Fprintln(w, "Note: --kb-index <index> may also be supplied by BIBLE_MEMORY_KB_INDEX or config.")
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
			"import": "import",
		},
		"memory": {
			"upload":       "upload",
			"upload-all":   "upload-all",
			"build-meta":   "build-meta",
			"status":       "status",
			"show":         "status",
			"list":         "list",
			"ls":           "list",
			"search":       "search",
			"cache-status": "cache-status",
			"download":     "download",
			"get":          "get",
			"save":         "save",
		},
		"skills": {
			"list":     "list",
			"ls":       "list",
			"search":   "search",
			"get":      "get",
			"show":     "get",
			"upload":   "upload",
			"download": "download",
		},
		"session": {
			"list": "list",
			"ls":   "list",
			"get":  "get",
			"save": "save",
		},
		"task": {
			"get":    "get",
			"status": "status",
			"show":   "status",
			"cancel": "cancel",
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
