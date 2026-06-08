// Package meta provides utilities to construct memory meta.json from message.json.
package meta

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode/utf8"
)

const (
	MaxTitleLen    = 200
	MaxAbstractLen = 500
	MaxOverviewLen = 2000
)

// Meta represents the structure of meta.json for a memory import.
type Meta struct {
	MemoryID      string   `json:"memory_id"`
	SessionID     string   `json:"session_id,omitempty"` // VS Code plugin meta often has this without memory_id
	Title         string   `json:"title"`
	Abstract      string   `json:"abstract"`
	Overview      string   `json:"overview,omitempty"`
	CreatedAt     string   `json:"created_at,omitempty"`
	UpdatedAt     string   `json:"updated_at,omitempty"`
	TaskIDs       []string `json:"task_ids,omitempty"`
	FeatureTags   []string `json:"feature_tags,omitempty"`
	DomainTags    []string `json:"domain_tags,omitempty"`
	ComponentTags []string `json:"component_tags,omitempty"`
	SourceClient  string   `json:"source_client,omitempty"`
	Language      string   `json:"language,omitempty"`
}

// BuildOptions controls how meta.json is generated.
type BuildOptions struct {
	// TitleOverride replaces the title derived from messages when set.
	TitleOverride string
	// AbstractOverride replaces the abstract derived from messages when set.
	AbstractOverride string
	// TaskIDs is an optional list of task IDs to embed.
	TaskIDs []string
	// FeatureTags is an optional list of feature tags.
	FeatureTags []string
	// DomainTags is an optional list of domain tags.
	DomainTags []string
	// AbstractTruncate allows truncating the abstract to MaxAbstractLen instead of erroring.
	AbstractTruncate bool
}

// messageJSON represents the top-level structure of message.json.
type messageJSON struct {
	SchemaVersion string          `json:"schema_version"`
	SessionID     string          `json:"session_id"`
	RequestID     string          `json:"requestId"`
	SourceClient  *sourceClient   `json:"sourceClient"`
	Requests      []requestEntry  `json:"requests"`
}

type sourceClient struct {
	Kind      string `json:"kind"`
	SessionID string `json:"sessionId"`
}

type requestEntry struct {
	RequestID string          `json:"requestId"`
	Message   *requestMessage `json:"message"`
	Response  []responseItem  `json:"response"`
	CreatedAt string          `json:"createdAt"`
}

type requestMessage struct {
	Text string `json:"text"`
}

type responseItem struct {
	Kind  string `json:"kind"`
	Value string `json:"value"`
}

// BuildMetaFromMessageJSON reads message.json from msgPath and produces a Meta struct.
// sessionDir is used to compute a fallback memory_id when session_id is absent.
func BuildMetaFromMessageJSON(msgPath string, sessionDir string, opts BuildOptions) (*Meta, error) {
	data, err := os.ReadFile(msgPath)
	if err != nil {
		return nil, fmt.Errorf("cannot read message.json: %w", err)
	}

	var msg messageJSON
	if err := json.Unmarshal(data, &msg); err != nil {
		return nil, fmt.Errorf("invalid message.json: %w", err)
	}

	sessionID := extractSessionID(msg)

	// Derive memory_id from session_id or fallback to directory name.
	memoryID := ""
	if sessionID != "" {
		memoryID = "mem_" + sessionID
	} else {
		memoryID = "mem_" + filepath.Base(sessionDir)
	}

	// Determine title.
	title := opts.TitleOverride
	if title == "" {
		title = firstUserText(msg.Requests)
		if title == "" {
			title = filepath.Base(sessionDir)
		}
		title = truncate(title, MaxTitleLen)
	}

	// Determine abstract.
	abstract := opts.AbstractOverride
	if abstract == "" {
		abstract = firstUserText(msg.Requests)
		if abstract == "" {
			abstract = "[空会话]"
		}
		if utf8.RuneCountInString(abstract) > MaxAbstractLen {
			if opts.AbstractTruncate {
				abstract = truncate(abstract, MaxAbstractLen)
			}
		}
	}

	// Timestamps.
	createdAt := firstRequestTime(msg.Requests)
	if createdAt == "" {
		if stat, err := os.Stat(msgPath); err == nil {
			createdAt = stat.ModTime().UTC().Format(time.RFC3339)
		}
	}
	updatedAt := time.Now().UTC().Format(time.RFC3339)

	// Source client.
	sourceClientKind := ""
	if msg.SourceClient != nil {
		sourceClientKind = msg.SourceClient.Kind
	}

	return &Meta{
		MemoryID:      memoryID,
		Title:         title,
		Abstract:      abstract,
		CreatedAt:     createdAt,
		UpdatedAt:     updatedAt,
		TaskIDs:       opts.TaskIDs,
		FeatureTags:   opts.FeatureTags,
		DomainTags:    opts.DomainTags,
		SourceClient:  sourceClientKind,
		Language:      "zh",
	}, nil
}

// WriteMetaJSON serialises meta to <sessionDir>/meta.json (0644).
func WriteMetaJSON(sessionDir string, meta *Meta) error {
	data, err := json.MarshalIndent(meta, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to encode meta.json: %w", err)
	}
	return os.WriteFile(filepath.Join(sessionDir, "meta.json"), data, 0o644)
}

// LoadMetaJSON reads and parses <sessionDir>/meta.json.
func LoadMetaJSON(sessionDir string) (*Meta, error) {
	data, err := os.ReadFile(filepath.Join(sessionDir, "meta.json"))
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, fmt.Errorf("cannot read meta.json: %w", err)
	}
	var m Meta
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, fmt.Errorf("invalid meta.json: %w", err)
	}
	return &m, nil
}

// PatchPluginMetaJSONForUpload adds memory_id and/or title to meta.json on disk when
// missing (VS Code plugin MemoryMeta shape). The file is read and written as a
// generic JSON object so keys not present on Meta (e.g. primary_request_intent)
// are preserved for the multipart upload.
func PatchPluginMetaJSONForUpload(sessionDir string, rawMessageJSON []byte) (bool, error) {
	path := filepath.Join(sessionDir, "meta.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return false, err
	}
	var root map[string]any
	if err := json.Unmarshal(data, &root); err != nil {
		return false, fmt.Errorf("invalid meta.json: %w", err)
	}
	getStr := func(key string) string {
		v, ok := root[key].(string)
		if !ok {
			return ""
		}
		return strings.TrimSpace(v)
	}
	changed := false
	sid := getStr("session_id")
	if sid == "" && len(rawMessageJSON) > 0 {
		var probe struct {
			SessionID string `json:"session_id"`
		}
		_ = json.Unmarshal(rawMessageJSON, &probe)
		sid = strings.TrimSpace(probe.SessionID)
	}
	if getStr("memory_id") == "" {
		if sid != "" {
			root["memory_id"] = "mem_" + sid
		} else {
			root["memory_id"] = "mem_" + filepath.Base(sessionDir)
		}
		changed = true
	}
	if getStr("title") == "" {
		ab := getStr("abstract")
		if ab != "" {
			root["title"] = truncate(ab, MaxTitleLen)
		} else if sid != "" {
			root["title"] = truncate(sid, MaxTitleLen)
		} else {
			root["title"] = truncate(filepath.Base(sessionDir), MaxTitleLen)
		}
		changed = true
	}
	if !changed {
		return false, nil
	}
	out, err := json.MarshalIndent(root, "", "  ")
	if err != nil {
		return false, err
	}
	return true, os.WriteFile(path, out, 0o644)
}

// SessionMessages is a simplified input structure for session save.
type SessionMessages struct {
	Title    string    `json:"title"`
	Messages []Message `json:"messages"`
}

// Message represents a single chat message.
type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// BuildMessageJSONFromMessages converts a list of chat messages to the message.json format.
func BuildMessageJSONFromMessages(sessionID string, msgs []Message) ([]byte, error) {
	requests := make([]map[string]any, 0)
	// Pair user+assistant messages into request entries.
	for i := 0; i < len(msgs); i++ {
		m := msgs[i]
		if strings.ToLower(m.Role) == "user" {
			req := map[string]any{
				"requestId": fmt.Sprintf("req_%d", i),
				"message": map[string]any{
					"text": m.Content,
					"parts": []map[string]any{
						{"kind": "text", "text": m.Content},
					},
				},
				"response":  []any{},
				"createdAt": time.Now().UTC().Format(time.RFC3339),
			}
			// Look for the next assistant message.
			if i+1 < len(msgs) && strings.ToLower(msgs[i+1].Role) == "assistant" {
				i++
				req["response"] = []map[string]any{
					{"kind": "textPart", "value": msgs[i].Content},
				}
			}
			requests = append(requests, req)
		}
	}

	// "bible_cli" 是协议层的来源工具标识符（对应服务端 source_client 字段），
	// 与实现语言无关，Python CLI 和 Go CLI 均使用此标识以保持历史数据连续性。
	// 不应随目录重命名而修改，否则会导致 OpenSearch 中新旧 memory 的 source_client 分裂。
	doc := map[string]any{
		"schema_version": "1.0",
		"session_id":     sessionID,
		"sourceClient":   map[string]any{"kind": "bible_cli"},
		"requests":       requests,
	}
	return json.MarshalIndent(doc, "", "  ")
}

// extractSessionID looks for session_id in common locations within message.json.
func extractSessionID(msg messageJSON) string {
	if msg.SessionID != "" {
		return msg.SessionID
	}
	if msg.RequestID != "" {
		return msg.RequestID
	}
	if msg.SourceClient != nil && msg.SourceClient.SessionID != "" {
		return msg.SourceClient.SessionID
	}
	return ""
}

// firstUserText returns the text of the first user message across all requests.
func firstUserText(requests []requestEntry) string {
	for _, req := range requests {
		if req.Message != nil && strings.TrimSpace(req.Message.Text) != "" {
			return strings.TrimSpace(req.Message.Text)
		}
	}
	return ""
}

// firstRequestTime returns the createdAt timestamp of the first request.
func firstRequestTime(requests []requestEntry) string {
	for _, req := range requests {
		if req.CreatedAt != "" {
			return req.CreatedAt
		}
	}
	return ""
}

// truncate cuts s to at most maxChars runes, appending "..." if truncated.
func truncate(s string, maxChars int) string {
	runes := []rune(s)
	if len(runes) <= maxChars {
		return s
	}
	if maxChars <= 3 {
		return string(runes[:maxChars])
	}
	return string(runes[:maxChars-3]) + "..."
}
