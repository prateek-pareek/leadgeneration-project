package email_health

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/acmecorp/prospectOS/api/internal/shared/middleware"
	"github.com/acmecorp/prospectOS/api/internal/shared/respond"
)

type Service struct {
	db          *pgxpool.Pool
	dnsResolver string
}

func NewService(db *pgxpool.Pool, dnsResolver string) *Service {
	return &Service{db: db, dnsResolver: dnsResolver}
}

type Handler struct{ svc *Service }

func NewHandler(svc *Service) *Handler { return &Handler{svc: svc} }

// ── Domains ───────────────────────────────────────────────────

func (h *Handler) ListDomains(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	rows, err := h.svc.db.Query(r.Context(), `
		SELECT id, domain, is_primary, health_score, last_checked_at, created_at
		FROM domains WHERE org_id=$1 ORDER BY created_at DESC
	`, orgID)
	if err != nil {
		respond.InternalError(w, "failed to list domains")
		return
	}
	defer rows.Close()
	type domain struct {
		ID            uuid.UUID `json:"id"`
		Domain        string    `json:"domain"`
		IsPrimary     bool      `json:"is_primary"`
		HealthScore   *int      `json:"health_score"`
		LastCheckedAt *string   `json:"last_checked_at"`
		CreatedAt     string    `json:"created_at"`
	}
	var items []domain
	for rows.Next() {
		var d domain
		_ = rows.Scan(&d.ID, &d.Domain, &d.IsPrimary, &d.HealthScore, &d.LastCheckedAt, &d.CreatedAt)
		items = append(items, d)
	}
	if items == nil {
		items = []domain{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) AddDomain(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	var body struct {
		Domain    string `json:"domain"`
		IsPrimary bool   `json:"is_primary"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Domain == "" {
		respond.BadRequest(w, "domain required")
		return
	}
	var id uuid.UUID
	err := h.svc.db.QueryRow(r.Context(), `
		INSERT INTO domains (org_id, domain, is_primary) VALUES ($1,$2,$3) RETURNING id
	`, orgID, strings.ToLower(body.Domain), body.IsPrimary).Scan(&id)
	if err != nil {
		respond.Conflict(w, "domain already exists")
		return
	}
	respond.JSON(w, http.StatusCreated, map[string]any{"id": id, "domain": body.Domain})
}

func (h *Handler) GetDomain(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	var d struct {
		ID          uuid.UUID `json:"id"`
		Domain      string    `json:"domain"`
		HealthScore *int      `json:"health_score"`
	}
	_ = h.svc.db.QueryRow(r.Context(), `
		SELECT id, domain, health_score FROM domains WHERE id=$1 AND org_id=$2
	`, id, orgID).Scan(&d.ID, &d.Domain, &d.HealthScore)
	respond.JSON(w, http.StatusOK, d)
}

func (h *Handler) DeleteDomain(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	_, _ = h.svc.db.Exec(r.Context(), `DELETE FROM domains WHERE id=$1 AND org_id=$2`, id, orgID)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "deleted"})
}

func (h *Handler) RunCheck(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		respond.BadRequest(w, "invalid domain id")
		return
	}

	var domain string
	err = h.svc.db.QueryRow(r.Context(), `SELECT domain FROM domains WHERE id=$1 AND org_id=$2`, id, orgID).Scan(&domain)
	if err != nil {
		respond.NotFound(w, "domain not found")
		return
	}

	result := h.svc.checkDomain(r.Context(), domain)

	checkJSON, _ := json.Marshal(result)
	var checkID uuid.UUID
	_ = h.svc.db.QueryRow(r.Context(), `
		INSERT INTO domain_checks (domain_id, org_id, spf_valid, dkim_valid, dmarc_valid,
			mx_records, blacklist_clean, health_score, raw_results, checked_at)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,NOW()) RETURNING id
	`, id, orgID,
		result["spf_valid"], result["dkim_valid"], result["dmarc_valid"],
		result["mx_records"], result["blacklist_clean"], result["health_score"],
		checkJSON,
	).Scan(&checkID)

	_, _ = h.svc.db.Exec(r.Context(), `
		UPDATE domains SET health_score=$1, last_checked_at=NOW() WHERE id=$2
	`, result["health_score"], id)

	respond.JSON(w, http.StatusOK, result)
}

func (h *Handler) ListChecks(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	rows, err := h.svc.db.Query(r.Context(), `
		SELECT id, health_score, blacklist_clean, spf_valid, dkim_valid, dmarc_valid, checked_at
		FROM domain_checks WHERE domain_id=$1 AND org_id=$2
		ORDER BY checked_at DESC LIMIT 30
	`, id, orgID)
	if err != nil {
		respond.InternalError(w, "failed to list checks")
		return
	}
	defer rows.Close()
	var items []map[string]any
	for rows.Next() {
		var checkID uuid.UUID
		var health *int
		var blacklistClean, spfValid, dkimValid, dmarcValid *bool
		var checkedAt string
		_ = rows.Scan(&checkID, &health, &blacklistClean, &spfValid, &dkimValid, &dmarcValid, &checkedAt)
		items = append(items, map[string]any{
			"id": checkID, "health_score": health,
			"blacklist_clean": blacklistClean, "spf_valid": spfValid,
			"dkim_valid": dkimValid, "dmarc_valid": dmarcValid, "checked_at": checkedAt,
		})
	}
	if items == nil {
		items = []map[string]any{}
	}
	respond.JSON(w, http.StatusOK, items)
}

// ── Accounts ──────────────────────────────────────────────────

func (h *Handler) ListAccounts(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	rows, err := h.svc.db.Query(r.Context(), `
		SELECT id, label, email_address, domain, is_active, daily_limit, warmup_status, created_at
		FROM email_accounts WHERE org_id=$1 ORDER BY created_at DESC
	`, orgID)
	if err != nil {
		respond.InternalError(w, "failed to list accounts")
		return
	}
	defer rows.Close()
	type account struct {
		ID           uuid.UUID `json:"id"`
		Label        string    `json:"label"`
		EmailAddress string    `json:"email_address"`
		Domain       string    `json:"domain"`
		IsActive     bool      `json:"is_active"`
		DailyLimit   int       `json:"daily_limit"`
		WarmupStatus string    `json:"warmup_status"`
		CreatedAt    string    `json:"created_at"`
	}
	var items []account
	for rows.Next() {
		var a account
		_ = rows.Scan(&a.ID, &a.Label, &a.EmailAddress, &a.Domain, &a.IsActive, &a.DailyLimit, &a.WarmupStatus, &a.CreatedAt)
		items = append(items, a)
	}
	if items == nil {
		items = []account{}
	}
	respond.JSON(w, http.StatusOK, items)
}

func (h *Handler) AddAccount(w http.ResponseWriter, r *http.Request) {
	orgID, ok := middleware.GetOrgID(r.Context())
	if !ok {
		respond.Unauthorized(w, "missing org context")
		return
	}
	var body struct {
		Label        string `json:"label"`
		EmailAddress string `json:"email_address"`
		Domain       string `json:"domain"`
		DailyLimit   int    `json:"daily_limit"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.EmailAddress == "" {
		respond.BadRequest(w, "email_address required")
		return
	}
	if body.DailyLimit == 0 {
		body.DailyLimit = 30
	}
	if body.Domain == "" {
		parts := strings.Split(body.EmailAddress, "@")
		if len(parts) == 2 {
			body.Domain = parts[1]
		}
	}
	var id uuid.UUID
	_ = h.svc.db.QueryRow(r.Context(), `
		INSERT INTO email_accounts (org_id, label, email_address, domain, daily_limit)
		VALUES ($1,$2,$3,$4,$5) RETURNING id
	`, orgID, body.Label, body.EmailAddress, body.Domain, body.DailyLimit).Scan(&id)
	respond.JSON(w, http.StatusCreated, map[string]any{"id": id})
}

func (h *Handler) GetAccount(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	var a struct {
		ID           uuid.UUID `json:"id"`
		Label        string    `json:"label"`
		EmailAddress string    `json:"email_address"`
		WarmupStatus string    `json:"warmup_status"`
	}
	_ = h.svc.db.QueryRow(r.Context(), `
		SELECT id, label, email_address, warmup_status FROM email_accounts WHERE id=$1 AND org_id=$2
	`, id, orgID).Scan(&a.ID, &a.Label, &a.EmailAddress, &a.WarmupStatus)
	respond.JSON(w, http.StatusOK, a)
}

func (h *Handler) UpdateAccount(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	var body struct {
		Label      *string `json:"label"`
		DailyLimit *int    `json:"daily_limit"`
		IsActive   *bool   `json:"is_active"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	_, _ = h.svc.db.Exec(r.Context(), `
		UPDATE email_accounts SET
			label = COALESCE($1, label),
			daily_limit = COALESCE($2, daily_limit),
			is_active = COALESCE($3, is_active),
			updated_at = NOW()
		WHERE id=$4 AND org_id=$5
	`, body.Label, body.DailyLimit, body.IsActive, id, orgID)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "updated"})
}

func (h *Handler) DeleteAccount(w http.ResponseWriter, r *http.Request) {
	orgID, _ := middleware.GetOrgID(r.Context())
	id, _ := uuid.Parse(chi.URLParam(r, "id"))
	_, _ = h.svc.db.Exec(r.Context(), `DELETE FROM email_accounts WHERE id=$1 AND org_id=$2`, id, orgID)
	respond.JSON(w, http.StatusOK, map[string]string{"message": "deleted"})
}

// ── DNS Checker ───────────────────────────────────────────────

func (s *Service) checkDomain(ctx context.Context, domain string) map[string]any {
	result := map[string]any{
		"domain":         domain,
		"spf_valid":      false,
		"dkim_valid":     false,
		"dmarc_valid":    false,
		"mx_records":     []string{},
		"blacklist_clean": true,
		"health_score":   0,
		"checked_at":     time.Now().UTC().Format(time.RFC3339),
	}

	r := &net.Resolver{
		PreferGo: true,
		Dial: func(ctx context.Context, network, address string) (net.Conn, error) {
			d := net.Dialer{Timeout: 5 * time.Second}
			return d.DialContext(ctx, "udp", s.dnsResolver)
		},
	}

	score := 0

	// SPF check
	txts, err := r.LookupTXT(ctx, domain)
	if err == nil {
		for _, txt := range txts {
			if strings.HasPrefix(txt, "v=spf1") {
				result["spf_valid"] = true
				result["spf_record"] = txt
				score += 25
				break
			}
		}
	}

	// DMARC check
	dmarcTXTs, err := r.LookupTXT(ctx, "_dmarc."+domain)
	if err == nil {
		for _, txt := range dmarcTXTs {
			if strings.HasPrefix(txt, "v=DMARC1") {
				result["dmarc_valid"] = true
				result["dmarc_record"] = txt
				policy := "none"
				if strings.Contains(txt, "p=reject") {
					policy = "reject"
					score += 30
				} else if strings.Contains(txt, "p=quarantine") {
					policy = "quarantine"
					score += 20
				} else {
					score += 10
				}
				result["dmarc_policy"] = policy
				break
			}
		}
	}

	// MX check
	mxRecords, err := r.LookupMX(ctx, domain)
	if err == nil && len(mxRecords) > 0 {
		mxHosts := make([]string, len(mxRecords))
		for i, mx := range mxRecords {
			mxHosts[i] = fmt.Sprintf("%d %s", mx.Pref, mx.Host)
		}
		result["mx_records"] = mxHosts
		score += 20
	}

	// Basic blacklist check against well-known RBLs
	blacklistsHit := s.checkBlacklists(ctx, domain)
	if len(blacklistsHit) == 0 {
		score += 25
	} else {
		result["blacklist_clean"] = false
		result["blacklists_hit"] = blacklistsHit
	}

	result["health_score"] = score
	return result
}

var publicRBLs = []string{
	"zen.spamhaus.org",
	"bl.spamcop.net",
	"dnsbl.sorbs.net",
}

func (s *Service) checkBlacklists(ctx context.Context, domain string) []string {
	// For domain blacklists, we check the domain directly
	// A full IP-based RBL check would need the sending IP
	var hit []string
	r := &net.Resolver{PreferGo: true}
	for _, rbl := range publicRBLs {
		lookup := domain + "." + rbl
		addrs, err := r.LookupHost(ctx, lookup)
		if err == nil && len(addrs) > 0 {
			hit = append(hit, rbl)
		}
	}
	return hit
}
