package commands

import (
	"strings"

	"bible-cli-go/internal/protocol"
)

// TaskCommandOptions aggregates flags from task subcommands.
type TaskCommandOptions struct {
	TaskID string
}

// TaskExecute dispatches a task subcommand.
func (d *Dispatcher) TaskExecute(action string, opts TaskCommandOptions) (map[string]any, error) {
	taskID := strings.TrimSpace(opts.TaskID)
	if taskID == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "task_id is required.", ExitCode: 1}
	}

	switch action {
	case "get", "status":
		return d.client.GetTask(taskID)
	case "cancel":
		return d.client.CancelTask(taskID)
	default:
		return nil, protocol.NotImplemented("task " + action)
	}
}
