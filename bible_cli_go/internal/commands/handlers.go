package commands

import (
	"strings"

	clienthttp "bible-cli-go/internal/client/http"
	"bible-cli-go/internal/config"
	"bible-cli-go/internal/protocol"
)

type Dispatcher struct {
	client *clienthttp.Client
}

func NewDispatcher(cfg config.ClientConfig) *Dispatcher {
	return &Dispatcher{client: clienthttp.New(cfg)}
}

func (d *Dispatcher) Handle(command string, action string, query string) (map[string]any, error) {
	switch command {
	case "health":
		return d.client.Health()
	case "system":
		return d.handleSystem(action)
	case "knowledge":
		return d.handleKnowledge(action, query)
	case "memory":
		return nil, protocol.NotImplemented(strings.TrimSpace(command + " " + action))
	case "skills":
		return nil, protocol.NotImplemented(strings.TrimSpace(command + " " + action))
	default:
		return nil, protocol.CLIError{Code: "INVALID_ARGUMENT", Message: "Unknown command.", ExitCode: 1}
	}
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

func (d *Dispatcher) handleKnowledge(action string, query string) (map[string]any, error) {
	switch action {
	case "list":
		return d.client.KnowledgeList()
	case "search":
		return d.client.KnowledgeSearch(query)
	default:
		return nil, protocol.NotImplemented(strings.TrimSpace("knowledge " + action))
	}
}
