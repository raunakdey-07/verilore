"""`GET /metrics` exists, speaks Prometheus, and says nothing about content (#113).

The issue said there was no metrics endpoint. There is: the app has been
instrumented with `prometheus-fastapi-instrumentator` since the Phase 1 scaffold, and
it was never documented or tested, so the gap analysis recorded it as missing.
These tests pin what an operator can rely on: the endpoint answers without a
credential, like `/health`; it counts requests by route template, method and
status class; and no label carries a corpus name, a path or a query.
"""

from __future__ import annotations

import re
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from verilore.api.main import _UNAUTHENTICATED_PREFIXES, app

#: Every label the HTTP series may carry. A new label is a decision about what
#: leaves the service, so it has to be added here on purpose.
HTTP_LABELS = {"handler", "method", "status", "le"}


async def test_metrics_speak_prometheus_and_count_requests_by_route():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        live = await client.get("/health/live")
        assert live.status_code == 200, live.text
        response = await client.get("/metrics")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain"), response.headers
    text = response.text
    assert "# TYPE http_requests_total counter" in text
    assert "# TYPE http_request_duration_seconds histogram" in text
    counted = re.search(
        r'^http_requests_total\{handler="/health/live",method="GET",status="2xx"\} (\d+)',
        text,
        re.M,
    )
    assert counted and int(counted.group(1)) >= 1, text[:2000]


async def test_metrics_need_no_credential_like_health():
    assert "/metrics" in _UNAUTHENTICATED_PREFIXES


async def test_no_label_carries_a_corpus_a_path_or_a_query():
    corpus = f"t{uuid4().hex[:12]}"
    marker = f"needle{uuid4().hex[:8]}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # The status does not matter here: found or not, the request is counted.
        await client.post("/api/memory/current", json={"corpus": corpus, "query": marker})
        text = (await client.get("/metrics")).text
    assert corpus not in text and marker not in text
    assert 'handler="/api/memory/' in text, "the memory route is not counted"
    http_lines = [line for line in text.splitlines() if line.startswith("http_")]
    labels = {name for line in http_lines for name in re.findall(r'(\w+)="', line)}
    assert labels <= HTTP_LABELS, sorted(labels - HTTP_LABELS)
