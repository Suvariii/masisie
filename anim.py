import asyncio, json, re
import websockets
from playwright.async_api import async_playwright

SITE_URL = "https://www.hepbet103.com/tr/live/sport/Soccer/"
INGEST_URL = "ws://127.0.0.1:8777/ingest"

def safe_json(x):
    try:
        return json.loads(x)
    except:
        return None

def extract_game_ids(data):
    """Swarm verisinden tüm game ID'lerini çıkar"""
    game_ids = set()
    
    def traverse(obj):
        if isinstance(obj, dict):
            if "game" in obj and isinstance(obj["game"], dict):
                for gid in obj["game"].keys():
                    if str(gid).strip():
                        game_ids.add(str(gid))
            for v in obj.values():
                traverse(v)
        elif isinstance(obj, list):
            for item in obj:
                traverse(item)
    
    traverse(data)
    return game_ids


class AnimationWSManager:
    """Her game_id için ayrı animation WebSocket yöneticisi"""
    
    def __init__(self, send_queue: asyncio.Queue):
        self.send_queue = send_queue
        self.active_connections = {}
        self.partner_id = None
        self.site_ref = None
        
    async def connect_for_game(self, game_id: str):
        """Belirli bir game_id için animation WebSocket'i aç"""
        if not self.partner_id or not self.site_ref:
            print(f"[ANIM] waiting for partner_id and site_ref...")
            return
            
        if game_id in self.active_connections:
            return  # Zaten bağlı
        
        ws_url = f"wss://animation.ml.bcua.io/animation_json_v2?partner_id={self.partner_id}&site_ref={self.site_ref}&game_id={game_id}"
        
        try:
            ws = await websockets.connect(ws_url, max_size=8_000_000)
            self.active_connections[game_id] = ws
            print(f"[ANIM] connected for game_id: {game_id} (total: {len(self.active_connections)})")
            
            # Bu game için mesajları dinle
            asyncio.create_task(self._listen_game(game_id, ws))
            
        except Exception as e:
            print(f"[ANIM] failed to connect game {game_id}: {e}")
    
    async def _listen_game(self, game_id: str, ws):
        """Belirli bir game'in animation mesajlarını dinle"""
        try:
            async for msg in ws:
                if isinstance(msg, bytes):
                    msg = msg.decode("utf-8", "ignore")
                
                obj = safe_json(msg)
                if obj and isinstance(obj, dict):
                    await self.send_queue.put(msg)
                    
        except Exception as e:
            print(f"[ANIM] game {game_id} connection closed: {e}")
        finally:
            if game_id in self.active_connections:
                del self.active_connections[game_id]


async def run_playwright_sniffer(send_queue: asyncio.Queue):
    anim_manager = AnimationWSManager(send_queue)
    discovered_games = set()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()

        print("[PW] goto:", SITE_URL)

        async def on_ws(ws):
            url = ws.url
            
            # Partner ID ve site_ref'i yakala
            if "animation_json" in url:
                print("[PW] animation websocket:", url)
                # URL'den partner_id ve site_ref çıkar
                match = re.search(r'partner_id=([^&]+)', url)
                if match:
                    anim_manager.partner_id = match.group(1)
                match = re.search(r'site_ref=([^&\s]+)', url)
                if match:
                    anim_manager.site_ref = match.group(1)
                    print(f"[ANIM] extracted partner_id={anim_manager.partner_id}, site_ref={anim_manager.site_ref}")
                    
                    # Daha önce tespit edilen game'ler için de bağlan
                    if discovered_games:
                        print(f"[ANIM] connecting to {len(discovered_games)} previously discovered games...")
                        for gid in list(discovered_games):
                            asyncio.create_task(anim_manager.connect_for_game(gid))
            
            if "swarm" in url:
                print("[PW] swarm websocket:", url)

            async def on_frame(payload):
                # payload bazen str bazen bytes gelir
                if isinstance(payload, (bytes, bytearray)):
                    try:
                        payload = payload.decode("utf-8", "ignore")
                    except:
                        return

                if not isinstance(payload, str):
                    return

                obj = safe_json(payload)
                if isinstance(obj, dict):
                    # Swarm data'dan game ID'leri çıkar
                    if "data" in obj:
                        game_ids = extract_game_ids(obj.get("data"))
                        
                        if game_ids:
                            print(f"[SWARM] detected {len(game_ids)} games: {list(game_ids)[:5]}...")
                        
                        # Yeni bulunan game'ler için animation WS aç
                        for gid in game_ids:
                            if gid not in discovered_games:
                                discovered_games.add(gid)
                                print(f"[SWARM] new game discovered: {gid}")
                                asyncio.create_task(anim_manager.connect_for_game(gid))
                    
                    # Swarm mesajını da gönder
                    if "data" in obj and "code" in obj:
                        await send_queue.put(payload)

            ws.on("framereceived", on_frame)
            ws.on("framesent", on_frame)

        page.on("websocket", on_ws)

        await page.goto(SITE_URL, wait_until="domcontentloaded")
        print("[PW] listening ws frames...")
        print("[PW] will auto-connect animation WS for all detected games...")

        while True:
            await page.wait_for_timeout(1000)


async def ingest_sender(send_queue: asyncio.Queue):
    while True:
        try:
            async with websockets.connect(
                INGEST_URL,
                max_size=8_000_000,
                ping_interval=20,
                ping_timeout=20
            ) as ws:
                print("[INGEST] connected ->", INGEST_URL)

                while True:
                    payload = await send_queue.get()
                    msg = {
                        "kind": "swarm_recv",
                        "payload": payload
                    }
                    await ws.send(json.dumps(msg, ensure_ascii=False))

        except Exception as e:
            print("[INGEST] reconnecting…", repr(e))
            await asyncio.sleep(1)


async def main():
    q = asyncio.Queue(maxsize=1000)
    await asyncio.gather(
        run_playwright_sniffer(q),
        ingest_sender(q),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[EXIT] stopped by user")
