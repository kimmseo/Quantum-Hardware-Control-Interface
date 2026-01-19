# 1. Define the Registry
# (Renamed to match standard conventions, but simple 'registry' is fine too)
registry = {}

# 2. Define the Decorator
def register_action(name):
    def decorator(func):
        registry[name] = func
        return func
    return decorator

# 3. Define Helper Functions
def get_all_actions():
    """
    Returns the FULL registry dictionary.
    Format: {'command_name': function_object}
    """
    # Return the dict, not a list of keys
    return registry

def get_action(name):
    """Returns the function object for a specific command name."""
    return registry.get(name)

def handle_command(raw_input):
    """
    Legacy handler for raw string input.
    (Kept for compatibility, though main.py handles parsing now)
    """
    # Debugging
    # print(f"DEBUG: Available commands: {list(registry.keys())}")

    if not raw_input:
        return

    parts = raw_input.strip().split()
    if not parts:
        return

    cmd_name = parts[0]
    args = parts[1:]

    if cmd_name in registry:
        try:
            # Execute the function with arguments
            result = registry[cmd_name](*args)
            return result
        except TypeError as e:
            print(f"[Error] Argument mismatch for '{cmd_name}': {e}")
            return False
        except Exception as e:
            print(f"[Error] Failed to execute '{cmd_name}': {e}")
            return False
    else:
        print(f"[Error] Unknown command: '{cmd_name}'")
        return False

# 4. Import Plugins Last (Required to fill the registry)
# This executes the decorator @register_action in those files
try:
    from . import laser_actions
    from . import cryo_actions
    from . import general_actions
except ImportError as e:
    print(f"[Warning] Failed to load some actions: {e}")
