import os, json, requests
from urllib.parse import quote

VALID_PLATFORMS = {"na1","euw1","kr","eun1","br1","la1","la2","tr1","ru","jp1","oc1"}

# Comma-separated env, e.g. "https://coach4league.com,https://www.coach4league.com,http://localhost:5173"
ALLOWED = [o.strip() for o in os.getenv("CORS_ORIGIN", "*").split(",")]

def _headers(event):
    hdrs = event.get("headers") or {}
    origin = hdrs.get("origin") or hdrs.get("Origin")
    if "*" in ALLOWED:
        allow = "*"
    elif origin and origin in ALLOWED:
        allow = origin
    else:
        allow = ALLOWED[0] if ALLOWED else "*"
    return {
        "content-type": "application/json",
        "access-control-allow-origin": allow,
        "access-control-allow-methods": "GET,OPTIONS",
        "access-control-allow-headers": "Content-Type"
    }

def _resp(event, status, body):
    return {"statusCode": status, "headers": _headers(event), "body": json.dumps(body)}

def lambda_handler(event, context):
    # CORS preflight
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _resp(event, 200, {"ok": True})

    # Read the key at request-time (helps after rotations)
    riot_key = (os.getenv("RIOT_KEY") or "").strip()
    if not riot_key:
        return _resp(event, 500, {"error": "missing_config", "message": "RIOT_KEY env var is not set"})
    # tiny debug: confirm you pasted the one you think you did
    print(f"[riot_key] len={len(riot_key)} suffix={riot_key[-6:] if riot_key else 'None'}")

    params = event.get("queryStringParameters") or {}
    summoner = (params.get("summoner") or "Faker").strip()
    platform = (params.get("platform") or "na1").strip().lower()

    if platform not in VALID_PLATFORMS:
        return _resp(event, 400, {"error":"invalid_platform","allowed":sorted(list(VALID_PLATFORMS))})

    url = f"https://{platform}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{quote(summoner, safe='')}"
    try:
        r = requests.get(url, headers={"X-Riot-Token": riot_key}, timeout=8)
        print(f"[riot] GET {url} -> {r.status_code}")
        if r.status_code != 200:
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
        return _resp(event, 500, {"error":"request_failed","details":str(e)})
