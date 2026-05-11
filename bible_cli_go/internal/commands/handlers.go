package commands

import (
	"strings"

	clienthttp "bible-cli-go/internal/client/http"
	"bible-cli-go/internal/config"
	"bible-cli-go/internal/protocol"
)

// Dispatcher holds an HTTP client and config for executing CLI commands.
type Dispatcher struct {
	client *clienthttp.Client
	cfg    config.ClientConfig
}

func NewDispatcher(cfg config.ClientConfig) *Dispatcher {
	return &Dispatcher{
		client: clienthttp.New(cfg),
		cfg:    cfg,
	}
}

func (d *Dispatcher) Handle(command string, action string, query string, tag string) (map[string]any, error) {
	switch command {
	case "health":
		return d.client.Health()
	case "system":
		return d.handleSystem(action)
	case "knowledge":
		return d.handleKnowledge(action, query)
	default:
		return nil, protocol.CLIError{Code: "INVALID_ARGUMENT", Message: "Unknown command.", ExitCode: 1}
	}
}

func (d *Dispatcher) Search(options clienthttp.SearchOptions) (map[string]any, error) {
	return d.client.Search(options)
}

func (d *Dispatcher) handleSystem(action string) (map[string]any, error) {
	switch action {
	case "status":
		return d.client.Status()
	case "info":
		return d.client.Info()
	default:
		return nil, protocol.NotImplemented(strings.TrimSpace("system " + action))
	}
}

func (d *Dispatcher) handleKnowledge(action string, query string, tag string) (map[string]any, error) {
	switch action {
	case "list":
		return d.client.KnowledgeList()
	case "search":
		return d.client.KnowledgeSearch(clienthttp.KnowledgeSearchRequest{Query: query, Tag: tag})
	default:
		return nil, protocol.NotImplemented(strings.TrimSpace("knowledge " + action))
	}
}
