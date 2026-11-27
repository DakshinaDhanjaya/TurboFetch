import asyncio
import base64
import hashlib
import json
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from turbofetch.app.engine.downloader import DownloadEngine, DownloadStatus
from turbofetch.app.server.pairing import PairingManager
from turbofetch.app.utils.config import ConfigManager
from turbofetch.app.utils.filename import categorize_file
from turbofetch.app.utils.logger import get_logger

logger = get_logger("server")

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class LocalServer:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 29512,
        pairing_token: str = "",
        download_engine: Optional[DownloadEngine] = None,
        config_manager: Optional[ConfigManager] = None,
        queue_manager: Optional[Any] = None,
        on_video_request: Optional[Callable[[str, dict[str, str]], None]] = None,
        on_download_confirm: Optional[Callable[[dict[str, Any]], None]] = None,
        on_quick_video: Optional[Callable[[str, dict[str, str]], None]] = None,
        on_show_window: Optional[Callable[[], None]] = None,
    ) -> None:
        self.host = "127.0.0.1" if host not in ("127.0.0.1", "localhost") else host
        self.port = port
        self.pairing = PairingManager(token=pairing_token, host=self.host, port=port)
        self.download_engine = download_engine
        self.config_manager = config_manager
        self.queue_manager = queue_manager
        self.on_video_request = on_video_request
        self.on_download_confirm = on_download_confirm
        self.on_quick_video = on_quick_video
        self.on_show_window = on_show_window
        self._server: Optional[asyncio.AbstractServer] = None
        self._ws_clients: set[asyncio.StreamWriter] = set()
        self._rate_windows: dict[str, deque[float]] = defaultdict(deque)
        self._rate_limit = 60

    @property
    def actual_port(self) -> int:
        if self._server and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self.port

    def update_token(self, token: str) -> None:
        self.pairing.set_token(token)

    def _is_origin_allowed(self, origin: Optional[str]) -> bool:
        if not origin:
            return True
        lower = origin.lower()
        return lower.startswith("chrome-extension://") or lower.startswith("moz-extension://")

    def _check_rate_limit(self, peer_ip: str) -> bool:
        now = time.monotonic()
        win = self._rate_windows[peer_ip]
        while win and now - win[0] > 60.0:
            win.popleft()
        if len(win) >= self._rate_limit:
            return False
        win.append(now)
        return True

    def _cors_headers(self, origin: Optional[str]) -> dict[str, str]:
        headers = {
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Max-Age": "600",
        }
        if origin and self._is_origin_allowed(origin):
            headers["Access-Control-Allow-Origin"] = origin
        return headers

    async def _send_json(
        self,
        writer: asyncio.StreamWriter,
        status_code: int,
        status_text: str,
        payload: Any,
        origin: Optional[str] = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(body)),
            "Connection": "close",
            **self._cors_headers(origin),
        }
        head = f"HTTP/1.1 {status_code} {status_text}\r\n" + "".join(
            f"{k}: {v}\r\n" for k, v in headers.items()
        ) + "\r\n"
        writer.write(head.encode("utf-8") + body)
        await writer.drain()

    async def _send_empty(
        self,
        writer: asyncio.StreamWriter,
        status_code: int,
        status_text: str,
        origin: Optional[str] = None,
    ) -> None:
        headers = {
            "Content-Length": "0",
            "Connection": "close",
            **self._cors_headers(origin),
        }
        head = f"HTTP/1.1 {status_code} {status_text}\r\n" + "".join(
            f"{k}: {v}\r\n" for k, v in headers.items()
        ) + "\r\n"
        writer.write(head.encode("utf-8"))
        await writer.drain()

    def _extract_bearer(self, headers: dict[str, str], query_params: dict[str, list[str]]) -> str:
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        token_vals = query_params.get("token", [])
        if token_vals:
            return token_vals[0].strip()
        return ""

    def _validate_url(self, url: Any) -> bool:
        if not isinstance(url, str) or not url.strip():
            return False
        parsed = urlparse(url.strip())
        return parsed.scheme.lower() in ("http", "https", "ftp") and bool(parsed.netloc)

    def _resolve_save_dir(self, filename: str, category: Optional[str] = None) -> tuple[str, str]:
        cfg = self.config_manager.get() if self.config_manager else None
        if cfg is None:
            return str(Path.home() / "Downloads"), category or "other"
        cat = category or categorize_file(filename, cfg.file_types)
        if cfg.auto_categorize and cat in cfg.save_locations:
            return cfg.save_locations[cat], cat
        return cfg.download_dir, cat

    async def _handle_websocket(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
        origin: Optional[str],
    ) -> None:
        ws_key = headers.get("sec-websocket-key", "")
        if not ws_key:
            await self._send_json(writer, 400, "Bad Request", {"error": "Missing WebSocket key"}, origin)
            return
        accept = base64.b64encode(
            hashlib.sha1((ws_key + _WS_GUID).encode("utf-8")).digest()
        ).decode("ascii")
        resp = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        )
        writer.write(resp.encode("utf-8"))
        await writer.drain()
        self._ws_clients.add(writer)
        try:
            while True:
                header_bytes = await reader.readexactly(2)
                opcode = header_bytes[0] & 0x0F
                masked = bool(header_bytes[1] & 0x80)
                length = header_bytes[1] & 0x7F
                if length == 126:
                    length = int.from_bytes(await reader.readexactly(2), "big")
                elif length == 127:
                    length = int.from_bytes(await reader.readexactly(8), "big")
                mask_key = await reader.readexactly(4) if masked else b""
                payload = await reader.readexactly(length) if length > 0 else b""
                if masked and payload:
                    payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    await self._send_ws_frame(writer, 0xA, payload)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            self._ws_clients.discard(writer)

    async def _send_ws_frame(self, writer: asyncio.StreamWriter, opcode: int, data: bytes) -> None:
        header = bytearray([0x80 | (opcode & 0x0F)])
        n = len(data)
        if n < 126:
            header.append(n)
        elif n < 65536:
            header.append(126)
            header.extend(n.to_bytes(2, "big"))
        else:
            header.append(127)
            header.extend(n.to_bytes(8, "big"))
        writer.write(bytes(header) + data)
        await writer.drain()

    async def broadcast_ws(self, event_type: str, data: dict[str, Any]) -> None:
        if not self._ws_clients:
            return
        msg = json.dumps({"event": event_type, "data": data}).encode("utf-8")
        dead: list[asyncio.StreamWriter] = []
        for client in list(self._ws_clients):
            try:
                await self._send_ws_frame(client, 0x1, msg)
            except (ConnectionError, OSError):
                dead.append(client)
        for d in dead:
            self._ws_clients.discard(d)

    async def _read_http_request(
        self, reader: asyncio.StreamReader
    ) -> Optional[tuple[str, str, dict[str, str], bytes]]:
        raw_head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15.0)
        lines = raw_head.decode("utf-8", errors="replace").split("\r\n")
        request_line = lines[0].split(" ")
        if len(request_line) < 2:
            return None
        method = request_line[0].upper()
        target = request_line[1]
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        content_length = int(headers.get("content-length", "0") or "0")
        if content_length > 10 * 1024 * 1024:
            raise ValueError("Payload too large")
        body = await reader.readexactly(content_length) if content_length > 0 else b""
        return method, target, headers, body

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        peer_ip = peer[0] if peer else "127.0.0.1"
        origin: Optional[str] = None
        close_conn = True
        try:
            req = await self._read_http_request(reader)
            if req is None:
                await self._send_json(writer, 400, "Bad Request", {"error": "Malformed request"})
                return
            method, target, headers, body = req
            origin = headers.get("origin")

            if origin and not self._is_origin_allowed(origin):
                await self._send_json(writer, 403, "Forbidden", {"error": "Origin not allowed"})
                return

            if method == "OPTIONS":
                await self._send_empty(writer, 204, "No Content", origin)
                return

            if not self._check_rate_limit(peer_ip):
                await self._send_json(writer, 429, "Too Many Requests", {"error": "Rate limit exceeded"}, origin)
                return

            parsed = urlparse(target)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/api/pair" and method == "POST":
                try:
                    data = json.loads(body.decode("utf-8")) if body else {}
                except json.JSONDecodeError:
                    await self._send_json(writer, 400, "Bad Request", {"error": "Invalid JSON"}, origin)
                    return
                ext_id = str(data.get("extension_id", "")).strip()
                provided_token = str(data.get("token", "")).strip()
                if self.pairing.pair_extension(ext_id, provided_token):
                    await self._send_json(
                        writer,
                        200,
                        "OK",
                        {"paired": True, "extension_id": ext_id},
                        origin,
                    )
                else:
                    await self._send_json(
                        writer,
                        401,
                        "Unauthorized",
                        {"error": "Invalid pairing token or extension ID"},
                        origin,
                    )
                return

            token = self._extract_bearer(headers, query)
            if not self.pairing.verify_token(token):
                await self._send_json(writer, 401, "Unauthorized", {"error": "Invalid or missing token"}, origin)
                return

            if path == "/ws" and headers.get("upgrade", "").lower() == "websocket":
                close_conn = False
                await self._handle_websocket(reader, writer, headers, origin)
                return

            await self._dispatch(method, path, body, writer, origin)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
            pass
        except ValueError as exc:
            await self._send_json(writer, 400, "Bad Request", {"error": str(exc)}, origin)
        except Exception as exc:
            logger.exception("Server error handling request")
            await self._send_json(writer, 500, "Internal Server Error", {"error": str(exc)}, origin)
        finally:
            if close_conn:
                try:
                    writer.close()
                    await writer.wait_closed()
                except OSError:
                    pass

    async def _dispatch(
        self,
        method: str,
        path: str,
        body: bytes,
        writer: asyncio.StreamWriter,
        origin: Optional[str],
    ) -> None:
        if method == "GET" and path == "/api/status":
            active = 0
            if self.download_engine:
                active = sum(
                    1
                    for d in self.download_engine.get_all_downloads()
                    if d.status == DownloadStatus.DOWNLOADING
                )
            await self._send_json(
                writer,
                200,
                "OK",
                {"status": "running", "version": "1.0.0", "active_downloads": active},
                origin,
            )
            return

        if method == "GET" and path == "/api/pairing":
            await self._send_json(
                writer,
                200,
                "OK",
                {
                    "pairing_url": self.pairing.get_pairing_url(),
                    "paired_extensions": sorted(self.pairing.paired_extensions),
                },
                origin,
            )
            return

        if method == "GET" and path == "/api/config":
            cfg = self.config_manager.get() if self.config_manager else None
            payload = (
                {
                    "file_types": cfg.file_types,
                    "default_connections": cfg.default_connections,
                    "download_dir": cfg.download_dir,
                }
                if cfg
                else {}
            )
            await self._send_json(writer, 200, "OK", payload, origin)
            return

        if method == "GET" and path == "/api/downloads":
            items = []
            if self.download_engine:
                for t in self.download_engine.get_all_downloads():
                    pct = (t.downloaded / t.size * 100.0) if t.size > 0 else 0.0
                    items.append(
                        {
                            "id": t.id,
                            "url": t.url,
                            "filename": t.filename,
                            "size": t.size,
                            "downloaded": t.downloaded,
                            "progress": round(pct, 2),
                            "speed": round(t.speed, 2),
                            "eta": round(t.eta, 2),
                            "status": t.status.value,
                            "category": t.category,
                        }
                    )
            await self._send_json(writer, 200, "OK", {"downloads": items}, origin)
            return

        data: dict[str, Any] = {}
        if body:
            try:
                data = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                await self._send_json(writer, 400, "Bad Request", {"error": "Invalid JSON body"}, origin)
                return

        if method == "POST" and path == "/api/show":
            if self.on_show_window is not None:
                self.on_show_window()
            await self._send_json(writer, 200, "OK", {"shown": True}, origin)
            return

        if method == "POST" and path == "/api/video":
            url = data.get("url")
            if not self._validate_url(url):
                await self._send_json(writer, 400, "Bad Request", {"error": "Invalid URL"}, origin)
                return
            cookies = (
                {str(k): str(v) for k, v in data["cookies"].items()}
                if isinstance(data.get("cookies"), dict)
                else {}
            )
            if bool(data.get("quick", False)) and self.on_quick_video is not None:
                self.on_quick_video(str(url).strip(), cookies)
            elif self.on_video_request is not None:
                self.on_video_request(str(url).strip(), cookies)
            await self._send_json(writer, 202, "Accepted", {"queued": True, "url": str(url).strip()}, origin)
            return

        if method == "POST" and path == "/api/download":
            url = data.get("url")
            if not self._validate_url(url):
                await self._send_json(writer, 400, "Bad Request", {"error": "Invalid URL"}, origin)
                return
            if self.download_engine is None:
                await self._send_json(writer, 503, "Service Unavailable", {"error": "Engine not ready"}, origin)
                return
            filename = str(data.get("filename") or "").strip() or None
            headers: dict[str, str] = {}
            if isinstance(data.get("headers"), dict):
                headers.update({str(k): str(v) for k, v in data["headers"].items()})
            if data.get("referrer"):
                headers["Referer"] = str(data["referrer"])
            if data.get("user_agent"):
                headers["User-Agent"] = str(data["user_agent"])
            cookies = (
                {str(k): str(v) for k, v in data["cookies"].items()}
                if isinstance(data.get("cookies"), dict)
                else {}
            )
            save_dir, category = self._resolve_save_dir(filename or str(url))
            cfg = self.config_manager.get() if self.config_manager else None
            conns = int(data.get("connections") or (cfg.default_connections if cfg else 8))
            proxy = self._proxy_url_from_config()
            if (
                cfg is not None
                and cfg.confirm_browser_download
                and self.on_download_confirm is not None
                and bool(data.get("confirm", True))
            ):
                self.on_download_confirm(
                    {
                        "url": str(url).strip(),
                        "filename": filename or "",
                        "save_path": save_dir,
                        "category": category,
                        "connections": conns,
                        "size": int(data.get("size") or -1),
                        "headers": headers,
                        "cookies": cookies,
                        "proxy": proxy,
                    }
                )
                await self._send_json(
                    writer,
                    202,
                    "Accepted",
                    {"confirming": True, "url": str(url).strip()},
                    origin,
                )
                return
            task = await self.download_engine.add_download(
                url=str(url).strip(),
                save_path=save_dir,
                filename=filename,
                headers=headers,
                cookies=cookies,
                proxy=proxy,
                connections=conns,
                category=category,
                start_now=bool(data.get("start_now", True)),
            )
            await self._send_json(
                writer,
                201,
                "Created",
                {"download_id": task.id, "filename": task.filename, "status": task.status.value},
                origin,
            )
            return

        if method == "POST" and path == "/api/download/batch":
            urls = data.get("urls")
            if not isinstance(urls, list) or not urls:
                await self._send_json(writer, 400, "Bad Request", {"error": "urls must be a non-empty list"}, origin)
                return
            if self.download_engine is None:
                await self._send_json(writer, 503, "Service Unavailable", {"error": "Engine not ready"}, origin)
                return
            created_ids: list[str] = []
            cfg = self.config_manager.get() if self.config_manager else None
            conns = cfg.default_connections if cfg else 8
            proxy = self._proxy_url_from_config()
            for item in urls:
                item_url = item.get("url") if isinstance(item, dict) else item
                if not self._validate_url(item_url):
                    continue
                fname = item.get("filename") if isinstance(item, dict) else None
                save_dir, category = self._resolve_save_dir(str(fname or item_url))
                task = await self.download_engine.add_download(
                    url=str(item_url).strip(),
                    save_path=save_dir,
                    filename=fname,
                    proxy=proxy,
                    connections=conns,
                    category=category,
                    start_now=True,
                )
                created_ids.append(task.id)
            await self._send_json(writer, 201, "Created", {"download_ids": created_ids}, origin)
            return

        if method == "POST" and path.startswith("/api/download/"):
            if self.download_engine is None:
                await self._send_json(writer, 503, "Service Unavailable", {"error": "Engine not ready"}, origin)
                return
            parts = [p for p in path.split("/") if p]
            download_id = ""
            action = ""
            if len(parts) == 4 and parts[:2] == ["api", "download"]:
                download_id, action = parts[2], parts[3]
            elif len(parts) == 3 and parts[:2] == ["api", "download"]:
                action = parts[2]
                download_id = str(data.get("id", "")).strip()

            if action in ("pause", "resume", "cancel") and download_id:
                if action == "pause":
                    await self.download_engine.pause_download(download_id)
                elif action == "resume":
                    await self.download_engine.resume_download(download_id)
                elif action == "cancel":
                    await self.download_engine.cancel_download(download_id)
                await self._send_json(writer, 200, "OK", {"id": download_id, "action": action}, origin)
                return

        await self._send_json(writer, 404, "Not Found", {"error": "Endpoint not found"}, origin)

    def _proxy_url_from_config(self) -> Optional[str]:
        if not self.config_manager:
            return None
        cfg = self.config_manager.get()
        if not cfg.proxy_enabled or not cfg.proxy_host:
            return None
        creds = ""
        if cfg.proxy_username:
            creds = f"{cfg.proxy_username}:{cfg.proxy_password}@"
        return f"{cfg.proxy_type}://{creds}{cfg.proxy_host}:{cfg.proxy_port}"

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.host,
            port=self.port,
        )
        logger.info("Local server listening on %s:%d", self.host, self.actual_port)

    async def stop(self) -> None:
        for ws in list(self._ws_clients):
            try:
                ws.close()
            except OSError:
                pass
        self._ws_clients.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        logger.info("Local server stopped")
