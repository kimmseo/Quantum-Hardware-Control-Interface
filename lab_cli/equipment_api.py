import time
from typing import Dict, Optional, Any
from datetime import datetime

# Import connection handlers
from .connections.laser import get_laser_details
from .connections.cryostat import get_cryostat_details, get_channel_temperature
# from .connections.oscilloscope import get_scope_details

# Config
EQUIPMENT_CONFIG = {
    "laser-01": {
        "type": "Toptica Laser",
        "ip": "192.168.0.39",
        "driver": "toptica_dlc"
    },
    "cryo-01": {
        "type": "Montana Cryostation",
        "ip": "192.168.0.178",
        "driver": "montana"
    },
    "scope-01": {
        "type": "Digital Oscilloscope",
        "ip": "192.168.0.92",
        "driver": "mock"
    }
}

def get_all_equipment() -> Dict[str, Any]:
    """Fetches live status from all configured devices."""
    results = {}

    for eq_id, config in EQUIPMENT_CONFIG.items():
        driver = config.get("driver")
        ip = config.get("ip")

        # Default Basic Info
        device_data = {
            "id": eq_id,
            "type": config["type"],
            "status": "Unknown",
            "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        # Dispatch to specific connection handler
        if driver == "toptica_dlc":
            details = get_laser_details(ip)
            device_data.update(details)

        elif driver == "montana":
            details = get_cryostat_details(ip)
            device_data.update(details)

        elif driver == "mock":
            device_data["status"] = "Idle"
            device_data["details"] = "Mock Device"

        results[eq_id] = device_data

    return results

def get_equipment_by_id(equipment_id: str) -> Optional[Dict[str, Any]]:
    """Fetches details for a single device."""
    config = EQUIPMENT_CONFIG.get(equipment_id)
    if not config:
        return None

    driver = config.get("driver")
    ip = config.get("ip")

    device_data = {
        "id": equipment_id,
        "type": config["type"],
        "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    if driver == "toptica_dlc":
        device_data.update(get_laser_details(ip))
    elif driver == "montana":
        device_data.update(get_cryostat_details(ip))
    else:
        device_data["status"] = "Idle (Mock)"

    return device_data

# Temp 3, Magnet cryostat
def get_magnet_temp_reading(channel_id: int = 3) -> float:
    """Helper to get the magnet temperature (defaults to Channel 3)."""
    config = EQUIPMENT_CONFIG.get("cryo-01")
    if not config or config.get("driver") != "montana":
        return 0.0

    return get_channel_temperature(config["ip"], channel_id)
