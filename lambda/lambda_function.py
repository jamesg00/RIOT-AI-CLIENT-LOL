import json, requests
from urllib.parse import quote

# 🚨 Hard-coded dev key (replace this each day when you regenerate)
RIOT_KEY = "RGAPI-e72c2eea-ebd5-4638-b8e2-73492f173358"

VALID_PLATFORMS = {"na1","euw1","kr","eun1","br1","la1","la2","tr1","ru","jp1","oc1"}

def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": "*",
            "access-control-allow-methods": "GET,OPTIONS",
            "access-control-allow-headers": "Content-Type"
        },
        "body": json.dumps(body)
    }

def lambda_handler(event, context):
    # Handle CORS preflight
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _resp(200, {"ok": True})

    params = event.get("queryStringParameters") or {}
    summoner = (params.get("summoner") or "Faker").strip()
    platform = (params.get("platform") or "na1").strip().lower()

    if platform not in VALID_PLATFORMS:
        return _resp(400, {"error":"invalid_platform","allowed":sorted(list(VALID_PLATFORMS))})

    url = f"https://{platform}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{quote(summoner, safe='')}"
    headers = {"X-Riot-Token": RIOT_KEY}

    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code != 200:
            return _resp(r.status_code, {"error":"Riot API error","status":r.status_code,"text":r.text[:200]})
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
        return _resp(500, {"error":"request_failed","details":str(e)})
