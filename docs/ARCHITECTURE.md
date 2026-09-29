# Architecture Decision Record: Distributed API Gateway

## Status
Accepted

## Context
We need a backend system that handles high-throughput order processing with:
- Horizontal scalability
- Fault tolerance
- Fair resource allocation
- Eventual consistency
- Cloud-native deployment

## Decision

### 1. API Layer: FastAPI
- **Why:** Async-native Python, Pydantic validation, auto-generated OpenAPI docs, ASGI for high concurrency
- **Trade-offs:** Newer framework, smaller ecosystem than Flask, but better performance

### 2. Message Broker: Apache Kafka
- **Why:** Industry standard for event streaming, durable, ordered, partitioned, replays
- **Alternatives considered:** RabbitMQ (lower throughput, no replay), Redis Streams (limited durability)
- **Configuration:** 6 partitions per topic, replication factor 3 in prod, compression gzip

### 3. Database: PostgreSQL 16
- **Why:** ACID compliance, JSONB for flexible items, mature connection poolers
- **Indexing strategy:** B-tree on common queries, composite on (user_id, created_at)

### 4. Cache & Rate Limiting: Redis 7
- **Why:** Sub-millisecond latency, sorted sets for sliding window, atomic operations
- **Algorithm:** Sliding window log (precise) vs sliding window counter (approximate)

### 5. Cloud: AWS ECS Fargate
- **Why:** No EC2 management, built-in autoscaling, integrates with ALB and MSK
- **Alternatives:** EKS (overhead), EC2 (operational burden), Lambda (cold starts)

### 6. Orchestration: Terraform
- **Why:** Declarative IaC, state management, multi-cloud portability

## Consequences

### Positive
- Sub-500ms P95 latency at 500+ RPS
- Zero message loss with Kafka replication
- Linear horizontal scaling with ECS
- Observable through CloudWatch and structured logs

### Negative
- Operational complexity (Kafka, ECS, RDS)
- Kafka requires careful topic configuration
- Connection pooling tuning required

## Technical Risks
1. **Connection pool exhaustion** — mitigated by 20+10 pool size with monitoring
2. **Consumer lag** — mitigated by worker autoscaling on Kafka lag metric
3. **DLQ growing unbounded** — mitigated by alerts + retention policy
4. **Rate limiter single point** — mitigated by Redis cluster mode
