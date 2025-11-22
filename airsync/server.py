import asyncio, logging, os, socket, qrcode, io, base64, platform, hashlib, mimetypes
try:
    import magic
except ImportError:
    magic = None
from .crypto import AESSipher
from .state import DeviceState
from .websocket_server import WebSocketServer
from zeroconf import Zeroconf, ServiceInfo

class Server:
    def __init__(self, key_path: str = "airsync.key", icon_cache_path: str = "cache/icons", discovery: bool = False):
        self.state = DeviceState()
        self.cipher = AESSipher(key_path)
        self.event_handlers = {}
        self.no_encrypt = False 
        self.discovery = discovery
        self.zeroconf = None
        self.service_info = None
        self.icon_cache_path = icon_cache_path
        os.makedirs(self.icon_cache_path, exist_ok=True)
        self._ws_server = WebSocketServer(state=self.state, cipher=self.cipher, parent_server=self, icon_cache_path=self.icon_cache_path)
        self._local_ip = self._get_local_ip()
        logging.debug("AirSync Server initialized.")

    def on_event(self, event_type: str):
        def decorator(func):
            if not asyncio.iscoroutinefunction(func):
                raise TypeError("Event handler must be an async function")
            self.event_handlers[event_type] = func
            return func
        return decorator

    async def _fire_event(self, event_type: str, *args):
        if event_type in self.event_handlers:
            try:
                return await self.event_handlers[event_type](*args)
            except Exception as e:
                logging.error(f"Error in event handler for '{event_type}': {e}", exc_info=True)
        return None

    async def start(self, host: str = "0.0.0.0", port: int = 5297, no_encrypt: bool = False):
        if no_encrypt:
            logging.warning("="*50 + "\nENCRYPTION DISABLED. This is for debugging only.\n" + "="*50)
        self._ws_server.host, self._ws_server.port, self._ws_server.no_encrypt, self.no_encrypt = host, port, no_encrypt, no_encrypt
        
        if self.discovery:
            logging.info("Starting service discovery...")
            try:
                service_name, service_type = platform.node(), "_airsync._tcp.local."
                self.service_info = ServiceInfo(type_=service_type, name=f"{service_name}.{service_type}", addresses=[socket.inet_aton(self._local_ip)], port=port, properties={})
                self.zeroconf = Zeroconf()
                await asyncio.to_thread(self.zeroconf.register_service, self.service_info)
                logging.info(f"Service discovery active. Advertising '{service_name}' on {service_type}")
            except Exception as e:
                logging.error(f"Failed to start service discovery: {e}", exc_info=True)
                self.discovery = False
        try:
            await self._ws_server.start()
        except Exception as e:
            logging.critical(f"Failed to start WebSocket server: {e}")
            return
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            logging.info("Shutting down server...")
        finally:
            await self.stop()

    async def stop(self):
        if self.discovery and self.zeroconf:
            logging.info("Stopping service discovery...")
            try:
                await asyncio.to_thread(self.zeroconf.unregister_service, self.service_info)
                await asyncio.to_thread(self.zeroconf.close)
                logging.info("Service discovery stopped.")
            except Exception as e:
                logging.warning(f"Error while stopping service discovery: {e}")
        await self._ws_server.stop()
        logging.info("AirSync server has stopped.")

    def get_state(self, key: str = None):
        return self.state.get_state(key)

    async def send_message(self, handler_id: str, message_dict: dict):
        await self._ws_server.send_to_handler(handler_id, message_dict)

    async def broadcast_message(self, message_dict: dict):
        await self._ws_server.broadcast(message_dict)
    
    def _get_mime_type(self, file_path):
        mime_type = mimetypes.guess_type(file_path)[0]
        if mime_type: return mime_type
        if magic:
            try: return magic.from_file(file_path, mime=True)
            except Exception as e: logging.warning(f"python-magic failed to get MIME type: {e}")
        return "application/octet-stream"

    async def send_file(self, file_path: str, handler_id: str):
        if not os.path.exists(file_path):
            logging.error(f"Cannot send file: {file_path} does not exist.")
            return
        logging.info(f"Preparing to send file: {file_path} to {handler_id}")
        try:
            file_name = os.path.basename(file_path)
            file_size = await asyncio.to_thread(os.path.getsize, file_path)
            mime_type = await asyncio.to_thread(self._get_mime_type, file_path)
            sha256 = hashlib.sha256()
            def read_and_hash():
                with open(file_path, "rb") as f:
                    while chunk := f.read(65536):
                        sha256.update(chunk)
            await asyncio.to_thread(read_and_hash)
            checksum = sha256.hexdigest()
            handler = self._ws_server.get_handler(handler_id)
            if not handler:
                logging.error(f"Cannot send file: No active handler with ID {handler_id}")
                return
            await handler.start_outgoing_file_transfer(file_path=file_path, file_name=file_name, file_size=file_size, mime_type=mime_type, checksum=checksum)
        except Exception as e:
            logging.error(f"Failed to initiate file transfer: {e}", exc_info=True)

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def get_qr_code(self) -> str:
        if self.no_encrypt: 
            logging.error("Cannot generate QR code: Encryption is disabled.")
            return None
        key_b64 = self.cipher.get_key_base64()
        port = self._ws_server.port
        ip = self._local_ip
        connect_uri = f"airsync://{ip}:{port}?key={key_b64}"
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(connect_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode('utf-8')

    def print_qr_code(self):
        if self.no_encrypt: 
            logging.error("Cannot print QR code: Encryption is disabled.")
            return
        key_b64 = self.cipher.get_key_base64()
        port = self._ws_server.port
        ip = self._local_ip
        connect_uri = f"airsync://{ip}:{port}?key={key_b64}"
        qr = qrcode.QRCode(version=1, border=2)
        qr.add_data(connect_uri)
        qr.make(fit=True)
        print("--- Scan QR Code to Connect ---")
        qr.print_tty()
        print("-------------------------------")