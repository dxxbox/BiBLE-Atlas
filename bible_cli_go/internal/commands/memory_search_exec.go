package commands

import (
	"strings"

	clienthttp "bible-cli-go/internal/client/http"
	"bible-cli-go/internal/fixtures"
	"bible-cli-go/internal/logger"
	"bible-cli-go/internal/protocol"
)

// runMemorySearch implements `bible memory search`.
//
// Two backends, same JSON shape in `data` for the plugin envelope:
//   - opts.TestMode (from peeled `--test` / `-test` in argv): fixtures, no HTTP.
//   - default: HTTP to Atlas; BIBLE_CLI_STUB_MODE=1 → stubMemorySearch only; otherwise errors propagate (no network stub).
func runMemorySearch(client *clienthttp.Client, opts MemoryCommandOptions) (map[string]any, error) {
	if strings.TrimSpace(opts.Query) == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "query is required for memory search.", ExitCode: 1}
	}
	topK := opts.TopK
	if topK <= 0 {
		topK = 5
	}
	logger.Info("memory.search.start", map[string]any{
		"query": opts.Query, "tag": opts.Tag, "top_k": topK, "test": opts.TestMode,
	})

	if opts.TestMode {
		return memorySearchFromFixtures(opts, topK)
	}
	return memorySearchLive(client, opts, topK)
}

// memorySearchFromFixtures loads embedded JSON (MemorySearchResult shape:
// results, total, kb_index, tag). Returned map is passed to the plugin as-is.
func memorySearchFromFixtures(opts MemoryCommandOptions, topK int) (map[string]any, error) {
	payload, err := fixtures.MemorySearchTestData(opts.Query, topK, opts.Tag)
	if err != nil {
		return nil, protocol.CLIError{Code: "INTERNAL", Message: err.Error(), ExitCode: 1}
	}
	logger.Info("memory.search.fixture", map[string]any{
		"path": "internal/fixtures/memory_search_test.json",
	})
	return payload, nil
}

// memorySearchLive calls POST /api/search/memory, or stubMemorySearch only when
// BIBLE_CLI_STUB_MODE is set. Network errors are returned to the caller.
func memorySearchLive(client *clienthttp.Client, opts MemoryCommandOptions, topK int) (map[string]any, error) {
	req := clienthttp.MemorySearchRequest{
		Query:      opts.Query,
		TopK:       topK,
		Threshold:  opts.Threshold,
		SearchType: opts.SearchType,
		FilterTag:  opts.Tag,
	}
	if isStubMode() {
		logger.Info("memory.search.stub", map[string]any{"reason": "BIBLE_CLI_STUB_MODE=1"})
		return stubMemorySearch(opts.Query, "stub_mode"), nil
	}
	payload, err := client.MemorySearch(req)
	if err != nil {
		return payload, err
	}
	return decorateServerResponse(payload), nil
}
