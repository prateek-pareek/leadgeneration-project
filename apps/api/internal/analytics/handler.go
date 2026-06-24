package analytics

import (
	"net/http"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/acmecorp/prospectOS/api/internal/shared/middleware"
	"github.com/acmecorp/prospectOS/api/internal/shared/respond"
)

type Handler struct{ db *pgxpool.Pool }

func NewHandler(db *pgxpool.Pool) *Handler { return &Handler{db: db} }

func (h *Handler) Overview(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}

	var leadsTotal, hotLeads, commentsDrafted, commentsPosted int
	var meetingsBooked int

	_ = h.db.QueryRow(r.Context(), `SELECT COUNT(*) FROM leads WHERE org_id=$1 AND deleted_at IS NULL`, orgID).Scan(&leadsTotal)
	_ = h.db.QueryRow(r.Context(), `
		SELECT COUNT(DISTINCT ls.lead_id) FROM lead_scores ls
		JOIN leads l ON l.id = ls.lead_id
		WHERE l.org_id=$1 AND ls.bucket='hot'
		AND ls.scored_at = (SELECT MAX(scored_at) FROM lead_scores WHERE lead_id=ls.lead_id)
	`, orgID).Scan(&hotLeads)
	_ = h.db.QueryRow(r.Context(), `SELECT COUNT(*) FROM comment_drafts WHERE org_id=$1`, orgID).Scan(&commentsDrafted)
	_ = h.db.QueryRow(r.Context(), `SELECT COUNT(*) FROM comment_drafts WHERE org_id=$1 AND status='posted'`, orgID).Scan(&commentsPosted)
	_ = h.db.QueryRow(r.Context(), `
		SELECT COUNT(*) FROM leads WHERE org_id=$1 AND pipeline_stage='Meeting Booked' AND deleted_at IS NULL
	`, orgID).Scan(&meetingsBooked)

	respond.JSON(w, http.StatusOK, map[string]any{
		"leads_discovered":  leadsTotal,
		"hot_leads":         hotLeads,
		"comments_drafted":  commentsDrafted,
		"comments_posted":   commentsPosted,
		"meetings_booked":   meetingsBooked,
	})
}

func (h *Handler) Leads(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	rows, err := h.db.Query(r.Context(), `
		SELECT DATE(created_at) as day, COUNT(*) as count
		FROM leads
		WHERE org_id=$1 AND created_at > NOW() - INTERVAL '30 days' AND deleted_at IS NULL
		GROUP BY day ORDER BY day ASC
	`, orgID)
	if err != nil {
		respond.InternalError(w, "query failed")
		return
	}
	defer rows.Close()
	var data []map[string]any
	for rows.Next() {
		var day string
		var count int
		_ = rows.Scan(&day, &count)
		data = append(data, map[string]any{"day": day, "count": count})
	}
	if data == nil {
		data = []map[string]any{}
	}
	respond.JSON(w, http.StatusOK, data)
}

func (h *Handler) Sources(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	rows, err := h.db.Query(r.Context(), `
		SELECT source, COUNT(*) as count
		FROM leads
		WHERE org_id=$1 AND deleted_at IS NULL
		GROUP BY source ORDER BY count DESC
	`, orgID)
	if err != nil {
		respond.InternalError(w, "query failed")
		return
	}
	defer rows.Close()
	var data []map[string]any
	for rows.Next() {
		var source string
		var count int
		_ = rows.Scan(&source, &count)
		data = append(data, map[string]any{"source": source, "count": count})
	}
	if data == nil {
		data = []map[string]any{}
	}
	respond.JSON(w, http.StatusOK, data)
}

func (h *Handler) Comments(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	var pending, approved, posted, rejected int
	_ = h.db.QueryRow(r.Context(), `SELECT COUNT(*) FROM comment_drafts WHERE org_id=$1 AND status='pending_approval'`, orgID).Scan(&pending)
	_ = h.db.QueryRow(r.Context(), `SELECT COUNT(*) FROM comment_drafts WHERE org_id=$1 AND status='approved'`, orgID).Scan(&approved)
	_ = h.db.QueryRow(r.Context(), `SELECT COUNT(*) FROM comment_drafts WHERE org_id=$1 AND status='posted'`, orgID).Scan(&posted)
	_ = h.db.QueryRow(r.Context(), `SELECT COUNT(*) FROM comment_drafts WHERE org_id=$1 AND status='rejected'`, orgID).Scan(&rejected)
	respond.JSON(w, http.StatusOK, map[string]int{
		"pending": pending, "approved": approved,
		"posted": posted, "rejected": rejected,
	})
}

func (h *Handler) Conversion(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	rows, err := h.db.Query(r.Context(), `
		SELECT pipeline_stage, COUNT(*) as count
		FROM leads
		WHERE org_id=$1 AND deleted_at IS NULL
		GROUP BY pipeline_stage ORDER BY count DESC
	`, orgID)
	if err != nil {
		respond.InternalError(w, "query failed")
		return
	}
	defer rows.Close()
	var data []map[string]any
	for rows.Next() {
		var stage string
		var count int
		_ = rows.Scan(&stage, &count)
		data = append(data, map[string]any{"stage": stage, "count": count})
	}
	if data == nil {
		data = []map[string]any{}
	}
	respond.JSON(w, http.StatusOK, data)
}
