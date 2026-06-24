package redis

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/redis/go-redis/v9"
)

func Connect(url string) (*redis.Client, error) {
	opts, err := redis.ParseURL(url)
	if err != nil {
		return nil, fmt.Errorf("parse redis url: %w", err)
	}

	client := redis.NewClient(opts)
	if err := client.Ping(context.Background()).Err(); err != nil {
		return nil, fmt.Errorf("ping redis: %w", err)
	}

	return client, nil
}

func Enqueue(ctx context.Context, rdb *redis.Client, queue string, payload any) error {
	b, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal job: %w", err)
	}
	return rdb.LPush(ctx, queue, b).Err()
}

func SetWithTTL(ctx context.Context, rdb *redis.Client, key string, value any, ttl time.Duration) error {
	b, err := json.Marshal(value)
	if err != nil {
		return err
	}
	return rdb.Set(ctx, key, b, ttl).Err()
}

func Get[T any](ctx context.Context, rdb *redis.Client, key string) (T, bool, error) {
	var zero T
	raw, err := rdb.Get(ctx, key).Bytes()
	if err == redis.Nil {
		return zero, false, nil
	}
	if err != nil {
		return zero, false, err
	}
	var val T
	if err := json.Unmarshal(raw, &val); err != nil {
		return zero, false, err
	}
	return val, true, nil
}
