// Package fixtures holds static JSON for `bible memory search --test`.
// Payload shape matches a real successful POST /api/search/memory body
// (MemorySearchResult); no extra CLI-only fields are added here.
package fixtures

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"strings"
)

//go:embed memory_search_test.json
var memorySearchTestJSON []byte

// MemorySearchTestData returns a deep copy of the embedded template with
// per-request tweaks: results trimmed to topK, optional filter tag, and the
// first hit abstract annotated with the query string.
func MemorySearchTestData(query string, topK int, filterTag string) (map[string]any, error) {
	var root map[string]any
	if err := json.Unmarshal(memorySearchTestJSON, &root); err != nil {
		return nil, fmt.Errorf("parse memory_search_test.json: %w", err)
	}

	rawResults, ok := root["results"].([]any)
	if !ok {
		return root, nil
	}

	if topK > 0 && len(rawResults) > topK {
		rawResults = append([]any(nil), rawResults[:topK]...)
		root["results"] = rawResults
	}

	root["total"] = float64(len(rawResults))

	if tag := strings.TrimSpace(filterTag); tag != "" {
		root["tag"] = tag
	}

	if len(rawResults) > 0 {
		if m, ok := rawResults[0].(map[string]any); ok {
			if ab, ok := m["abstract"].(string); ok {
				m["abstract"] = fmt.Sprintf("%s [query=%q]", ab, query)
			}
		}
	}

	return root, nil
}
