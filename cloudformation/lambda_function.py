"""
Lambda 2 - setPrice

Accepts a JSON body with a coin name and a target/alert price, then
persists the value to AWS SSM Parameter Store under the path:
  /price-alerts/{coin}

The function also validates the submitted price against the live
CoinGecko API so the caller gets immediate feedback on whether the
alert price is above or below the current market price.

External service: CoinGecko API (https://www.coingecko.com/en/api)
Storage:          AWS SSM Parameter Store (free tier, Standard tier)
"""

import json
import os
import urllib.request
import urllib.error
import boto3
from botocore.exceptions import BotoCoreError, ClientError

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

ALLOWED_COINS = {"bitcoin", "ethereum", "solana", "ripple", "dogecoin"}

# SSM path prefix - can be overridden via environment variable for flexibility
SSM_PREFIX = os.environ.get("SSM_PREFIX", "/price-alerts")

ssm = boto3.client("ssm")


def build_response(status_code: int, body: dict) -> dict:
    """Return a standard API Gateway proxy response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def fetch_current_price(coin: str) -> float | None:
    """
    Fetch the current USD price for `coin` from CoinGecko.
    Returns None if the request fails so the caller can decide how to handle it.
    """
    url = f"{COINGECKO_BASE}/simple/price?ids={coin}&vs_currencies=usd"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            return data[coin]["usd"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
        print(f"CoinGecko fetch error: {exc}")
        return None


def handler(event, context):
    # Parse and validate the request body
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return build_response(400, {"error": "Request body must be valid JSON."})

    coin = str(body.get("coin", "")).lower()
    alert_price = body.get("alertPrice")

    if not coin:
        return build_response(400, {"error": "Missing required field: coin"})

    if coin not in ALLOWED_COINS:
        return build_response(
            400,
            {
                "error": f'Unsupported coin "{coin}". '
                f'Allowed values: {", ".join(sorted(ALLOWED_COINS))}'
            },
        )

    if alert_price is None:
        return build_response(400, {"error": "Missing required field: alertPrice"})

    try:
        alert_price = float(alert_price)
        if alert_price <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return build_response(
            400, {"error": "alertPrice must be a positive number."}
        )

    # Fetch live price for context (non-blocking - we still save even if CoinGecko is temporarily unavailable)
    current_price = fetch_current_price(coin)

    # Persist the alert price in SSM Parameter Store
    ssm_key = f"{SSM_PREFIX}/{coin}"
    try:
        ssm.put_parameter(
            Name=ssm_key,
            Value=str(alert_price),
            Type="String",
            Overwrite=True,
            Description=f"Price alert for {coin} in USD",
        )
    except (BotoCoreError, ClientError) as exc:
        print(f"SSM put_parameter error: {exc}")
        return build_response(
            502, {"error": "Failed to save alert price. Please try again later."}
        )
    
    # Build a helpful response
    response_body = {
        "message": f"Alert price for {coin} set successfully.",
        "coin": coin,
        "alertPrice": alert_price,
        "ssmKey": ssm_key,
    }

    if current_price is not None:
        response_body["currentPrice"] = current_price
        if alert_price > current_price:
            response_body["status"] = "Alert price is ABOVE current market price."
        elif alert_price < current_price:
            response_body["status"] = "Alert price is BELOW current market price."
        else:
            response_body["status"] = "Alert price matches current market price."

    return build_response(200, response_body)
