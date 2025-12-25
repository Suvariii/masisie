import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from http import HTTPStatus

import websockets

HOST = "0.0.0.0"
PORT = int(os.getenv("PORT", 8777))

def jloads_maybe(s: Any) -> Any:
    if isinstance(s, (dict, list)):
        return s
    if not isinstance(s, str):
        return None
    try:
        return json.loads(s)
    except Exception:
        return None

def now_ms() -> int:
    return int(time.time() * 1000)

def safe_int(x, default=0) -> int:
    try:
        return int(float(x))
    except Exception:
        return default

# Futbol event mapping
SOCCER_STAT_TO_EVENT = {
    "attack": "ATTACK",
    "dangerous_attack": "DANGEROUS_ATTACK",
    "corner": "CORNER",
    "free_kick": "FREE_KICK_ZONE",
    "shot_on_target": "SHOT_ON_TARGET",
    "ballSafe": "SAFE_POSSESSION",
    "throw_in": "THROW_IN",
    "foul": "FOUL",
    "penalty": "PENALTY",
}

# Basketbol event mapping
BASKETBALL_STAT_TO_EVENT = {
    "attack": "ATTACK",
    "shot_on_target": "SHOT_ON_TARGET",
    "foul": "FOUL",
    "free_throw": "FREE_THROW",
    "turnover": "TURNOVER",
    "rebound": "REBOUND",
    "three_point": "THREE_POINT",
    "two_point": "TWO_POINT",
}

def get_stat_mapping(sport: str) -> dict:
    """Sport türüne göre event mapping döndür"""
    if sport == "Basketball":
        return BASKETBALL_STAT_TO_EVENT
    return SOCCER_STAT_TO_EVENT

@dataclass
class Game:
    game_id: str
    team1: str = "Team 1"
    team2: str = "Team 2"
    tournament: str = "-"
    sport: str = "Soccer"
    is_live: int = 1
    current_game_time: str = ""
    score1: int = 0
    score2: int = 0
    stats: Dict[str, Dict[str, int]] = field(default_factory=dict)
    last_update_ms: int = field(default_factory=now_ms)

@dataclass
class Event:
    game_id: str
    type: str
    team: Optional[int]
    ts: int

def collect_games(node: Any, out: Dict[str, dict], sport_id: str = "1") -> None:
    """
    Game'leri toplarken sport_id'yi de taşı
    sport -> 1: Soccer, 2: Basketball
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "sport" and isinstance(v, dict):
                # Sport seviyesindeyiz, her sport_id için recursive
                for sid, sport_data in v.items():
                    collect_games(sport_data, out, sport_id=str(sid))
            elif k == "game" and isinstance(v, dict):
                # Game seviyesine ulaştık
                for gid, gobj in v.items():
                    gid = str(gid).strip()
                    if gid and isinstance(gobj, dict):
                        # Game object'e sport_id'yi ekle
                        gobj_with_sport = gobj.copy()
                        gobj_with_sport["_sport_id"] = sport_id
                        out[gid] = gobj_with_sport
            else:
                collect_games(v, out, sport_id)
    elif isinstance(node, list):
        for it in node:
            collect_games(it, out, sport_id)

def detect_score_from_game_obj(gobj: dict) -> Optional[Tuple[int, int]]:
    info = gobj.get("info")
    if isinstance(info, dict):
        sc = info.get("score")
        if isinstance(sc, str) and "-" in sc:
            a, b = sc.split("-", 1)
            return (safe_int(a), safe_int(b))
        if isinstance(sc, dict):
            return (safe_int(sc.get("1")), safe_int(sc.get("2")))
    return None

def normalize_stats(gobj: dict) -> Dict[str, Dict[str, int]]:
    res: Dict[str, Dict[str, int]] = {}
    stats = gobj.get("stats")
    if not isinstance(stats, dict):
        return res
    for sname, sval in stats.items():
        if not isinstance(sval, dict):
            continue
        if "team1_value" in sval or "team2_value" in sval:
            res[sname] = {"1": safe_int(sval.get("team1_value", 0)), "2": safe_int(sval.get("team2_value", 0))}
    return res

def extract_minute(gobj: dict) -> str:
    info = gobj.get("info")
    if isinstance(info, dict) and info.get("current_game_time") is not None:
        return str(info.get("current_game_time"))
    return ""

def ws_path(ws) -> str:
    # websockets 10/11: ws.path
    p = getattr(ws, "path", None)
    if p:
        return p
    # websockets 12/13: ws.request.path
    req = getattr(ws, "request", None)
    if req and getattr(req, "path", None):
        return req.path
    return "/"

class Engine:
    def __init__(self):
        self.games: Dict[str, Game] = {}
        self.front_clients: List[Any] = []

    def upsert_game(self, gid: str) -> Game:
        if gid not in self.games:
            self.games[gid] = Game(game_id=gid)
        return self.games[gid]

    def apply_swarm_payload(self, swarm_obj: dict) -> List[Event]:
        events: List[Event] = []
        data = swarm_obj.get("data")
        if not isinstance(data, dict):
            return events

        # DEBUG: Data yapısını logla
        if "sport" in data:
            sport_keys = list(data["sport"].keys()) if isinstance(data.get("sport"), dict) else []
            print(f"[DEBUG] Data has sport keys: {sport_keys}")

        extracted: Dict[str, dict] = {}
        collect_games(data, extracted)
        
        print(f"[DEBUG] Collected {len(extracted)} games from swarm data")
        
        # İlk birkaç game'in sport_id'sini logla
        for gid in list(extracted.keys())[:3]:
            sid = extracted[gid].get("_sport_id", "NOT SET")
            print(f"[DEBUG] Sample game {gid} has _sport_id={sid}")

        ts = now_ms()
        for gid, gobj in extracted.items():
            g = self.upsert_game(gid)
            g.last_update_ms = ts

            # Sport türünü game object'ten al (_sport_id)
            sport_id = gobj.get("_sport_id", "1")
            print(f"[DEBUG] Game {gid} has _sport_id: {sport_id}")
            
            # Sport_id'ye göre sport türünü belirle
            # 1 = Soccer, 2 = Tennis, 3 = Basketball (e-sports), vb.
            if sport_id in ("2", "3"):  # 2 veya 3 basketbol olabilir
                g.sport = "Basketball"
                print(f"[SPORT] 🏀 Game {gid} -> Basketball (sport_id={sport_id})")
            else:
                g.sport = "Soccer"
                print(f"[SPORT] ⚽ Game {gid} -> Soccer (sport_id={sport_id})")

            # Takım isimlerini çek
            team_info = gobj.get("team1_name") or gobj.get("team1")
            if team_info:
                if isinstance(team_info, dict):
                    g.team1 = team_info.get("name", g.team1)
                elif isinstance(team_info, str):
                    g.team1 = team_info
            
            team_info = gobj.get("team2_name") or gobj.get("team2")
            if team_info:
                if isinstance(team_info, dict):
                    g.team2 = team_info.get("name", g.team2)
                elif isinstance(team_info, str):
                    g.team2 = team_info
            
            # Info içinden de kontrol et
            info = gobj.get("info")
            if isinstance(info, dict):
                if info.get("team1_name"):
                    g.team1 = str(info.get("team1_name"))
                if info.get("team2_name"):
                    g.team2 = str(info.get("team2_name"))
                
                # Tournament bilgisi
                if info.get("league"):
                    league = info.get("league")
                    if isinstance(league, dict):
                        g.tournament = league.get("name", g.tournament)
                    elif isinstance(league, str):
                        g.tournament = league
                elif info.get("tournament_name"):
                    g.tournament = str(info.get("tournament_name"))

            minute = extract_minute(gobj)
            if minute:
                g.current_game_time = minute

            sc = detect_score_from_game_obj(gobj)
            if sc:
                g.score1, g.score2 = sc

            new_stats = normalize_stats(gobj)
            if new_stats:
                # Sport türüne göre event mapping seç
                stat_mapping = get_stat_mapping(g.sport)
                
                for sname, tvals in new_stats.items():
                    if sname not in stat_mapping:
                        continue
                    prev = g.stats.get(sname, {"1": 0, "2": 0})
                    n1, n2 = tvals.get("1", 0), tvals.get("2", 0)
                    p1, p2 = prev.get("1", 0), prev.get("2", 0)
                    d1, d2 = n1 - p1, n2 - p2
                    if d1 > 0 or d2 > 0:
                        team = 1 if d1 >= d2 else 2
                        etype = stat_mapping[sname]
                        # Futbol için özel tekrar mantığı
                        repeat = 2 if g.sport == "Soccer" and sname in ("dangerous_attack", "attack") and (d1 + d2) >= 3 else 1
                        for _ in range(repeat):
                            events.append(Event(game_id=gid, type=etype, team=team, ts=ts))

                g.stats.update(new_stats)

        return events

    def snapshot_matches(self) -> List[dict]:
        items = sorted(self.games.values(), key=lambda x: x.last_update_ms, reverse=True)
        res = []
        for g in items[:250]:
            res.append({
                "game_id": g.game_id,
                "title": f"{g.team1} vs {g.team2}",
                "team1": g.team1,
                "team2": g.team2,
                "score1": g.score1,
                "score2": g.score2,
                "minute": g.current_game_time,
                "sport": g.sport,
                "tournament": g.tournament,
                "is_live": g.is_live,
                "last_update_ms": g.last_update_ms,
            })
        return res

    async def broadcast_front(self, msg: dict):
        if not self.front_clients:
            return
        raw = json.dumps(msg, ensure_ascii=False)
        dead = []
        for ws in self.front_clients:
            try:
                await ws.send(raw)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                self.front_clients.remove(ws)
            except ValueError:
                pass

engine = Engine()

async def process_request(path, request_headers):
    """HTTP isteklerini ele al (health check için)"""
    if path in ["/", "/health"]:
        return (HTTPStatus.OK, [], b"OK\n")
    # WebSocket yükseltmesine izin ver
    return None

async def handler(ws):
    path = ws_path(ws)

    if path.startswith("/frontend"):
        engine.front_clients.append(ws)
        await engine.broadcast_front({"type": "matches", "matches": engine.snapshot_matches()})
        try:
            async for _ in ws:
                pass
        finally:
            if ws in engine.front_clients:
                engine.front_clients.remove(ws)
        return

    if path.startswith("/ingest"):
        async for msg in ws:
            obj = jloads_maybe(msg)
            if not isinstance(obj, dict):
                continue

            swarm_obj = None
            if obj.get("kind") == "swarm_recv":
                swarm_obj = jloads_maybe(obj.get("payload"))
            elif "code" in obj and "data" in obj:
                swarm_obj = obj

            if not isinstance(swarm_obj, dict):
                continue

            events = engine.apply_swarm_payload(swarm_obj)

            if events:
                await engine.broadcast_front({
                    "type": "events",
                    "events": [{"game_id": e.game_id, "etype": e.type, "team": e.team, "ts": e.ts} for e in events],
                })

            await engine.broadcast_front({"type": "matches", "matches": engine.snapshot_matches()})
        return

    # başka path geldiyse kapat
    await ws.close()

async def main():
    print(f"[SERVER] Starting on {HOST}:{PORT}")
    print(f"  - HTTP health check: http://{HOST}:{PORT}/health")
    print(f"  - WebSocket frontend: ws://{HOST}:{PORT}/frontend")
    print(f"  - WebSocket ingest: ws://{HOST}:{PORT}/ingest")
    
    # WebSocket server'ı process_request callback ile başlat
    async with websockets.serve(
        handler,
        HOST,
        PORT,
        process_request=process_request,
        ping_interval=20,
        ping_timeout=20,
        max_size=8_000_000
    ):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
