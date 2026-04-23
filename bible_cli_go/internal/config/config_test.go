package config

import "testing"

func TestFromEnvUsesPriorityAndDefaults(t *testing.T) {
	t.Setenv("BIBLE_CLI_BASE_URL", "")
	t.Setenv("BIBLE_ATLAS_BASE_URL", "http://atlas.local")
	t.Setenv("BIBLE_CLI_TIMEOUT_SECONDS", "")
	t.Setenv("BIBLE_CLI_TRUST_ENV", "")

	cfg := FromEnv()

	if cfg.BaseURL != "http://atlas.local" {
		t.Fatalf("expected fallback base url, got %q", cfg.BaseURL)
	}
	if cfg.TimeoutSeconds != 30 {
		t.Fatalf("expected default timeout 30, got %d", cfg.TimeoutSeconds)
	}
	if cfg.TrustEnv {
		t.Fatalf("expected default trust_env false")
	}
}

func TestFromEnvUsesPreferredBaseURLAndParsedValues(t *testing.T) {
	t.Setenv("BIBLE_CLI_BASE_URL", "http://cli.local")
	t.Setenv("BIBLE_ATLAS_BASE_URL", "http://atlas.local")
	t.Setenv("BIBLE_CLI_TIMEOUT_SECONDS", "15")
	t.Setenv("BIBLE_CLI_TRUST_ENV", "yes")

	cfg := FromEnv()

	if cfg.BaseURL != "http://cli.local" {
		t.Fatalf("expected preferred base url, got %q", cfg.BaseURL)
	}
	if cfg.TimeoutSeconds != 15 {
		t.Fatalf("expected timeout 15, got %d", cfg.TimeoutSeconds)
	}
	if !cfg.TrustEnv {
		t.Fatalf("expected trust_env true")
	}
}

func TestFromEnvInvalidTimeoutFallsBackToDefault(t *testing.T) {
	t.Setenv("BIBLE_CLI_TIMEOUT_SECONDS", "invalid")

	cfg := FromEnv()
	if cfg.TimeoutSeconds != 30 {
		t.Fatalf("expected default timeout 30 on invalid value, got %d", cfg.TimeoutSeconds)
	}
}
