-- Database initialization SQL.
-- Creates tables, indexes, and seed data.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT FALSE,
    tier VARCHAR(50) DEFAULT 'free' NOT NULL,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_users_tier_active ON users(tier, is_active);
CREATE INDEX IF NOT EXISTS ix_users_username ON users(username);
CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    total_amount NUMERIC(12, 2) NOT NULL,
    status VARCHAR(50) DEFAULT 'PENDING' NOT NULL,
    items JSONB NOT NULL,
    shipping_address TEXT NOT NULL,
    idempotency_key VARCHAR(255) UNIQUE,
    correlation_id VARCHAR(255) NOT NULL,
    retry_count INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW() NOT NULL,
    processed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_orders_user_id ON orders(user_id);
CREATE INDEX IF NOT EXISTS ix_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS ix_orders_created_at ON orders(created_at);
CREATE INDEX IF NOT EXISTS ix_orders_idempotency_key ON orders(idempotency_key);
CREATE INDEX IF NOT EXISTS ix_orders_correlation_id ON orders(correlation_id);
CREATE INDEX IF NOT EXISTS ix_orders_created_status ON orders(created_at, status);
CREATE INDEX IF NOT EXISTS ix_orders_user_created ON orders(user_id, created_at);

-- Processed events table for idempotency
CREATE TABLE IF NOT EXISTS processed_events (
    event_id VARCHAR(255) PRIMARY KEY,
    order_id UUID NOT NULL,
    processed_at TIMESTAMP DEFAULT NOW() NOT NULL,
    ttl_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_processed_events_ttl ON processed_events(ttl_at);
CREATE INDEX IF NOT EXISTS ix_processed_events_order_id ON processed_events(order_id);

-- API keys table
CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id),
    key_hash VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(100) NOT NULL,
    rate_limit_override INTEGER,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW() NOT NULL,
    expires_at TIMESTAMP,
    last_used_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_api_keys_user_active ON api_keys(user_id, is_active);
CREATE INDEX IF NOT EXISTS ix_api_keys_key_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS ix_api_keys_expires_at ON api_keys(expires_at);

-- Auto-update updated_at timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_orders_updated_at ON orders;
CREATE TRIGGER update_orders_updated_at
    BEFORE UPDATE ON orders
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Seed a test user (password: "password123" hashed with bcrypt)
-- bcrypt hash of "password123": $2b$12$LQv3c1yqBo9SkvG3fB8G5.4w3y0L9XK6Y3kfGc3Vk3jTQ1pFmKm9nO
INSERT INTO users (username, email, hashed_password, tier)
VALUES ('demo_user', 'demo@example.com', '$2b$12$LQv3c1yqBo9SkvG3fB8G5.4w3y0L9XK6Y3kfGc3Vk3jTQ1pFmKm9nO', 'premium')
ON CONFLICT (username) DO NOTHING;

-- Analyze tables for query planner
ANALYZE;
