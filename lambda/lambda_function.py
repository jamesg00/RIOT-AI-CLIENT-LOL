import os, json, requests

def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": "*",  # for quick dev; lock down later
            "access-control-allow-methods": "GET,OPTIONS",
            "access-control-allow-headers": "Content-Type"
        },
        "body": json.dumps(body)
    }

def lambda_handler(event, context):
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _resp(200, {"ok": True})

    params = event.get("queryStringParameters") or {}
    summoner = params.get("summoner", "Faker")
    platform = params.get("platform", "na1")

    raw_key = os.getenv("RIOT_KEY", "")
    riot_key = raw_key.strip()  # trim any stray spaces/newlines
    print(f"[debug] using key len={len(riot_key)} suffix={riot_key[-6:] if riot_key else 'None'}")
    if not riot_key:
        return _resp(500, {"error": "Missing RIOT_KEY env var in Lambda"})

    url = f"https://{platform}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{summoner}"
    print(f"[debug] GET {url}")
    headers = {"X-Riot-Token": riot_key}

    try:
        r = requests.get(url, headers=headers, timeout=8)
        print(f"[debug] riot status={r.status_code}")
        if r.status_code != 200:
            return _resp(r.status_code, {"error": "Riot API error",
                                         "status": r.status_code,
                                         "text": r.text[:200]})
        data = r.json()
        return _resp(200, {
            "query": {"summoner": summoner, "platform": platform},
            "summoner": {
                "name": data.get("name"),
                "level": data.get("summonerLevel"),
                "puuid": data.get("puuid")
            }
        })
    except requests.RequestException as e:
        return _resp(500, {"error": "request_failed", "details": str(e)})