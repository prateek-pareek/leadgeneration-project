package leads

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/acmecorp/prospectOS/api/internal/audit"
	"github.com/acmecorp/prospectOS/api/internal/jobs"
	"github.com/acmecorp/prospectOS/api/internal/shared/middleware"
)

var ErrNotFound = errors.New("lead not found")

type Service struct {
	db       *pgxpool.Pool
	audit    *audit.Service
	enqueuer *jobs.Enqueuer
}

func NewService(db *pgxpool.Pool, audit *audit.Service, enqueuer *jobs.Enqueuer) *Service {
	return &Service{db: db, audit: audit, enqueuer: enqueuer}
}

type CreateLeadInput struct {
	PostID    *uuid.UUID `json:"post_id"`
	AuthorID  *uuid.UUID `json:"author_id"`
	CompanyID *uuid.UUID `json:"company_id"`
	Source    string     `json:"source"`
	Tags      []string   `json:"tags"`
}

type UpdateLeadInput struct {
	PipelineStage *string    `json:"pipeline_stage"`
	OwnerID       *uuid.UUID `json:"owner_id"`
	Tags          []string   `json:"tags"`
	NextAction    *string    `json:"next_action"`
	NextActionAt  *time.Time `json:"next_action_at"`
}

func (s *Service) List(ctx context.Context, orgID uuid.UUID, p listParams) (*ListResult, error) {
	args := []any{orgID}
	where := "l.org_id = $1 AND l.deleted_at IS NULL AND l.is_suppressed = false"
	idx := 2

	if p.Stage != "" {
		where += fmt.Sprintf(" AND l.pipeline_stage = $%d", idx)
		args = append(args, p.Stage)
		idx++
	}
	if p.Q != "" {
		where += fmt.Sprintf(" AND (a.display_name ILIKE $%d OR a.handle ILIKE $%d)", idx, idx)
		args = append(args, "%"+p.Q+"%")
		idx++
	}

	countRow := s.db.QueryRow(ctx, fmt.Sprintf(`
		SELECT COUNT(*) FROM leads l
		LEFT JOIN authors a ON a.id = l.author_id
		WHERE %s`, where), args...)
	var total int
	_ = countRow.Scan(&total)

	args = append(args, p.Limit, p.Offset)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
		SELECT
			l.id, l.org_id, l.author_id, l.company_id, l.post_id, l.source,
			l.status, l.pipeline_stage, l.owner_id, l.tags,
			l.next_action, l.next_action_at, l.last_contact_at,
			l.is_suppressed, l.created_at, l.updated_at,
			a.handle, a.display_name, a.platform, a.profile_url,
			ls.score, ls.bucket
		FROM leads l
		LEFT JOIN authors a ON a.id = l.author_id
		LEFT JOIN LATERAL (
			SELECT score, bucket FROM lead_scores
			WHERE lead_id = l.id ORDER BY scored_at DESC LIMIT 1
		) ls ON true
		WHERE %s
		ORDER BY l.created_at DESC
		LIMIT $%d OFFSET $%d`, where, idx, idx+1), args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var items []Lead
	for rows.Next() {
		var l Lead
		var authorHandle, authorName, authorPlatform, authorProfileURL *string
		var score *int
		var bucket *string

		err := rows.Scan(
			&l.ID, &l.OrgID, &l.AuthorID, &l.CompanyID, &l.PostID, &l.Source,
			&l.Status, &l.PipelineStage, &l.OwnerID, &l.Tags,
			&l.NextAction, &l.NextActionAt, &l.LastContactAt,
			&l.IsSuppressed, &l.CreatedAt, &l.UpdatedAt,
			&authorHandle, &authorName, &authorPlatform, &authorProfileURL,
			&score, &bucket,
		)
		if err != nil {
			continue
		}
		if authorHandle != nil {
			l.Author = &AuthorSummary{
				Handle:      *authorHandle,
				DisplayName: authorName,
				Platform:    authorPlatform,
				ProfileURL:  authorProfileURL,
			}
		}
		if score != nil {
			l.LatestScore = &ScoreSummary{Score: *score, Bucket: *bucket}
		}
		items = append(items, l)
	}

	return &ListResult{Data: items, Total: total, Limit: p.Limit, Offset: p.Offset}, nil
}

func (s *Service) Get(ctx context.Context, orgID, leadID uuid.UUID) (*Lead, error) {
	var l Lead
	err := s.db.QueryRow(ctx, `
		SELECT id, org_id, author_id, company_id, post_id, source,
		       status, pipeline_stage, owner_id, tags,
		       next_action, next_action_at, last_contact_at,
		       is_suppressed, created_at, updated_at
		FROM leads
		WHERE id = $1 AND org_id = $2 AND deleted_at IS NULL
	`, leadID, orgID).Scan(
		&l.ID, &l.OrgID, &l.AuthorID, &l.CompanyID, &l.PostID, &l.Source,
		&l.Status, &l.PipelineStage, &l.OwnerID, &l.Tags,
		&l.NextAction, &l.NextActionAt, &l.LastContactAt,
		&l.IsSuppressed, &l.CreatedAt, &l.UpdatedAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	return &l, err
}

func (s *Service) Create(ctx context.Context, orgID uuid.UUID, input CreateLeadInput) (*Lead, error) {
	userID, _ := middleware.GetUserID(ctx)
	if input.Source == "" {
		input.Source = "manual"
	}
	if input.Tags == nil {
		input.Tags = []string{}
	}

	var l Lead
	err := s.db.QueryRow(ctx, `
		INSERT INTO leads (org_id, post_id, author_id, company_id, source, owner_id, tags)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
		RETURNING id, org_id, author_id, company_id, post_id, source,
		          status, pipeline_stage, owner_id, tags, created_at, updated_at
	`, orgID, input.PostID, input.AuthorID, input.CompanyID, input.Source, userID, input.Tags,
	).Scan(
		&l.ID, &l.OrgID, &l.AuthorID, &l.CompanyID, &l.PostID, &l.Source,
		&l.Status, &l.PipelineStage, &l.OwnerID, &l.Tags, &l.CreatedAt, &l.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}

	s.audit.Log(ctx, orgID, "lead.created", "lead", l.ID, nil, &l)
	_ = s.enqueuer.EnqueueResearch(ctx, l.ID, orgID)

	return &l, nil
}

func (s *Service) Update(ctx context.Context, orgID, leadID uuid.UUID, input UpdateLeadInput) (*Lead, error) {
	old, err := s.Get(ctx, orgID, leadID)
	if err != nil {
		return nil, err
	}

	_, err = s.db.Exec(ctx, `
		UPDATE leads SET
			pipeline_stage = COALESCE($1, pipeline_stage),
			owner_id       = COALESCE($2, owner_id),
			tags           = COALESCE($3, tags),
			next_action    = COALESCE($4, next_action),
			next_action_at = COALESCE($5, next_action_at),
			updated_at     = NOW()
		WHERE id = $6 AND org_id = $7
	`, input.PipelineStage, input.OwnerID, input.Tags,
		input.NextAction, input.NextActionAt, leadID, orgID)
	if err != nil {
		return nil, err
	}

	updated, _ := s.Get(ctx, orgID, leadID)
	s.audit.Log(ctx, orgID, "lead.updated", "lead", leadID, old, updated)
	return updated, nil
}

func (s *Service) Delete(ctx context.Context, orgID, leadID uuid.UUID) error {
	_, err := s.db.Exec(ctx, `
		UPDATE leads SET deleted_at = NOW() WHERE id = $1 AND org_id = $2
	`, leadID, orgID)
	s.audit.Log(ctx, orgID, "lead.deleted", "lead", leadID, nil, nil)
	return err
}

func (s *Service) AdvanceStage(ctx context.Context, orgID, leadID uuid.UUID) (*Lead, error) {
	stages := []string{
		"Discovered", "Qualified", "Researched", "Comment Drafted",
		"Comment Posted", "Replied", "Connection Sent", "DM Drafted",
		"Email Drafted", "Email Sent", "Meeting Booked", "Proposal Sent",
	}

	lead, err := s.Get(ctx, orgID, leadID)
	if err != nil {
		return nil, err
	}

	nextStage := lead.PipelineStage
	for i, stage := range stages {
		if stage == lead.PipelineStage && i+1 < len(stages) {
			nextStage = stages[i+1]
			break
		}
	}

	return s.Update(ctx, orgID, leadID, UpdateLeadInput{PipelineStage: &nextStage})
}

func (s *Service) Suppress(ctx context.Context, orgID, leadID uuid.UUID, reason string) error {
	_, err := s.db.Exec(ctx, `
		UPDATE leads SET
			is_suppressed = true,
			suppressed_at = NOW(),
			suppression_reason = $1,
			updated_at = NOW()
		WHERE id = $2 AND org_id = $3
	`, reason, leadID, orgID)
	s.audit.Log(ctx, orgID, "lead.suppressed", "lead", leadID, nil, map[string]string{"reason": reason})
	return err
}

func (s *Service) GetPipeline(ctx context.Context, orgID uuid.UUID) (map[string][]Lead, error) {
	rows, err := s.db.Query(ctx, `
		SELECT l.id, l.pipeline_stage, a.display_name, a.handle, a.platform,
		       ls.score, ls.bucket
		FROM leads l
		LEFT JOIN authors a ON a.id = l.author_id
		LEFT JOIN LATERAL (
			SELECT score, bucket FROM lead_scores
			WHERE lead_id = l.id ORDER BY scored_at DESC LIMIT 1
		) ls ON true
		WHERE l.org_id = $1 AND l.deleted_at IS NULL AND l.is_suppressed = false
		ORDER BY l.created_at DESC
		LIMIT 500
	`, orgID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	pipeline := make(map[string][]Lead)
	for rows.Next() {
		var l Lead
		var authorName, authorHandle, authorPlatform *string
		var score *int
		var bucket *string
		_ = rows.Scan(&l.ID, &l.PipelineStage, &authorName, &authorHandle, &authorPlatform, &score, &bucket)
		if authorHandle != nil {
			l.Author = &AuthorSummary{Handle: *authorHandle, DisplayName: authorName, Platform: authorPlatform}
		}
		if score != nil {
			l.LatestScore = &ScoreSummary{Score: *score, Bucket: *bucket}
		}
		pipeline[l.PipelineStage] = append(pipeline[l.PipelineStage], l)
	}
	return pipeline, nil
}
