# Distributed Rate-Limited API Gateway
### Event-Driven Order Processing System - Final Year Project

> High-throughput backend system with FastAPI, Kafka, PostgreSQL, and Redis. Designed for AWS ECS deployment with autoscaling.

---

## Architecture Overview

```
                        ┌─────────────────┐
                        │   AWS ALB       │
                        │  (Load Balance) │
                        └────────┬────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
        ┌─────▼──────┐    ┌─────▼──────┐    ┌─────▼──────┐
        │  ECS       │    │  ECS       │    │  ECS       │
        │ Gateway #1  │    │ Gateway #2  │    │ Gateway #N  │
        │ (4 workers) │    │ (4 workers) │    │ (4 workers) │
        └─────┬──────┘    └─────┬──────┘    └─────┬──────┘
              │                 │                  │
              └─────────────────┼──────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                        │
  ┌─────▼──────┐         ┌─────▼──────┐        ┌──────▼───────┐
  │   Redis    │         │ PostgreSQL  │        │    Kafka      │
  │ Rate Limit │         │  (Orders)   │        │ orders topic  │
  └────────────┘         └─────────────┘        └──────┬───────┘
                                                        │
                                               ┌────────▼────────┐
                                               │  ECS Workers    │
                                               │ (Auto-scale 1-10)│
                                               └─────────────────┘
```

## Quick Start

### 1. Start Infrastructure
```bash
docker compose -f infra/docker/docker-compose.yml up -d
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Create Database Tables
```bash
python scripts/create_tables.py
```

### 4. Run Gateway
```bash
uvicorn gateway.app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 5. Run Worker
```bash
python -m worker.app.consumer
```

### 6. Run Tests
```bash
pytest gateway/tests/ worker/tests/ -v
```

> New to the project? Read **`PROJECT_GUIDE.txt`** — a complete walkthrough of
> the architecture, every technology in the stack, the design patterns, and a
> study roadmap.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Register new user |
| POST | `/api/v1/auth/login` | Get JWT token |
| POST | `/api/v1/orders` | Create order |
| GET | `/api/v1/orders/{id}` | Get order status |
| GET | `/api/v1/orders` | List orders |
| GET | `/health` | Health check |

## Load Testing

### Locust
```bash
locust -f loadtest/locust/order_load_test.py \
  --host http://localhost:8000 \
  --users 100 --spawn-rate 10 --run-time 60s \
  --headless --csv=loadtest/results/run_1
```

### k6
```bash
k6 run loadtest/k6/order_load_test.js \
  -e BASE_URL=http://localhost:8000 -e STAGES=load
```

## Key Features

- **Distributed Rate Limiting** - Redis sliding window, per-user/IP/tier limits
- **Event-Driven Processing** - Kafka with retry and dead-letter queues
- **Idempotency** - Idempotency key headers + Postgres unique constraints
- **Async Processing** - Full async/await with connection pooling
- **Autoscaling** - AWS ECS with CPU/memory-based policies
- **Infrastructure as Code** - Full Terraform for AWS deployment

## Project Structure

```
distributed-api-gateway/
├── gateway/           FastAPI API Gateway
│   ├── app/
│   │   ├── api/v1/   REST endpoints
│   │   ├── core/     Security & config
│   │   ├── db/       Async DB sessions
│   │   ├── models/   SQLAlchemy models
│   │   ├── schemas/  Pydantic schemas
│   │   └── services/  Business logic
│   └── tests/
├── worker/           Kafka consumer worker
│   ├── app/
│   │   ├── consumer.py  Main consumer
│   │   ├── processor.py Order processing
│   │   └── db.py       Worker DB session
│   └── tests/
├── common/          Shared code
├── infra/
│   ├── docker/      Dockerfiles & Compose
│   └── terraform/   AWS ECS infrastructure
├── loadtest/        Locust + k6 tests
├── scripts/         DB init scripts
└── docs/            Project report
```

## Expected Performance

| Metric | Value |
|--------|-------|
| P95 Latency | < 300ms |
| P99 Latency | < 500ms |
| Throughput | 500+ RPS |
| Error Rate | < 1% |

## AWS Deployment

```bash
cd infra/terraform
terraform init
terraform plan -var="db_password=YOUR_PASSWORD"
terraform apply -var="db_password=YOUR_PASSWORD"
```

See `docs/PROJECT_REPORT.md` for the full technical report.
