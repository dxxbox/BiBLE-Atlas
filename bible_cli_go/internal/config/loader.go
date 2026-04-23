package config

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

const (
	defaultBaseURL        = "http://127.0.0.1:5555"
	defaultTimeoutSeconds = 30
	defaultTrustEnv       = false
)

type configFilePayload struct {
	ServerURL      *string `json:"server_url"`
	BaseURL        *string `json:"base_url"`
	TimeoutSeconds *int    `json:"timeout_seconds"`
	TrustEnv       *bool   `json:"trust_env"`
}

// LoadResolvedConfig merges config layers with precedence:
// env > user file > system file > defaults.
func LoadResolvedConfig() ResolvedConfig {
	return loadResolvedConfig(resolveUserConfigPath(), resolveSystemConfigPath())
}

func loadResolvedConfig(userPath string, systemPath string) ResolvedConfig {
	resolved := ResolvedConfig{
		ClientConfig: ClientConfig{
			BaseURL:        defaultBaseURL,
			TimeoutSeconds: defaultTimeoutSeconds,
			TrustEnv:       defaultTrustEnv,
		},
		BaseURLSource:        SourceDefault,
		TimeoutSecondsSource: SourceDefault,
		TrustEnvSource:       SourceDefault,
	}

	applyFileLayer(&resolved, systemPath, SourceSystemFile)
	applyFileLayer(&resolved, userPath, SourceUserFile)
	applyEnvLayer(&resolved)

	return resolved
}

func resolveUserConfigPath() string {
	home, err := os.UserHomeDir()
	if err != nil || strings.TrimSpace(home) == "" {
		return ""
	}
	return filepath.Join(home, ".bible", "config.json")
}

func resolveSystemConfigPath() string {
	return "/etc/bible/config.json"
}

func applyFileLayer(resolved *ResolvedConfig, path string, source ConfigSource) {
	if strings.TrimSpace(path) == "" {
		return
	}

	body, err := os.ReadFile(path)
	if err != nil {
		return
	}

	var payload configFilePayload
	if err := json.Unmarshal(body, &payload); err != nil {
		return
	}

	if payload.BaseURL != nil && strings.TrimSpace(*payload.BaseURL) != "" {
		resolved.BaseURL = strings.TrimSpace(*payload.BaseURL)
		resolved.BaseURLSource = source
	} else if payload.ServerURL != nil && strings.TrimSpace(*payload.ServerURL) != "" {
		resolved.BaseURL = strings.TrimSpace(*payload.ServerURL)
		resolved.BaseURLSource = source
	}

	if payload.TimeoutSeconds != nil && *payload.TimeoutSeconds > 0 {
		resolved.TimeoutSeconds = *payload.TimeoutSeconds
		resolved.TimeoutSecondsSource = source
	}

	if payload.TrustEnv != nil {
		resolved.TrustEnv = *payload.TrustEnv
		resolved.TrustEnvSource = source
	}
}

func applyEnvLayer(resolved *ResolvedConfig) {
	if baseURL := strings.TrimSpace(os.Getenv("BIBLE_CLI_BASE_URL")); baseURL != "" {
		resolved.BaseURL = baseURL
		resolved.BaseURLSource = SourceEnvCLI
	} else if baseURL := strings.TrimSpace(os.Getenv("BIBLE_ATLAS_BASE_URL")); baseURL != "" {
		resolved.BaseURL = baseURL
		resolved.BaseURLSource = SourceEnvAtlas
	}

	if timeoutRaw := strings.TrimSpace(os.Getenv("BIBLE_CLI_TIMEOUT_SECONDS")); timeoutRaw != "" {
		if timeout, err := strconv.Atoi(timeoutRaw); err == nil && timeout > 0 {
			resolved.TimeoutSeconds = timeout
			resolved.TimeoutSecondsSource = SourceEnvCLI
		}
	}

	if trustRaw := strings.TrimSpace(os.Getenv("BIBLE_CLI_TRUST_ENV")); trustRaw != "" {
		if trust, ok := parseStrictBoolEnv(trustRaw); ok {
			resolved.TrustEnv = trust
			resolved.TrustEnvSource = SourceEnvCLI
		}
	}
}

func parseStrictBoolEnv(raw string) (bool, bool) {
	normalized := strings.ToLower(strings.TrimSpace(raw))
	switch normalized {
	case "1", "true", "yes", "on":
		return true, true
	case "0", "false", "no", "off":
		return false, true
	default:
		return false, false
	}
}
