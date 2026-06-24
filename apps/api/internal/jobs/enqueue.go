package jobs

import (
	"context"
	"encoding/json"

	"github.com/google/uuid"
	goredis "github.com/redis/go-redis/v9"
)

const QueueKey = "prospectOS:jobs"

type Enqueuer struct {
	rdb *goredis.Client
}

func NewEnqueuer(rdb *goredis.Client) *Enqueuer {
	return &Enqueuer{rdb: rdb}
}

type Job struct {
	Type    string         `json:"type"`
	Payload map[string]any `json:"payload"`
}

func (e *Enqueuer) Enqueue(ctx context.Context, jobType string, payload map[string]any) error {
	job := Job{Type: jobType, Payload: payload}
	b, err := json.Marshal(job)
	if err != nil {
		return err
	}
	return e.rdb.LPush(ctx, QueueKey, b).Err()
}

func (e *Enqueuer) EnqueueAnalyze(ctx context.Context, leadID, orgID uuid.UUID) error {
	return e.Enqueue(ctx, "lead.analyze", map[string]any{
		"lead_id": leadID.String(),
		"org_id":  orgID.String(),
	})
}

func (e *Enqueuer) EnqueueResearch(ctx context.Context, leadID, orgID uuid.UUID) error {
	return e.Enqueue(ctx, "lead.research", map[string]any{
		"lead_id": leadID.String(),
		"org_id":  orgID.String(),
	})
}

func (e *Enqueuer) EnqueueScoring(ctx context.Context, leadID, orgID uuid.UUID) error {
	return e.Enqueue(ctx, "lead.score", map[string]any{
		"lead_id": leadID.String(),
		"org_id":  orgID.String(),
	})
}

func (e *Enqueuer) EnqueueCommentDraft(ctx context.Context, leadID, orgID uuid.UUID) error {
	return e.Enqueue(ctx, "comment.generate", map[string]any{
		"lead_id": leadID.String(),
		"org_id":  orgID.String(),
	})
}

func (e *Enqueuer) EnqueueCommentPost(ctx context.Context, draftID, orgID uuid.UUID) error {
	return e.Enqueue(ctx, "comment.post", map[string]any{
		"draft_id": draftID.String(),
		"org_id":   orgID.String(),
	})
}

func (e *Enqueuer) EnqueueSourceScan(ctx context.Context, sourceID, orgID uuid.UUID) error {
	return e.Enqueue(ctx, "source.scan", map[string]any{
		"source_id": sourceID.String(),
		"org_id":    orgID.String(),
	})
}
