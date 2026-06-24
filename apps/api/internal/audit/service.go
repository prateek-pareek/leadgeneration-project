package audit

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/acmecorp/prospectOS/api/internal/shared/middleware"
	"github.com/acmecorp/prospectOS/api/internal/shared/respond"
)

type Service struct {
	db *pgxpool.Pool
}

func NewService(db *pgxpool.Pool) *Service {
	return &Service{db: db}
}

func (s *Service) Log(ctx context.Context, orgID uuid.UUID, action, resourceType string, resourceID uuid.UUID, before, after any) {
	userID, _ := middleware.GetUserID(ctx)

	beforeJSON, _ := json.Marshal(before)
	afterJSON, _ := json.Marshal(after)

	_, err := s.db.Exec(ctx, `
		INSERT INTO audit_events (org_id, user_id, action, resource_type, resource_id, before_state, after_state)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
	`, orgID, userID, action, resourceType, resourceID, beforeJSON, afterJSON)
	if err != nil {
		slog.Error("audit log failed", "action", action, "err", err)
	}
}

func (s *Service) ListHandler(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}

	rows, err := s.db.Query(r.Context(), `
		SELECT id, user_id, action, resource_type, resource_id, created_at
		FROM audit_events
		WHERE org_id = $1
		ORDER BY created_at DESC
		LIMIT 100
	`, orgID)
	if err != nil {
		respond.InternalError(w, "failed to fetch audit log")
		return
	}
	defer rows.Close()

	type event struct {
		ID           uuid.UUID  `json:"id"`
		UserID       *uuid.UUID `json:"user_id"`
		Action       string     `json:"action"`
		ResourceType *string    `json:"resource_type"`
		ResourceID   *uuid.UUID `json:"resource_id"`
		CreatedAt    string     `json:"created_at"`
	}

	var events []event
	for rows.Next() {
		var e event
		_ = rows.Scan(&e.ID, &e.UserID, &e.Action, &e.ResourceType, &e.ResourceID, &e.CreatedAt)
		events = append(events, e)
	}
	if events == nil {
		events = []event{}
	}

	respond.JSON(w, http.StatusOK, events)
}
