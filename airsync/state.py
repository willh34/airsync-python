import threading
import logging
from copy import deepcopy

class DeviceState:
    """
    A thread-safe class to cache the last known state of connected devices.
    
    This allows the developer to query the state (e.g., for widgets)
    without directly polling the device.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._state = {
            "device_info": {},    # From 'device' message
            "status": {},         # From 'status' message (battery, music)
            "notifications": {},  # Map of {notif_id: notif_data}
            "app_icons": {},      # Map of {package_name: icon_data}
            "clipboard": {},      # From 'clipboardUpdate' message
        }
        logging.debug("DeviceState initialized.")

    def set_device_info(self, data):
        """Sets the initial device info."""
        with self._lock:
            # For now, we only support one device's state.
            # A future improvement could manage state per-handler_id.
            self._state["device_info"] = data
            logging.info(f"State: Device info set for {data.get('name')}")

    def update_state(self, key, data):
        """Updates a specific part of the cached state."""
        with self._lock:
            if key == "notification":
                notif_id = data.get("id")
                if notif_id:
                    self._state["notifications"][notif_id] = data
                    logging.debug(f"State: Added notification {notif_id}")
            elif key == "notificationUpdate":
                notif_id = data.get("id")
                if data.get("dismissed") and notif_id in self._state["notifications"]:
                    del self._state["notifications"][notif_id]
                    logging.debug(f"State: Dismissed notification {notif_id}")
            elif key == "appIcons":
                self._state["app_icons"].update(data)
                logging.info(f"State: App icons updated. Total apps: {len(self._state['app_icons'])}")
            elif key == "clipboardUpdate":
                self._state["clipboard"] = data
                logging.info("State: Clipboard updated.")
            elif key in self._state:
                self._state[key] = data
                logging.debug(f"State: Updated key '{key}'")
            else:
                # --- ADDED ---
                # This is the source of the "Unknown key 'device'" log.
                # We can just log it as debug instead of warning.
                logging.debug(f"State: Ignoring update for unknown key '{key}'")
                # --- END ADDED ---

    def get_state(self, key=None):
        """
        Gets a deepcopy of the state.
        
        :param key: (Optional) The specific state key to retrieve.
        :return: A (deep)copy of the state dictionary.
        """
        with self._lock:
            if key:
                # Use deepcopy to prevent consumer from mutating the cache
                return deepcopy(self._state.get(key, {}))
            return deepcopy(self._state)


