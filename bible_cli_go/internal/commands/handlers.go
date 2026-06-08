package commands

import (
	"strings"

	clienthttp "bible-cli-go/internal/client/http"
	"bible-cli-go/internal/config"
	"bible-cli-go/internal/logger"
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
	logger.Debug("dispatcher.handle", map[string]any{"command": command, "action": action})
	switch command {
	case "health":
		return d.client.Health()
	case "system":
		return d.handleSystem(action)
	case "knowledge":
		return d.handleKnowledge(action, query, tag)
	default:
		return nil, protocol.CLIError{Code: "INVALID_ARGUMENT", Message: "Unknown command.", ExitCode: 1}
	}
}

func (d *Dispatcher) Search(options clienthttp.SearchOptions) (map[string]any, error) {
	logger.Debug("dispatcher.search", map[string]any{"query": options.Query, "top_k": options.TopK})
	return d.client.Search(options)
}

func (d *Dispatcher) handleSystem(action string) (map[string]any, error) {
	logger.Debug("dispatcher.system", map[string]any{"action": action})
	switch action {
	case "status":
		payload, err := d.client.Status()
		if err != nil {
			return payload, err
		}
		return decorateServerResponse(payload), nil
	case "info":
		payload, err := d.client.Info()
		if err != nil {
			return payload, err
		}
		return decorateServerResponse(payload), nil
	default:
		return nil, protocol.NotImplemented(strings.TrimSpace("system " + action))
	}
}

func (d *Dispatcher) handleKnowledge(action string, query string, tag string) (map[string]any, error) {
	logger.Debug("dispatcher.knowledge", map[string]any{"action": action, "tag": tag})
	switch action {
	case "list":
		payload, err := d.client.KnowledgeList()
		if err != nil {
			return payload, err
		}
		return decorateServerResponse(payload), nil
	case "search":
		payload, err := d.client.KnowledgeSearch(clienthttp.KnowledgeSearchRequest{Query: query, Tag: tag})
		if err != nil {
			return payload, err
		}
		return decorateServerResponse(payload), nil
	default:
		return nil, protocol.NotImplemented(strings.TrimSpace("knowledge " + action))
	}
}
