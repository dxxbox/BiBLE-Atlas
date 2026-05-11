package config

type ConfigSource string

const (
	SourceDefault    ConfigSource = "default"
	SourceSystemFile ConfigSource = "system_file"
	SourceUserFile   ConfigSource = "user_file"
	SourceEnvCLI     ConfigSource = "env_bible_cli"
	SourceEnvAtlas   ConfigSource = "env_bible_atlas"
)

// MemoryUploadConfig holds tunable defaults for the memory upload commands.
type MemoryUploadConfig struct {
	KbIndex             string  `json:"kb_index"`
	VectorModel         string  `json:"vector_model"`
	SkipIfExists        bool    `json:"skip_if_exists"`
	MaxAttachmentSizeMB int     `json:"max_attachment_size_mb"`
	Workers             int     `json:"workers"`
	RetryMax            int     `json:"retry_max"`
	RetryBackoff        float64 `json:"retry_backoff"`
	AbstractTruncate    bool    `json:"abstract_truncate"`
}

// MemorySearchConfig holds defaults for memory search.
type MemorySearchConfig struct {
	DefaultSearchType string `json:"default_search_type"`
	DefaultTopK       int    `json:"default_top_k"`
	VectorModel       string `json:"vector_model"`
}

// MemoryDownloadConfig holds poll settings for async download.
type MemoryDownloadConfig struct {
	PollIntervalSeconds int `json:"poll_interval_seconds"`
	PollTimeoutSeconds  int `json:"poll_timeout_seconds"`
}

// MemoryConfig groups memory-related configuration.
type MemoryConfig struct {
	Upload   MemoryUploadConfig   `json:"upload"`
	Search   MemorySearchConfig   `json:"search"`
	Download MemoryDownloadConfig `json:"download"`
}

// SkillSearchConfig holds defaults for skill search.
type SkillSearchConfig struct {
	PassiveTopK       int     `json:"passive_top_k"`
	PassiveThreshold  float64 `json:"passive_threshold"`
}

// SkillConfig groups skill-related configuration.
type SkillConfig struct {
	Search SkillSearchConfig `json:"search"`
}

type ResolvedConfig struct {
	ClientConfig
	BaseURLSource        ConfigSource
	TimeoutSecondsSource ConfigSource
	TrustEnvSource       ConfigSource
}
