package comments

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/acmecorp/prospectOS/api/internal/audit"
	"github.com/acmecorp/prospectOS/api/internal/jobs"
	"github.com/acmecorp/prospectOS/api/internal/shared/middleware"
	"github.com/acmecorp/prospectOS/api/internal/shared/respond"
)

type Service struct {
	db       *pgxpool.Pool
	audit    *audit.Service
}

func NewService(db *pgxpool.Pool, audit *audit.Service) *Service {
	return &Service{db: db, audit: audit}
}

type Handler struct {
	svc      *Service
	enqueuer *jobs.Enqueuer
}

func NewHandler(svc *Service, enqueuer *jobs.Enqueuer) *Handler {
	return &Handler{svc: svc, enqueuer: enqueuer}
}

func (h *Handler) List(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	status := r.URL.Query().Get("status")

	query := `
		SELECT cd.id, cd.lead_id, cd.post_id, cd.variants, cd.selected_variant, cd.status,
		       cd.approved_at, cd.posted_at, cd.posted_url, cd.created_at,
		       p.platform, p.url, p.text as post_text
		FROM comment_drafts cd
		LEFT JOIN posts p ON p.id = cd.post_id
		WHERE cd.org_id = $1`
	args := []any{orgID}
	if status != "" {
		query += " AND cd.status = $2"
		args = append(args, status)
	}
	query += " ORDER BY cd.created_at DESC LIMIT 100"

	rows, err := h.svc.db.Query(r.Context(), query, args...)
	if err != nil {
		respond.InternalError(w, "failed to list drafts")
		return
	}
	defer rows.Close()

	type draft struct {
		ID               uuid.UUID  `json:"id"`
		LeadID           uuid.UUID  `json:"lead_id"`
		PostID           *uuid.UUID `json:"post_id"`
		Variants         []byte     `json:"variants"`
		SelectedVariant  []byte     `json:"selected_variant"`
		Status           string     `json:"status"`
		ApprovedAt       *string    `json:"approved_at"`
		PostedAt         *string    `json:"posted_at"`
		PostedURL        *string    `json:"posted_url"`
		CreatedAt        string     `json:"created_at"`
		Platform         *string    `json:"platform"`
		PostURL          *string    `json:"post_url"`
		PostText         *string    `json:"post_text"`
	}

	var items []draft
	for rows.Next() {
		var d draft
		_ = rows.Scan(
			&d.ID, &d.LeadID, &d.PostID, &d.Variants, &d.SelectedVariant, &d.Status,
			&d.ApprovedAt, &d.PostedAt, &d.PostedURL, &d.CreatedAt,
			&d.Platform, &d.PostURL, &d.PostText,
		)
		items = append(items, d)
	}
	if items == nil {
		items = []draft{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) Generate(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	var body struct {
		LeadID uuid.UUID `json:"lead_id"`
		Tone   string    `json:"tone"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		respond.BadRequest(w, "invalid body")
		return
	}
	if body.LeadID == uuid.Nil {
		respond.BadRequest(w, "lead_id required")
		return
	}

	if err := h.enqueuer.EnqueueCommentDraft(r.Context(), body.LeadID, orgID); err != nil {
		respond.InternalError(w, "failed to enqueue comment generation")
		return
	}

	h.svc.audit.Log(r.Context(), orgID, "comment.generate_requested", "lead", body.LeadID, nil, nil)
	respond.JSON(w, http.StatusAccepted, map[string]string{
		"message": "comment generation queued — check approval queue in ~30 seconds",
		"lead_id": body.LeadID.String(),
	})
}

func (h *Handler) Get(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid id")
		return
	}
	var draft struct {
		ID       uuid.UUID `json:"id"`
		LeadID   uuid.UUID `json:"lead_id"`
		Variants []byte    `json:"variants"`
		Status   string    `json:"status"`
	}
	err = h.svc.db.QueryRow(r.Context(), `
		SELECT id, lead_id, variants, status
		FROM comment_drafts WHERE id=$1 AND org_id=$2
	`, id, orgID).Scan(&draft.ID, &draft.LeadID, &draft.Variants, &draft.Status)
	if err != nil {
		respond.NotFound(w, "draft not found")
		return
	}
	respond.JSON(w, http.StatusOK, draft)
}

func (h *Handler) Update(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	var body struct {
		SelectedVariant map[string]any `json:"selected_variant"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	b, _ := json.Marshal(body.SelectedVariant)
	_, _ = h.svc.db.Exec(r.Context(), `
		UPDATE comment_drafts SET selected_variant=$1, updated_at=NOW() WHERE id=$2 AND org_id=$3
	`, b, id, orgID)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "updated"})
}

func (h *Handler) Approve(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	userID, _ := middleware.GetUserID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))

	var body struct {
		SelectedText string `json:"selected_text"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)

	selectedJSON, _ := json.Marshal(map[string]string{"text": body.SelectedText})
	_, err := h.svc.db.Exec(r.Context(), `
		UPDATE comment_drafts SET
			status = 'approved',
			selected_variant = $1,
			approved_by = $2,
			approved_at = NOW(),
			updated_at = NOW()
		WHERE id = $3 AND org_id = $4 AND status = 'pending_approval'
	`, selectedJSON, userID, id, orgID)
	if err != nil {
		respond.InternalError(w, "failed to approve")
		return
	}
	_, _ = h.svc.db.Exec(r.Context(), `
		UPDATE approvals SET status='approved', decided_by=$1, decision_at=NOW() WHERE ref_id=$2
	`, userID, id)
	_ = h.enqueuer.EnqueueCommentPost(r.Context(), id, orgID)
	h.svc.audit.Log(r.Context(), orgID, "comment.approved", "comment_draft", id, nil, nil)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "approved — ready to post"})
}

func (h *Handler) Reject(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	userID, _ := middleware.GetUserID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))

	var body struct {
		Reason string `json:"reason"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)

	_, _ = h.svc.db.Exec(r.Context(), `
		UPDATE comment_drafts SET
			status = 'rejected', rejection_reason = $1,
			approved_by = $2, approved_at = NOW(), updated_at = NOW()
		WHERE id = $3 AND org_id = $4
	`, body.Reason, userID, id, orgID)
	_, _ = h.svc.db.Exec(r.Context(), `
		UPDATE approvals SET status='rejected', decided_by=$1, decision_at=NOW(), decision_notes=$2 WHERE ref_id=$3
	`, userID, body.Reason, id)
	h.svc.audit.Log(r.Context(), orgID, "comment.rejected", "comment_draft", id, nil, nil)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "rejected"})
}

func (h *Handler) MarkPosted(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	var body struct {
		PostedURL string `json:"posted_url"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	_, _ = h.svc.db.Exec(r.Context(), `
		UPDATE comment_drafts SET status='posted', posted_at=NOW(), posted_url=$1, updated_at=NOW()
		WHERE id=$2 AND org_id=$3
	`, body.PostedURL, id, orgID)
	_, _ = h.svc.db.Exec(r.Context(), `
		UPDATE leads SET pipeline_stage='Comment Posted', updated_at=NOW()
		WHERE id = (SELECT lead_id FROM comment_drafts WHERE id=$1)
	`, id)
	h.svc.audit.Log(r.Context(), orgID, "comment.posted", "comment_draft", id, nil, nil)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "marked as posted"})
}
