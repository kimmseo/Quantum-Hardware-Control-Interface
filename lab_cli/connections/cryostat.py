import sys
import requests
import json
import time
import socket
import struct
from pathlib import Path

CRYO_PORT = 2224

# Dynamic Path Setup
current_dir = Path(__file__).resolve().parent
libs_path = current_dir.parent / "read_only" / "Python Montana examples" / "libs"

if not libs_path.exists():
    # Fallback for local testing if folder structure differs
    libs_path = Path(r"C:\Users\qmqin\VSCode-v2\read_only\Python Montana examples\libs")

if libs_path.exists():
    libs_path_str = str(libs_path)
    if libs_path_str not in sys.path:
        sys.path.append(libs_path_str)

# Debugging
#print(f"DEBUG: Looking for libs at: {libs_path}")
#print(f"DEBUG: Path exists? {libs_path.exists()}")
#print(f"DEBUG: Current sys.path: {sys.path}")

# Import Library
try:
    import scryostation
except ImportError as e:
    print(f"DEBUG: Import failed details: {e}")
    scryostation = None

# Patch Requests
_cryo_session = requests.Session()
def persistent_get(url, params=None, **kwargs):
    return _cryo_session.get(url=url, params=params, **kwargs)
requests.get = persistent_get

# Helper: Direct REST Fallback
def _send_rest_put(ip: str, endpoint: str, data_payload):
    """Sends a PUT request with correct JSON headers (Fix for Error 400)."""
    url = f"http://{ip}:47101/v1/{endpoint}"
    headers = {'Content-Type': 'application/json'}
    try:
        resp = requests.put(url, data=json.dumps(data_payload), headers=headers, timeout=5)
        if resp.status_code in [200, 204]:
            return True, "Success"
        else:
            return False, f"Server Error {resp.status_code}: {resp.text}"
    except Exception as e:
        return False, str(e)

def get_cryostat_details(ip: str) -> dict:
    """Fetches current status (Temp, Pressure, Magnet)."""
    if not scryostation:
        return {"status": "Error", "details": "Library Import Failed"}

    try:
        cryo = scryostation.SCryostation(ip)

        # Temp & Pressure
        temp = cryo.get_temperature() if hasattr(cryo, 'get_temperature') else 0.0
        pressure = cryo.get_pressure() if hasattr(cryo, 'get_pressure') else 0.0

        # Magnet
        field = 0.0
        # Try different naming conventions for Magneto-Optic vs Standard
        if hasattr(cryo, 'get_magnet_target_field'):
            field = cryo.get_magnet_target_field()
        elif hasattr(cryo, 'getMagnetTargetField'):
             field = cryo.getMagnetTargetField()
        elif hasattr(cryo, 'get_mo_target_field'): # Specific to Magneto-Optic
             field = cryo.get_mo_target_field()

        return {
            "status": "Active",
            "temperature_k": float(temp),
            "pressure_torr": float(pressure),
            "magnet_field_tesla": float(field),
            "details": "Connected"
        }
    except Exception as e:
        return {"status": "Connection Error", "details": str(e)}

def set_temperature(ip: str, target_k: float) -> str:
    """Sets the platform target temperature[cite: 588]."""
    if not scryostation: return "Library missing"

    try:
        cryo = scryostation.SCryostation(ip)
        # Try Library Method
        if hasattr(cryo, 'set_platform_target_temperature'):
            cryo.set_platform_target_temperature(target_k)
            return f"Command sent: Set Temp to {target_k} K"
        elif hasattr(cryo, 'setRenderTargetTemperature'):
            cryo.setRenderTargetTemperature(target_k)
            return f"Command sent: Set Temp to {target_k} K"

        # Fallback to REST
        success, msg = _send_rest_put(ip, "controller/properties/platformTargetTemperature", target_k)
        return msg if not success else f"REST Command: Set Temp to {target_k} K"

    except Exception as e:
        return f"Error setting temp: {e}"

def set_magnet_field(ip: str, target_tesla: float) -> str:
    """Sets the magnetic field[cite: 520]. Auto-enables magnet if needed."""
    if not scryostation: return "Library missing"

    # Safety Check: Limits like +/- 2T or 0.7T depending on model
    # Can add a software limit here

    try:
        cryo = scryostation.SCryostation(ip)

        # Ensure Magnet is Enabled
        # Try library methods to enable
        try:
            if hasattr(cryo, 'set_magnet_state'): cryo.set_magnet_state(True)
            elif hasattr(cryo, 'setMagnetState'): cryo.setMagnetState(True)
        except:
            pass # Continue to try setting field anyway

        # Set Field
        # Try Library Method (Standard)
        if hasattr(cryo, 'set_magnet_target_field'):
            cryo.set_magnet_target_field(target_tesla)
            return f"Command sent: Field {target_tesla} T"

        # Try Library Method (CamelCase)
        elif hasattr(cryo, 'setMagnetTargetField'):
            cryo.setMagnetTargetField(target_tesla)
            return f"Command sent: Field {target_tesla} T"

        # Try Library Method (Magneto-Optic module specific)
        elif hasattr(cryo, 'set_mo_target_field'):
            cryo.set_mo_target_field(target_tesla)
            return f"Command sent: MO Field {target_tesla} T"

        # Fallback to REST
        success, msg = _send_rest_put(ip, "magnet/targetField", target_tesla)
        if success:
            # Also ensure enabled via REST
            _send_rest_put(ip, "magnet/state", "ENABLED")
            return f"REST Command: Field {target_tesla} T"
        else:
            return f"Failed to set field via Library or REST. {msg}"

    except Exception as e:
        return f"Error setting field: {e}"

def _send_cryo_command(ip: str, cmd_str: str) -> str:
    """
    Sends a text command to the Cryostation using the required 2-byte length
    prefix protocol
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(3.0) # Set a reasonable timeout
            s.connect((ip, CRYO_PORT))

            # Protocol: 2 bytes length + Command String
            # Encode the length as a 2-byte unsigned short
            # (Big Endian standard for network)
            cmd_bytes = cmd_str.encode('ascii')
            length_prefix = struct.pack('>H', len(cmd_bytes))

            # Send full message
            s.sendall(length_prefix + cmd_bytes)

            # Receive Response Length (First 2 bytes)
            resp_len_bytes = s.recv(2)
            if not resp_len_bytes:
                return "Error: No response"

            resp_len = struct.unpack('>H', resp_len_bytes)[0]

            # Receive Response Body
            response = s.recv(resp_len).decode('ascii')
            return response

    except Exception as e:
        return f"Error: {str(e)}"

def set_vacuum_pump(ip: str, enable: bool) -> str:
    """
    Controls the Cryostation Vacuum Pump to manage vibrations

    Args:
        ip (str): IP address of the cryostat
        enable (bool): True to RUN (SVPR), False to STOP (SVPS)

    Returns:
        str: Response from the cryostat (e.g., "OK, Vacuum pump set False")
    """
    # SVPR = Set Vacuum Pump Running
    # SVPS = Set Vacuum Pump Stopped
    command = "SVPR" if enable else "SVPS"

    response = _send_cryo_command(ip, command)
    return response
