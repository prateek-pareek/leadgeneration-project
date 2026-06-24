package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/acmecorp/prospectOS/api/internal/shared/config"
	"github.com/acmecorp/prospectOS/api/internal/shared/db"
	"github.com/acmecorp/prospectOS/api/internal/shared/logger"
	"github.com/acmecorp/prospectOS/api/internal/shared/redis"
	"github.com/acmecorp/prospectOS/api/internal/router"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		fmt.Fprintf(os.Stderr, "config error: %v\n", err)
		os.Exit(1)
	}

	log := logger.New(cfg.AppEnv)
	slog.SetDefault(log)

	pool, err := db.Connect(cfg.DatabaseURL)
	if err != nil {
		log.Error("db connect failed", "err", err)
		os.Exit(1)
	}
	defer pool.Close()

	if err := db.RunMigrations(cfg.DatabaseURL); err != nil {
		log.Error("migrations failed", "err", err)
		os.Exit(1)
	}

	rdb, err := redis.Connect(cfg.RedisURL)
	if err != nil {
		log.Error("redis connect failed", "err", err)
		os.Exit(1)
	}
	defer rdb.Close()

	r := router.New(cfg, pool, rdb, log)

	srv := &http.Server{
		Addr:         fmt.Sprintf(":%d", cfg.AppPort),
		Handler:      r,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	go func() {
		log.Info("server starting", "port", cfg.AppPort, "env", cfg.AppEnv)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Error("server error", "err", err)
			os.Exit(1)
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Info("shutting down...")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		log.Error("shutdown error", "err", err)
	}
}
