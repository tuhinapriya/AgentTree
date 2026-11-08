from __future__ import annotations

import requests


def reset_demo(base_url: str = "http://127.0.0.1:8000", run_id: str = "agenttree-transactional-demo") -> dict:
    cleanup = requests.post(f"{base_url}/runs/{run_id}/cleanup", timeout=10)
    cleanup.raise_for_status()
    response = requests.post(f"{base_url}/runs/{run_id}/demo/reset", timeout=10)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reset the demo run state")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--run-id", default="agenttree-transactional-demo")
    args = parser.parse_args()
    print(reset_demo(args.base_url, args.run_id))
