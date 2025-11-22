import asyncio, logging
from websockets.server import serve, WebSocketServerProtocol
from websockets.exceptions import ConnectionClosed
from .websocket_handler import WebSocketHandler

class WebSocketServer:
    def __init__(self, state, cipher, parent_server, icon_cache_path):
        self.state = state
        self.cipher = cipher
        self.parent_server = parent_server
        self.icon_cache_path = icon_cache_path
        self.server = None
        self.handlers = set()
        self.host = "0.0.0.0"
        self.port = 5297
        self.no_encrypt = False

    async def _handler_wrapper(self, websocket: WebSocketServerProtocol):
        handler = WebSocketHandler(websocket=websocket, state=self.state, cipher=self.cipher, no_encrypt=self.no_encrypt, parent_server=self.parent_server, icon_cache_path=self.icon_cache_path)
        self.handlers.add(handler)
        try:
            await handler.listen()
        except ConnectionClosed as e:
            logging.info(f"Connection closed: {websocket.remote_address} (Code: {e.code})")
        except Exception as e:
            logging.error(f"Error in handler for {websocket.remote_address}: {e}", exc_info=True)
        finally:
            if handler in self.handlers:
                self.handlers.remove(handler)
            await self.parent_server._fire_event("device_disconnected", handler.handler_id)
            logging.info(f"Device disconnected: {websocket.remote_address}. Total handlers: {len(self.handlers)}")

    async def start(self):
        if self.server:
            logging.warning("WebSocket server is already running.")
            return
        logging.info(f"Starting WebSocket server on {self.host}:{self.port}...")
        try:
            self.server = await serve(self._handler_wrapper, self.host, self.port, max_size=100 * 1024 * 1024)
        except Exception as e:
            logging.critical(f"Failed to start WebSocket server: {e}", exc_info=True)
            raise

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
            logging.info("WebSocket server stopped.")
        for handler in list(self.handlers):
            await handler.close()
        self.handlers.clear()

    async def send_to_handler(self, handler_id: str, message_dict: dict):
        found_handler = next((h for h in self.handlers if h.handler_id == handler_id), None)
        if found_handler and found_handler.is_authenticated:
            await found_handler.send(message_dict)
        else:
            logging.warning(f"Could not send message: Handler {handler_id} not found or not authenticated.")

    def get_handler(self, handler_id: str):
        return next((h for h in self.handlers if h.handler_id == handler_id), None)

    async def broadcast(self, message_dict: dict):
        if not self.handlers:
            return
        tasks = [asyncio.create_task(h.send(message_dict)) for h in self.handlers if h.is_authenticated]
        if not tasks:
            return
        try:
            await asyncio.wait(tasks, timeout=5)
        except Exception as e:
            logging.error(f"Error during broadcast: {e}", exc_info=True)