package config

import (
	"context"

	"github.com/sethvargo/go-envconfig"
)

type Config struct {
	AppEnv      string `env:"APP_ENV,default=development"`
	AppPort     int    `env:"APP_PORT,default=8080"`
	AppSecret   string `env:"APP_SECRET,required"`
	DatabaseURL string `env:"DATABASE_URL,required"`
	RedisURL    string `env:"REDIS_URL,required"`

	EncryptionKey string `env:"ENCRYPTION_KEY,required"`

	JWTSecret     string `env:"JWT_SECRET,required"`
	JWTAccessTTL  string `env:"JWT_ACCESS_TTL,default=15m"`
	JWTRefreshTTL string `env:"JWT_REFRESH_TTL,default=168h"`

	LiteLLMBaseURL string `env:"LITELLM_BASE_URL,required"`
	LiteLLMAPIKey  string `env:"LITELLM_API_KEY,required"`

	MeilisearchURL       string `env:"MEILISEARCH_URL,default=http://meilisearch:7700"`
	MeilisearchMasterKey string `env:"MEILISEARCH_MASTER_KEY"`

	FrontendURL string `env:"FRONTEND_URL,default=https://app.acmecorp.com"`

	SentryDSN string `env:"SENTRY_DSN"`

	DNSResolver string `env:"DNS_RESOLVER,default=8.8.8.8:53"`
}

func Load() (*Config, error) {
	var cfg Config
	if err := envconfig.Process(context.Background(), &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}
