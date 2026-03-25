#!/usr/bin/env python3
"""Performance profiling script for STS2 MCP server."""

import time
import requests
import json
import sys
from statistics import mean, stdev
from typing import Callable

GAME_API_URL = "http://127.0.0.1:8080"

def measure_operation(name: str, operation: Callable, iterations: int = 10) -> None:
    """Measure operation latency."""
    times = []
    errors = 0

    print(f"\n📊 Measuring: {name}")
    print(f"   Running {iterations} iterations...")

    for i in range(iterations):
        try:
            start = time.perf_counter()
            result = operation()
            elapsed = (time.perf_counter() - start) * 1000  # ms
            times.append(elapsed)
            if i == 0:
                print(f"   ✓ First iteration: {elapsed:.2f}ms")
        except Exception as e:
            errors += 1
            print(f"   ✗ Error: {e}")

    if times:
        avg = mean(times)
        min_t = min(times)
        max_t = max(times)
        std = stdev(times) if len(times) > 1 else 0

        print(f"   Results: avg={avg:.2f}ms, min={min_t:.2f}ms, max={max_t:.2f}ms, σ={std:.2f}ms")
        print(f"   Errors: {errors}/{iterations}")
    else:
        print(f"   Failed to measure (all errors)")

def main():
    print("🚀 STS2 Performance Profiling")
    print(f"📍 Game API: {GAME_API_URL}")

    # Test 1: Health check
    measure_operation(
        "Health check (GET /health)",
        lambda: requests.get(f"{GAME_API_URL}/health"),
        iterations=20
    )

    # Test 2: State retrieval
    measure_operation(
        "State retrieval (GET /state)",
        lambda: requests.get(f"{GAME_API_URL}/state"),
        iterations=10
    )

    # Test 3: Available actions
    measure_operation(
        "Available actions (GET /actions/available)",
        lambda: requests.get(f"{GAME_API_URL}/actions/available"),
        iterations=10
    )

    # Test 4: Full decision cycle (state + actions)
    def full_cycle():
        requests.get(f"{GAME_API_URL}/state")
        return requests.get(f"{GAME_API_URL}/actions/available")

    measure_operation(
        "Full cycle (state + actions)",
        full_cycle,
        iterations=10
    )

    # Test 5: JSON parsing overhead
    def parse_state():
        response = requests.get(f"{GAME_API_URL}/state")
        return response.json()

    measure_operation(
        "State JSON parsing",
        parse_state,
        iterations=10
    )

    print("\n✅ Profile complete")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️  Cancelled")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
