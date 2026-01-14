# Last updated 5th December 2025
import typer
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from rich.live import Live
import shlex
import time
import sys
import inspect

from . import actions
# Force load the plugins
from .actions import laser_actions
from .actions import cryo_actions
from .actions import general_actions
# TODO: from .actions import oscillo_actions

# Application Modules
# Import from the generic registry and actions, not specific drivers
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

# MONITORING COMMANDS

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


# GENERIC CONTROL COMMANDS

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

    # Check for missing parameters using the NEW required_params list
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


# EXPERIMENT BUILDER COMMANDS

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

    import numpy as np
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

            # Prepare Arguments (Substitute variables)
            kwargs = {}
            for param in action_def.params:
                raw_val = str(step_config.get(param, ""))
                # Try to format "{field}" -> "0.5"
                try:
                    formatted_val = raw_val.format(**context)
                except KeyError:
                    formatted_val = raw_val # Keep raw if key missing or malformed
                except ValueError:
                    formatted_val = raw_val

                kwargs[param] = formatted_val

            # Pass context for logging/filenames/logic
            kwargs["context"] = context

            # RUN IT
            try:
                success = action_def.func(**kwargs)
                if not success:
                    console.print(f"[red]Step {i+1} ({action_name}) Failed![/red]")
            except Exception as e:
                console.print(f"[red]Error in step {i+1}: {e}[/red]")

    console.print("\n[bold green]Loop Complete[/bold green]")


# INTERACTIVE SHELL

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
