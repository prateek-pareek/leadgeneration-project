package posts

import (
	"encoding/json"
	"net/http"
	"strconv"

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

	limit := 50
	if l := r.URL.Query().Get("limit"); l != "" {
		if v, err := strconv.Atoi(l); err == nil && v > 0 && v <= 200 {
			limit = v
		}
	}

	rows, err := h.svc.db.Query(r.Context(), `
		SELECT p.id, p.platform, p.url, p.text, p.title,
		       p.posted_at, p.engagement, p.is_processed, p.discovered_at,
		       a.handle, a.display_name
		FROM posts p
		LEFT JOIN authors a ON a.id = p.author_id
		WHERE p.org_id = $1
		ORDER BY p.discovered_at DESC
		LIMIT $2
	`, orgID, limit)
	if err != nil {
		respond.InternalError(w, "failed to list posts")
		return
	}
	defer rows.Close()

	type postItem struct {
		ID          uuid.UUID  `json:"id"`
		Platform    string     `json:"platform"`
		URL         string     `json:"url"`
		Text        string     `json:"text"`
		Title       *string    `json:"title"`
		PostedAt    *string    `json:"posted_at"`
		Engagement  []byte     `json:"engagement"`
		IsProcessed bool       `json:"is_processed"`
		DiscoveredAt string    `json:"discovered_at"`
		AuthorHandle *string   `json:"author_handle"`
		AuthorName   *string   `json:"author_name"`
	}

	var items []postItem
	for rows.Next() {
		var p postItem
		_ = rows.Scan(
			&p.ID, &p.Platform, &p.URL, &p.Text, &p.Title,
			&p.PostedAt, &p.Engagement, &p.IsProcessed, &p.DiscoveredAt,
			&p.AuthorHandle, &p.AuthorName,
		)
		items = append(items, p)
	}
	if items == nil {
		items = []postItem{}
	}
	respond.JSON(w, http.StatusOK, map[string]any{"data": items, "total": len(items)})
}

func (h *Handler) Get(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid post id")
		return
	}
	var post struct {
		ID       uuid.UUID `json:"id"`
		Platform string    `json:"platform"`
		URL      string    `json:"url"`
		Text     string    `json:"text"`
	}
	err = h.svc.db.QueryRow(r.Context(), `
		SELECT id, platform, url, text FROM posts WHERE id=$1 AND org_id=$2
	`, id, orgID).Scan(&post.ID, &post.Platform, &post.URL, &post.Text)
	if err != nil {
		respond.NotFound(w, "post not found")
		return
	}
	respond.JSON(w, http.StatusOK, post)
}

func (h *Handler) Create(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	var body struct {
		Platform string `json:"platform"`
		URL      string `json:"url"`
		Text     string `json:"text"`
		Title    string `json:"title"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.URL == "" || body.Text == "" {
		respond.BadRequest(w, "url and text required")
		return
	}
	platform := body.Platform
	if platform == "" {
		platform = "manual"
	}

	var id uuid.UUID
	err := h.svc.db.QueryRow(r.Context(), `
		INSERT INTO posts (org_id, platform, url, text, title, external_id)
		VALUES ($1,$2,$3,$4,$5,$6) RETURNING id
	`, orgID, platform, body.URL, body.Text, body.Title, uuid.New().String()).Scan(&id)
	if err != nil {
		respond.InternalError(w, "failed to create post")
		return
	}

	var leadID uuid.UUID
	err = h.svc.db.QueryRow(r.Context(), `
		INSERT INTO leads (org_id, post_id, source)
		VALUES ($1, $2, $3) RETURNING id
	`, orgID, id, platform).Scan(&leadID)
	if err != nil {
		respond.InternalError(w, "failed to create lead from post")
		return
	}
	_, _ = h.svc.db.Exec(r.Context(), `UPDATE posts SET is_processed = true WHERE id = $1`, id)
	_ = h.svc.enqueuer.EnqueueAnalyze(r.Context(), leadID, orgID)

	respond.JSON(w, http.StatusCreated, map[string]any{"id": id, "lead_id": leadID})
}

func (h *Handler) Delete(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	_, _ = h.svc.db.Exec(r.Context(), `DELETE FROM posts WHERE id=$1 AND org_id=$2`, id, orgID)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "deleted"})
}

func (h *Handler) Process(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	postID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid post id")
		return
	}

	// Create a lead from this post and enqueue research
	var leadID uuid.UUID
	err = h.svc.db.QueryRow(r.Context(), `
		INSERT INTO leads (org_id, post_id, source)
		VALUES ($1, $2, 'manual') RETURNING id
	`, orgID, postID).Scan(&leadID)
	if err != nil {
		respond.InternalError(w, "failed to create lead from post")
		return
	}

	_ = h.svc.enqueuer.EnqueueAnalyze(r.Context(), leadID, orgID)
	respond.JSON(w, http.StatusAccepted, map[string]any{"lead_id": leadID, "message": "processing"})
}
