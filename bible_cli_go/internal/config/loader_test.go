package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestLoadResolvedConfigDefaults(t *testing.T) {
	resolved := loadResolvedConfig("", "")

	if resolved.BaseURL != defaultBaseURL {
		t.Fatalf("expected default base url %q, got %q", defaultBaseURL, resolved.BaseURL)
	}
	if resolved.TimeoutSeconds != defaultTimeoutSeconds {
		t.Fatalf("expected default timeout %d, got %d", defaultTimeoutSeconds, resolved.TimeoutSeconds)
	}
	if resolved.TrustEnv != defaultTrustEnv {
		t.Fatalf("expected default trust_env %v, got %v", defaultTrustEnv, resolved.TrustEnv)
	}
	if resolved.BaseURLSource != SourceDefault {
		t.Fatalf("expected default source, got %q", resolved.BaseURLSource)
	}
}

func TestLoadResolvedConfigPrioritySystemUserEnv(t *testing.T) {
	systemPath := writeTempConfig(t, `{"server_url":"http://system.local","timeout_seconds":10,"trust_env":false}`)
	userPath := writeTempConfig(t, `{"base_url":"http://user.local","timeout_seconds":20,"trust_env":true}`)

	t.Setenv("BIBLE_CLI_BASE_URL", "http://env-cli.local")
	t.Setenv("BIBLE_ATLAS_BASE_URL", "http://env-atlas.local")
	t.Setenv("BIBLE_CLI_TIMEOUT_SECONDS", "35")
	t.Setenv("BIBLE_CLI_TRUST_ENV", "off")

	resolved := loadResolvedConfig(userPath, systemPath)

	if resolved.BaseURL != "http://env-cli.local" {
		t.Fatalf("expected env cli base url, got %q", resolved.BaseURL)
	}
	if resolved.TimeoutSeconds != 35 {
		t.Fatalf("expected env timeout 35, got %d", resolved.TimeoutSeconds)
	}
	if resolved.TrustEnv {
		t.Fatalf("expected env trust_env false")
	}

	if resolved.BaseURLSource != SourceEnvCLI {
		t.Fatalf("expected base source env cli, got %q", resolved.BaseURLSource)
	}
	if resolved.TimeoutSecondsSource != SourceEnvCLI {
		t.Fatalf("expected timeout source env cli, got %q", resolved.TimeoutSecondsSource)
	}
	if resolved.TrustEnvSource != SourceEnvCLI {
		t.Fatalf("expected trust source env cli, got %q", resolved.TrustEnvSource)
	}
}

func TestLoadResolvedConfigUsesAtlasFallback(t *testing.T) {
	t.Setenv("BIBLE_CLI_BASE_URL", "")
	t.Setenv("BIBLE_ATLAS_BASE_URL", "http://atlas.local")

	resolved := loadResolvedConfig("", "")

	if resolved.BaseURL != "http://atlas.local" {
		t.Fatalf("expected atlas fallback base url, got %q", resolved.BaseURL)
	}
	if resolved.BaseURLSource != SourceEnvAtlas {
		t.Fatalf("expected atlas source, got %q", resolved.BaseURLSource)
	}
}

func TestLoadResolvedConfigInvalidValuesFallback(t *testing.T) {
	systemPath := writeTempConfig(t, `{"server_url":"http://system.local","timeout_seconds":8,"trust_env":false}`)
	userPath := writeTempConfig(t, `{"base_url":"http://user.local","timeout_seconds":12,"trust_env":true}`)

	t.Setenv("BIBLE_CLI_TIMEOUT_SECONDS", "invalid")
	t.Setenv("BIBLE_CLI_TRUST_ENV", "not-a-bool")

	resolved := loadResolvedConfig(userPath, systemPath)

	if resolved.BaseURL != "http://user.local" {
		t.Fatalf("expected user base url, got %q", resolved.BaseURL)
	}
	if resolved.TimeoutSeconds != 12 {
		t.Fatalf("expected user timeout fallback, got %d", resolved.TimeoutSeconds)
	}
	if !resolved.TrustEnv {
		t.Fatalf("expected user trust_env fallback true")
	}
}

func writeTempConfig(t *testing.T, content string) string {
	t.Helper()

	dir := t.TempDir()
	path := filepath.Join(dir, "config.json")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("failed to write temp config: %v", err)
	}
	return path
}
