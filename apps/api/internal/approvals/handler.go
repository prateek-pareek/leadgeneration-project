package approvals

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
	db    *pgxpool.Pool
	audit *audit.Service
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
	if status == "" {
		status = "pending"
	}
	aType := r.URL.Query().Get("type")

	query := `
		SELECT a.id, a.type, a.ref_id, a.lead_id, a.status, a.created_at,
		       l_author.display_name, l_author.handle, l_author.platform as author_platform,
		       p.text, p.url, p.platform as post_platform, p.posted_at,
		       ls.score, ls.bucket,
		       cd.variants, cd.selected_variant, cd.status as draft_status
		FROM approvals a
		LEFT JOIN leads l ON l.id = a.lead_id
		LEFT JOIN authors l_author ON l_author.id = l.author_id
		LEFT JOIN posts p ON p.id = l.post_id
		LEFT JOIN comment_drafts cd ON cd.id = a.ref_id AND a.type = 'comment_draft'
		LEFT JOIN LATERAL (
			SELECT score, bucket FROM lead_scores
			WHERE lead_id = l.id ORDER BY scored_at DESC LIMIT 1
		) ls ON true
		WHERE a.org_id = $1 AND a.status = $2`
	args := []any{orgID, status}
	if aType != "" {
		query += " AND a.type = $3"
		args = append(args, aType)
	}
	query += " ORDER BY a.created_at DESC LIMIT 50"

	rows, err := h.svc.db.Query(r.Context(), query, args...)
	if err != nil {
		respond.InternalError(w, "failed to list approvals")
		return
	}
	defer rows.Close()

	var items []map[string]any
	for rows.Next() {
		var (
			id, aTypeVal, aStatus, createdAt string
			refID                            uuid.UUID
			leadID                           *uuid.UUID
			authorName, authorHandle         *string
			authorPlatform                   *string
			postText, postURL                *string
			postPlatform                     *string
			postedAt                         *string
			score                            *int
			bucket                           *string
			variants, selectedVariant        []byte
			draftStatus                      *string
		)
		_ = rows.Scan(
			&id, &aTypeVal, &refID, &leadID, &aStatus, &createdAt,
			&authorName, &authorHandle, &authorPlatform,
			&postText, &postURL, &postPlatform, &postedAt,
			&score, &bucket,
			&variants, &selectedVariant, &draftStatus,
		)

		item := map[string]any{
			"id":        id,
			"type":      aTypeVal,
			"refId":     refID.String(),
			"leadId":    nil,
			"status":    aStatus,
			"createdAt": createdAt,
		}
		if leadID != nil {
			item["leadId"] = leadID.String()
		}

		lead := map[string]any{}
		if authorName != nil || authorHandle != nil {
			lead["author"] = map[string]any{
				"displayName": authorName,
				"handle":      authorHandle,
				"platform":    authorPlatform,
			}
		}
		if postText != nil || postURL != nil {
			lead["post"] = map[string]any{
				"text":     postText,
				"url":      postURL,
				"platform": postPlatform,
				"postedAt": postedAt,
			}
		}
		if score != nil {
			lead["latestScore"] = map[string]any{
				"score":  *score,
				"bucket": bucket,
			}
		}
		if len(lead) > 0 {
			item["lead"] = lead
		}

		if aTypeVal == "comment_draft" && len(variants) > 0 {
			var parsed []any
			_ = json.Unmarshal(variants, &parsed)
			item["commentDraft"] = map[string]any{
				"id":       refID.String(),
				"variants": parsed,
				"status":   draftStatus,
			}
		}

		items = append(items, item)
	}
	if items == nil {
		items = []map[string]any{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) Count(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	var count int
	_ = h.svc.db.QueryRow(r.Context(), `
		SELECT COUNT(*) FROM approvals WHERE org_id=$1 AND status='pending'
	`, orgID).Scan(&count)
	respond.JSON(w, http.StatusOK, map[string]int{"pending": count, "count": count})
}

func (h *Handler) Get(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	var a struct {
		ID     uuid.UUID `json:"id"`
		Type   string    `json:"type"`
		Status string    `json:"status"`
	}
	err := h.svc.db.QueryRow(r.Context(), `
		SELECT id, type, status FROM approvals WHERE id=$1 AND org_id=$2
	`, id, orgID).Scan(&a.ID, &a.Type, &a.Status)
	if err != nil {
		respond.NotFound(w, "approval not found")
		return
	}
	respond.JSON(w, http.StatusOK, a)
}

func (h *Handler) Approve(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	userID, _ := middleware.GetUserID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))

	var body struct {
		SelectedText string `json:"selected_text"`
		Notes        string `json:"notes"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)

	var refID uuid.UUID
	var aType string
	err := h.svc.db.QueryRow(r.Context(), `
		UPDATE approvals SET status='approved', decided_by=$1, decision_at=NOW(), decision_notes=$2
		WHERE id=$3 AND org_id=$4 AND status='pending'
		RETURNING ref_id, type
	`, userID, body.Notes, id, orgID).Scan(&refID, &aType)
	if err != nil {
		respond.InternalError(w, "failed to approve")
		return
	}

	if aType == "comment_draft" {
		selected, _ := json.Marshal(map[string]string{"text": body.SelectedText})
		_, _ = h.svc.db.Exec(r.Context(), `
			UPDATE comment_drafts SET status='approved', selected_variant=$1, approved_by=$2, approved_at=NOW()
			WHERE id=$3
		`, selected, userID, refID)
		_ = h.enqueuer.EnqueueCommentPost(r.Context(), refID, orgID)
	} else if aType == "outreach_draft" {
		_, _ = h.svc.db.Exec(r.Context(), `
			UPDATE outreach_drafts SET status='approved', approved_by=$1, approved_at=NOW() WHERE id=$2
		`, userID, refID)
	}

	h.svc.audit.Log(r.Context(), orgID, "approval.approved", "approval", id, nil, map[string]string{"type": aType})
	respond.JSON(w, http.StatusOK, map[string]string{
		"message": "approved — comment queued for posting assist",
	})
}

func (h *Handler) Reject(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	userID, _ := middleware.GetUserID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))

	var body struct {
		Reason string `json:"reason"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)

	var refID uuid.UUID
	var aType string
	err := h.svc.db.QueryRow(r.Context(), `
		UPDATE approvals SET status='rejected', decided_by=$1, decision_at=NOW(), decision_notes=$2
		WHERE id=$3 AND org_id=$4 AND status='pending'
		RETURNING ref_id, type
	`, userID, body.Reason, id, orgID).Scan(&refID, &aType)
	if err != nil {
		respond.InternalError(w, "failed to reject")
		return
	}

	if aType == "comment_draft" {
		_, _ = h.svc.db.Exec(r.Context(), `
			UPDATE comment_drafts SET status='rejected', rejection_reason=$1 WHERE id=$2
		`, body.Reason, refID)
	}

	h.svc.audit.Log(r.Context(), orgID, "approval.rejected", "approval", id, nil, nil)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "rejected"})
}
