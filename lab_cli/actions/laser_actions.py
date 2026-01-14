# Last updated 14 Jan 2026
import os
import time
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from rich.console import Console
from . import register_action
from ..equipment_api import EQUIPMENT_CONFIG

# Toptica Import logic
try:
    from toptica.lasersdk.dlcpro.v2_0_3 import DLCpro, NetworkConnection
    from toptica.lasersdk.utils.dlcpro import extract_float_arrays
    HAS_SDK = True
except ImportError:
    HAS_SDK = False

console = Console()

def _get_dlc_connection(conf_key="laser-01"):
    """Helper to get DLC connection details."""
    if not HAS_SDK:
        console.print("[red]Toptica SDK missing.[/red]")
        return None, None

    conf = EQUIPMENT_CONFIG.get(conf_key)
    if not conf:
        console.print(f"[red]Configuration for {conf_key} not found.[/red]")
        return None, None

    return conf["ip"], DLCpro

def _internal_set_power(dlc, power_mw: float):
    """
    Helper function to set laser power (mW).
    Automatically enables Power Stabilization if available.
    """
    console.print(f"Setting power to {power_mw} mW...")
    try:
        # Method 1: Power Stabilization (Preferred for constant output)
        if hasattr(dlc.laser1, 'power_stabilization'):
            # Auto-enable stabilization before setting the value
            dlc.laser1.power_stabilization.enabled.set(True)
            dlc.laser1.power_stabilization.setpoint.set(float(power_mw))
            console.print("[green]Power Stabilization Enabled & Set.[/green]")
            return True

        # Method 2: Direct CTL Power (Fallback)
        elif hasattr(dlc.laser1, 'ctl') and hasattr(dlc.laser1.ctl, 'power'):
            dlc.laser1.ctl.power.set(float(power_mw))
            return True

        else:
            console.print("[yellow]Warning: Could not identify power control \
                          attribute. Power not changed.[/yellow]")
            return False

    except Exception as e:
        console.print(f"[yellow]Warning: Failed to set power: {e}[/yellow]")
        return False

@register_action("enable-power-stabilization")
def action_enable_stabilization(state: int):
    """
    Enables (1) or Disables (0) the Power Stabilization loop.
    Usage: enable-power-stabilization 1
    """
    ip, _ = _get_dlc_connection()
    if not ip: return False

    try:
        with DLCpro(NetworkConnection(ip)) as dlc:
            # Check if feature exists
            if not hasattr(dlc.laser1, 'power_stabilization'):
                console.print("[red]Error: This laser does not have Power \
                              Stabilization.[/red]")
                return False

            enable_bool = (int(state) == 1)
            dlc.laser1.power_stabilization.enabled.set(enable_bool)

            status_str = "ENABLED" if enable_bool else "DISABLED"
            console.print(f"[green]Power Stabilization {status_str} \
                          successfully.[/green]")
            return True

    except Exception as e:
        console.print(f"[red]Failed to switch stabilization: {e}[/red]")
        return False

@register_action("set-laser-power")
def action_set_power(power: float):
    """
    Sets the laser power in mW and enables stabilization.
    Usage: set-laser-power 70 (Sets power to 70mW)
    """
    ip, _ = _get_dlc_connection()
    if not ip: return False

    try:
        with DLCpro(NetworkConnection(ip)) as dlc:
            success = _internal_set_power(dlc, power)
            if success:
                console.print(f"[green]Laser power setpoint updated \
                              to {power} mW.[/green]")
                return True
            else:
                return False
    except Exception as e:
        console.print(f"[red]Failed to connect or set power: {e}[/red]")
        return False

@register_action("sweep-laser")
def action_sweep(start_nm: float, end_nm: float, speed: float, power: float,
                 context: dict = None):
    """
    Performs a wide scan sweep and saves data.
    Automatically enables power stabilization at the requested power.
    Usage: sweep-laser start_nm=... end_nm=... speed=... power=70
    """
    ip, _ = _get_dlc_connection()
    if not ip: return False

    # Generate filename
    suffix = ""
    if context:
        for k, v in context.items():
            suffix += f"_{k}_{v}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = "Data_Sweeps"
    if not os.path.exists(folder): os.makedirs(folder)
    filename_base = os.path.join(folder, f"Sweep_{timestamp}{suffix}")

    try:
        with DLCpro(NetworkConnection(ip)) as dlc:
            # Set Power (Auto-enables stabilization)
            _internal_set_power(dlc, power)

            # Setup Sweep Parameters
            console.print(f"Sweeping {start_nm}-{end_nm} nm @ {speed} nm/s...")
            dlc.laser1.wide_scan.scan_begin.set(float(start_nm))
            dlc.laser1.wide_scan.scan_end.set(float(end_nm))
            dlc.laser1.wide_scan.speed.set(float(speed))

            # Setup Recorder
            scan_range = abs(float(end_nm) - float(start_nm))
            duration = scan_range / float(speed)

            # Explicitly set rate to 100 Hz
            dlc.laser1.recorder.sample_rate.set(100.0)

            # Add small buffer to recording time
            dlc.laser1.recorder.recording_time.set(duration + 1.0)

            # Start Sweep
            dlc.laser1.wide_scan.start()

            # Monitor State: 0 = Idle/Off, 1 = Moving/Scanning
            while dlc.laser1.wide_scan.state.get() != 0:
                time.sleep(0.5)

            # Fetch Data
            total_samples = dlc.laser1.recorder.data.recorded_sample_count.get()
            console.print(f"Acquiring {total_samples} samples...")

            x_data = []
            y_data = []

            if total_samples > 0:
                index = 0
                while index < total_samples:
                    chunk = min(1024, total_samples - index)
                    raw = dlc.laser1.recorder.data.get_data(index, chunk)

                    # Parse binary data
                    xy = extract_float_arrays('xy', raw)
                    if 'x' in xy: x_data.extend(xy['x'])
                    if 'y' in xy: y_data.extend(xy['y'])

                    index += chunk

            # Save Data
            if x_data and y_data:
                df = pd.DataFrame({"Wavelength": x_data, "Intensity": y_data})
                df.to_excel(f"{filename_base}.xlsx", index=False)

                plt.figure()
                plt.plot(df["Wavelength"], df["Intensity"])
                plt.title(os.path.basename(filename_base))
                plt.xlabel("Wavelength (nm)")
                plt.ylabel("Intensity")
                plt.grid(True)
                plt.savefig(f"{filename_base}.png")
                plt.close()
                console.print(f"[green]Saved: {os.path.basename(filename_base)}[/green]")
                return True
            else:
                console.print("[red]No data recorded.[/red]")
                return False

    except Exception as e:
        console.print(f"[red]Sweep Failed: {e}[/red]")
        return False
