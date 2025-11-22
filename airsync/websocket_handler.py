import asyncio, json, logging, os, base64, binascii, hashlib, tempfile, uuid
from websockets.exceptions import ConnectionClosed

class WebSocketHandler:
    def __init__(self, websocket, state, cipher, no_encrypt, parent_server, icon_cache_path):
        self.ws = websocket
        self.state = state
        self.cipher = cipher
        self.no_encrypt = no_encrypt
        self.parent_server = parent_server
        self.icon_cache_path = icon_cache_path
        self.handler_id = str(id(self))
        self.is_authenticated = False
        self.file_transfers = {}
        logging.debug(f"Handler {self.handler_id} created for {self.ws.remote_address}")

    async def send(self, message_dict: dict):
        if self.ws.closed:
            return
        try:
            message_str = json.dumps(message_dict)
            if not self.no_encrypt:
                message_str = self.cipher.encrypt_message(message_str)
            await self.ws.send(message_str)
        except ConnectionClosed:
            logging.info(f"Handler {self.handler_id}: Connection closed while trying to send.")
        except Exception as e:
            logging.warning(f"Handler {self.handler_id}: Failed to send message: {e}")

    async def listen(self):
        logging.info(f"Handler {self.handler_id}: New connection from {self.ws.remote_address}")
        try:
            async for message_str in self.ws:
                try:
                    if not self.no_encrypt:
                        message_str = self.cipher.decrypt_message(message_str)
                    if not message_str: continue
                    msg = json.loads(message_str)
                    msg_type, data = msg.get("type"), msg.get("data", {})
                    if not self.is_authenticated and msg_type != "device":
                        await self.close(code=1002, reason="Protocol violation: first message must be 'device'")
                        return
                    handler_method = getattr(self, f"handle_{msg_type}", self.handle_unknown)
                    await handler_method(data)
                except json.JSONDecodeError:
                    logging.warning(f"Handler {self.handler_id}: Received invalid JSON: {message_str[:100]}...")
                except Exception as e:
                    logging.error(f"Handler {self.handler_id}: Error handling message: {e}", exc_info=True)
        except ConnectionClosed:
            logging.info(f"Handler {self.handler_id}: Connection from {self.ws.remote_address} closed cleanly.")
        except Exception as e:
            logging.error(f"Handler {self.handler_id}: Listen loop error: {e}", exc_info=True)
        finally:
            for tf_id, transfer in self.file_transfers.items():
                if "handle" in transfer:
                    logging.warning(f"Cleaning up incomplete incoming file transfer: {tf_id}")
                    await asyncio.to_thread(transfer["handle"].close)
                    if os.path.exists(transfer["path"]):
                        await asyncio.to_thread(os.remove, transfer["path"])
            self.file_transfers.clear()

    async def close(self, code=1000, reason="Closing connection"):
        if not self.ws.closed:
            try:
                await self.ws.close(code=code, reason=reason)
            except Exception as e:
                logging.warning(f"Handler {self.handler_id}: Error during graceful close: {e}")

    async def handle_device(self, data):
        if self.is_authenticated:
            logging.warning(f"Handler {self.handler_id}: Received duplicate 'device' message. Ignoring.")
            return
        logging.info(f"Handler {self.handler_id}: Device handshake received: {data.get('name')}")
        self.state.set_device_info(data)
        self.is_authenticated = True
        try:
            mac_info_data = await self.parent_server._fire_event("mac_info_request", self.handler_id, data)
            if not mac_info_data: raise Exception("'mac_info_request' handler returned None or empty data.")
            app_icons_state = self.state.get_state("app_icons")
            mac_info_data["savedAppPackages"] = list(app_icons_state.keys())
            await self.send({"type": "macInfo", "data": mac_info_data})
            await self.parent_server._fire_event("device_connected", self.handler_id)
        except Exception as e:
            logging.critical(f"Handler {self.handler_id}: Failed to get macInfo from event handler: {e}")
            await self.close(code=1011, reason="Failed to get macInfo")

    async def handle_status(self, data):
        self.state.update_state("status", data)
        await self.parent_server._fire_event("status", data, self.handler_id)

    async def handle_notification(self, data):
        self.state.update_state("notification", data)
        await self.parent_server._fire_event("notification", data, self.handler_id)

    async def handle_notificationActionResponse(self, data): logging.debug(f"Notification action response: {data}")
    async def handle_notificationUpdate(self, data):
        self.state.update_state("notificationUpdate", data)
        await self.parent_server._fire_event("notificationUpdate", data, self.handler_id)
    async def handle_dismissalResponse(self, data): logging.debug(f"Notification dismissal response: {data}")
    async def handle_mediaControlResponse(self, data): logging.debug(f"Media control response: {data}")

    async def handle_macMediaControl(self, data):
        logging.info(f"Mac media control requested: {data}")
        await self.parent_server._fire_event("macMediaControl", data, self.handler_id)
        await self.send({"type": "macMediaControlResponse", "data": {"action": data.get("action"), "success": True}})

    async def handle_appIcons(self, data):
        logging.info(f"Handler {self.handler_id}: Received appIcons message with {len(data)} icons.")
        app_icons_metadata, cached_count = {}, 0
        for package_name, icon_data in data.items():
            icon_b64_raw = icon_data.get('icon')
            app_icons_metadata[package_name] = { "name": icon_data.get("name"), "systemApp": icon_data.get("systemApp"), "listening": icon_data.get("listening") }
            if not icon_b64_raw: continue
            icon_path = os.path.join(self.icon_cache_path, f"{package_name}.png")
            try:
                file_exists = await asyncio.to_thread(os.path.exists, icon_path)
                file_size = await asyncio.to_thread(os.path.getsize, icon_path) if file_exists else 0
                if not file_exists or file_size == 0:
                    icon_b64_data = icon_b64_raw.split(',', 1)[1] if "," in icon_b64_raw else icon_b64_raw
                    icon_b64_data = icon_b64_data.strip().replace("-", "+").replace("_", "/")
                    icon_b64_padded = icon_b64_data + ('=' * (-len(icon_b64_data) % 4))
                    decoded_data = await asyncio.to_thread(base64.b64decode, icon_b64_padded)
                    dir_name = os.path.dirname(icon_path)
                    if not await asyncio.to_thread(os.path.exists, dir_name):
                        await asyncio.to_thread(os.makedirs, dir_name, exist_ok=True)
                    
                    def write_file():
                        with open(icon_path, "wb") as f: f.write(decoded_data)
                    await asyncio.to_thread(write_file)
                    cached_count += 1
            except binascii.Error as e: logging.error(f"Failed to cache icon for {package_name}: {e}.")
            except Exception as e: logging.error(f"Failed to cache icon for {package_name}: {e}")
        logging.info(f"App icon caching complete. Wrote {cached_count} new icons to cache.")
        self.state.update_state("app_icons", app_icons_metadata)
        await self.parent_server._fire_event("app_icons", app_icons_metadata, self.handler_id)

    async def handle_clipboardUpdate(self, data):
        self.state.update_state("clipboardUpdate", data)
        await self.parent_server._fire_event("clipboardUpdate", data, self.handler_id)

    async def start_outgoing_file_transfer(self, file_path, file_name, file_size, mime_type, checksum):
        transfer_id = str(uuid.uuid4())
        chunk_size = 64 * 1024
        total_chunks = (file_size + chunk_size - 1) // chunk_size
        self.file_transfers[transfer_id] = {"ack_events": {i: asyncio.Event() for i in range(total_chunks)}, "verified_event": asyncio.Event()}
        logging.info(f"Handler {self.handler_id}: Starting outgoing transfer {transfer_id} ({file_name}, {total_chunks} chunks)")
        try:
            await self.send({"type": "fileTransferInit", "data": {"id": transfer_id, "name": file_name, "size": file_size, "mime": mime_type, "checksum": checksum,}})
            def read_chunks():
                with open(file_path, "rb") as f:
                    while chunk := f.read(chunk_size): yield chunk
            chunk_reader = await asyncio.to_thread(read_chunks)
            for index, chunk_data in enumerate(chunk_reader):
                chunk_b64 = await asyncio.to_thread(base64.b64encode, chunk_data)
                await self.send({"type": "fileChunk", "data": {"id": transfer_id, "index": index, "chunk": chunk_b64.decode('utf-8')}})
                try:
                    await asyncio.wait_for(self.file_transfers[transfer_id]["ack_events"][index].wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    logging.error(f"Handler {self.handler_id}: Timed out waiting for ack on chunk {index}")
                    raise Exception("File transfer timed out")
            await self.send({"type": "fileTransferComplete", "data": {"id": transfer_id, "name": file_name, "size": file_size, "checksum": checksum}})
            try:
                await asyncio.wait_for(self.file_transfers[transfer_id]["verified_event"].wait(), timeout=30.0)
                logging.info(f"Handler {self.handler_id}: Transfer {transfer_id} verified by phone.")
            except asyncio.TimeoutError:
                logging.error(f"Handler {self.handler_id}: Timed out waiting for final 'transferVerified' message.")
        except Exception as e:
            logging.error(f"Handler {self.handler_id}: File transfer {transfer_id} failed: {e}", exc_info=True)
        finally:
            if transfer_id in self.file_transfers: del self.file_transfers[transfer_id]

    async def handle_fileTransferInit(self, data):
        tf_id = data.get("id")
        try:
            temp_file = await asyncio.to_thread(tempfile.NamedTemporaryFile, delete=False, prefix="airsync_")
            self.file_transfers[tf_id] = {"meta": data, "path": temp_file.name, "handle": temp_file, "hash": hashlib.sha256()}
            logging.info(f"Handler {self.handler_id}: Receiving file: {data.get('name')}")
            await self.parent_server._fire_event("fileTransferInit", data, self.handler_id)
        except Exception as e:
            logging.error(f"Failed to open temp file for transfer {tf_id}: {e}")
            if tf_id in self.file_transfers:
                await asyncio.to_thread(self.file_transfers[tf_id]['handle'].close)
                if await asyncio.to_thread(os.path.exists, self.file_transfers[tf_id]['path']):
                    await asyncio.to_thread(os.remove, self.file_transfers[tf_id]['path'])
                del self.file_transfers[tf_id]

    async def handle_fileChunk(self, data):
        tf_id = data.get("id")
        if tf_id in self.file_transfers:
            try:
                chunk_data = await asyncio.to_thread(base64.b64decode, data.get("chunk", ""))
                transfer = self.file_transfers[tf_id]
                await asyncio.to_thread(transfer["handle"].write, chunk_data)
                transfer["hash"].update(chunk_data)
            except Exception as e:
                logging.error(f"Failed to write file chunk for {tf_id}: {e}")
        else:
            logging.warning(f"Handler {self.handler_id}: Received chunk for unknown transfer ID {tf_id}")

    async def handle_fileChunkAck(self, data):
        transfer_id, index = data.get("id"), data.get("index")
        if transfer_id in self.file_transfers and "ack_events" in self.file_transfers[transfer_id]:
            if ack_event := self.file_transfers[transfer_id]["ack_events"].get(index):
                ack_event.set()
            else: logging.warning(f"Handler {self.handler_id}: Received ack for unknown chunk index {index}")
        else: logging.warning(f"Handler {self.handler_id}: Received ack for unknown transfer {transfer_id}")
            
    async def handle_fileTransferComplete(self, data):
        tf_id = data.get("id")
        if tf_id in self.file_transfers:
            transfer = self.file_transfers[tf_id]
            await asyncio.to_thread(transfer["handle"].close)
            final_hash, doc_hash, verified = transfer["hash"].hexdigest(), data.get("checksum"), True
            if doc_hash and doc_hash != "null":
                if final_hash == doc_hash: logging.info(f"File checksum VERIFIED for {tf_id}: {final_hash}")
                else: logging.warning(f"File checksum MISMATCH for {tf_id}! Doc: {doc_hash}, Got: {final_hash}"); verified = False
            else: logging.info(f"No checksum provided for {tf_id}, assuming verified.")
            logging.info(f"Handler {self.handler_id}: File transfer complete: {data.get('name')}")
            data["temp_path"], data["verified"] = transfer["path"], verified
            await self.parent_server._fire_event("fileTransferComplete", data, self.handler_id)
            await self.send({"type": "transferVerified", "data": {"id": tf_id, "verified": verified}})
            del self.file_transfers[tf_id]
        else:
            logging.warning(f"Handler {self.handler_id}: Received complete for unknown transfer ID {tf_id}")

    async def handle_transferVerified(self, data):
        transfer_id, verified = data.get("id"), data.get("verified", False)
        if transfer_id in self.file_transfers and "verified_event" in self.file_transfers[transfer_id]:
            logging.info(f"Handler {self.handler_id}: Phone reports verification for {transfer_id}: {verified}")
            if verified_event := self.file_transfers[transfer_id].get("verified_event"):
                verified_event.set()
        else:
            logging.info(f"Handler {self.handler_id}: File transfer verified by device: {data}")

    async def handle_unknown(self, data):
        logging.warning(f"Handler {self.handler_id}: Received unknown message type.")