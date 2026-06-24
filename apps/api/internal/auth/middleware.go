package auth

import (
	"context"
	"net/http"
	"strings"

	"github.com/google/uuid"
	"github.com/acmecorp/prospectOS/api/internal/shared/middleware"
	"github.com/acmecorp/prospectOS/api/internal/shared/respond"
)

func (s *Service) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		header := r.Header.Get("Authorization")
		if !strings.HasPrefix(header, "Bearer ") {
			respond.Unauthorized(w, "missing authorization token")
			return
		}

		token := strings.TrimPrefix(header, "Bearer ")
		c, err := s.ValidateAccessToken(token)
		if err != nil {
			respond.Unauthorized(w, "invalid or expired token")
			return
		}

		userID, err := uuid.Parse(c.UserID)
		if err != nil {
			respond.Unauthorized(w, "invalid token claims")
			return
		}
		orgID, err := uuid.Parse(c.OrgID)
		if err != nil {
			respond.Unauthorized(w, "invalid token claims")
			return
		}

		ctx := context.WithValue(r.Context(), middleware.UserIDKey, userID)
		ctx = context.WithValue(ctx, middleware.OrgIDKey, orgID)
		ctx = context.WithValue(ctx, middleware.UserRoleKey, c.Role)
		ctx = context.WithValue(ctx, claimsKey{}, c)

		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

func RequireRole(roles ...string) func(http.Handler) http.Handler {
	allowed := make(map[string]bool, len(roles))
	for _, r := range roles {
		allowed[r] = true
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			role, ok := middleware.GetUserRole(r.Context())
			if !ok || !allowed[role] {
				respond.Forbidden(w, "insufficient permissions")
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}
