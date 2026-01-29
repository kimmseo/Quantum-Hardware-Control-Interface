# Quantum Hardware Control Interface

A versatile, future-proof command-line interface (CLI) for automating laboratory equipment, running complex experiments, and monitoring hardware status.

This tool has evolved from a simple status monitor into a **modular automation framework**. It allows researchers to define experiment "recipes" interactively, loop over variables (like magnetic field or temperature), and acquire data without writing new Python code for every measurement.

---

## Supported Hardware

* **Toptica DLC Pro Lasers** — Full control via Toptica SDK (Emission, Power, Wide Scans).
* **Montana Instruments Cryostation** — Control via REST API/Library (Temperature, Magnetic Field, Pressure).
* **Keysight Oscilloscopes** — Screen capture and triggering via VISA.
* **Generic/Mock Devices** — Extensible support for any device driver.

---

## Key Features

### 1. Modular Action Registry

The core of the system is the **Action Registry**. Instead of hardcoding experiments, the CLI exposes atomic actions (e.g., `set-temp`, `sweep-laser`, `delay`).

* **Future-Proof:** Adding a new instrument is as simple as dropping a new Python file into the `actions/` folder. The CLI automatically detects and registers the new commands.

### 2. "No-Code" Experiment Builder

* **Define:** Create custom experiment workflows interactively inside the terminal.
* **Loop:** Execute workflows while sweeping a variable (e.g., “Loop `my_scan` while varying `field` from 0 T to 1 T”).
* **Save:** Recipes are stored in `user_experiments.json` and can be reused instantly.

### 3. Automated Data Acquisition

* Laser sweeps are saved as **Excel (.xlsx)** files for analysis and **PNG** images for quick reference.
* Output folders are automatically organized by experiment type and timestamp.

---

## Installation & Setup

### 1. Prerequisites

Ensure you have **Python 3.8+** installed.
NI-VISA drivers are required if using Oscilloscopes via USB/TCP.

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Folder Structure

Your project should be arranged like this:

```text
lab_cli/
├── main.py                 # Entry point
├── equipment_api.py        # Configuration (IP addresses)
├── experiment_registry.py  # JSON storage for user recipes
├── actions/                # <<< Place new action scripts here
│   ├── __init__.py
│   ├── cryo_actions.py
│   ├── laser_actions.py
│   └── general_actions.py
└── connections/            # Hardware drivers
    ├── laser.py
    ├── cryostat.py
    └── scryostation.py     # (Copy this from Montana Examples/libs)
```

### 4. Configuration

Edit `lab_cli/equipment_api.py` to set the IP addresses for your lab:

```python
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
    }
}
```

### 5. Install the application

```bash
pip install -e .
```

### 6. Start the application

```bash
lab-cli interactive
```

---

## Usage Guide

You can run the CLI in **Interactive Mode** (recommended) or via individual commands.

---

### 1. Interactive Shell

Start the persistent shell session:

```bash
python -m lab_cli.main interactive
```

You will see the prompt:

```
lab-cli >
```

---

### 2. Monitoring Status

Check the live health, temperature, and field of all devices:

```bash
status
```

See detailed properties of a single device:

```bash
inspect laser-01
inspect cryo-01
```

---

### 3. Running Instant Actions

You can execute any registered action immediately. Arguments are passed as `key=value`.

**Set Temperature:**

```bash
run set-temp target=295
```

**Set Magnetic Field:**

```bash
run set-field target=0.5
```

**Run a Laser Sweep:**

```bash
run sweep-laser start_nm=1530 end_nm=1535 speed=5 power=0.7
```

---

### 4. Defining & Looping Experiments
*(The Automation Workflow)*

Below is an example of creating an experiment called `my_magnet_sweep`.

---

#### Step A: Define the Recipe

```bash
define my_magnet_sweep
```

Follow the interactive prompts:

1. **Set the Magnetic Field**
   *Action:* `set-field`
   *value for `target`:* `{field}`
   *(Curly braces mark this as a loop variable.)*

2. **Wait for Stability**
   *Action:* `delay`
   *value for `seconds`:* `10`

3. **Run the Laser Sweep**
   *Action:* `sweep-laser`
   *Parameters:*
   - `start_nm`: `1530`
   - `end_nm`: `1535`
   - `speed`: `5`
   - `power`: `0.7`

4. **Save & Exit**
   *Action:* `finish`

---

#### Step B: Run the Loop

```bash
run-loop my_magnet_sweep --variable field --start 0 --end 0.5 --step 0.1
```

The system will:

1. Set field to 0.0 T
2. Wait 10 s
3. Sweep laser & save data
4. Set field to 0.1 T
5. Repeat until 0.5 T

---

## 5. Comprehensive Command Reference

### Core CLI Commands

| Command       | Arguments                                      | Description |
|-------------- |------------------------------------------------|-------------|
| `status`      | `[refresh_rate]`                               | Shows live dashboard of all devices. |
| `inspect`     | `device_id`                                    | Shows detailed status for a device. |
| `run`         | `action_name` `[key=value]...`                 | Executes a hardware action. |
| `define`      | `name`                                         | Starts the experiment-builder wizard. |
| `run-loop`    | `name` `--variable` `--start` `--end` `--step` | Loops an experiment while varying a variable. |
| `interactive` | *(none)*                                       | Enters persistent shell mode. |
| `exit`        | *(none)*                                       | Leaves the shell. |

---

### Hardware Actions (for `run`)

| Device    | Action Name     | Parameters                         | Description |
|-----------|------------------|------------------------------------|-------------|
| Cryostat  | `set-temp`       | `target`                           | Sets platform temperature (K). |
|           | `set-field`      | `target`                           | Sets magnetic field (T). |
| Laser     | `sweep-laser`    | `start_nm`, `end_nm`, `speed`, `power` | Performs a wide scan and saves data. |
| General   | `delay`          | `seconds`                          | Pauses execution. |
|           | `log`            | `message`                          | Prints a log message. |

---

## Developer Guide: Adding New Actions

To add support for a new device (e.g., a spectrometer), **you do not need to modify `main.py`**.

1. Create a new file:

```
lab_cli/actions/spectrometer_actions.py
```

2. Use the `@register_action` decorator:

```python
from . import register_action

@register_action("measure-spectrum")
def action_measure(integration_time: int, context: dict = None):
    """Captures a spectrum."""
    print(f"Measuring for {integration_time} ms...")
    # Add driver code here
    return True
```

3. Restart the CLI. The new command will appear:

```bash
run measure-spectrum
```

---
