"""
AirSync Python Library
---------------------

A Python library for implementing the AirSync protocol, based on the 
"Discord.py" event-driven model.

This allows developers to easily integrate AirSync functionality into
their own Python applications.

Basic Usage:
    import airsync
    import asyncio
    import logging

    # 1. Create the server instance
    server = airsync.Server()

    # 2. Register the (required) mac_info_request handler
    @server.on_event("mac_info_request")
    async def provide_mac_info(handler_id, device_info):
        logging.info(f"Providing macInfo for {device_info.get('name')}")
        return {
            "name": "My Python App",
            "type": "PC",
            "isPlus": True,
            "isPlusSubscription": True
        }
    
    # 3. Register handlers for events you care about
    @server.on_event("notification")
    async def on_notification(data, handler_id):
        logging.info(f"Notification: [{data.get('app')}] {data.get('title')}")

    # 4. Start the server in your main async function
    async def main():
        logging.getLogger().setLevel(logging.INFO)
        server.print_qr_code()
        await server.start()

    if __name__ == "__main__":
        asyncio.run(main())
"""
from .server import Server

# This makes `airsync.Server` the main import
__all__ = ["Server"]

