package config

type ConfigSource string

const (
	SourceDefault    ConfigSource = "default"
	SourceSystemFile ConfigSource = "system_file"
	SourceUserFile   ConfigSource = "user_file"
	SourceEnvCLI     ConfigSource = "env_bible_cli"
	SourceEnvAtlas   ConfigSource = "env_bible_atlas"
)

type ResolvedConfig struct {
	ClientConfig
	BaseURLSource        ConfigSource
	TimeoutSecondsSource ConfigSource
	TrustEnvSource       ConfigSource
}
