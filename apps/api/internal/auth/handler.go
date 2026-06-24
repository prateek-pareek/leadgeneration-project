package auth

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/acmecorp/prospectOS/api/internal/shared/respond"
)

type Handler struct {
	svc *Service
}

func NewHandler(svc *Service) *Handler {
	return &Handler{svc: svc}
}

type loginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

type loginResponse struct {
	AccessToken  string    `json:"access_token"`
	RefreshToken string    `json:"refresh_token"`
	ExpiresAt    time.Time `json:"expires_at"`
	User         userDTO   `json:"user"`
}

func (h *Handler) Login(w http.ResponseWriter, r *http.Request) {
	var req loginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respond.BadRequest(w, "invalid request body")
		return
	}
	if req.Email == "" || req.Password == "" {
		respond.BadRequest(w, "email and password required")
		return
	}

	result, err := h.svc.Login(r.Context(), req.Email, req.Password, r.RemoteAddr, r.UserAgent())
	if err != nil {
		respond.Unauthorized(w, "invalid credentials")
		return
	}

	respond.JSON(w, http.StatusOK, loginResponse{
		AccessToken:  result.AccessToken,
		RefreshToken: result.RefreshToken,
		ExpiresAt:    result.ExpiresAt,
		User:         toUserDTO(result.User),
	})
}

func (h *Handler) Logout(w http.ResponseWriter, r *http.Request) {
	token := extractBearerToken(r)
	if token == "" {
		respond.Unauthorized(w, "missing token")
		return
	}
	if err := h.svc.Logout(r.Context(), token); err != nil {
		respond.InternalError(w, "logout failed")
		return
	}
	respond.JSON(w, http.StatusOK, map[string]string{"message": "logged out"})
}

func (h *Handler) Me(w http.ResponseWriter, r *http.Request) {
	user, err := h.svc.GetCurrentUser(r.Context())
	if err != nil {
		respond.Unauthorized(w, "not authenticated")
		return
	}
	respond.JSON(w, http.StatusOK, toUserDTO(user))
}

func (h *Handler) Refresh(w http.ResponseWriter, r *http.Request) {
	var body struct {
		RefreshToken string `json:"refresh_token"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		respond.BadRequest(w, "invalid body")
		return
	}

	result, err := h.svc.RefreshToken(r.Context(), body.RefreshToken)
	if err != nil {
		respond.Unauthorized(w, "invalid or expired refresh token")
		return
	}

	respond.JSON(w, http.StatusOK, loginResponse{
		AccessToken:  result.AccessToken,
		RefreshToken: result.RefreshToken,
		ExpiresAt:    result.ExpiresAt,
		User:         toUserDTO(result.User),
	})
}

type registerRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
	FullName string `json:"full_name"`
	OrgName  string `json:"org_name"`
}

func (h *Handler) Register(w http.ResponseWriter, r *http.Request) {
	var req registerRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		respond.BadRequest(w, "invalid request body")
		return
	}

	result, err := h.svc.Register(r.Context(), RegisterInput{
		Email:    req.Email,
		Password: req.Password,
		FullName: req.FullName,
		OrgName:  req.OrgName,
	})
	if err != nil {
		respond.Conflict(w, err.Error())
		return
	}

	respond.JSON(w, http.StatusCreated, loginResponse{
		AccessToken:  result.AccessToken,
		RefreshToken: result.RefreshToken,
		ExpiresAt:    result.ExpiresAt,
		User:         toUserDTO(result.User),
	})
}

func (h *Handler) ForgotPassword(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Email string `json:"email"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Email == "" {
		respond.BadRequest(w, "email required")
		return
	}
	// Always return 200 to prevent email enumeration
	_, _ = h.svc.ForgotPassword(r.Context(), body.Email)
	respond.JSON(w, http.StatusOK, map[string]string{
		"message": "If that email exists, a reset link has been sent.",
	})
}

func (h *Handler) ResetPassword(w http.ResponseWriter, r *http.Request) {
	var body struct {
		Token    string `json:"token"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		respond.BadRequest(w, "invalid body")
		return
	}
	if err := h.svc.ResetPassword(r.Context(), body.Token, body.Password); err != nil {
		respond.BadRequest(w, err.Error())
		return
	}
	respond.JSON(w, http.StatusOK, map[string]string{"message": "password updated"})
}

func extractBearerToken(r *http.Request) string {
	header := r.Header.Get("Authorization")
	if len(header) > 7 && header[:7] == "Bearer " {
		return header[7:]
	}
	return ""
}
