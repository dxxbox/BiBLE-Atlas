package config

import (
	"os"
	"strconv"
	"strings"
)

type ClientConfig struct {
	BaseURL        string
	Token          string
	TimeoutSeconds int
	TrustEnv       bool
	Memory         MemoryConfig
	Skill          SkillConfig
}

func FromEnv() ClientConfig {
	baseURL := firstNonEmpty(
		os.Getenv("BIBLE_CLI_BASE_URL"),
		os.Getenv("BIBLE_ATLAS_BASE_URL"),
		"http://127.0.0.1:5555",
	)

	timeout := 30
	if rawTimeout := strings.TrimSpace(os.Getenv("BIBLE_CLI_TIMEOUT_SECONDS")); rawTimeout != "" {
		if parsed, err := strconv.Atoi(rawTimeout); err == nil && parsed > 0 {
			timeout = parsed
		}
	}

	trustEnv := parseBoolEnv(os.Getenv("BIBLE_CLI_TRUST_ENV"), false)

	return ClientConfig{
		BaseURL:        baseURL,
		TimeoutSeconds: timeout,
		TrustEnv:       trustEnv,
	}
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return value
		}
	}
	return ""
}

func parseBoolEnv(raw string, defaultValue bool) bool {
	normalized := strings.ToLower(strings.TrimSpace(raw))
	if normalized == "" {
		return defaultValue
	}

	switch normalized {
	case "1", "true", "yes", "on":
		return true
	case "0", "false", "no", "off":
		return false
	default:
		return defaultValue
	}
}
