package sources

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/acmecorp/prospectOS/api/internal/jobs"
	"github.com/acmecorp/prospectOS/api/internal/shared/middleware"
	"github.com/acmecorp/prospectOS/api/internal/shared/respond"
)

type Service struct {
	db       *pgxpool.Pool
	enqueuer *jobs.Enqueuer
}

func NewService(db *pgxpool.Pool, enqueuer *jobs.Enqueuer) *Service {
	return &Service{db: db, enqueuer: enqueuer}
}

type Handler struct{ svc *Service }

func NewHandler(svc *Service) *Handler { return &Handler{svc: svc} }

func (h *Handler) List(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	rows, err := h.svc.db.Query(r.Context(), `
		SELECT id, name, type, config, is_active, last_run_at, next_run_at,
		       created_at, posts_found, last_error
		FROM sources WHERE org_id = $1 ORDER BY created_at DESC
	`, orgID)
	if err != nil {
		respond.InternalError(w, "failed to list sources")
		return
	}
	defer rows.Close()
	var items []map[string]any
	for rows.Next() {
		var s struct {
			ID         uuid.UUID `json:"id"`
			Name       string    `json:"name"`
			Type       string    `json:"type"`
			Config     []byte    `json:"config"`
			IsActive   bool      `json:"is_active"`
			LastRunAt  *string   `json:"last_run_at"`
			NextRunAt  *string   `json:"next_run_at"`
			CreatedAt  string    `json:"created_at"`
			PostsFound *int      `json:"posts_found"`
			LastError  *string   `json:"last_error"`
		}
		_ = rows.Scan(
			&s.ID, &s.Name, &s.Type, &s.Config, &s.IsActive,
			&s.LastRunAt, &s.NextRunAt, &s.CreatedAt, &s.PostsFound, &s.LastError,
		)
		status := "active"
		if !s.IsActive {
			status = "paused"
		}
		if s.LastError != nil && *s.LastError != "" {
			status = "error"
		}
		var config any
		if len(s.Config) > 0 {
			_ = json.Unmarshal(s.Config, &config)
		}
		items = append(items, map[string]any{
			"id": s.ID, "name": s.Name, "type": s.Type, "config": config,
			"status": status, "is_active": s.IsActive,
			"last_run_at": s.LastRunAt, "lastRunAt": s.LastRunAt,
			"next_run_at": s.NextRunAt, "created_at": s.CreatedAt,
			"posts_found": s.PostsFound, "postsFound": s.PostsFound,
			"last_error": s.LastError, "lastError": s.LastError,
		})
	}
	if items == nil {
		items = []map[string]any{}
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
		Name   string         `json:"name"`
		Type   string         `json:"type"`
		Config map[string]any `json:"config"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		respond.BadRequest(w, "invalid body")
		return
	}
	if body.Name == "" || body.Type == "" {
		respond.BadRequest(w, "name and type required")
		return
	}
	allowed := map[string]bool{
		"hackernews": true, "reddit": true, "linkedin": true, "threads": true,
		"twitter": true, "x": true, "producthunt": true, "devto": true,
		"google_places": true, "job_portals": true, "freelance_marketplaces": true,
		"github": true, "indiehackers": true, "manual": true,
	}
	if !allowed[body.Type] {
		respond.BadRequest(w, "unsupported source type")
		return
	}
	configJSON, _ := json.Marshal(body.Config)
	var id uuid.UUID
	err := h.svc.db.QueryRow(r.Context(), `
		INSERT INTO sources (org_id, name, type, config) VALUES ($1,$2,$3,$4) RETURNING id
	`, orgID, body.Name, body.Type, configJSON).Scan(&id)
	if err != nil {
		respond.InternalError(w, "failed to create source")
		return
	}
	respond.JSON(w, http.StatusCreated, map[string]any{"id": id, "name": body.Name, "type": body.Type})
}

func (h *Handler) Get(w http.ResponseWriter, r *http.Request) {
	respond.JSON(w, http.StatusOK, map[string]string{"id": chi.URLParam(r, "id")})
}

func (h *Handler) Update(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	var body struct {
		Name     *string `json:"name"`
		IsActive *bool   `json:"is_active"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	_, _ = h.svc.db.Exec(r.Context(), `
		UPDATE sources SET
			name = COALESCE($1, name),
			is_active = COALESCE($2, is_active),
			updated_at = NOW()
		WHERE id = $3 AND org_id = $4
	`, body.Name, body.IsActive, id, orgID)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "updated"})
}

func (h *Handler) Delete(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	_, _ = h.svc.db.Exec(r.Context(), `DELETE FROM sources WHERE id = $1 AND org_id = $2`, id, orgID)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "deleted"})
}

func (h *Handler) Run(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid source id")
		return
	}
	_ = h.svc.enqueuer.EnqueueSourceScan(r.Context(), id, orgID)
	respond.JSON(w, http.StatusAccepted, map[string]string{"message": "scan enqueued"})
}
