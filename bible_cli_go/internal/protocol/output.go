package protocol

import (
	"encoding/json"
	"io"
)

type Response struct {
	OK    bool       `json:"ok"`
	Data  any        `json:"data,omitempty"`
	Error *ErrorBody `json:"error,omitempty"`
}

type ErrorBody struct {
	Code    string `json:"code"`
	Message string `json:"message"`
}

func PrintSuccess(w io.Writer, data any) error {
	return PrintResponse(w, Response{OK: true, Data: data})
}

func PrintFailure(w io.Writer, code string, message string) error {
	return PrintResponse(w, Response{
		OK: false,
		Error: &ErrorBody{
			Code:    code,
			Message: message,
		},
	})
}

func PrintResponse(w io.Writer, response Response) error {
	return PrintJSON(w, response)
}

func PrintJSON(w io.Writer, payload any) error {
	encoded, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	_, err = w.Write(append(encoded, '\n'))
	return err
}
