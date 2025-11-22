import airsync, asyncio, logging, os, platform, pyperclip, shutil
from notifypy import Notify
from pathlib import Path

CURRENT_HANDLER_ID = None
logging.getLogger().setLevel(logging.INFO)
CACHE_DIR = "cache"
ICON_CACHE_DIR = os.path.join(CACHE_DIR, "icons")
DOWNLOADS_DIR = Path.home() / "Downloads"
os.makedirs(ICON_CACHE_DIR, exist_ok=True)
os.makedirs(DOWNLOADS_DIR, exist_ok=True) 

server = airsync.Server(
    key_path=os.path.join(CACHE_DIR, "airsync.key"),
    icon_cache_path=ICON_CACHE_DIR,
    discovery=True
)

@server.on_event("mac_info_request")
async def provide_mac_info(handler_id, device_info):
    logging.info(f"Device '{device_info.get('name')}' requesting macInfo.")
    return {
        "name": platform.node(), "categoryType": "PC", "exactDeviceName": "My PC",
        "model": "AirSync-Py", "type": "PC", "isPlus": True, "isPlusSubscription": True,
    }

async def send_file_task(handler_id):
    try:
        file_path = FILE PATH HERE
        if file_path:
            logging.info(f"Attempting to send file: {file_path}")
            await server.send_file(file_path, handler_id)
            logging.info(f"File sending complete: {file_path}")
        else:
            logging.info("File selection cancelled.")
    except Exception as e:
        logging.error(f"Failed to send file: {e}", exc_info=True)

@server.on_event("device_connected")
async def on_connect(handler_id):
    global CURRENT_HANDLER_ID
    CURRENT_HANDLER_ID = handler_id
    logging.info(f"Device {handler_id} connected!")

@server.on_event("device_disconnected")
async def on_disconnect(handler_id):
    global CURRENT_HANDLER_ID
    if CURRENT_HANDLER_ID == handler_id:
        CURRENT_HANDLER_ID = None
    logging.info(f"Device {handler_id} disconnected.")

@server.on_event("notification")
async def on_notification(data, handler_id):
    logging.info(f"Notification: {data.get('app')} - {data.get('title')}")
    notification = Notify()
    notification.application_name = data.get('app')
    notification.title = data.get('title')
    notification.message = data.get('body')
    package_name = data.get('package')
    if package_name:
        icon_path = os.path.join(ICON_CACHE_DIR, f"{package_name}.png")
        if os.path.exists(icon_path):
            notification.icon = icon_path
    notification.send()

@server.on_event("appIcons")
async def on_app_icons(data, handler_id):
    logging.info(f"Received metadata for {len(data)} app icons.")

@server.on_event("status")
async def on_status(data, handler_id):
    if "battery" in data:
        logging.info(f"Battery: {data['battery'].get('level')}% (Charging: {data['battery'].get('isCharging')})")
    if "music" in data and data['music'].get('title'):
        music = data['music']
        logging.info(f"Music: {music.get('title')} - {music.get('artist')}")

@server.on_event("clipboardUpdate")
async def on_clipboard(data, handler_id):
    text = data.get('text')
    logging.info(f"Phone clipboard updated: {text[:50]}...")
    pyperclip.copy(text)

@server.on_event("fileTransferInit")
async def on_file_init(data, handler_id):
    logging.info(f"Receiving file: {data.get('name')} ({data.get('size')} bytes)")

@server.on_event("fileTransferComplete")
async def on_file_complete(data, handler_id):
    temp_path = data.get("temp_path")
    final_name = data.get("name")
    
    if not temp_path or not final_name or not data.get("verified") or not os.path.exists(temp_path):
        logging.error(f"File transfer failed or was incomplete for: {final_name}")
        if temp_path and os.path.exists(temp_path):
             await asyncio.to_thread(os.remove, temp_path)
        return

    final_name = os.path.basename(final_name)
    dest_path = os.path.join(DOWNLOADS_DIR, final_name)
    
    try:
        await asyncio.to_thread(shutil.move, temp_path, dest_path)
        logging.info(f"File transfer complete. Saved to: {dest_path}")
    except Exception as e:
        logging.error(f"Failed to move completed file: {e}")
        await asyncio.to_thread(os.remove, temp_path)

async def background_task():
    while True:
        await asyncio.sleep(30)
        
        state = server.get_state()
        if state.get('status', {}).get('battery'):
            logging.debug(f"BG Task: Battery is {state['status']['battery']['level']}%")

async def main():
    asyncio.create_task(background_task())
    server.print_qr_code() 
    
    logging.info("Starting AirSync server... Press Ctrl+C to stop.")
    await server.start(port=5297)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Server shutting down...")