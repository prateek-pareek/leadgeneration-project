package leads

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/acmecorp/prospectOS/api/internal/shared/middleware"
	"github.com/acmecorp/prospectOS/api/internal/shared/respond"
)

type Handler struct {
	svc *Service
}

func NewHandler(svc *Service) *Handler {
	return &Handler{svc: svc}
}

type listParams struct {
	Stage  string
	Bucket string
	Owner  string
	Q      string
	Sort   string
	Limit  int
	Offset int
}

func (h *Handler) List(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}

	params := listParams{
		Stage:  r.URL.Query().Get("stage"),
		Bucket: r.URL.Query().Get("bucket"),
		Owner:  r.URL.Query().Get("owner"),
		Q:      r.URL.Query().Get("q"),
		Sort:   r.URL.Query().Get("sort"),
		Limit:  50,
		Offset: 0,
	}
	if l := r.URL.Query().Get("limit"); l != "" {
		if v, err := strconv.Atoi(l); err == nil && v > 0 && v <= 200 {
			params.Limit = v
		}
	}
	if o := r.URL.Query().Get("offset"); o != "" {
		if v, err := strconv.Atoi(o); err == nil && v >= 0 {
			params.Offset = v
		}
	}

	result, err := h.svc.List(r.Context(), orgID, params)
	if err != nil {
		respond.InternalError(w, "failed to list leads")
		return
	}

	respond.JSON(w, http.StatusOK, result)
}

func (h *Handler) Get(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}

	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}

	lead, err := h.svc.Get(r.Context(), orgID, leadID)
	if err != nil {
		respond.NotFound(w, "lead not found")
		return
	}

	respond.JSON(w, http.StatusOK, lead)
}

func (h *Handler) Create(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}

	var input CreateLeadInput
	if err := json.NewDecoder(r.Body).Decode(&input); err != nil {
		respond.BadRequest(w, "invalid request body")
		return
	}

	lead, err := h.svc.Create(r.Context(), orgID, input)
	if err != nil {
		respond.InternalError(w, "failed to create lead")
		return
	}

	respond.JSON(w, http.StatusCreated, lead)
}

func (h *Handler) Update(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}

	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}

	var input UpdateLeadInput
	if err := json.NewDecoder(r.Body).Decode(&input); err != nil {
		respond.BadRequest(w, "invalid request body")
		return
	}

	lead, err := h.svc.Update(r.Context(), orgID, leadID, input)
	if err != nil {
		respond.InternalError(w, "failed to update lead")
		return
	}

	respond.JSON(w, http.StatusOK, lead)
}

func (h *Handler) Delete(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}

	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}

	if err := h.svc.Delete(r.Context(), orgID, leadID); err != nil {
		respond.InternalError(w, "failed to delete lead")
		return
	}

	respond.JSON(w, http.StatusOK, map[string]string{"message": "deleted"})
}

func (h *Handler) Advance(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}

	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}

	lead, err := h.svc.AdvanceStage(r.Context(), orgID, leadID)
	if err != nil {
		respond.InternalError(w, "failed to advance stage")
		return
	}

	respond.JSON(w, http.StatusOK, lead)
}

func (h *Handler) Activity(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}
	rows, err := h.svc.db.Query(r.Context(), `
		SELECT id, type, description, metadata, created_at
		FROM activities
		WHERE lead_id = $1 AND org_id = $2
		ORDER BY created_at DESC LIMIT 50
	`, leadID, orgID)
	if err != nil {
		respond.InternalError(w, "failed to fetch activity")
		return
	}
	defer rows.Close()
	type event struct {
		ID          uuid.UUID `json:"id"`
		Type        string    `json:"type"`
		Description string    `json:"description"`
		Metadata    []byte    `json:"metadata"`
		CreatedAt   string    `json:"created_at"`
	}
	var items []event
	for rows.Next() {
		var e event
		_ = rows.Scan(&e.ID, &e.Type, &e.Description, &e.Metadata, &e.CreatedAt)
		items = append(items, e)
	}
	if items == nil {
		items = []event{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) Score(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}
	var score struct {
		ID               uuid.UUID `json:"id"`
		Score            int       `json:"score"`
		Bucket           string    `json:"bucket"`
		DimensionScores  []byte    `json:"dimension_scores"`
		TopSignals       []byte    `json:"top_signals"`
		Explanation      string    `json:"explanation"`
		RecommendedAction string   `json:"recommended_action"`
		CreatedAt        string    `json:"created_at"`
	}
	err = h.svc.db.QueryRow(r.Context(), `
		SELECT id, score, bucket, dimension_scores, top_signals, explanation, recommended_action, created_at
		FROM lead_scores WHERE lead_id=$1 AND org_id=$2
		ORDER BY created_at DESC LIMIT 1
	`, leadID, orgID).Scan(
		&score.ID, &score.Score, &score.Bucket, &score.DimensionScores,
		&score.TopSignals, &score.Explanation, &score.RecommendedAction, &score.CreatedAt,
	)
	if err != nil {
		respond.NotFound(w, "no score yet")
		return
	}
	respond.JSON(w, http.StatusOK, score)
}

func (h *Handler) Research(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}
	rows, err := h.svc.db.Query(r.Context(), `
		SELECT id, content, model_used, created_at
		FROM research_briefs WHERE lead_id=$1 AND org_id=$2
		ORDER BY created_at DESC LIMIT 5
	`, leadID, orgID)
	if err != nil {
		respond.InternalError(w, "failed to fetch research")
		return
	}
	defer rows.Close()
	type brief struct {
		ID        uuid.UUID `json:"id"`
		Content   []byte    `json:"content"`
		ModelUsed string    `json:"model_used"`
		CreatedAt string    `json:"created_at"`
	}
	var items []brief
	for rows.Next() {
		var b brief
		_ = rows.Scan(&b.ID, &b.Content, &b.ModelUsed, &b.CreatedAt)
		items = append(items, b)
	}
	if items == nil {
		items = []brief{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) CommentDrafts(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}
	rows, err := h.svc.db.Query(r.Context(), `
		SELECT id, variants, selected_variant, status, approved_at, posted_at, created_at
		FROM comment_drafts WHERE lead_id=$1 AND org_id=$2
		ORDER BY created_at DESC LIMIT 20
	`, leadID, orgID)
	if err != nil {
		respond.InternalError(w, "failed to fetch comment drafts")
		return
	}
	defer rows.Close()
	type draft struct {
		ID              uuid.UUID  `json:"id"`
		Variants        []byte     `json:"variants"`
		SelectedVariant []byte     `json:"selected_variant"`
		Status          string     `json:"status"`
		ApprovedAt      *string    `json:"approved_at"`
		PostedAt        *string    `json:"posted_at"`
		CreatedAt       string     `json:"created_at"`
	}
	var items []draft
	for rows.Next() {
		var d draft
		_ = rows.Scan(&d.ID, &d.Variants, &d.SelectedVariant, &d.Status, &d.ApprovedAt, &d.PostedAt, &d.CreatedAt)
		items = append(items, d)
	}
	if items == nil {
		items = []draft{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) OutreachDrafts(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}
	rows, err := h.svc.db.Query(r.Context(), `
		SELECT id, message_type, subject, body, status, created_at
		FROM outreach_drafts WHERE lead_id=$1 AND org_id=$2
		ORDER BY created_at DESC LIMIT 10
	`, leadID, orgID)
	if err != nil {
		respond.InternalError(w, "failed to fetch outreach drafts")
		return
	}
	defer rows.Close()
	type odraft struct {
		ID          uuid.UUID `json:"id"`
		MessageType string    `json:"message_type"`
		Subject     *string   `json:"subject"`
		Body        string    `json:"body"`
		Status      string    `json:"status"`
		CreatedAt   string    `json:"created_at"`
	}
	var items []odraft
	for rows.Next() {
		var d odraft
		_ = rows.Scan(&d.ID, &d.MessageType, &d.Subject, &d.Body, &d.Status, &d.CreatedAt)
		items = append(items, d)
	}
	if items == nil {
		items = []odraft{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) Tasks(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}
	rows, err := h.svc.db.Query(r.Context(), `
		SELECT id, title, description, priority, status, due_at, created_at
		FROM tasks WHERE lead_id=$1 AND org_id=$2 AND deleted_at IS NULL
		ORDER BY due_at ASC NULLS LAST, created_at DESC
	`, leadID, orgID)
	if err != nil {
		respond.InternalError(w, "failed to fetch tasks")
		return
	}
	defer rows.Close()
	type task struct {
		ID          uuid.UUID `json:"id"`
		Title       string    `json:"title"`
		Description *string   `json:"description"`
		Priority    string    `json:"priority"`
		Status      string    `json:"status"`
		DueAt       *string   `json:"due_at"`
		CreatedAt   string    `json:"created_at"`
	}
	var items []task
	for rows.Next() {
		var t task
		_ = rows.Scan(&t.ID, &t.Title, &t.Description, &t.Priority, &t.Status, &t.DueAt, &t.CreatedAt)
		items = append(items, t)
	}
	if items == nil {
		items = []task{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) Notes(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}
	rows, err := h.svc.db.Query(r.Context(), `
		SELECT n.id, n.content, n.created_at, u.name as author_name
		FROM notes n
		LEFT JOIN users u ON u.id = n.created_by
		WHERE n.lead_id=$1 AND n.org_id=$2
		ORDER BY n.created_at DESC
	`, leadID, orgID)
	if err != nil {
		respond.InternalError(w, "failed to fetch notes")
		return
	}
	defer rows.Close()
	type note struct {
		ID         uuid.UUID `json:"id"`
		Content    string    `json:"content"`
		CreatedAt  string    `json:"created_at"`
		AuthorName *string   `json:"author_name"`
	}
	var items []note
	for rows.Next() {
		var n note
		_ = rows.Scan(&n.ID, &n.Content, &n.CreatedAt, &n.AuthorName)
		items = append(items, n)
	}
	if items == nil {
		items = []note{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) CreateNote(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	userID, _ := middleware.GetUserID(r.Context())
	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}
	var body struct {
		Content string `json:"content"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Content == "" {
		respond.BadRequest(w, "content required")
		return
	}
	var id uuid.UUID
	err = h.svc.db.QueryRow(r.Context(), `
		INSERT INTO notes (org_id, lead_id, content, created_by)
		VALUES ($1, $2, $3, $4)
		RETURNING id
	`, orgID, leadID, body.Content, userID).Scan(&id)
	if err != nil {
		respond.InternalError(w, "failed to create note")
		return
	}
	respond.JSON(w, http.StatusCreated, map[string]string{"id": id.String(), "message": "note created"})
}

func (h *Handler) BulkAction(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	var body struct {
		Action  string      `json:"action"`
		LeadIDs []uuid.UUID `json:"lead_ids"`
		Value   string      `json:"value"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || len(body.LeadIDs) == 0 {
		respond.BadRequest(w, "action and lead_ids required")
		return
	}

	switch body.Action {
	case "change_stage":
		if body.Value == "" {
			respond.BadRequest(w, "value required for change_stage")
			return
		}
		_, err := h.svc.db.Exec(r.Context(), `
			UPDATE leads SET pipeline_stage=$1, updated_at=NOW()
			WHERE id = ANY($2) AND org_id=$3 AND deleted_at IS NULL
		`, body.Value, body.LeadIDs, orgID)
		if err != nil {
			respond.InternalError(w, "bulk stage update failed")
			return
		}
	case "suppress":
		_, err := h.svc.db.Exec(r.Context(), `
			UPDATE leads SET status='suppressed', deleted_at=NOW()
			WHERE id = ANY($1) AND org_id=$2 AND deleted_at IS NULL
		`, body.LeadIDs, orgID)
		if err != nil {
			respond.InternalError(w, "bulk suppress failed")
			return
		}
	case "delete":
		_, err := h.svc.db.Exec(r.Context(), `
			UPDATE leads SET deleted_at=NOW()
			WHERE id = ANY($1) AND org_id=$2
		`, body.LeadIDs, orgID)
		if err != nil {
			respond.InternalError(w, "bulk delete failed")
			return
		}
	default:
		respond.BadRequest(w, "unknown action: "+body.Action)
		return
	}

	respond.JSON(w, http.StatusOK, map[string]any{
		"message": "bulk action applied",
		"count":   len(body.LeadIDs),
	})
}

func (h *Handler) Pipeline(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}

	rows, err := h.svc.db.Query(r.Context(), `
		SELECT
			l.id, l.pipeline_stage, l.source, l.created_at,
			a.display_name, a.handle, a.platform,
			ls.score, ls.bucket
		FROM leads l
		LEFT JOIN authors a ON a.id = l.author_id
		LEFT JOIN LATERAL (
			SELECT score, bucket FROM lead_scores
			WHERE lead_id = l.id ORDER BY created_at DESC LIMIT 1
		) ls ON true
		WHERE l.org_id = $1 AND l.deleted_at IS NULL
		ORDER BY l.created_at DESC
	`, orgID)
	if err != nil {
		respond.InternalError(w, "failed to fetch pipeline")
		return
	}
	defer rows.Close()

	type leadCard struct {
		ID            uuid.UUID `json:"id"`
		PipelineStage string    `json:"pipeline_stage"`
		Source        string    `json:"source"`
		CreatedAt     string    `json:"created_at"`
		Author        struct {
			DisplayName *string `json:"display_name"`
			Handle      *string `json:"handle"`
			Platform    *string `json:"platform"`
		} `json:"author"`
		LatestScore *struct {
			Score  *int    `json:"score"`
			Bucket *string `json:"bucket"`
		} `json:"latest_score,omitempty"`
	}

	pipeline := make(map[string][]leadCard)
	for rows.Next() {
		var c leadCard
		var score *int
		var bucket *string
		_ = rows.Scan(
			&c.ID, &c.PipelineStage, &c.Source, &c.CreatedAt,
			&c.Author.DisplayName, &c.Author.Handle, &c.Author.Platform,
			&score, &bucket,
		)
		if score != nil {
			c.LatestScore = &struct {
				Score  *int    `json:"score"`
				Bucket *string `json:"bucket"`
			}{Score: score, Bucket: bucket}
		}
		pipeline[c.PipelineStage] = append(pipeline[c.PipelineStage], c)
	}
	respond.JSON(w, http.StatusOK, pipeline)
}

func (h *Handler) Suppress(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}

	leadID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid lead id")
		return
	}

	var body struct {
		Reason string `json:"reason"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)

	if err := h.svc.Suppress(r.Context(), orgID, leadID, body.Reason); err != nil {
		respond.InternalError(w, "failed to suppress lead")
		return
	}

	respond.JSON(w, http.StatusOK, map[string]string{"message": "suppressed"})
}
