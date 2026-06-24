package middleware

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"
)

type contextKey string

const (
	CorrelationIDKey contextKey = "correlation_id"
	UserIDKey        contextKey = "user_id"
	OrgIDKey         contextKey = "org_id"
	UserRoleKey      contextKey = "user_role"
)

func CorrelationID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.Header.Get("X-Correlation-ID")
		if id == "" {
			id = uuid.New().String()
		}
		ctx := context.WithValue(r.Context(), CorrelationIDKey, id)
		w.Header().Set("X-Correlation-ID", id)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func RequestLogger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rw := &responseWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rw, r)

		corrID, _ := r.Context().Value(CorrelationIDKey).(string)
		slog.Info("request",
			"method", r.Method,
			"path", r.URL.Path,
			"status", rw.status,
			"latency_ms", time.Since(start).Milliseconds(),
			"correlation_id", corrID,
			"ip", r.RemoteAddr,
		)
	})
}

type responseWriter struct {
	http.ResponseWriter
	status int
}

func (rw *responseWriter) WriteHeader(status int) {
	rw.status = status
	rw.ResponseWriter.WriteHeader(status)
}

func GetUserID(ctx context.Context) (uuid.UUID, bool) {
	v, ok := ctx.Value(UserIDKey).(uuid.UUID)
	return v, ok
}

func GetOrgID(ctx context.Context) (uuid.UUID, bool) {
	v, ok := ctx.Value(OrgIDKey).(uuid.UUID)
	return v, ok
}

func GetUserRole(ctx context.Context) (string, bool) {
	v, ok := ctx.Value(UserRoleKey).(string)
	return v, ok
}
