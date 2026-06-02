package cli

import (
	"flag"
	"io"
	"strings"

	"bible-cli-go/internal/commands"
	"bible-cli-go/internal/protocol"
)

type multiStringFlag []string

func (m *multiStringFlag) String() string {
	return strings.Join(*m, ",")
}

func (m *multiStringFlag) Set(value string) error {
	*m = append(*m, value)
	return nil
}

func parseKnowledgeImportFlags(args []string, opts *commands.KnowledgeCommandOptions) error {
	fs := flag.NewFlagSet("knowledge import", flag.ContinueOnError)
	fs.SetOutput(io.Discard)

	var files multiStringFlag
	fs.Var(&files, "file", "File to import; may be repeated")
	kbIndexPtr := fs.String("kb-index", "", "Knowledge base index")
	tagPtr := fs.String("tag", "", "Knowledge base tag, for example design or flow")
	vectorModelPtr := fs.String("vector-model", "", "Vector model override")
	parserScriptPtr := fs.String("parser-script", "", "Optional parser script file")
	parserContextPtr := fs.String("parser-context", "", "Optional parser context JSON")
	waitPtr := fs.Bool("wait", false, "Wait for async import task to complete")

	if err := parseFlagSet(fs, args); err != nil {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}
	if fs.NArg() > 0 {
		return protocol.CLIError{Code: "INVALID_ARGS", Message: "knowledge import does not accept positional arguments (use --file).", ExitCode: 1}
	}

	opts.Files = files
	opts.KbIndex = *kbIndexPtr
	opts.Tag = *tagPtr
	opts.VectorModel = *vectorModelPtr
	opts.ParserScript = *parserScriptPtr
	opts.ParserContext = *parserContextPtr
	opts.Wait = *waitPtr
	return nil
}
