package auth

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"
)

var (
	ErrInvalidCredentials = errors.New("invalid credentials")
	ErrUserNotFound       = errors.New("user not found")
	ErrTokenInvalid       = errors.New("token invalid")
)

type User struct {
	ID        uuid.UUID
	OrgID     uuid.UUID
	Email     string
	Name      string
	AvatarURL *string
	Role      string
	CreatedAt time.Time
}

type LoginResult struct {
	AccessToken  string
	RefreshToken string
	ExpiresAt    time.Time
	User         *User
}

type claims struct {
	UserID string `json:"uid"`
	OrgID  string `json:"oid"`
	Role   string `json:"role"`
	Type   string `json:"typ"` // access|refresh
	jwt.RegisteredClaims
}

type Service struct {
	db            *pgxpool.Pool
	jwtSecret     []byte
	accessTTL     time.Duration
	refreshTTL    time.Duration
}

func NewService(db *pgxpool.Pool, jwtSecret string, accessTTL, refreshTTL time.Duration) *Service {
	return &Service{
		db:         db,
		jwtSecret:  []byte(jwtSecret),
		accessTTL:  accessTTL,
		refreshTTL: refreshTTL,
	}
}

func (s *Service) Login(ctx context.Context, email, password, ip, userAgent string) (*LoginResult, error) {
	var user User
	var passwordHash string

	err := s.db.QueryRow(ctx, `
		SELECT id, org_id, email, name, avatar_url, role, password_hash
		FROM users
		WHERE email = $1 AND deleted_at IS NULL
	`, email).Scan(
		&user.ID, &user.OrgID, &user.Email, &user.Name,
		&user.AvatarURL, &user.Role, &passwordHash,
	)
	if err != nil {
		return nil, ErrInvalidCredentials
	}

	if err := bcrypt.CompareHashAndPassword([]byte(passwordHash), []byte(password)); err != nil {
		return nil, ErrInvalidCredentials
	}

	accessToken, expiresAt, err := s.mintToken(&user, "access", s.accessTTL)
	if err != nil {
		return nil, fmt.Errorf("mint access token: %w", err)
	}

	refreshToken, _, err := s.mintToken(&user, "refresh", s.refreshTTL)
	if err != nil {
		return nil, fmt.Errorf("mint refresh token: %w", err)
	}

	// Store refresh token hash in sessions
	hash, _ := bcrypt.GenerateFromPassword([]byte(refreshToken), 10)
	_, _ = s.db.Exec(ctx, `
		INSERT INTO sessions (user_id, token_hash, ip_address, user_agent, expires_at)
		VALUES ($1, $2, $3::inet, $4, $5)
	`, user.ID, string(hash), ip, userAgent, time.Now().Add(s.refreshTTL))

	// Update last login
	_, _ = s.db.Exec(ctx, `UPDATE users SET last_login_at = NOW() WHERE id = $1`, user.ID)

	return &LoginResult{
		AccessToken:  accessToken,
		RefreshToken: refreshToken,
		ExpiresAt:    expiresAt,
		User:         &user,
	}, nil
}

func (s *Service) Logout(ctx context.Context, token string) error {
	c, err := s.parseToken(token, "access")
	if err != nil {
		return ErrTokenInvalid
	}
	userID, _ := uuid.Parse(c.UserID)
	_, err = s.db.Exec(ctx, `DELETE FROM sessions WHERE user_id = $1`, userID)
	return err
}

func (s *Service) RefreshToken(ctx context.Context, refreshToken string) (*LoginResult, error) {
	c, err := s.parseToken(refreshToken, "refresh")
	if err != nil {
		return nil, ErrTokenInvalid
	}

	userID, _ := uuid.Parse(c.UserID)
	var user User
	err = s.db.QueryRow(ctx, `
		SELECT id, org_id, email, name, avatar_url, role
		FROM users WHERE id = $1 AND deleted_at IS NULL
	`, userID).Scan(&user.ID, &user.OrgID, &user.Email, &user.Name, &user.AvatarURL, &user.Role)
	if err != nil {
		return nil, ErrUserNotFound
	}

	accessToken, expiresAt, err := s.mintToken(&user, "access", s.accessTTL)
	if err != nil {
		return nil, err
	}
	newRefresh, _, err := s.mintToken(&user, "refresh", s.refreshTTL)
	if err != nil {
		return nil, err
	}

	return &LoginResult{
		AccessToken:  accessToken,
		RefreshToken: newRefresh,
		ExpiresAt:    expiresAt,
		User:         &user,
	}, nil
}

func (s *Service) GetCurrentUser(ctx context.Context) (*User, error) {
	c, ok := ctx.Value(claimsKey{}).(*claims)
	if !ok {
		return nil, ErrTokenInvalid
	}
	userID, _ := uuid.Parse(c.UserID)
	var user User
	err := s.db.QueryRow(ctx, `
		SELECT id, org_id, email, name, avatar_url, role, created_at
		FROM users WHERE id = $1 AND deleted_at IS NULL
	`, userID).Scan(&user.ID, &user.OrgID, &user.Email, &user.Name, &user.AvatarURL, &user.Role, &user.CreatedAt)
	if err != nil {
		return nil, ErrUserNotFound
	}
	return &user, nil
}

func (s *Service) ValidateAccessToken(tokenStr string) (*claims, error) {
	return s.parseToken(tokenStr, "access")
}

func (s *Service) mintToken(user *User, tokenType string, ttl time.Duration) (string, time.Time, error) {
	expiresAt := time.Now().Add(ttl)
	c := &claims{
		UserID: user.ID.String(),
		OrgID:  user.OrgID.String(),
		Role:   user.Role,
		Type:   tokenType,
		RegisteredClaims: jwt.RegisteredClaims{
			ExpiresAt: jwt.NewNumericDate(expiresAt),
			IssuedAt:  jwt.NewNumericDate(time.Now()),
			Subject:   user.ID.String(),
		},
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, c)
	signed, err := token.SignedString(s.jwtSecret)
	return signed, expiresAt, err
}

func (s *Service) parseToken(tokenStr, expectedType string) (*claims, error) {
	token, err := jwt.ParseWithClaims(tokenStr, &claims{}, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method")
		}
		return s.jwtSecret, nil
	})
	if err != nil || !token.Valid {
		return nil, ErrTokenInvalid
	}
	c, ok := token.Claims.(*claims)
	if !ok || c.Type != expectedType {
		return nil, ErrTokenInvalid
	}
	return c, nil
}

type RegisterInput struct {
	Email    string
	Password string
	FullName string
	OrgName  string
}

func (s *Service) Register(ctx context.Context, input RegisterInput) (*LoginResult, error) {
	if input.Email == "" || input.Password == "" || input.FullName == "" || input.OrgName == "" {
		return nil, errors.New("all fields required")
	}
	if len(input.Password) < 8 {
		return nil, errors.New("password must be at least 8 characters")
	}

	var exists int
	_ = s.db.QueryRow(ctx, `SELECT COUNT(*) FROM users WHERE email = $1`, input.Email).Scan(&exists)
	if exists > 0 {
		return nil, errors.New("email already registered")
	}

	hash, err := bcrypt.GenerateFromPassword([]byte(input.Password), 12)
	if err != nil {
		return nil, fmt.Errorf("hash password: %w", err)
	}

	slug := toSlug(input.OrgName)

	tx, err := s.db.Begin(ctx)
	if err != nil {
		return nil, fmt.Errorf("begin tx: %w", err)
	}
	defer tx.Rollback(ctx)

	orgID := uuid.New()
	if _, err = tx.Exec(ctx, `
		INSERT INTO organizations (id, name, slug, plan)
		VALUES ($1, $2, $3, 'free')
	`, orgID, input.OrgName, slug); err != nil {
		return nil, fmt.Errorf("create org: %w", err)
	}

	userID := uuid.New()
	if _, err = tx.Exec(ctx, `
		INSERT INTO users (id, org_id, email, name, password_hash, role)
		VALUES ($1, $2, $3, $4, $5, 'admin')
	`, userID, orgID, input.Email, input.FullName, string(hash)); err != nil {
		return nil, fmt.Errorf("create user: %w", err)
	}

	if err = tx.Commit(ctx); err != nil {
		return nil, fmt.Errorf("commit: %w", err)
	}

	return s.Login(ctx, input.Email, input.Password, "", "")
}

func (s *Service) ForgotPassword(ctx context.Context, email string) (string, error) {
	var userID uuid.UUID
	err := s.db.QueryRow(ctx, `SELECT id FROM users WHERE email=$1 AND deleted_at IS NULL`, email).Scan(&userID)
	if err != nil {
		return "", nil // always succeed to prevent email enumeration
	}

	tokenBytes := make([]byte, 32)
	if _, err := rand.Read(tokenBytes); err != nil {
		return "", err
	}
	token := hex.EncodeToString(tokenBytes)

	_, _ = s.db.Exec(ctx, `
		INSERT INTO sessions (user_id, token_hash, ip_address, user_agent, expires_at)
		VALUES ($1, $2, '0.0.0.0'::inet, 'password-reset', $3)
	`, userID, "reset:"+token, time.Now().Add(1*time.Hour))

	return token, nil // in production, email this token; for now return it
}

func (s *Service) ResetPassword(ctx context.Context, token, newPassword string) error {
	if len(newPassword) < 8 {
		return errors.New("password must be at least 8 characters")
	}
	var userID uuid.UUID
	err := s.db.QueryRow(ctx, `
		SELECT user_id FROM sessions
		WHERE token_hash = $1 AND expires_at > NOW() AND user_agent = 'password-reset'
	`, "reset:"+token).Scan(&userID)
	if err != nil {
		return errors.New("invalid or expired reset token")
	}

	hash, err := bcrypt.GenerateFromPassword([]byte(newPassword), 12)
	if err != nil {
		return err
	}

	_, err = s.db.Exec(ctx, `
		UPDATE users SET password_hash=$1, updated_at=NOW() WHERE id=$2
	`, string(hash), userID)
	if err != nil {
		return err
	}

	_, _ = s.db.Exec(ctx, `
		DELETE FROM sessions WHERE token_hash=$1
	`, "reset:"+token)

	return nil
}

func toSlug(name string) string {
	slug := strings.ToLower(name)
	slug = regexp.MustCompile(`[^a-z0-9]+`).ReplaceAllString(slug, "-")
	slug = strings.Trim(slug, "-")
	if slug == "" {
		b := make([]byte, 4)
		_, _ = rand.Read(b)
		slug = hex.EncodeToString(b)
	}
	return slug
}

type claimsKey struct{}
