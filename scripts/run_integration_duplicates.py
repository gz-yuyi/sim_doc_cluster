#!/usr/bin/env python3
"""Simple integration test that verifies duplicate articles form a cluster."""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Callable

import httpx


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def build_article(article_id: str, title: str, content: str) -> dict:
    return {
        "article_id": article_id,
        "title": title,
        "content": content,
        "publish_time": iso_now(),
        "source": "integration_suite",
        "state": 1,
        "top": 0,
        "tags": [{"id": 42, "name": "integration"}],
        "topic": [{"id": "topic_integration", "name": "integration"}],
    }


def with_retry(fn: Callable[[], httpx.Response], attempts: int = 3, pause: float = 0.5) -> httpx.Response:
    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(pause)
    raise last_exc if last_exc else RuntimeError("retry failed")


def fetch_cluster_id(client: httpx.Client, article_id: str, attempts: int = 5, pause: float = 0.8) -> str:
    for _ in range(attempts):
        resp = client.get(f"/api/v1/articles/{article_id}")
        resp.raise_for_status()
        article = resp.json().get("article", {})
        cluster_id = article.get("cluster_id")
        if cluster_id:
            return cluster_id
        time.sleep(pause)
    raise AssertionError(f"article {article_id} never received cluster_id")


def run(base_url: str, timeout: float) -> None:
    aid_prefix = uuid.uuid4().hex[:8]
    doc_a = build_article(f"int_{aid_prefix}_a", "香港大埔公寓火灾", "香港大埔公寓发生火灾，消防正在扑救。")
    doc_b = build_article(f"int_{aid_prefix}_b", "香港大埔居民楼火灾", "香港大埔公寓发生火灾，消防正在扑救。")

    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        # Health
        health = with_retry(lambda: client.get("/api/v1/system/health"))
        health.raise_for_status()
        status = health.json().get("status")
        print(f"[health] status={status}")

        # Submit docs
        for doc in (doc_a, doc_b):
            resp = client.post("/api/v1/articles/", json=doc)
            resp.raise_for_status()
            print(f"[submit] {doc['article_id']} ok")

        # Fetch clusters
        cluster_a = fetch_cluster_id(client, doc_a["article_id"])
        cluster_b = fetch_cluster_id(client, doc_b["article_id"])
        assert cluster_a == cluster_b, "duplicate articles did not share cluster"
        print(f"[cluster] shared cluster_id={cluster_a}")

        # Similar endpoint
        similar = client.get(f"/api/v1/articles/{doc_b['article_id']}/similar")
        similar.raise_for_status()
        articles = [item["article_id"] for item in similar.json().get("articles", [])]
        assert doc_a["article_id"] in articles, "expected article A in similar list"
        print(f"[similar] {doc_b['article_id']} sees {articles}")

    print("✅ integration test passed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Duplicate clustering integration test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout in seconds")
    args = parser.parse_args()

    try:
        run(args.base_url, args.timeout)
    except AssertionError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception as exc:  # noqa: BLE001
        print(f"❌ unexpected error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()

