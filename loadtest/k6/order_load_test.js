/**
 * k6 Load Testing Script for Distributed API Gateway
 *
 * Usage:
 *   k6 run loadtest/k6/order_load_test.js
 *   k6 run loadtest/k6/order_load_test.js -e STAGES=spike
 *   k6 run loadtest/k6/order_load_test.js -e BASE_URL=http://localhost:8000 -e STAGES=stress
 */
import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const STAGES_MODE = __ENV.STAGES || 'load';

const errorRate = new Rate('errors');
const orderCreation = new Trend('order_creation');
const orderReadLatency = new Trend('order_read');

const stageConfigs = {
  load: [
    { duration: '10s', target: 20 },
    { duration: '30s', target: 50 },
    { duration: '20s', target: 50 },
    { duration: '10s', target: 0 },
  ],
  spike: [
    { duration: '10s', target: 5 },
    { duration: '30s', target: 200 },
    { duration: '30s', target: 200 },
    { duration: '10s', target: 0 },
  ],
  stress: [
    { duration: '20s', target: 25 },
    { duration: '60s', target: 100 },
    { duration: '60s', target: 200 },
    { duration: '20s', target: 0 },
  ],
};

export const options = {
  stages: stageConfigs[STAGES_MODE] || stageConfigs.load,
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<1000'],
    http_req_failed: ['rate<0.05'],
    errors: ['rate<0.1'],
    order_creation: ['p(95)<800'],
  },
  noConnectionReuse: true,
};

function randomItem() {
  const products = ['Widget', 'Gadget', 'Tool', 'Device', 'System', 'Module'];
  return {
    product_id: `prod_${Math.random().toString(36).substring(7)}`,
    name: products[Math.floor(Math.random() * products.length)],
    quantity: Math.floor(Math.random() * 3) + 1,
    unit_price: parseFloat((Math.random() * 190 + 10).toFixed(2)),
  };
}

function getAuthToken() {
  const username = `loadtest_${Date.now()}_${Math.random().toString(36).substring(7)}`;

  http.post(
    `${BASE_URL}/api/v1/auth/register`,
    JSON.stringify({
      username: username,
      email: `${username}@loadtest.com`,
      password: 'TestPass123!',
    }),
    { headers: { 'Content-Type': 'application/json' } }
  );

  const loginRes = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    `username=${username}&password=TestPass123!`,
    { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
  );

  return loginRes.status === 200 ? loginRes.json('access_token') : '';
}

export function setup() {
  return { token: getAuthToken() };
}

export default function(data) {
  const headers = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${data.token}`,
  };

  group('Order Creation', () => {
    const numItems = Math.floor(Math.random() * 4) + 1;
    const items = Array.from({ length: numItems }, randomItem);
    const total = items.reduce((sum, item) => sum + item.quantity * item.unit_price, 0);

    const payload = JSON.stringify({
      items: items,
      total_amount: parseFloat(total.toFixed(2)),
      shipping_address: `${Math.floor(Math.random() * 9999)} Main St, City, ST ${Math.floor(Math.random() * 90000) + 10000}`,
      idempotency_key: `idem_${Date.now()}_${Math.random().toString(36).substring(7)}`,
    });

    const res = http.post(`${BASE_URL}/api/v1/orders`, payload, { headers });

    const success = check(res, {
      'order created': (r) => r.status === 201 || r.status === 409,
      'response has order_id': (r) => r.status === 201 && r.json('order_id') !== undefined,
      'status is PENDING': (r) => r.status === 201 && r.json('status') === 'PENDING',
      'response time < 500ms': (r) => r.timings.duration < 500,
    });

    errorRate.add(!success);
    if (res.status === 201) orderCreation.add(res.timings.duration);
  });

  sleep(Math.random() * 0.5 + 0.1);
}

export function handleSummary(data) {
  const m = data.metrics;
  const p95 = m.http_req_duration?.values?.['p(95)'] || 0;
  const p99 = m.http_req_duration?.values?.['p(99)'] || 0;
  const avg = m.http_req_duration?.values?.avg || 0;
  const total = m.http_reqs?.values?.count || 0;
  const rps = m.http_reqs?.values?.rate || 0;
  const failRate = m.http_req_failed?.values?.rate || 0;

  return {
    'stdout': `
===============================================
  LOAD TEST RESULTS (${STAGES_MODE.toUpperCase()})
===============================================
  Total Requests:     ${total}
  Requests/sec (RPS): ${rps.toFixed(2)}
  Failure Rate:       ${(failRate * 100).toFixed(2)}%
  Avg Latency:        ${avg.toFixed(2)} ms
  P95 Latency:        ${p95.toFixed(2)} ms
  P99 Latency:        ${p99.toFixed(2)} ms
===============================================
`,
    'loadtest/results/summary.json': JSON.stringify({
      total_requests: total,
      rps: parseFloat(rps.toFixed(2)),
      failure_rate: parseFloat((failRate * 100).toFixed(2)),
      avg_latency_ms: parseFloat(avg.toFixed(2)),
      p95_latency_ms: parseFloat(p95.toFixed(2)),
      p99_latency_ms: parseFloat(p99.toFixed(2)),
    }, null, 2),
  };
}
