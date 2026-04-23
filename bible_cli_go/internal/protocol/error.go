package protocol

import (
	"fmt"
	"io"
)

const CommandNotImplementedExitCode = 3

type CLIError struct {
	Code     string
	Message  string
	ExitCode int
}

func (e CLIError) Error() string {
	return e.Message
}

func PrintCLIError(w io.Writer, err CLIError) {
	fmt.Fprintf(w, "Error[%s]: %s\n", err.Code, err.Message)
}

func NotImplemented(commandPath string) CLIError {
	return CLIError{
		Code:     "CLI_NOT_IMPLEMENTED",
		Message:  fmt.Sprintf("Command '%s' is not implemented yet.", commandPath),
		ExitCode: CommandNotImplementedExitCode,
	}
}

func WrapAsCLIError(err error) CLIError {
	if cliErr, ok := err.(CLIError); ok {
		return cliErr
	}
	return CLIError{
		Code:     "CLI_ERROR",
		Message:  err.Error(),
		ExitCode: 1,
	}
}
