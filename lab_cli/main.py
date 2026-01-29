# Last updated 19 Jan 2026
import typer
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from rich.live import Live
import shlex
import time
import sys
import inspect
import os
import json
import numpy as np # Ensure numpy is imported for run-loop
from typing import List

from . import actions
# Force load the plugins
from .actions import laser_actions
from .actions import cryo_actions
from .actions import general_actions

# Application Modules
from .experiment_registry import save_experiment, get_experiment
from .actions import get_all_actions, get_action
from .equipment_api import get_all_equipment, get_equipment_by_id

app = typer.Typer(
    help="CLI to monitor and control lab equipment.",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_show_locals=False
)

console = Console()

# --- EXPERIMENT MANAGEMENT COMMANDS (SINGLE FILE VERSION) ---

# Location: One level up from the current package directory
EXPERIMENTS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), \
                                "user_experiments.json")

def _load_experiments():
    """Helper to load the monolithic experiments file."""
    if not os.path.exists(EXPERIMENTS_FILE):
        return {}
    try:
        with open(EXPERIMENTS_FILE, 'r') as f:
            return json.load(f)
    except json.JSONDecodeError:
        console.print("[red]Error: user_experiments.json is corrupted.[/red]")
        return {}
    except Exception as e:
        console.print(f"[red]Error loading experiments: {e}[/red]")
        return {}

def _save_experiments(data):
    """Helper to save the monolithic experiments file."""
    try:
        with open(EXPERIMENTS_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        console.print(f"[red]Error saving experiments: {e}[/red]")
        return False

def _edit_experiment_steps(exp_name: str, steps: list, full_data: dict):
    """Helper to edit steps within a specific experiment."""
    while True:
        console.print(f"\n[bold underline]Editing Experiment: {exp_name}[/bold underline]")
        for i, step in enumerate(steps):
            # Format step for display
            step_type = step.get('type', 'Unknown')
            params = ", ".join([f"{k}={v}" for k, v in step.items() if k != "type"])
            console.print(f"{i+1}. [cyan]{step_type}[/cyan] ({params})")

        choice = Prompt.ask("\nSelect Step ID to edit (or 'save', 'cancel', 'add')")

        if choice.lower() == 'cancel':
            return

        if choice.lower() == 'save':
            full_data[exp_name] = steps
            if _save_experiments(full_data):
                console.print(f"[green]Experiment '{exp_name}' saved successfully![/green]")
            return

        if choice.lower() == 'add':
            console.print("[yellow]To add steps, please use the 'define' command to overwrite \
                          this experiment.[/yellow]")
            continue

        # Parse Step Selection
        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(steps): raise ValueError
        except ValueError:
            console.print("[red]Invalid index.[/red]")
            continue

        # Edit Specific Step
        selected_step = steps[idx]
        console.print(f"[yellow]Editing Step {idx+1}: {selected_step.get('type')}[/yellow]")

        # Ask for param to change
        keys = list(selected_step.keys())
        param_choice = Prompt.ask("Enter parameter to change", choices=keys + ['delete', 'back'])

        if param_choice == 'back':
            continue

        if param_choice == 'delete':
            if typer.confirm(f"Delete step {idx+1}?"):
                steps.pop(idx)
                console.print("[red]Step removed.[/red]")
            continue

        # Change Value
        current_val = selected_step.get(param_choice)
        new_val = Prompt.ask(f"New value for '{param_choice}'", default=str(current_val))
        selected_step[param_choice] = new_val
        console.print(f"[green]Updated {param_choice} -> {new_val}[/green]")


@app.command("manage")
def manage_experiments():
    """
    Interactive menu to View, Edit, or Delete saved experiments.
    """
    # 1. Load Data
    data = _load_experiments()
    if not data:
        console.print(f"[yellow]No experiments found in {EXPERIMENTS_FILE}.[/yellow]")
        return

    exp_names = list(data.keys())

    # 2. Display Table
    table = Table(title=f"Stored Experiments")
    table.add_column("ID", justify="center", style="cyan", no_wrap=True)
    table.add_column("Name", style="magenta")
    table.add_column("Steps", justify="center")

    for i, name in enumerate(exp_names):
        step_count = len(data[name])
        table.add_row(str(i+1), name, str(step_count))

    console.print(table)

    # 3. Select Experiment
    selection = Prompt.ask("Select ID", default="q")
    if selection.lower() == 'q': return

    try:
        idx = int(selection) - 1
        if idx < 0 or idx >= len(exp_names): raise ValueError
    except ValueError:
        console.print("[red]Invalid selection.[/red]")
        return

    target_name = exp_names[idx]
    target_steps = data[target_name]

    # 4. Choose Action
    action = Prompt.ask(
        f"\nAction for [bold]{target_name}[/bold]",
        choices=["view", "edit", "delete", "rename", "cancel"],
        default="view"
    )

    if action == "view":
        console.print_json(data=target_steps)

    elif action == "delete":
        if typer.confirm(f"Are you sure you want to DELETE '{target_name}'?"):
            del data[target_name]
            _save_experiments(data)
            console.print(f"[red]Deleted '{target_name}'[/red]")

    elif action == "rename":
        new_name = Prompt.ask("Enter new name")
        if new_name in data:
            console.print("[red]Name already exists![/red]")
        else:
            data[new_name] = data.pop(target_name)
            _save_experiments(data)
            console.print(f"[green]Renamed to '{new_name}'[/green]")

    elif action == "edit":
        _edit_experiment_steps(target_name, target_steps, data)


# --- MONITORING COMMANDS ---

@app.command("status")
def status_monitor(refresh_rate: float = 2.0):
    """
    Continuously monitors and displays the status of all connected equipment.
    Press Ctrl+C to stop.
    """
    console.print("[bold blue]Starting Equipment Monitor... (Press Ctrl+C to stop)[/bold blue]")

    try:
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                # Fetch live data
                equipment_data = get_all_equipment()

                # Build Table
                table = Table(title=f"Lab Equipment Status (Updated: {time.strftime('%H:%M:%S')})")
                table.add_column("ID", style="cyan", no_wrap=True)
                table.add_column("Type", style="magenta")
                table.add_column("Status", justify="center")
                table.add_column("Key Readings", style="green")

                for eq_id, data in equipment_data.items():
                    # Status Coloring
                    status = data.get("status", "Unknown")
                    style = "green" if status == "Active" else "red"
                    if status == "Idle": style = "yellow"

                    # Format Readings (Generic approach)
                    readings = []
                    # We look for common scientific keys dynamically
                    for key, val in data.items():
                        if key in ["id", "type", "status", "last_check", "details"]: continue
                        if isinstance(val, (int, float)):
                            readings.append(f"{key}={val}")

                    readings_str = ", ".join(readings) if readings else "-"

                    table.add_row(
                        eq_id,
                        data.get("type", "Unknown"),
                        f"[{style}]{status}[/{style}]",
                        readings_str
                    )

                live.update(table)
                time.sleep(refresh_rate)

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Monitor stopped.[/bold yellow]")


@app.command("inspect")
def inspect_device(device_id: str):
    """
    Get detailed information for a specific device by ID.
    Example: inspect laser-01
    """
    data = get_equipment_by_id(device_id)
    if not data:
        console.print(f"[bold red]Device ID '{device_id}' not found.[/bold red]")
        return

    console.print(f"\n[bold underline]Device Report: {device_id}[/bold underline]")
    for key, value in data.items():
        console.print(f"[cyan]{key}:[/cyan] {value}")


# --- GENERIC CONTROL COMMANDS ---

@app.command("run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def run_action_cli(ctx: typer.Context, action_name: str):
    """
    Executes ANY registered action immediately.
    """
    # Look up the action
    action_def = get_action(action_name)
    if not action_def:
        console.print(f"[red]Error: Action '{action_name}' not found.[/red]")
        console.print("Available actions: " + ", ".join(get_all_actions().keys()))
        return

    # Determine params and callable function
    if hasattr(action_def, "params") and hasattr(action_def, "func"):
        # It is a wrapper object
        required_params = action_def.params
        action_func = action_def.func
    else:
        # It is a raw function
        sig = inspect.signature(action_def)
        # We filter out 'context' because the system injects it, the user shouldn't type it
        required_params = [p for p in sig.parameters if p != "context"]
        action_func = action_def

    # Parse extra arguments
    kwargs = {}
    for arg in ctx.args:
        if "=" in arg:
            key, value = arg.split("=", 1)
            key = key.lstrip("-")
            kwargs[key] = value

    # Check for missing parameters
    missing = [p for p in required_params if p not in kwargs]
    if missing:
        console.print(f"[yellow]Missing parameters for '{action_name}':[/yellow]")
        for param in missing:
            val = Prompt.ask(f"Enter value for '{param}'")
            kwargs[param] = val

    # Run the Action
    console.print(f"[bold]Running {action_name}...[/bold]")
    try:
        # Call the resolved function explicitly
        success = action_func(**kwargs)
        if success:
            console.print(f"[green]✔ Action {action_name} completed.[/green]")
        else:
            console.print(f"[red]✘ Action {action_name} failed.[/red]")
    except Exception as e:
        console.print(f"[bold red]Error executing action: {e}[/bold red]")


# --- EXPERIMENT BUILDER COMMANDS ---

@app.command("define")
def define_experiment(name: str):
    """
    Interactively define a NEW experiment recipe using ANY registered action.
    """
    console.print(f"[bold green]Defining Generic Experiment: {name}[/bold green]")

    actions = get_all_actions()
    steps = []

    while True:
        choices = list(actions.keys()) + ["finish"]
        cmd_type = Prompt.ask("\nSelect Action", choices=choices)

        if cmd_type == "finish":
            break

        action_def = actions[cmd_type]
        step_data = {"type": cmd_type}

        # Inspect parameters
        if hasattr(action_def, "params"):
             required_params = action_def.params
        else:
             sig = inspect.signature(action_def)
             required_params = [p for p in sig.parameters if p != "context"]

        console.print(f"[italic]Configuring {cmd_type}... (Use {{var}} for variables)[/italic]")

        # Loop over the FIXED parameter list
        for param in required_params:
            val = Prompt.ask(f"Value for '{param}'")
            step_data[param] = val

        steps.append(step_data)
        console.print(f"[cyan]Added step: {step_data}[/cyan]")

    save_experiment(name, steps)
    console.print(f"[bold green]Saved '{name}' with {len(steps)} steps.[/bold green]")

@app.command("run-loop")
def run_loop_generic(
    name: str,
    variable: str = typer.Option("x", help="Variable name to loop"),
    start: float = typer.Option(..., help="Start value"),
    end: float = typer.Option(..., help="End value"),
    step: float = typer.Option(..., help="Step size"),
):
    """
    Loops ANY defined experiment over a specific variable.
    """
    steps = get_experiment(name)
    if not steps:
        console.print(f"[red]Experiment '{name}' not found.[/red]")
        return

    # Handle range direction
    if start > end and step > 0: step = -step
    # Add tiny buffer to include the end value
    values = np.arange(start, end + step/10000.0, step)

    console.print(f"[bold]Looping '{name}' over {variable} ({start} -> {end})[/bold]")
    if not typer.confirm("Start?"): return

    for val in values:
        val = round(float(val), 5)
        console.print(f"\n[bold yellow]--- {variable} = {val} ---[/bold yellow]")

        # Context holds the current loop variable
        context = {variable: val}

        # Execute Steps
        for i, step_config in enumerate(steps):
            action_name = step_config["type"]
            action_def = get_action(action_name)

            if not action_def:
                console.print(f"[red]Unknown action: {action_name}[/red]")
                continue

            # Inspect parameters dynamically
            if hasattr(action_def, "params"):
                 param_names = action_def.params
            else:
                 # It is a raw function
                 sig = inspect.signature(action_def)
                 param_names = [p for p in sig.parameters if p != "context"]

            # Prepare Arguments (Substitute variables)
            kwargs = {}
            for param in param_names:
                raw_val = str(step_config.get(param, ""))

                # Format "{field}" -> "0.5" using the context
                try:
                    formatted_val = raw_val.format(**context)
                except (KeyError, ValueError, IndexError):
                    formatted_val = raw_val

                kwargs[param] = formatted_val

            # Pass context for logging/filenames/logic
            kwargs["context"] = context

            # RUN IT
            try:
                # Call the function directly (action_def IS the function)
                if hasattr(action_def, "func"):
                    success = action_def.func(**kwargs)
                else:
                    success = action_def(**kwargs)

                if not success:
                    console.print(f"[red]Step {i+1} ({action_name}) Failed![/red]")
            except Exception as e:
                console.print(f"[red]Error in step {i+1}: {e}[/red]")
                import traceback
                traceback.print_exc()

    console.print("\n[bold green]Loop Complete[/bold green]")

"""
Define your experiments with placeholders as usual (e.g., {field}, {power}). Then, just type:

lab-cli > run-multi set_magnet measure_spectrum

The program will then guide you:

    Enter Variable Name: field

    Values: 0:0.5:0.1 (This generates 0, 0.1, 0.2, 0.3, 0.4, 0.5)

    Enter Variable Name: power

    Values: 50,55,60,65,70,75 (Manual list)

    Enter Variable Name: done

It will check that you have 6 steps for both, and then execute the loop,
changing both variables simultaneously for every step.
"""

@app.command("run-multi")
def run_multi(
    experiments: List[str] = typer.Argument(..., help="List of experiment names to run"),
    delay: float = typer.Option(2.0, help="Delay (s) between experiments")
):
    """
    Interactively defines multiple variables to loop over simultaneously.
    No external files required. Enter 'done' when finished adding variables.
    """
    import numpy as np

    # Interactive Variable Setup
    # Stores lists of values: {'field': [0, 0.1], 'power': [50, 60]}
    variables = {}

    console.print("[bold green]Define your Loop Variables:[/bold green]")
    console.print("Formats accepted:\n - Range:  start:end:step (e.g. 0:1:0.1)\n \
                  - Manual: val1,val2,val3 (e.g. 50,60,70)")

    while True:
        var_name = Prompt.ask("\n[bold cyan]Enter Variable Name[/bold cyan] \
                              (or 'done' to finish)")
        if var_name.lower() == 'done':
            if not variables:
                console.print("[red]No variables defined![/red]")
                return
            break

        val_str = Prompt.ask(f"Values for '{var_name}'")

        try:
            # Parse "start:end:step" -> Numpy Array
            if ":" in val_str:
                parts = [float(x) for x in val_str.split(":")]
                if len(parts) == 3:
                    start, end, step = parts
                    # Handle negative steps
                    if start > end and step > 0: step = -step
                    # Create array with small buffer to include end value
                    vals = np.arange(start, end + step/10000.0, step)
                    vals = [round(x, 5) for x in vals.tolist()]
                else:
                    console.print("[red]Range format must be start:end:step[/red]")
                    continue

            # Parse "v1,v2,v3" -> List
            else:
                vals = [x.strip() for x in val_str.split(",")]

            variables[var_name] = vals
            console.print(f"[green]Added '{var_name}' with {len(vals)} steps: {vals}[/green]")

        except Exception as e:
            console.print(f"[red]Error parsing values: {e}[/red]")

    # Validation (Ensure all lists are same length)
    lengths = {k: len(v) for k, v in variables.items()}
    max_len = max(lengths.values())

    # Check for mismatches
    if len(set(lengths.values())) > 1:
        console.print(f"\n[bold red]Warning: Variable lengths do not match! {lengths}[/bold red]")
        console.print(f"The loop will run for {max_len} iterations.")
        console.print("Variables with fewer steps will repeat their last value.")
        if not typer.confirm("Continue?"): return

    # Execution Loop
    console.print(f"\n[bold]Starting Multi-Variable Loop ({max_len} iterations)...[/bold]")

    for i in range(max_len):
        # Build Context for this iteration
        context = {}
        for var, val_list in variables.items():
            # Get value safely (repeat last if index out of bounds)
            idx = min(i, len(val_list) - 1)
            context[var] = val_list[idx]

        loop_info = ", ".join([f"{k}={v}" for k, v in context.items()])
        console.print(f"\n[bold yellow]=== Iteration {i+1}/{max_len}: {loop_info} ===[/bold yellow]")

        # Run Sequence
        for exp_idx, exp_name in enumerate(experiments):
            steps = get_experiment(exp_name)
            if not steps:
                console.print(f"[red]Skipping unknown experiment: {exp_name}[/red]")
                continue

            console.print(f"[bold cyan]  Running: {exp_name}[/bold cyan]")

            # Execute Steps
            for step_idx, step_config in enumerate(steps):
                action_name = step_config["type"]
                action_def = get_action(action_name)

                if not action_def:
                    continue

                # Inspect Params
                if hasattr(action_def, "params"):
                    param_names = action_def.params
                else:
                    sig = inspect.signature(action_def)
                    param_names = [p for p in sig.parameters if p != "context"]

                # Substitute Variables
                kwargs = {}
                for param in param_names:
                    raw_val = str(step_config.get(param, ""))
                    try:
                        formatted_val = raw_val.format(**context)
                    except (KeyError, ValueError, IndexError):
                        formatted_val = raw_val
                    kwargs[param] = formatted_val

                kwargs["context"] = context

                # Execute
                try:
                    if hasattr(action_def, "func"):
                        action_def.func(**kwargs)
                    else:
                        action_def(**kwargs)
                except Exception as e:
                    console.print(f"[red]    Error in {exp_name} step \
                                  {step_idx+1}: {e}[/red]")

            # Delay between experiments
            if exp_idx < len(experiments) - 1:
                console.print(f"    [dim]Waiting {delay}s...[/dim]")
                time.sleep(delay)

    console.print("\n[bold green]Multi-Run Complete[/bold green]")


# --- INTERACTIVE SHELL ---

@app.command("interactive")
def interactive_shell():
    """
    Starts an interactive shell session.
    """
    console.print("\n[bold green]Entering interactive lab shell.[/bold green]")
    console.print("Type '[bold cyan]exit[/bold cyan]' to leave.")

    while True:
        try:
            command = Prompt.ask("[bold magenta]lab-cli >[/bold magenta]", default="")

            if command.lower() in ["exit", "quit"]:
                console.print("[bold yellow]Exiting shell.[/bold yellow]")
                break

            if not command.strip():
                continue

            # Process command
            args = shlex.split(command)

            # Run the typer command programmatically
            try:
                app(args, standalone_mode=False)
            except SystemExit:
                pass # Prevent the shell from closing on command exit
            except Exception as e:
                console.print(f"[bold red]Error running command:[/bold red] {e}")

        except KeyboardInterrupt:
            console.print("\n[bold yellow]Exiting shell.[/bold yellow]")
            break

if __name__ == "__main__":
    app()
