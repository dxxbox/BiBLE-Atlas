package commands

import (
	"path/filepath"
	"strings"
)

func normalizedStoragePaths(paths []string) []string {
	normalized := make([]string, 0, len(paths))
	seen := map[string]struct{}{}
	for _, rawPath := range paths {
		path := strings.TrimSpace(rawPath)
		if path == "" {
			continue
		}
		if _, exists := seen[path]; exists {
			continue
		}
		seen[path] = struct{}{}
		normalized = append(normalized, path)
	}
	return normalized
}

func artifactName(taskPayload map[string]any) string {
	result, _ := taskPayload["result"].(map[string]any)
	name, _ := result["artifact_name"].(string)
	if strings.TrimSpace(name) == "" {
		return ""
	}
	return strings.TrimSpace(filepath.Base(name))
}
