"""
MCP Server exposing calculator, echo, weather, and string utility tools.

Uses the `mcp` Python SDK (modelcontextprotocol/python-sdk) and runs over
HTTP+SSE transport on a configurable port (default 8000).

Usage:
    python -m mcp_server.server
    python -m mcp_server.server --port 8001
"""

import argparse
import math
import random
from datetime import datetime

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------

mcp = FastMCP("MCP Traffic Classification Server")


# ---------------------------------------------------------------------------
# Calculator tools
# ---------------------------------------------------------------------------


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


@mcp.tool()
def subtract(a: float, b: float) -> float:
    """Subtract b from a."""
    return a - b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


@mcp.tool()
def divide(a: float, b: float) -> float:
    """Divide a by b."""
    if b == 0:
        raise ValueError("Division by zero")
    return a / b


@mcp.tool()
def power(base: float, exponent: float) -> float:
    """Raise base to the power of exponent."""
    return math.pow(base, exponent)


@mcp.tool()
def sqrt(x: float) -> float:
    """Return the square root of x."""
    if x < 0:
        raise ValueError("Cannot take square root of a negative number")
    return math.sqrt(x)


# ---------------------------------------------------------------------------
# Echo tools
# ---------------------------------------------------------------------------


@mcp.tool()
def echo(message: str) -> str:
    """Echo the given message back."""
    return message


@mcp.tool()
def echo_upper(message: str) -> str:
    """Echo the message in upper case."""
    return message.upper()


@mcp.tool()
def echo_reversed(message: str) -> str:
    """Echo the message reversed."""
    return message[::-1]


# ---------------------------------------------------------------------------
# Weather tools (simulated)
# ---------------------------------------------------------------------------


WEATHER_CONDITIONS = [
    "sunny",
    "cloudy",
    "rainy",
    "snowy",
    "windy",
    "foggy",
    "partly cloudy",
]

CITIES = {
    "new york": {"lat": 40.71, "lon": -74.01},
    "london": {"lat": 51.51, "lon": -0.13},
    "tokyo": {"lat": 35.68, "lon": 139.69},
    "sydney": {"lat": -33.87, "lon": 151.21},
    "paris": {"lat": 48.86, "lon": 2.35},
}


@mcp.tool()
def get_weather(city: str) -> dict:
    """Get simulated current weather for a city."""
    city_lower = city.lower()
    coords = CITIES.get(city_lower, {"lat": 0.0, "lon": 0.0})
    return {
        "city": city,
        "temperature_c": round(random.uniform(-10, 40), 1),
        "condition": random.choice(WEATHER_CONDITIONS),
        "humidity_pct": random.randint(20, 95),
        "wind_kph": round(random.uniform(0, 80), 1),
        "latitude": coords["lat"],
        "longitude": coords["lon"],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@mcp.tool()
def get_forecast(city: str, days: int = 5) -> list:
    """Get simulated weather forecast for a city."""
    if days < 1 or days > 10:
        raise ValueError("days must be between 1 and 10")
    return [
        {
            "day": i + 1,
            "temperature_high_c": round(random.uniform(0, 40), 1),
            "temperature_low_c": round(random.uniform(-15, 20), 1),
            "condition": random.choice(WEATHER_CONDITIONS),
        }
        for i in range(days)
    ]


# ---------------------------------------------------------------------------
# String utility tools
# ---------------------------------------------------------------------------


@mcp.tool()
def count_words(text: str) -> int:
    """Count the number of words in the given text."""
    return len(text.split())


@mcp.tool()
def count_characters(text: str, include_spaces: bool = True) -> int:
    """Count characters in text, optionally excluding spaces."""
    if include_spaces:
        return len(text)
    return len(text.replace(" ", ""))


@mcp.tool()
def to_title_case(text: str) -> str:
    """Convert text to title case."""
    return text.title()


@mcp.tool()
def replace_substring(text: str, old: str, new: str) -> str:
    """Replace all occurrences of old with new in text."""
    return text.replace(old, new)


@mcp.tool()
def split_text(text: str, delimiter: str = " ") -> list:
    """Split text by the given delimiter."""
    return text.split(delimiter)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    args = parser.parse_args()

    mcp.settings.host = args.host
    mcp.settings.port = args.port
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
