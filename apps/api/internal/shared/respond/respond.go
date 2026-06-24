package respond

import (
	"encoding/json"
	"net/http"
)

type errorBody struct {
	Error   string `json:"error"`
	Code    int    `json:"code"`
}

func JSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func BadRequest(w http.ResponseWriter, msg string) {
	JSON(w, http.StatusBadRequest, errorBody{Error: msg, Code: http.StatusBadRequest})
}

func Unauthorized(w http.ResponseWriter, msg string) {
	JSON(w, http.StatusUnauthorized, errorBody{Error: msg, Code: http.StatusUnauthorized})
}

func Forbidden(w http.ResponseWriter, msg string) {
	JSON(w, http.StatusForbidden, errorBody{Error: msg, Code: http.StatusForbidden})
}

func NotFound(w http.ResponseWriter, msg string) {
	JSON(w, http.StatusNotFound, errorBody{Error: msg, Code: http.StatusNotFound})
}

func InternalError(w http.ResponseWriter, msg string) {
	JSON(w, http.StatusInternalServerError, errorBody{Error: msg, Code: http.StatusInternalServerError})
}

func Conflict(w http.ResponseWriter, msg string) {
	JSON(w, http.StatusConflict, errorBody{Error: msg, Code: http.StatusConflict})
}

func UnprocessableEntity(w http.ResponseWriter, msg string) {
	JSON(w, http.StatusUnprocessableEntity, errorBody{Error: msg, Code: http.StatusUnprocessableEntity})
}
