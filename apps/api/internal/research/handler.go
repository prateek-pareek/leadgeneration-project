package research

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
	_ = h.enqueuer.EnqueueResearch(r.Context(), body.LeadID, orgID)
	respond.JSON(w, http.StatusAccepted, map[string]string{"message": "research enqueued"})
}

func (h *Handler) List(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	rows, err := h.db.Query(r.Context(), `
		SELECT id, lead_id, company_name, company_description, company_stage,
		       founder_confidence, is_decision_maker, budget_signal,
		       service_fit, confidence_overall, created_at
		FROM research_briefs WHERE org_id=$1
		ORDER BY created_at DESC LIMIT 100
	`, orgID)
	if err != nil {
		respond.InternalError(w, "failed to list briefs")
		return
	}
	defer rows.Close()
	var items []map[string]any
	for rows.Next() {
		var id, leadID uuid.UUID
		var companyName, companyDesc, stage, budgetSignal *string
		var founderConf *float64
		var isDecisionMaker *bool
		var serviceFit []string
		var confidence float64
		var createdAt string
		_ = rows.Scan(&id, &leadID, &companyName, &companyDesc, &stage,
			&founderConf, &isDecisionMaker, &budgetSignal,
			&serviceFit, &confidence, &createdAt)
		items = append(items, map[string]any{
			"id": id, "lead_id": leadID, "company_name": companyName,
			"company_stage": stage, "founder_confidence": founderConf,
			"is_decision_maker": isDecisionMaker, "budget_signal": budgetSignal,
			"service_fit": serviceFit, "confidence_overall": confidence,
			"created_at": createdAt,
		})
	}
	if items == nil {
		items = []map[string]any{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) Get(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	var brief struct {
		ID          uuid.UUID `json:"id"`
		LeadID      uuid.UUID `json:"lead_id"`
		BriefText   string    `json:"brief_text"`
		ServiceFit  []string  `json:"service_fit"`
		PainPoints  []string  `json:"pain_points"`
		EngAngle    string    `json:"engagement_angle"`
		Confidence  float64   `json:"confidence_overall"`
		CreatedAt   string    `json:"created_at"`
	}
	err := h.db.QueryRow(r.Context(), `
		SELECT id, lead_id, brief_text, service_fit, pain_points, engagement_angle,
		       confidence_overall, created_at
		FROM research_briefs WHERE id=$1 AND org_id=$2
	`, id, orgID).Scan(
		&brief.ID, &brief.LeadID, &brief.BriefText, &brief.ServiceFit,
		&brief.PainPoints, &brief.EngAngle, &brief.Confidence, &brief.CreatedAt,
	)
	if err != nil {
		respond.NotFound(w, "brief not found")
		return
	}
	respond.JSON(w, http.StatusOK, brief)
}
