package cache

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
)

const CacheFilename = ".bible-memory-cache.json"

// MemoryCacheEntry is the structure persisted to .bible-memory-cache.json
// after a successful upload. It enables local idempotency checks on the next run.
type MemoryCacheEntry struct {
	MemoryID     string `json:"memory_id"`
	KbIndex      string `json:"kb_index"`
	MetaHash     string `json:"meta_hash"`
	TaskID       string `json:"task_id"`
	UploadStatus string `json:"upload_status"`
	UploadedAt   string `json:"uploaded_at"`
	ServerURL    string `json:"server_url"`
}

// LoadCache reads the cache entry from <sessionDir>/.bible-memory-cache.json.
// Returns (nil, nil) when the file does not exist.
func LoadCache(sessionDir string) (*MemoryCacheEntry, error) {
	path := filepath.Join(sessionDir, CacheFilename)
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var entry MemoryCacheEntry
	if err := json.Unmarshal(data, &entry); err != nil {
		return nil, err
	}
	return &entry, nil
}

// SaveCache writes entry to <sessionDir>/.bible-memory-cache.json (0644).
func SaveCache(sessionDir string, entry MemoryCacheEntry) error {
	data, err := json.MarshalIndent(entry, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(filepath.Join(sessionDir, CacheFilename), data, 0o644)
}

// SHA256File computes the SHA-256 hex digest of the file at path and returns
// it as "sha256:<hex>" (matching the format used in .bible-memory-cache.json).
func SHA256File(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return "sha256:" + hex.EncodeToString(h.Sum(nil)), nil
}
