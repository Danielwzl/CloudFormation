/**
 * Lambda 1 - getPrice
 *
 * Fetches the current price of a cryptocurrency from the CoinGecko public API.
 * Accepts a query parameter `coin` (e.g. bitcoin, ethereum).
 * Falls back to "bitcoin" if no coin is specified.
 *
 * External service: CoinGecko API (https://www.coingecko.com/en/api)
 * No API key required for basic usage.
 */

const COINGECKO_BASE = "https://api.coingecko.com/api/v3";

// Coins that are accepted. Keeps the surface area small and avoids
// passing arbitrary strings directly into the upstream URL.
const ALLOWED_COINS = new Set([
  "bitcoin",
  "ethereum",
  "solana",
  "ripple",
  "dogecoin",
]);

/**
 * Build a standard JSON response object for API Gateway.
 * CORS headers are included so a browser-based client can call the endpoint.
 */
function buildResponse(statusCode, body) {
  return {
    statusCode,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
    body: JSON.stringify(body),
  };
}

export const handler = async (event) => {
  // Parse and validate the query parameter
  const coin = (event.queryStringParameters?.coin ?? "bitcoin").toLowerCase();

  if (!ALLOWED_COINS.has(coin)) {
    return buildResponse(400, {
      error: `Unsupported coin "${coin}". Allowed values: ${[...ALLOWED_COINS].join(", ")}`,
    });
  }

  // Call CoinGecko
  let raw;
  try {
    const url = `${COINGECKO_BASE}/simple/price?ids=${coin}&vs_currencies=usd&include_24hr_change=true`;
    const res = await fetch(url);

    if (!res.ok) {
      // Surface the upstream status code to help with debugging
      throw new Error(`CoinGecko responded with HTTP ${res.status}`);
    }

    raw = await res.json();
  } catch (err) {
    console.error("Upstream fetch failed:", err);
    return buildResponse(502, {
      error: "Failed to retrieve price from upstream service. Please try again later.",
    });
  }

  // Shape the response
  const data = raw[coin];
  if (!data) {
    return buildResponse(502, {
      error: "Unexpected response structure from upstream service.",
    });
  }

  return buildResponse(200, {
    coin,
    currency: "usd",
    price: data.usd,
    change24h: data.usd_24h_change ?? null,
    retrievedAt: new Date().toISOString(),
  });
};
