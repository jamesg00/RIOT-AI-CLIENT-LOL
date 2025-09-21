import os, json, time, requests
from urllib.parse import quote

# --------- Config ---------
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGIN", "*").split(",")]
RIOT_KEY = (os.getenv("RIOT_KEY") or "").strip()           # <-- keep secret in Lambda env
BEDROCK_MODEL = (os.getenv("BEDROCK_MODEL_ID") or "").strip()
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# Platform -> Region map for Match-V5
MATCH_REGION = {
    # americas
    "na1":"americas","br1":"americas","la1":"americas","la2":"americas",
    # europe
    "euw1":"europe","eun1":"europe","tr1":"europe","ru":"europe",
    # asia
    "kr":"asia","jp1":"asia","oc1":"asia"
}
VALID_PLATFORMS = set(MATCH_REGION.keys())

# --------- Helpers ---------
def _allow_origin(event):
    hdrs = event.get("headers") or {}
    origin = hdrs.get("origin") or hdrs.get("Origin")
    if "*" in ALLOWED_ORIGINS:
        return "*"
    if origin and origin in ALLOWED_ORIGINS:
        return origin
    return ALLOWED_ORIGINS[0] if ALLOWED_ORIGINS else "*"

def _resp(event, status, body):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": _allow_origin(event),
            "access-control-allow-methods": "GET,OPTIONS",
            "access-control-allow-headers": "Content-Type"
        },
        "body": json.dumps(body)
    }

def _riot_headers():
    if not RIOT_KEY:
        raise RuntimeError("Missing RIOT_KEY env var")
    return {"X-Riot-Token": RIOT_KEY}

def fetch_summoner(platform: str, name: str):
    url = f"https://{platform}.api.riotgames.com/lol/summoner/v4/summoners/by-name/{quote(name, safe='')}"
    r = requests.get(url, headers=_riot_headers(), timeout=8)
    r.raise_for_status()
    return r.json()

def fetch_match_ids(platform: str, puuid: str, count: int = 5):
    region = MATCH_REGION.get(platform, "americas")
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids"
    r = requests.get(url, params={"start":0,"count":count}, headers=_riot_headers(), timeout=10)
    r.raise_for_status()
    return r.json()

def fetch_match(region: str, match_id: str):
    url = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
    r = requests.get(url, headers=_riot_headers(), timeout=12)
    r.raise_for_status()
    return r.json()

def summarize_player(puuid: str, matches: list):
    games = 0
    k=d=a=0
    cs_total = 0.0
    minutes_total = 0.0
    champs = {}
    for m in matches:
        try:
            info = m.get("info", {})
            dur_s = float(info.get("gameDuration", 0))
            minutes = max(dur_s/60.0, 1e-6)
            for p in info.get("participants", []):
                if p.get("puuid") == puuid:
                    games += 1
                    k += int(p.get("kills",0))
                    d += int(p.get("deaths",0))
                    a += int(p.get("assists",0))
                    cs_total += float(p.get("totalMinionsKilled",0)) + float(p.get("neutralMinionsKilled",0))
                    minutes_total += minutes
                    champ = p.get("championName","Unknown")
                    champs[champ] = champs.get(champ,0)+1
                    break
        except Exception:
            continue
    kda = (k+a)/max(d,1) if games else 0.0
    csmin = (cs_total/minutes_total) if minutes_total>0 else 0.0
    top_champ = max(champs, key=champs.get) if champs else None
    return {
        "games": games,
        "avg_kda": round(kda,2),
        "avg_cs_per_min": round(csmin,2),
        "top_champion": top_champ
    }

def maybe_bedrock_tip(summary: dict, summoner: dict):
    """Optional: only runs if BEDROCK_MODEL is set and you enabled that model in Bedrock."""
    if not BEDROCK_MODEL:
        return "Bedrock not enabled."
    try:
        import boto3, json as _json
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        system = ("You are a concise, motivating League of Legends coach. "
                  "Given the player's recent-match summary, provide 3 specific, actionable tips "
                  "for the next 5 games. Be precise and kind.")
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "system": system,
            "messages": [
                {"role":"user","content":[{"type":"text","text":_json.dumps({
                    "player":{"name":summoner.get("name"),"level":summoner.get("summonerLevel")},
                    "summary": summary
                })}]}
            ],
            "max_tokens": 350
        }
        resp = bedrock.invoke_model(
            modelId=BEDROCK_MODEL,
            body=json.dumps(body),
            contentType="application/json",
            accept="application/json"
        )
        data = json.loads(resp["body"].read())
        return data.get("content",[{}])[0].get("text","")
    except Exception as e:
        return f"Bedrock not configured yet: {e}"

# --------- Lambda entry ---------
def lambda_handler(event, context):
    # CORS preflight
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _resp(event, 200, {"ok": True})

    params = event.get("queryStringParameters") or {}
    summoner = (params.get("summoner") or "Faker").strip()
    platform  = (params.get("platform")  or "na1").strip().lower()

    if platform not in VALID_PLATFORMS:
        return _resp(event, 400, {"error":"invalid_platform","allowed":sorted(list(VALID_PLATFORMS))})

    if not RIOT_KEY:
        return _resp(event, 500, {"error":"missing_riot_key"})

    # 1) Summoner
    try:
        s = fetch_summoner(platform, summoner)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 502
        return _resp(event, status, {"error":"summoner_lookup_failed","details":(e.response.text[:200] if e.response else str(e))})
    except Exception as e:
        return _resp(event, 502, {"error":"summoner_lookup_failed","details":str(e)})

    puuid = s.get("puuid")
    region = MATCH_REGION.get(platform, "americas")

    # 2) Recent matches + summary (small count to stay within dev limits)
    try:
        ids = fetch_match_ids(platform, puuid, count=5)
        matches = []
        for mid in ids:
            try:
                matches.append(fetch_match(region, mid))
                time.sleep(0.05)  # be polite
            except Exception:
                pass
        summary = summarize_player(puuid, matches)
    except Exception as e:
        return _resp(event, 502, {"error":"match_fetch_failed","details":str(e)})

    # 3) Optional Bedrock coaching
    coach = maybe_bedrock_tip(summary, s)

    return _resp(event, 200, {
        "player": {
            "summoner": s.get("name"),
            "platform": platform,
            "level": s.get("summonerLevel"),
            "puuid": puuid
        },
        "summary": summary,
        "coach": coach
    })
