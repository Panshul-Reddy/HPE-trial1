"""
HTTP REST traffic generator.

Sends realistic GET / POST / PUT / DELETE requests to the non-MCP HTTP server
to produce labelled non-MCP traffic.

Usage:
    python -m non_mcp_traffic.http_traffic
    python -m non_mcp_traffic.http_traffic --url http://localhost:5000 --requests 50
"""

import argparse
import logging
import random
import time

import requests

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SAMPLE_PAYLOADS = [
    {"name": "widget", "color": "blue", "quantity": 10},
    {"title": "hello world", "body": "some content", "userId": 1},
    {"product": "laptop", "price": 999.99, "in_stock": True},
    {"username": "alice", "email": "alice@example.com"},
    {"key": "value", "number": 42, "flag": False},
]


def run_http_traffic(base_url: str, num_requests: int, delay: float = 0.1) -> None:
    """Generate HTTP traffic against base_url."""
    created_ids: list[int] = []

    for i in range(num_requests):
        method = random.choice(["GET", "GET", "POST", "PUT", "DELETE"])

        try:
            if method == "GET":
                if created_ids and random.random() < 0.5:
                    item_id = random.choice(created_ids)
                    r = requests.get(f"{base_url}/items/{item_id}", timeout=5)
                else:
                    r = requests.get(f"{base_url}/items", timeout=5)

            elif method == "POST":
                payload = random.choice(SAMPLE_PAYLOADS)
                r = requests.post(f"{base_url}/items", json=payload, timeout=5)
                if r.status_code == 201:
                    new_id = r.json().get("id")
                    if new_id:
                        created_ids.append(new_id)

            elif method == "PUT":
                if created_ids:
                    item_id = random.choice(created_ids)
                    payload = random.choice(SAMPLE_PAYLOADS)
                    r = requests.put(f"{base_url}/items/{item_id}", json=payload, timeout=5)
                else:
                    r = requests.get(f"{base_url}/health", timeout=5)

            elif method == "DELETE":
                if created_ids:
                    item_id = created_ids.pop(random.randrange(len(created_ids)))
                    r = requests.delete(f"{base_url}/items/{item_id}", timeout=5)
                else:
                    r = requests.get(f"{base_url}/health", timeout=5)
            else:
                r = requests.get(f"{base_url}/health", timeout=5)

            logger.debug("HTTP %s %d", method, r.status_code)

        except requests.RequestException as exc:
            logger.warning("HTTP request failed: %s", exc)

        if delay > 0:
            time.sleep(delay * random.uniform(0.5, 1.5))

    logger.info("HTTP traffic generator: sent %d requests to %s", num_requests, base_url)


def main() -> None:
    parser = argparse.ArgumentParser(description="HTTP REST Traffic Generator")
    parser.add_argument("--url", default="http://localhost:5000", help="Base URL of HTTP server")
    parser.add_argument("--requests", type=int, default=50, help="Number of HTTP requests to send")
    parser.add_argument("--delay", type=float, default=0.1, help="Mean delay between requests (s)")
    args = parser.parse_args()

    run_http_traffic(args.url, args.requests, args.delay)


if __name__ == "__main__":
    main()
