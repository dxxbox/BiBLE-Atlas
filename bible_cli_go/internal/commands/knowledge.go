package commands

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	clienthttp "bible-cli-go/internal/client/http"
	"bible-cli-go/internal/config"
	"bible-cli-go/internal/protocol"
)

// KnowledgeCommandOptions aggregates flags from knowledge subcommands.
type KnowledgeCommandOptions struct {
	Files         []string
	ParserScript  string
	KbIndex       string
	Tag           string
	VectorModel   string
	ParserContext string
	Wait          bool
}

// KnowledgeExecute dispatches a knowledge subcommand.
func (d *Dispatcher) KnowledgeExecute(action string, query string, tag string, opts KnowledgeCommandOptions) (map[string]any, error) {
	switch action {
	case "list":
		return d.client.KnowledgeList()
	case "search":
		return d.client.KnowledgeSearch(clienthttp.KnowledgeSearchRequest{Query: query, Tag: tag})
	case "import":
		return knowledgeImport(d.client, opts, d.cfg)
	default:
		return nil, protocol.NotImplemented(strings.TrimSpace("knowledge " + action))
	}
}

func knowledgeImport(client *clienthttp.Client, opts KnowledgeCommandOptions, cfg config.ClientConfig) (map[string]any, error) {
	if len(opts.Files) == 0 {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "--file is required for knowledge import.", ExitCode: 1}
	}

	tag := strings.TrimSpace(opts.Tag)
	if tag == "" {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "--tag is required for knowledge import.", ExitCode: 1}
	}

	kbIndex := resolveKbIndex(opts.KbIndex, cfg)
	if kbIndex == "" {
		return nil, protocol.CLIError{
			Code:     "INVALID_ARGS",
			Message:  "kb_index is required. Provide --kb-index flag or set BIBLE_MEMORY_KB_INDEX environment variable.",
			ExitCode: 1,
		}
	}

	files := make([]clienthttp.MemoryFile, 0, len(opts.Files))
	for _, rawPath := range opts.Files {
		fp := strings.TrimSpace(rawPath)
		if fp == "" {
			continue
		}
		if _, err := os.Stat(fp); os.IsNotExist(err) {
			return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: fmt.Sprintf("File not found: %s", fp), ExitCode: 1}
		}
		files = append(files, clienthttp.MemoryFile{
			Filename:    filepath.Base(fp),
			Path:        fp,
			ContentType: "application/octet-stream",
		})
	}
	if len(files) == 0 {
		return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: "--file is required for knowledge import.", ExitCode: 1}
	}

	var parserScript *clienthttp.MemoryFile
	if strings.TrimSpace(opts.ParserScript) != "" {
		fp := strings.TrimSpace(opts.ParserScript)
		if _, err := os.Stat(fp); os.IsNotExist(err) {
			return nil, protocol.CLIError{Code: "INVALID_ARGS", Message: fmt.Sprintf("Parser script not found: %s", fp), ExitCode: 1}
		}
		parserScript = &clienthttp.MemoryFile{
			Filename:    filepath.Base(fp),
			Path:        fp,
			ContentType: "text/x-python",
			FieldName:   "parser_script",
		}
	}

	req := clienthttp.KnowledgeImportRequest{
		Files:         files,
		ParserScript:  parserScript,
		KbIndex:       kbIndex,
		Tag:           tag,
		VectorModel:   resolveVectorModel(opts.VectorModel, cfg),
		ParserContext: opts.ParserContext,
	}
	payload, err := client.ImportKnowledge(req)
	if err != nil {
		return nil, err
	}

	if opts.Wait {
		taskID, _ := payload["task_id"].(string)
		if taskID != "" {
			return client.PollTask(taskID, 3*time.Second, 5*time.Minute)
		}
	}

	return payload, nil
}
