package http

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	nethttp "net/http"
	"net/url"
	"strings"
	"time"

	"bible-cli-go/internal/config"
	"bible-cli-go/internal/protocol"
)

type Client struct {
	baseURL string
	client  *nethttp.Client
}

func New(cfg config.ClientConfig) *Client {
	return &Client{
		baseURL: strings.TrimRight(cfg.BaseURL, "/"),
		client: &nethttp.Client{
			Timeout: time.Duration(cfg.TimeoutSeconds) * time.Second,
		},
	}
}

func (c *Client) Health() (map[string]any, error) {
	return c.Status()
}

func (c *Client) Status() (map[string]any, error) {
	payload, err := c.getEnvelopeOrPlain("/api/v1/system/status", "/health")
	if err != nil {
		return nil, err
	}
	return payload, nil
}

func (c *Client) Info() (map[string]any, error) {
	payload, err := c.getEnvelopeOrPlain("/api/v1/system/info", "/info")
	if err != nil {
		return nil, err
	}
	return payload, nil
}

func (c *Client) KnowledgeList() (map[string]any, error) {
	payload, err := c.getEnvelope("/api/v1/knowledge/list")
	if err != nil {
		return nil, err
	}
	return payload, nil
}

func (c *Client) KnowledgeSearch(query string) (map[string]any, error) {
	endpoint := "/api/v1/knowledge/search"
	if strings.TrimSpace(query) != "" {
		endpoint = endpoint + "?" + url.Values{"query": []string{query}}.Encode()
	}
	payload, err := c.getEnvelope(endpoint)
	if err != nil {
		return nil, err
	}
	return payload, nil
}

func (c *Client) getEnvelope(path string) (map[string]any, error) {
	payload, statusCode, err := c.getJSON(path)
	if err != nil {
		return nil, err
	}

	status, _ := payload["status"].(string)
	if status == "ok" {
		result, exists := payload["result"]
		if !exists {
			return payload, nil
		}
		if resultObject, ok := result.(map[string]any); ok {
			return resultObject, nil
		}
		return map[string]any{"result": result}, nil
	}

	if status == "error" {
		return nil, parseErrorPayload(payload["error"], statusCode)
	}

	return nil, protocol.CLIError{
		Code:     "INTERNAL",
		Message:  "Malformed response envelope.",
		ExitCode: 1,
	}
}

func (c *Client) getEnvelopeOrPlain(primaryPath string, fallbackPath string) (map[string]any, error) {
	payload, err := c.getEnvelope(primaryPath)
	if err == nil {
		return payload, nil
	}

	apiErr, ok := err.(protocol.CLIError)
	if !ok || apiErr.Code != "NOT_FOUND" {
		return nil, err
	}

	fallbackPayload, _, fallbackErr := c.getJSON(fallbackPath)
	if fallbackErr != nil {
		return nil, fallbackErr
	}
	return fallbackPayload, nil
}

func (c *Client) getJSON(path string) (map[string]any, int, error) {
	request, err := nethttp.NewRequest(nethttp.MethodGet, c.baseURL+path, nil)
	if err != nil {
		return nil, 0, protocol.CLIError{Code: "INVALID_ARGS", Message: err.Error(), ExitCode: 1}
	}

	response, err := c.client.Do(request)
	if err != nil {
		var netErr net.Error
		if errors.As(err, &netErr) && netErr.Timeout() {
			return nil, 0, protocol.CLIError{Code: "TIMEOUT", Message: "HTTP request timed out.", ExitCode: 1}
		}
		return nil, 0, protocol.CLIError{Code: "UNAVAILABLE", Message: "HTTP transport error.", ExitCode: 1}
	}
	defer response.Body.Close()

	body, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, response.StatusCode, protocol.CLIError{Code: "INTERNAL", Message: "Failed to read HTTP response body.", ExitCode: 1}
	}

	var payload map[string]any
	if len(body) == 0 {
		payload = map[string]any{}
	} else if err := json.Unmarshal(body, &payload); err != nil {
		return nil, response.StatusCode, protocol.CLIError{Code: "INTERNAL", Message: "Invalid JSON response.", ExitCode: 1}
	}

	if response.StatusCode >= 400 {
		return nil, response.StatusCode, errorFromStatus(response.StatusCode, payload)
	}

	return payload, response.StatusCode, nil
}

func parseErrorPayload(raw any, statusCode int) error {
	errObject, _ := raw.(map[string]any)
	code, _ := errObject["code"].(string)
	message, _ := errObject["message"].(string)
	if strings.TrimSpace(code) == "" {
		code = mapHTTPStatusToCode(statusCode)
	}
	code = normalizeExternalErrorCode(code, statusCode)
	if strings.TrimSpace(message) == "" {
		message = "Unknown server error"
	}

	return protocol.CLIError{
		Code:     code,
		Message:  message,
		ExitCode: 1,
	}
}

func errorFromStatus(statusCode int, payload map[string]any) error {
	if status, _ := payload["status"].(string); status == "error" {
		return parseErrorPayload(payload["error"], statusCode)
	}

	detail := ""
	if detailValue, ok := payload["detail"]; ok {
		detail = fmt.Sprintf("%v", detailValue)
	}
	if strings.TrimSpace(detail) == "" {
		detail = fmt.Sprintf("HTTP request failed with %d.", statusCode)
	}

	return protocol.CLIError{
		Code:     mapHTTPStatusToCode(statusCode),
		Message:  detail,
		ExitCode: 1,
	}
}

func mapHTTPStatusToCode(statusCode int) string {
	switch statusCode {
	case 400:
		return "INVALID_ARGS"
	case 401:
		return "UNAUTHENTICATED"
	case 403:
		return "PERMISSION_DENIED"
	case 404:
		return "NOT_FOUND"
	case 409:
		return "CONFLICT"
	case 412:
		return "FAILED_PRECONDITION"
	case 429:
		return "RESOURCE_EXHAUSTED"
	case 501:
		return "SEV_NOT_IMPLEMENTED"
	case 503:
		return "UNAVAILABLE"
	case 504:
		return "TIMEOUT"
	default:
		return "INTERNAL"
	}
}

func normalizeExternalErrorCode(code string, statusCode int) string {
	normalized := strings.ToUpper(strings.TrimSpace(code))
	if statusCode == nethttp.StatusNotImplemented {
		return "SEV_NOT_IMPLEMENTED"
	}

	switch normalized {
	case "INVALID_ARGUMENT":
		return "INVALID_ARGS"
	case "DEADLINE_EXCEEDED", "TIMEOUT":
		return "TIMEOUT"
	case "NOT_IMPLEMENTED":
		return "SEV_NOT_IMPLEMENTED"
	default:
		return normalized
	}
}
