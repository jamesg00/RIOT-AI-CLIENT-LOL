import os, json, requests
from urllib.parse import quote

# Optional: comma-separated list in env (e.g. "https://coach4league.com,http://localhost:5173,tauri://localhost")
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGIN", "*").split(",")]

VALID_PLATFORMS = {
    "na1","br1","la1","la2","oc1","euw1","eun1","tr1","ru","kr","jp1"
}

def _cors_headers(event):
    origin = (event.get("headers") or {}).get("origin") or (event.get("headers") or {}).get("Origin")
    if "*" in ALLOWED_ORIGINS:
        allow = "*"
    elif origin and origin in ALLOWED_ORIGINS:
        allow = origin
    else:
        # fall back to first allowed, or "*"
        allow = ALLOWED_ORIGINS[0] if ALLOWED_ORIGINS else "*"
    return {
        "content-type": "application/json",
        "access-control-allow-origin": allow,
        "access-control-allow-methods": "GET,OPTIONS",
        "access-control-allow-headers": "Content-Type"
    }

def _resp(event, status, body):
    return {"statusCode": status, "headers": _cors_headers(event), "body": json.dumps(body)}

def lambda_handler(event, context):
    # CORS preflight
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _resp(event, 200, {"ok": True})

    params = event.get("queryStringParameters") or {}
    summoner = (params.get("summoner") or "Faker").strip()
    platform = (params.get("platform") or "na1").strip().lower()

    if platform not in VALID_PLATFORMS:
        return _resp(event, 400, {"error": "invalid_platform", "allowed": sorted(VALID_PLATFORMS)})

    riot_key = (os.getenv("RIOT_KEY") or "").strip()
    print(f"[debug] key_len={len(riot_key)} suffix={riot_key[-6:] if riot_key else 'None'}")
    if not riot_key:
        return _resp(event, 500, {"error": "Missing RIOT_KEY env var in Lambda"})

    # URL-encode summoner (handles spaces/special chars)
    url = f"https://{platform}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{quote(summoner, safe='')}"
    print(f"[debug] GET {url}")
    headers = {"X-Riot-Token": riot_key}

    try:
        r = requests.get(url, headers=headers, timeout=8)
        print(f"[debug] riot status={r.status_code} body_prefix={r.text[:80]!r}")
        if r.status_code != 200:
            # Bubble up Riot's message while developing
            return _resp(event, r.status_code, {
                "error": "Riot API error",
                "status": r.status_code,
                "text": r.text[:200]
            })

        data = r.json()
        return _resp(event, 200, {
            "query": {"summoner": summoner, "platform": platform},
            "summoner": {
                "name": data.get("name"),
                "level": data.get("summonerLevel"),
                "puuid": data.get("puuid")
            }
        })
    except requests.RequestException as e:
        return _resp(event, 500, {"error": "request_failed", "details": str(e)})
