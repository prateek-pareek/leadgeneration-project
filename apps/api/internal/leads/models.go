package leads

import "time"
import "github.com/google/uuid"

type AuthorSummary struct {
	Handle      string  `json:"handle"`
	DisplayName *string `json:"display_name"`
	Platform    *string `json:"platform"`
	ProfileURL  *string `json:"profile_url"`
}

type ScoreSummary struct {
	Score  int    `json:"score"`
	Bucket string `json:"bucket"`
}

type Lead struct {
	ID            uuid.UUID      `json:"id"`
	OrgID         uuid.UUID      `json:"org_id"`
	AuthorID      *uuid.UUID     `json:"author_id"`
	CompanyID     *uuid.UUID     `json:"company_id"`
	PostID        *uuid.UUID     `json:"post_id"`
	Source        string         `json:"source"`
	Status        string         `json:"status"`
	PipelineStage string         `json:"pipeline_stage"`
	OwnerID       *uuid.UUID     `json:"owner_id"`
	Tags          []string       `json:"tags"`
	NextAction    *string        `json:"next_action"`
	NextActionAt  *time.Time     `json:"next_action_at"`
	LastContactAt *time.Time     `json:"last_contact_at"`
	IsSuppressed  bool           `json:"is_suppressed"`
	CreatedAt     time.Time      `json:"created_at"`
	UpdatedAt     time.Time      `json:"updated_at"`
	Author        *AuthorSummary `json:"author,omitempty"`
	LatestScore   *ScoreSummary  `json:"latest_score,omitempty"`
}

type ListResult struct {
	Data   []Lead `json:"data"`
	Total  int    `json:"total"`
	Limit  int    `json:"limit"`
	Offset int    `json:"offset"`
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
