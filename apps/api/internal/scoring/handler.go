package scoring

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

type Handler struct {
	db       *pgxpool.Pool
	enqueuer *jobs.Enqueuer
}

func NewHandler(db *pgxpool.Pool, enqueuer *jobs.Enqueuer) *Handler {
	return &Handler{db: db, enqueuer: enqueuer}
}

func (h *Handler) Trigger(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	var body struct {
		LeadID uuid.UUID `json:"lead_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		respond.BadRequest(w, "invalid body")
		return
	}
	_ = h.enqueuer.EnqueueScoring(r.Context(), body.LeadID, orgID)
	respond.JSON(w, http.StatusAccepted, map[string]string{"message": "scoring enqueued"})
}

func (h *Handler) List(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	rows, err := h.db.Query(r.Context(), `
		SELECT DISTINCT ON (lead_id) id, lead_id, score, bucket, top_signals, explanation, scored_at
		FROM lead_scores WHERE org_id=$1
		ORDER BY lead_id, scored_at DESC
		LIMIT 200
	`, orgID)
	if err != nil {
		respond.InternalError(w, "query failed")
		return
	}
	defer rows.Close()
	var items []map[string]any
	for rows.Next() {
		var id, leadID uuid.UUID
		var score int
		var bucket, explanation, scoredAt string
		var signals []string
		_ = rows.Scan(&id, &leadID, &score, &bucket, &signals, &explanation, &scoredAt)
		items = append(items, map[string]any{
			"id": id, "lead_id": leadID, "score": score, "bucket": bucket,
			"top_signals": signals, "explanation": explanation, "scored_at": scoredAt,
		})
	}
	if items == nil {
		items = []map[string]any{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) Latest(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	leadID, _ := uuid.Parse(chi.URLParam(r, "leadId"))
	var score struct {
		ID          uuid.UUID `json:"id"`
		Score       int       `json:"score"`
		Bucket      string    `json:"bucket"`
		Explanation string    `json:"explanation"`
		TopSignals  []string  `json:"top_signals"`
		ScoredAt    string    `json:"scored_at"`
	}
	err := h.db.QueryRow(r.Context(), `
		SELECT id, score, bucket, explanation, top_signals, scored_at
		FROM lead_scores
		WHERE lead_id=$1 AND org_id=$2
		ORDER BY scored_at DESC LIMIT 1
	`, leadID, orgID).Scan(
		&score.ID, &score.Score, &score.Bucket,
		&score.Explanation, &score.TopSignals, &score.ScoredAt,
	)
	if err != nil {
		respond.NotFound(w, "score not found")
		return
	}
	respond.JSON(w, http.StatusOK, score)
}
