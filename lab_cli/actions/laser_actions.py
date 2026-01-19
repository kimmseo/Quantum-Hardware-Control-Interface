# Last updated 19 Jan 2026
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

def _force_set(obj, param_name, value):
    """
    Robust setter that handles read-only properties by accessing private
    backing attributes or calling .set() methods.
    """
    # 1. Try Direct Assignment (Standard)
    try:
        setattr(obj, param_name, value)
        return True
    except AttributeError:
        pass # Expected for read-only properties

    # 2. Try Private Attribute with .set() (Common Toptica pattern)
    # e.g., obj.scan_begin is read-only, but obj._scan_begin is the controller
    private_name = f"_{param_name}"
    if hasattr(obj, private_name):
        internal_obj = getattr(obj, private_name)

        # Method A: Call .set() on the private object
        if hasattr(internal_obj, 'set'):
            try:
                internal_obj.set(value)
                return True
            except Exception as e:
                console.print(f"[yellow]Debug: {private_name}.set() failed: {e}[/yellow]")

        # Method B: Direct assignment to private var (Last resort)
        # Some SDKs wrap the value in the private var
        try:
            setattr(obj, private_name, value)
            return True
        except Exception:
            pass

    # 3. Check for specific '_set' suffix (Like sample_count_set)
    setter_name = f"{param_name}_set"
    if hasattr(obj, setter_name):
        target = getattr(obj, setter_name)
        if callable(target): # It's a method like set_param(val)
            target(value)
        else: # It's a property like param_set = val
            setattr(obj, setter_name, value)
        return True

    console.print(f"[red]Error: Could not set '{param_name}' - No setter found.[/red]")
    return False

def _internal_set_power(dlc, power_mw: float):
    """
    Helper function to set laser power (mW).
    """
    console.print(f"Setting power to {power_mw} mW...")
    try:
        # Method 1: Power Stabilization
        if hasattr(dlc.laser1, 'power_stabilization'):
            # Use _force_set to handle read-only 'enabled' and 'setpoint'
            # Based on debug output: _enabled and _setpoint exist
            _force_set(dlc.laser1.power_stabilization, 'enabled', True)
            _force_set(dlc.laser1.power_stabilization, 'setpoint', float(power_mw))

            console.print("[green]Power Stabilization Enabled & Set.[/green]")
            return True

        # Method 2: Direct CTL Power
        elif hasattr(dlc.laser1, 'ctl') and hasattr(dlc.laser1.ctl, 'power'):
            _force_set(dlc.laser1.ctl, 'power', float(power_mw))
            return True

        else:
            console.print("[yellow]Warning: Could not identify power control.[/yellow]")
            return False

    except Exception as e:
        console.print(f"[yellow]Warning: Failed to set power: {e}[/yellow]")
        return False

@register_action("enable-power-stabilization")
def action_enable_stabilization(state: int):
    """
    Enables (1) or Disables (0) the Power Stabilization loop.
    """
    ip, _ = _get_dlc_connection()
    if not ip: return False

    try:
        with DLCpro(NetworkConnection(ip)) as dlc:
            if not hasattr(dlc.laser1, 'power_stabilization'):
                console.print("[red]Error: No Power Stabilization module.[/red]")
                return False

            enable_bool = (int(state) == 1)
            # Use force setter
            if _force_set(dlc.laser1.power_stabilization, 'enabled', enable_bool):
                status_str = "ENABLED" if enable_bool else "DISABLED"
                console.print(f"[green]Power Stabilization {status_str}.[/green]")
                return True
            return False

    except Exception as e:
        console.print(f"[red]Failed to switch stabilization: {e}[/red]")
        return False

@register_action("set-laser-power")
def action_set_power(power: float):
    """
    Sets the laser power in mW and enables stabilization.
    """
    ip, _ = _get_dlc_connection()
    if not ip: return False

    try:
        with DLCpro(NetworkConnection(ip)) as dlc:
            success = _internal_set_power(dlc, power)
            if success:
                console.print(f"[green]Laser power updated to {power} mW.[/green]")
                return True
            return False
    except Exception as e:
        console.print(f"[red]Failed to connect or set power: {e}[/red]")
        return False

@register_action("sweep-laser")
def action_sweep(start_nm: float, end_nm: float, speed: float, power: float,
                 context: dict = None):
    """
    Performs a wide scan sweep with safety timeouts and status logging.
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
            # 1. Set Power
            _internal_set_power(dlc, power)

            console.print(f"Sweeping {start_nm}-{end_nm} nm @ {speed} nm/s...")

            # 2. Setup Sweep Parameters (Using _force_set)
            if not _force_set(dlc.laser1.wide_scan, 'scan_begin', float(start_nm)):
                return False
            _force_set(dlc.laser1.wide_scan, 'scan_end', float(end_nm))
            _force_set(dlc.laser1.wide_scan, 'speed', float(speed))

            # 3. Setup Recorder
            scan_range = abs(float(end_nm) - float(start_nm))
            duration = scan_range / float(speed)

            # Add safety buffer (minimum 10s or 20% extra)
            timeout_buffer = max(10.0, duration * 0.2)
            max_wait_time = duration + timeout_buffer

            _force_set(dlc.laser1.recorder, 'sampling_rate', 100.0)
            _force_set(dlc.laser1.recorder, 'recording_time', duration + 2.0)

            # 4. Start Sweep
            dlc.laser1.wide_scan.start()

            # 5. Monitor State with Timeout
            start_time = time.time()
            console.print(f"[cyan]Waiting for sweep (Max wait: {max_wait_time:.1f}s)...[/cyan]")

            last_state = -99

            while True:
                # Check for Timeout
                elapsed = time.time() - start_time
                if elapsed > max_wait_time:
                    console.print(f"\n[bold red]TIMEOUT: Sweep took longer than {max_wait_time:.1f}s.[/bold red]")
                    try:
                        dlc.laser1.wide_scan.stop() # Attempt to force stop
                    except:
                        pass
                    break

                # Read State
                try:
                    # Depending on SDK, this might need .get() or just direct access.
                    # We try direct access first (standard for properties)
                    current_state = dlc.laser1.wide_scan.state
                except Exception:
                    # Fallback if direct access fails
                    try:
                        current_state = dlc.laser1.wide_scan.state.get()
                    except:
                        current_state = -1

                # Check for Completion (State 0 = Idle)
                if current_state == 0:
                    console.print("\n[green]Sweep Complete (State 0).[/green]")
                    break

                # Log state changes
                if current_state != last_state:
                    console.print(f"Laser State: {current_state} (Scanning...)")
                    last_state = current_state

                time.sleep(0.5)

            # 6. Fetch Data
            # recorded_sample_count is read-only, direct access usually works
            try:
                total_samples = dlc.laser1.recorder.data.recorded_sample_count
            except TypeError:
                # Fallback if it requires .get()
                total_samples = dlc.laser1.recorder.data.recorded_sample_count.get()

            console.print(f"Acquiring {total_samples} samples...")

            x_data = []
            y_data = []

            if total_samples > 0:
                index = 0
                while index < total_samples:
                    chunk = min(1024, total_samples - index)
                    raw = dlc.laser1.recorder.data.get_data(index, chunk)

                    xy = extract_float_arrays('xy', raw)
                    if 'x' in xy: x_data.extend(xy['x'])
                    if 'y' in xy: y_data.extend(xy['y'])

                    index += chunk

            # 7. Save Data
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
        import traceback
        traceback.print_exc()
        return False
