import argparse
import datetime
import io
import logging
import os
import platform
import pyautogui
import signal
import subprocess
import sys
import time

from PIL import Image

from gui_agents.s3.agents.grounding import OSWorldACI
from gui_agents.s3.agents.agent_s import AgentS3
from gui_agents.s3.browser.aci import BROWSER_PLATFORM, BrowserACI
from gui_agents.s3.browser.bridge import EXTENSION_DIR, ChromeBridge
from gui_agents.s3.core.engine import check_claude_code_login
from gui_agents.s3.utils.local_env import LocalEnv

current_platform = platform.system().lower()

# Global flag to track pause state for debugging
paused = False


def get_char():
    """Get a single character from stdin without pressing Enter"""
    try:
        # Import termios and tty on Unix-like systems
        if platform.system() in ["Darwin", "Linux"]:
            import termios
            import tty

            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(sys.stdin.fileno())
                ch = sys.stdin.read(1)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            return ch
        else:
            # Windows fallback
            import msvcrt

            return msvcrt.getch().decode("utf-8", errors="ignore")
    except:
        return input()  # Fallback for non-terminal environments


def signal_handler(signum, frame):
    """Handle Ctrl+C signal for debugging during agent execution"""
    global paused

    if not paused:
        print("\n\n🔸 Agent-S Workflow Paused 🔸")
        print("=" * 50)
        print("Options:")
        print("  • Press Ctrl+C again to quit")
        print("  • Press Esc to resume workflow")
        print("=" * 50)

        paused = True

        while paused:
            try:
                print("\n[PAUSED] Waiting for input... ", end="", flush=True)
                char = get_char()

                if ord(char) == 3:  # Ctrl+C
                    print("\n\n🛑 Exiting Agent-S...")
                    sys.exit(0)
                elif ord(char) == 27:  # Esc
                    print("\n\n▶️  Resuming Agent-S workflow...")
                    paused = False
                    break
                else:
                    print(f"\n   Unknown command: '{char}' (ord: {ord(char)})")

            except KeyboardInterrupt:
                print("\n\n🛑 Exiting Agent-S...")
                sys.exit(0)
    else:
        # Already paused, second Ctrl+C means quit
        print("\n\n🛑 Exiting Agent-S...")
        sys.exit(0)


# Set up signal handler for Ctrl+C
signal.signal(signal.SIGINT, signal_handler)

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

datetime_str: str = datetime.datetime.now().strftime("%Y%m%d@%H%M%S")

log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)

file_handler = logging.FileHandler(
    os.path.join("logs", "normal-{:}.log".format(datetime_str)), encoding="utf-8"
)
debug_handler = logging.FileHandler(
    os.path.join("logs", "debug-{:}.log".format(datetime_str)), encoding="utf-8"
)
stdout_handler = logging.StreamHandler(sys.stdout)
sdebug_handler = logging.FileHandler(
    os.path.join("logs", "sdebug-{:}.log".format(datetime_str)), encoding="utf-8"
)

file_handler.setLevel(logging.INFO)
debug_handler.setLevel(logging.DEBUG)
stdout_handler.setLevel(logging.INFO)
sdebug_handler.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    fmt="\x1b[1;33m[%(asctime)s \x1b[31m%(levelname)s \x1b[32m%(module)s/%(lineno)d-%(processName)s\x1b[1;33m] \x1b[0m%(message)s"
)
file_handler.setFormatter(formatter)
debug_handler.setFormatter(formatter)
stdout_handler.setFormatter(formatter)
sdebug_handler.setFormatter(formatter)

stdout_handler.addFilter(logging.Filter("desktopenv"))
sdebug_handler.addFilter(logging.Filter("desktopenv"))

logger.addHandler(file_handler)
logger.addHandler(debug_handler)
logger.addHandler(stdout_handler)
logger.addHandler(sdebug_handler)

platform_os = platform.system()


def show_permission_dialog(code: str, action_description: str):
    """Show a platform-specific permission dialog and return True if approved."""
    if platform.system() == "Darwin":
        result = os.system(
            f'osascript -e \'display dialog "Do you want to execute this action?\n\n{code} which will try to {action_description}" with title "Action Permission" buttons {{"Cancel", "OK"}} default button "OK" cancel button "Cancel"\''
        )
        return result == 0
    elif platform.system() == "Linux":
        result = os.system(
            f'zenity --question --title="Action Permission" --text="Do you want to execute this action?\n\n{code}" --width=400 --height=200'
        )
        return result == 0
    return False


def scale_screen_dimensions(width: int, height: int, max_dim_size: int):
    scale_factor = min(max_dim_size / width, max_dim_size / height, 1)
    safe_width = int(width * scale_factor)
    safe_height = int(height * scale_factor)
    return safe_width, safe_height


def claude_grounding_dimensions(width: int, height: int):
    # Claude locates elements most accurately on screenshots of about 1280x800 (WXGA)
    scale_factor = min(1280 / width, 800 / height, 1)
    return int(width * scale_factor), int(height * scale_factor)


def run_agent(
    agent, instruction: str, scaled_width: int, scaled_height: int, max_steps=15
):
    global paused
    obs = {}
    traj = "Task:\n" + instruction
    subtask_traj = ""
    for step in range(max_steps):
        # Check if we're in paused state and wait
        while paused:
            time.sleep(0.1)
        # Get screen shot using pyautogui
        screenshot = pyautogui.screenshot()
        screenshot = screenshot.resize((scaled_width, scaled_height), Image.LANCZOS)

        # Save the screenshot to a BytesIO object
        buffered = io.BytesIO()
        screenshot.save(buffered, format="PNG")

        # Get the byte value of the screenshot
        screenshot_bytes = buffered.getvalue()
        # Convert to base64 string.
        obs["screenshot"] = screenshot_bytes

        # Check again for pause state before prediction
        while paused:
            time.sleep(0.1)

        print(f"\n🔄 Step {step + 1}/{max_steps}: Getting next action from agent...")

        # Get next action code from the agent
        info, code = agent.predict(instruction=instruction, observation=obs)

        if "done" in code[0].lower() or "fail" in code[0].lower():
            if platform.system() == "Darwin":
                os.system(
                    f'osascript -e \'display dialog "Task Completed" with title "OpenACI Agent" buttons "OK" default button "OK"\''
                )
            elif platform.system() == "Linux":
                os.system(
                    f'zenity --info --title="OpenACI Agent" --text="Task Completed" --width=200 --height=100'
                )

            break

        if "next" in code[0].lower():
            continue

        if "wait" in code[0].lower():
            print("⏳ Agent requested wait...")
            time.sleep(5)
            continue

        else:
            time.sleep(1.0)
            print("EXECUTING CODE:", code[0])

            # Check for pause state before execution
            while paused:
                time.sleep(0.1)

            # Ask for permission before executing
            exec(code[0])
            time.sleep(1.0)

            # Update task and subtask trajectories
            if "reflection" in info and "executor_plan" in info:
                traj += (
                    "\n\nReflection:\n"
                    + str(info["reflection"])
                    + "\n\n----------------------\n\nPlan:\n"
                    + info["executor_plan"]
                )


def connect_browser(port: int) -> ChromeBridge:
    browser = ChromeBridge(port=port)
    if not browser.wait_for_extension(5):
        print(
            f"Waiting for the Agent S Chrome extension to connect on port {port}...\n"
            "If it is not installed yet: open chrome://extensions in Chrome, turn on "
            "Developer mode, click 'Load unpacked' and choose this folder:\n"
            f"  {EXTENSION_DIR}"
        )
        browser.wait_for_extension()
    print(
        "Agent S extension connected. Agent S works in the purple 'Agent S' tab group "
        "with its own cursor, so you can keep using your mouse, keyboard and other tabs."
    )
    return browser


def run_browser_agent(agent, grounding_agent, browser, instruction: str, max_steps=15):
    """Run a task in Agent S's own Chrome tab; the tab must already be started."""
    global paused
    status = "stopped"
    try:
        for step in range(max_steps):
            while paused:
                time.sleep(0.1)
            screenshot_bytes, width, height = browser.screenshot()
            # The tab can be resized between steps; coordinates follow its current size
            grounding_agent.width, grounding_agent.height = width, height

            print(
                f"\n🔄 Step {step + 1}/{max_steps}: Getting next action from agent..."
            )
            info, code = agent.predict(
                instruction=instruction, observation={"screenshot": screenshot_bytes}
            )
            action = code[0].strip()

            if action in ("DONE", "FAIL"):
                status = "done" if action == "DONE" else "failed"
                break
            if action in ("NEXT", "WAIT"):
                continue

            while paused:
                time.sleep(0.1)
            print("EXECUTING CODE:", action)
            # Runs in the agent's tab through the extension, not on your screen
            exec(action, {"browser": browser})
            time.sleep(1.0)
    except (ConnectionError, RuntimeError) as e:
        print(f"\n🛑 Agent S stopped: {e}")
        status = "failed"
    finally:
        try:
            browser.stop(status)
        except Exception as e:
            logger.warning("Could not hand the Agent S tab back: %s", e)

    print(f"\nAgent S finished the task: {status}")
    if platform.system() == "Darwin":
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "Task {status}" with title "Agent S"',
            ],
            check=False,
        )
    return status


def main():
    parser = argparse.ArgumentParser(description="Run AgentS3 with specified model.")
    parser.add_argument(
        "--provider",
        type=str,
        default="claude_code",
        help="Specify the provider to use (e.g., claude_code, openai, anthropic, etc.). "
        "claude_code uses the Claude subscription the `claude` CLI is logged in with, no API key needed.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="sonnet",
        help="Specify the model to use (e.g., sonnet, opus or a full Claude model ID for claude_code; gpt-5-2025-08-07 for openai)",
    )
    parser.add_argument(
        "--model_url",
        type=str,
        default="",
        help="The URL of the main generation model API.",
    )
    parser.add_argument(
        "--model_api_key",
        type=str,
        default="",
        help="The API key of the main generation model.",
    )
    parser.add_argument(
        "--model_temperature",
        type=float,
        default=None,
        help="Temperature to fix the generation model at (e.g. o3 can only be run with 1.0)",
    )

    # Grounding model config: Claude through the Claude Code CLI by default, or a self-hosted endpoint
    parser.add_argument(
        "--ground_provider",
        type=str,
        default="claude_code",
        help="The provider for the grounding model (claude_code by default, or e.g. huggingface for UI-TARS)",
    )
    parser.add_argument(
        "--ground_url",
        type=str,
        default="",
        help="The URL of the grounding model (not needed for claude_code)",
    )
    parser.add_argument(
        "--ground_api_key",
        type=str,
        default="",
        help="The API key of the grounding model.",
    )
    parser.add_argument(
        "--ground_model",
        type=str,
        default=None,
        help="The model name for the grounding model (defaults to --model for claude_code)",
    )
    parser.add_argument(
        "--grounding_width",
        type=int,
        default=None,
        help="Width of screenshot image after processor rescaling (worked out from the screen for claude_code)",
    )
    parser.add_argument(
        "--grounding_height",
        type=int,
        default=None,
        help="Height of screenshot image after processor rescaling (worked out from the screen for claude_code)",
    )

    # AgentS3 specific arguments
    parser.add_argument(
        "--max_trajectory_length",
        type=int,
        default=8,
        help="Maximum number of image turns to keep in trajectory",
    )
    parser.add_argument(
        "--enable_reflection",
        action="store_true",
        default=True,
        help="Enable reflection agent to assist the worker agent",
    )
    parser.add_argument(
        "--enable_local_env",
        action="store_true",
        default=False,
        help="Enable local coding environment for code execution (WARNING: Executes arbitrary code locally)",
    )
    parser.add_argument(
        "--max_steps",
        type=int,
        default=15,
        help="Maximum number of actions the agent takes for a task",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        default=False,
        help="Work in Agent S's own tab group in your Chrome, with its own cursor, instead of "
        "using your mouse and keyboard. Needs the Agent S Chrome extension.",
    )
    parser.add_argument(
        "--browser_port",
        type=int,
        default=8765,
        help="Local port the Agent S Chrome extension connects to",
    )
    parser.add_argument(
        "--start_url",
        type=str,
        default="https://www.google.com",
        help="Page the agent's Chrome tab opens first (with --browser)",
    )
    parser.add_argument(
        "--task",
        type=str,
        help="The task instruction for Agent-S3 to perform.",
    )

    args = parser.parse_args()

    if args.ground_provider != "claude_code":
        missing = [
            flag
            for flag, value in [
                ("--ground_url", args.ground_url),
                ("--ground_model", args.ground_model),
                ("--grounding_width", args.grounding_width),
                ("--grounding_height", args.grounding_height),
            ]
            if not value
        ]
        if missing:
            parser.error(
                f"{', '.join(missing)} required when --ground_provider is {args.ground_provider}"
            )

    if "claude_code" in (args.provider, args.ground_provider):
        ok, message = check_claude_code_login()
        print(message)
        if not ok:
            sys.exit(1)

    browser = None
    if args.browser:
        browser = connect_browser(args.browser_port)
        browser.start(args.start_url)
        _, screen_width, screen_height = browser.screenshot()
    else:
        screen_width, screen_height = pyautogui.size()

    # Re-scales screenshot size to ensure it fits in UI-TARS context limit
    scaled_width, scaled_height = scale_screen_dimensions(
        screen_width, screen_height, max_dim_size=2400
    )

    grounding_width, grounding_height = args.grounding_width, args.grounding_height
    if args.ground_provider == "claude_code" and not (
        grounding_width and grounding_height
    ):
        grounding_width, grounding_height = claude_grounding_dimensions(
            screen_width, screen_height
        )

    # Load the general engine params
    engine_params = {
        "engine_type": args.provider,
        "model": args.model,
        "base_url": args.model_url,
        "api_key": args.model_api_key,
        "temperature": getattr(args, "model_temperature", None),
    }

    # Load the grounding engine from a custom endpoint
    engine_params_for_grounding = {
        "engine_type": args.ground_provider,
        "model": args.ground_model or args.model,
        "base_url": args.ground_url,
        "api_key": args.ground_api_key,
        "grounding_width": grounding_width,
        "grounding_height": grounding_height,
    }

    # Initialize environment based on user preference
    local_env = None
    if args.enable_local_env and args.browser:
        print("The local coding environment is not available with --browser.")
    elif args.enable_local_env:
        print(
            "⚠️  WARNING: Local coding environment enabled. This will execute arbitrary code locally!"
        )
        local_env = LocalEnv()

    if args.browser:
        grounding_agent = BrowserACI(
            engine_params_for_generation=engine_params,
            engine_params_for_grounding=engine_params_for_grounding,
            width=screen_width,
            height=screen_height,
        )
    else:
        grounding_agent = OSWorldACI(
            env=local_env,
            platform=current_platform,
            engine_params_for_generation=engine_params,
            engine_params_for_grounding=engine_params_for_grounding,
            width=screen_width,
            height=screen_height,
        )

    agent = AgentS3(
        engine_params,
        grounding_agent,
        platform=BROWSER_PLATFORM if args.browser else current_platform,
        max_trajectory_length=args.max_trajectory_length,
        enable_reflection=args.enable_reflection,
    )

    def run(query):
        agent.reset()
        if browser:
            run_browser_agent(agent, grounding_agent, browser, query, args.max_steps)
        else:
            # Run the agent on your own device
            run_agent(agent, query, scaled_width, scaled_height, args.max_steps)

    task = args.task

    # handle query from command line
    if isinstance(task, str) and task.strip():
        run(task)
        return

    while True:
        query = input("Query: ")
        run(query)

        response = input("Would you like to provide another query? (y/n): ")
        if response.lower() != "y":
            break
        if browser:
            browser.start(args.start_url)


if __name__ == "__main__":
    main()
