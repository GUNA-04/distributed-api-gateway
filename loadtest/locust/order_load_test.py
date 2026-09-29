"""
Locust load testing for the API Gateway.
Tests order creation endpoints under realistic traffic patterns.

Usage:
  pip install locust
  locust -f loadtest/locust/order_load_test.py --host http://localhost:8000 --users 100 --spawn-rate 10 --run-time 60s --headless --csv=loadtest/results/run_1
"""
import random
import uuid
import json
from locust import HttpUser, task, between, events
from faker import Faker

fake = Faker()


class OrderUser(HttpUser):
    """
    Simulates a typical user making order API requests.
    Mimics real traffic: 70% order creation, 20% order status, 10% list.
    """

    wait_time = between(100, 500)
    weight = 1

    def on_start(self):
        self.user_id = str(uuid.uuid4())
        self.token = self._register_and_login()
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def _register_and_login(self) -> str:
        username = f"user_{uuid.uuid4().hex[:8]}"
        password = "TestPass123!"

        try:
            self.client.post(
                "/api/v1/auth/register",
                json={
                    "username": username,
                    "email": f"{username}@test.com",
                    "password": password,
                },
                name="POST /auth/register"
            )
        except Exception:
            pass

        response = self.client.post(
            "/api/v1/auth/login",
            data={"username": username, "password": password},
            name="POST /auth/login"
        )

        if response.status_code == 200:
            return response.json().get("access_token", "")
        return ""

    @task(70)
    def create_order(self):
        if not self.token:
            return

        num_items = random.randint(1, 5)
        items = []
        total = 0
        for _ in range(num_items):
            qty = random.randint(1, 3)
            price = round(random.uniform(10, 200), 2)
            items.append({
                "product_id": str(uuid.uuid4()),
                "name": fake.word(),
                "quantity": qty,
                "unit_price": price,
            })
            total += qty * price

        order_data = {
            "items": items,
            "total_amount": round(total, 2),
            "shipping_address": fake.address(),
        }

        with self.client.post(
            "/api/v1/orders",
            json=order_data,
            headers=self.headers,
            name="POST /orders",
            catch_response=True,
        ) as response:
            if response.status_code == 201:
                response.success()
            elif response.status_code == 429:
                response.failure("Rate limited")
            else:
                response.failure(f"Got status {response.status_code}")

    @task(20)
    def get_order_status(self):
        if not self.token:
            return
        order_id = str(uuid.uuid4())
        with self.client.get(
            f"/api/v1/orders/{order_id}",
            headers=self.headers,
            name="GET /orders/{id}",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 404):
                response.success()
            else:
                response.failure(f"Got status {response.status_code}")

    @task(10)
    def list_orders(self):
        if not self.token:
            return
        with self.client.get(
            "/api/v1/orders",
            params={"limit": 20, "offset": 0},
            headers=self.headers,
            name="GET /orders",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 401):
                response.success()
            else:
                response.failure(f"Got status {response.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("=" * 60)
    print("LOAD TEST STARTED")
    print(f"Host: {environment.host}")
    print(f"Users: {environment.runner.target_user_count if hasattr(environment.runner, 'target_user_count') else 'N/A'}")
    print("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("=" * 60)
    print("LOAD TEST COMPLETED")
    stats = environment.stats
    print(f"Total requests: {stats.total.num_requests}")
    print(f"Total failures: {stats.total.num_failures}")
    print(f"Median response time: {stats.total.median_response_time}ms")
    print(f"P95 response time: {stats.total.get_response_time_percentile(0.95)}ms")
    print(f"P99 response time: {stats.total.get_response_time_percentile(0.99)}ms")
    print(f"RPS: {stats.total.total_rps:.2f}")
    print("=" * 60)
