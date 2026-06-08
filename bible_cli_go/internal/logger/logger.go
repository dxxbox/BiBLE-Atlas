// Package logger provides a lightweight structured JSON file logger for the Bible CLI.
//
// Log entries are written as newline-delimited JSON to ~/.bible/cli.log (or the path
// set by BIBLE_CLI_LOG_FILE).  When the binary is built by `go test` and BIBLE_CLI_LOG_FILE
// is unset, logs go to $TMPDIR/bible-cli-go-test-<pid>.log instead so normal CLI sessions
// are not mixed with test output.  Set BIBLE_CLI_LOG_DISABLE=1 to disable file logging entirely.
// The log is meant for post-hoc debugging of plugin-CLI interactions; it does NOT write to
// stdout/stderr so it never interferes with the JSON protocol used between the VS Code
// extension and the CLI.
//
// Usage:
//
//	logger.Init()
//	logger.Info("cli.invoke", map[string]any{"args": os.Args[1:]})
//	logger.Error("cli.failed", map[string]any{"code": "X", "message": "..."})
package logger

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"flag"
	"sync"
	"time"
)

// Level represents log severity.
type Level string

const (
	LevelDebug Level = "DEBUG"
	LevelInfo  Level = "INFO"
	LevelError Level = "ERROR"
)

// entry is a single structured log line.
type entry struct {
	Timestamp string         `json:"ts"`
	Level     Level          `json:"level"`
	Event     string         `json:"event"`
	Fields    map[string]any `json:"fields,omitempty"`
}

// globalLogger is the package-level singleton, initialised by Init().
var globalLogger *fileLogger
var initOnce sync.Once

type fileLogger struct {
	mu   sync.Mutex
	file *os.File
	enc  *json.Encoder
}

// Init opens (or creates) the log file and initialises the global logger.
// It is safe to call multiple times - only the first call has effect.
// If the log file cannot be opened the logger silently becomes a no-op.
func Init() {
	initOnce.Do(func() {
		path := resolveLogPath()
		if path == "" {
			return
		}
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return
		}
		f, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
		if err != nil {
			return
		}
		enc := json.NewEncoder(f)
		enc.SetEscapeHTML(false)
		globalLogger = &fileLogger{file: f, enc: enc}
	})
}

// resolveLogPath returns the log file path via env override or the default
// location (~/.bible/cli.log).  Test binaries use a temp file unless overridden.
func resolveLogPath() string {
	if strings.EqualFold(strings.TrimSpace(os.Getenv("BIBLE_CLI_LOG_DISABLE")), "1") {
		return ""
	}
	if v := strings.TrimSpace(os.Getenv("BIBLE_CLI_LOG_FILE")); v != "" {
		return v
	}
	if flag.Lookup("test.v") != nil {
		return filepath.Join(os.TempDir(), fmt.Sprintf("bible-cli-go-test-%d.log", os.Getpid()))
	}
	home, err := os.UserHomeDir()
	if err != nil || strings.TrimSpace(home) == "" {
		return ""
	}
	return filepath.Join(home, ".bible", "cli.log")
}

// log writes a structured entry to the log file.  If the logger is not
// initialised the call is silently ignored.
func log(level Level, event string, fields map[string]any) {
	if globalLogger == nil {
		return
	}
	e := entry{
		Timestamp: time.Now().UTC().Format(time.RFC3339Nano),
		Level:     level,
		Event:     event,
		Fields:    fields,
	}
	globalLogger.mu.Lock()
	defer globalLogger.mu.Unlock()
	// Ignore write errors - logging must never crash the CLI.
	_ = globalLogger.enc.Encode(e)
}

// Debug writes a DEBUG-level log entry.
func Debug(event string, fields map[string]any) { log(LevelDebug, event, fields) }

// Info writes an INFO-level log entry.
func Info(event string, fields map[string]any) { log(LevelInfo, event, fields) }

// Error writes an ERROR-level log entry.
func Error(event string, fields map[string]any) { log(LevelError, event, fields) }

// Invoke logs the start of a CLI invocation with its full argument list and
// returns the start time so the caller can measure elapsed time.
func Invoke(args []string) time.Time {
	start := time.Now()
	fields := map[string]any{
		"summary": summarizeInvocation(args),
		"argc":    len(args),
		"args":    args,
	}
	if len(args) > 0 {
		fields["argv0"] = args[0]
	}
	if len(args) > 1 {
		fields["argv1"] = args[1]
	}
	Debug("cli.invoke", fields)
	return start
}

const maxSummaryRunes = 280

// summarizeInvocation returns a single-line, human-readable preview for cli.log
// (truncated). Does not redact — callers should avoid putting secrets in argv.
func summarizeInvocation(args []string) string {
	if len(args) == 0 {
		return "(empty)"
	}
	s := strings.Join(args, " ")
	r := []rune(s)
	if len(r) <= maxSummaryRunes {
		return s
	}
	return string(r[:maxSummaryRunes-3]) + "..."
}

// Done logs the successful completion of a CLI invocation.
// When a response payload is available it also records whether the result came
// from the real server or from local stub fallback logic.
func Done(start time.Time, command string, action string, response map[string]any) {
	fields := map[string]any{
		"command":   command,
		"action":    action,
		"elapsedMs": fmt.Sprintf("%.0f", float64(time.Since(start).Microseconds())/1000),
	}
	if response != nil {
		if stub, ok := response["stub"]; ok {
			fields["stub"] = stub
		}
		if mode, ok := response["response_mode"]; ok {
			fields["response_mode"] = mode
		}
		if reason, ok := response["stub_reason"]; ok {
			fields["stub_reason"] = reason
		}
		// Compact summary for ~/.bible/cli.log (stdout still carries full JSON envelope).
		if v, ok := response["total"]; ok {
			fields["data_total"] = v
		}
		if arr, ok := response["results"].([]any); ok {
			fields["data_results_len"] = len(arr)
		}
		if v, ok := response["session_id"]; ok {
			fields["data_session_id"] = v
		}
		if v, ok := response["task_id"]; ok {
			fields["data_task_id"] = v
		}
		if v, ok := response["kb_index"]; ok {
			fields["data_kb_index"] = v
		}
		if v, ok := response["tag"]; ok {
			fields["data_tag"] = v
		}
		if v, ok := response["status"]; ok {
			fields["data_status"] = v
		}
		if arr, ok := response["results"].([]any); ok && len(arr) > 0 {
			if m, ok := arr[0].(map[string]any); ok {
				if sid, ok := m["session_id"].(string); ok && sid != "" {
					fields["first_hit_session_id"] = sid
				}
				if ab, ok := m["abstract"].(string); ok && ab != "" {
					fields["first_hit_abstract_preview"] = truncateRunes(ab, 160)
				}
			}
		}
	}
	Info("cli.done", fields)
}

func truncateRunes(s string, max int) string {
	if max <= 0 {
		return ""
	}
	r := []rune(s)
	if len(r) <= max {
		return s
	}
	if max <= 3 {
		return "..."
	}
	return string(r[:max-3]) + "..."
}

// Failed logs a failed CLI invocation with error code and message.
func Failed(start time.Time, code string, message string) {
	msgOneLine := strings.ReplaceAll(strings.ReplaceAll(message, "\r\n", "\n"), "\n", " | ")
	Error("cli.failed", map[string]any{
		"code":            code,
		"message":         message,
		"message_preview": truncateRunes(msgOneLine, 220),
		"message_len":     len(message),
		"elapsedMs":       fmt.Sprintf("%.0f", float64(time.Since(start).Microseconds())/1000),
	})
}
