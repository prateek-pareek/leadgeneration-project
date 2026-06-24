package tasks

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/acmecorp/prospectOS/api/internal/shared/middleware"
	"github.com/acmecorp/prospectOS/api/internal/shared/respond"
)

type Handler struct{ db *pgxpool.Pool }

func NewHandler(db *pgxpool.Pool) *Handler { return &Handler{db: db} }

func (h *Handler) List(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	status := r.URL.Query().Get("status")
	if status == "" {
		status = "open"
	}
	rows, err := h.db.Query(r.Context(), `
		SELECT id, lead_id, assigned_to, title, description, due_at, priority, status, created_at
		FROM tasks WHERE org_id=$1 AND status=$2
		ORDER BY due_at ASC NULLS LAST, created_at DESC LIMIT 100
	`, orgID, status)
	if err != nil {
		respond.InternalError(w, "failed to list tasks")
		return
	}
	defer rows.Close()
	type task struct {
		ID          uuid.UUID  `json:"id"`
		LeadID      *uuid.UUID `json:"lead_id"`
		AssignedTo  *uuid.UUID `json:"assigned_to"`
		Title       string     `json:"title"`
		Description *string    `json:"description"`
		DueAt       *string    `json:"due_at"`
		Priority    string     `json:"priority"`
		Status      string     `json:"status"`
		CreatedAt   string     `json:"created_at"`
	}
	var items []task
	for rows.Next() {
		var t task
		_ = rows.Scan(&t.ID, &t.LeadID, &t.AssignedTo, &t.Title, &t.Description, &t.DueAt, &t.Priority, &t.Status, &t.CreatedAt)
		items = append(items, t)
	}
	if items == nil {
		items = []task{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) Create(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	var body struct {
		LeadID      *uuid.UUID `json:"lead_id"`
		AssignedTo  *uuid.UUID `json:"assigned_to"`
		Title       string     `json:"title"`
		Description string     `json:"description"`
		DueAt       *time.Time `json:"due_at"`
		Priority    string     `json:"priority"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Title == "" {
		respond.BadRequest(w, "title required")
		return
	}
	if body.Priority == "" {
		body.Priority = "medium"
	}
	var id uuid.UUID
	_ = h.db.QueryRow(r.Context(), `
		INSERT INTO tasks (org_id, lead_id, assigned_to, title, description, due_at, priority)
		VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id
	`, orgID, body.LeadID, body.AssignedTo, body.Title, body.Description, body.DueAt, body.Priority).Scan(&id)
	respond.JSON(w, http.StatusCreated, map[string]any{"id": id})
}

func (h *Handler) Get(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	var t struct {
		ID       uuid.UUID `json:"id"`
		Title    string    `json:"title"`
		Status   string    `json:"status"`
		Priority string    `json:"priority"`
	}
	_ = h.db.QueryRow(r.Context(), `
		SELECT id, title, status, priority FROM tasks WHERE id=$1 AND org_id=$2
	`, id, orgID).Scan(&t.ID, &t.Title, &t.Status, &t.Priority)
	respond.JSON(w, http.StatusOK, t)
}

func (h *Handler) Update(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	var body struct {
		Status   *string `json:"status"`
		Priority *string `json:"priority"`
		Title    *string `json:"title"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	completedAt := ""
	if body.Status != nil && *body.Status == "done" {
		completedAt = "NOW()"
	}
	_ = completedAt
	_, _ = h.db.Exec(r.Context(), `
		UPDATE tasks SET
			status = COALESCE($1, status),
			priority = COALESCE($2, priority),
			title = COALESCE($3, title),
			updated_at = NOW()
		WHERE id=$4 AND org_id=$5
	`, body.Status, body.Priority, body.Title, id, orgID)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "updated"})
}

func (h *Handler) Delete(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	_, _ = h.db.Exec(r.Context(), `DELETE FROM tasks WHERE id=$1 AND org_id=$2`, id, orgID)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "deleted"})
}
