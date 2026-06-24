package router

import (
	"log/slog"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	chimiddleware "github.com/go-chi/chi/v5/middleware"
	"github.com/go-chi/cors"
	"github.com/go-chi/httprate"
	"github.com/jackc/pgx/v5/pgxpool"
	goredis "github.com/redis/go-redis/v9"

	"github.com/acmecorp/prospectOS/api/internal/analytics"
	"github.com/acmecorp/prospectOS/api/internal/approvals"
	"github.com/acmecorp/prospectOS/api/internal/audit"
	"github.com/acmecorp/prospectOS/api/internal/auth"
	"github.com/acmecorp/prospectOS/api/internal/comments"
	"github.com/acmecorp/prospectOS/api/internal/email_health"
	"github.com/acmecorp/prospectOS/api/internal/jobs"
	"github.com/acmecorp/prospectOS/api/internal/leads"
	"github.com/acmecorp/prospectOS/api/internal/posts"
	"github.com/acmecorp/prospectOS/api/internal/research"
	"github.com/acmecorp/prospectOS/api/internal/scoring"
	"github.com/acmecorp/prospectOS/api/internal/shared/config"
	"github.com/acmecorp/prospectOS/api/internal/shared/middleware"
	"github.com/acmecorp/prospectOS/api/internal/sources"
	"github.com/acmecorp/prospectOS/api/internal/tasks"
)

func New(cfg *config.Config, db *pgxpool.Pool, rdb *goredis.Client, log *slog.Logger) http.Handler {
	r := chi.NewRouter()

	// Global middleware
	r.Use(chimiddleware.RealIP)
	r.Use(middleware.CorrelationID)
	r.Use(middleware.RequestLogger)
	r.Use(chimiddleware.Recoverer)
	allowedOrigins := []string{cfg.FrontendURL}
	if cfg.AppEnv == "development" {
		allowedOrigins = []string{"http://localhost:3000", "http://localhost:3001"}
	}
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   allowedOrigins,
		AllowedMethods:   []string{"GET", "POST", "PATCH", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Authorization", "Content-Type", "X-Correlation-ID"},
		ExposedHeaders:   []string{"X-Correlation-ID"},
		AllowCredentials: true,
		MaxAge:           300,
	}))

	// Build services
	accessTTL, _ := time.ParseDuration(cfg.JWTAccessTTL)
	refreshTTL, _ := time.ParseDuration(cfg.JWTRefreshTTL)

	authSvc := auth.NewService(db, cfg.JWTSecret, accessTTL, refreshTTL)
	auditSvc := audit.NewService(db)
	jobEnqueuer := jobs.NewEnqueuer(rdb)

	// Handlers
	authHandler := auth.NewHandler(authSvc)
	leadsSvc := leads.NewService(db, auditSvc, jobEnqueuer)
	leadsHandler := leads.NewHandler(leadsSvc)
	sourcesSvc := sources.NewService(db, jobEnqueuer)
	sourcesHandler := sources.NewHandler(sourcesSvc)
	postsSvc := posts.NewService(db, jobEnqueuer)
	postsHandler := posts.NewHandler(postsSvc)
	commentsSvc := comments.NewService(db, auditSvc)
	commentsHandler := comments.NewHandler(commentsSvc, jobEnqueuer)
	approvalsSvc := approvals.NewService(db, auditSvc)
	approvalsHandler := approvals.NewHandler(approvalsSvc)
	researchHandler := research.NewHandler(db, jobEnqueuer)
	scoringHandler := scoring.NewHandler(db, jobEnqueuer)
	emailHealthSvc := email_health.NewService(db, cfg.DNSResolver)
	emailHealthHandler := email_health.NewHandler(emailHealthSvc)
	analyticsHandler := analytics.NewHandler(db)
	tasksHandler := tasks.NewHandler(db)

	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})

	r.Route("/api/v1", func(r chi.Router) {
		// Auth (rate-limited)
		r.Group(func(r chi.Router) {
			r.Use(httprate.LimitByIP(5, time.Minute))
			r.Post("/auth/login", authHandler.Login)
			r.Post("/auth/register", authHandler.Register)
			r.Post("/auth/forgot-password", authHandler.ForgotPassword)
			r.Post("/auth/reset-password", authHandler.ResetPassword)
		})

		r.Post("/auth/refresh", authHandler.Refresh)

		// Authenticated routes
		r.Group(func(r chi.Router) {
			r.Use(authSvc.Middleware)
			r.Use(httprate.LimitByIP(60, time.Minute))

			r.Post("/auth/logout", authHandler.Logout)
			r.Get("/auth/me", authHandler.Me)

			// Leads
			r.Route("/leads", func(r chi.Router) {
				r.Get("/", leadsHandler.List)
				r.Post("/", leadsHandler.Create)
				r.Post("/bulk-action", leadsHandler.BulkAction)
				r.Route("/{id}", func(r chi.Router) {
					r.Get("/", leadsHandler.Get)
					r.Patch("/", leadsHandler.Update)
					r.Delete("/", leadsHandler.Delete)
					r.Post("/advance", leadsHandler.Advance)
					r.Post("/suppress", leadsHandler.Suppress)
					r.Get("/activity", leadsHandler.Activity)
					r.Get("/score", leadsHandler.Score)
					r.Get("/research", leadsHandler.Research)
					r.Get("/comment-drafts", leadsHandler.CommentDrafts)
					r.Get("/outreach-drafts", leadsHandler.OutreachDrafts)
					r.Get("/tasks", leadsHandler.Tasks)
					r.Get("/notes", leadsHandler.Notes)
					r.Post("/notes", leadsHandler.CreateNote)
				})
			})

			// Sources
			r.Route("/sources", func(r chi.Router) {
				r.Get("/", sourcesHandler.List)
				r.Post("/", sourcesHandler.Create)
				r.Route("/{id}", func(r chi.Router) {
					r.Get("/", sourcesHandler.Get)
					r.Patch("/", sourcesHandler.Update)
					r.Delete("/", sourcesHandler.Delete)
					r.Post("/run", sourcesHandler.Run)
				})
			})

			// Posts
			r.Route("/posts", func(r chi.Router) {
				r.Get("/", postsHandler.List)
				r.Post("/", postsHandler.Create)
				r.Route("/{id}", func(r chi.Router) {
					r.Get("/", postsHandler.Get)
					r.Delete("/", postsHandler.Delete)
					r.Post("/process", postsHandler.Process)
				})
			})

			// Comment drafts
			r.Route("/comment-drafts", func(r chi.Router) {
				r.Get("/", commentsHandler.List)
				r.Post("/generate", commentsHandler.Generate)
				r.Route("/{id}", func(r chi.Router) {
					r.Get("/", commentsHandler.Get)
					r.Patch("/", commentsHandler.Update)
					r.Post("/approve", commentsHandler.Approve)
					r.Post("/reject", commentsHandler.Reject)
					r.Post("/mark-posted", commentsHandler.MarkPosted)
				})
			})

			// Approvals
			r.Route("/approvals", func(r chi.Router) {
				r.Get("/", approvalsHandler.List)
				r.Get("/count", approvalsHandler.Count)
				r.Route("/{id}", func(r chi.Router) {
					r.Get("/", approvalsHandler.Get)
					r.Post("/approve", approvalsHandler.Approve)
					r.Post("/reject", approvalsHandler.Reject)
				})
			})

			// Research
			r.Post("/research/trigger", researchHandler.Trigger)
			r.Get("/research", researchHandler.List)
			r.Get("/research/{id}", researchHandler.Get)

			// Scoring
			r.Post("/scoring/trigger", scoringHandler.Trigger)
			r.Get("/scores", scoringHandler.List)
			r.Get("/scores/{leadId}/latest", scoringHandler.Latest)

			// Email health
			r.Route("/email-health", func(r chi.Router) {
				r.Route("/domains", func(r chi.Router) {
					r.Get("/", emailHealthHandler.ListDomains)
					r.Post("/", emailHealthHandler.AddDomain)
					r.Route("/{id}", func(r chi.Router) {
						r.Get("/", emailHealthHandler.GetDomain)
						r.Delete("/", emailHealthHandler.DeleteDomain)
						r.Post("/check", emailHealthHandler.RunCheck)
						r.Get("/checks", emailHealthHandler.ListChecks)
					})
				})
				r.Route("/accounts", func(r chi.Router) {
					r.Get("/", emailHealthHandler.ListAccounts)
					r.Post("/", emailHealthHandler.AddAccount)
					r.Route("/{id}", func(r chi.Router) {
						r.Get("/", emailHealthHandler.GetAccount)
						r.Patch("/", emailHealthHandler.UpdateAccount)
						r.Delete("/", emailHealthHandler.DeleteAccount)
					})
				})
			})

			// CRM pipeline
			r.Get("/crm/pipeline", leadsHandler.Pipeline)

			// Tasks
			r.Route("/tasks", func(r chi.Router) {
				r.Get("/", tasksHandler.List)
				r.Post("/", tasksHandler.Create)
				r.Route("/{id}", func(r chi.Router) {
					r.Get("/", tasksHandler.Get)
					r.Patch("/", tasksHandler.Update)
					r.Delete("/", tasksHandler.Delete)
				})
			})

			// Analytics
			r.Route("/analytics", func(r chi.Router) {
				r.Get("/overview", analyticsHandler.Overview)
				r.Get("/leads", analyticsHandler.Leads)
				r.Get("/sources", analyticsHandler.Sources)
				r.Get("/comments", analyticsHandler.Comments)
				r.Get("/conversion", analyticsHandler.Conversion)
			})

			// Audit log
			r.Get("/audit-log", func(w http.ResponseWriter, r *http.Request) {
				auditSvc.ListHandler(w, r)
			})
		})
	})

	return r
}
