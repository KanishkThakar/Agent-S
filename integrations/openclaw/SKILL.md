# Agent-S - Autonomous GUI Agent

Agent-S is a powerful autonomous agent that can control your computer's graphical interface to complete complex tasks. It combines vision and action understanding to interact with any GUI element.

## What It Does

Agent-S can:
- Navigate and interact with desktop applications
- Fill forms, click buttons, and manipulate GUI elements
- Complete multi-step workflows across different applications
- Take screenshots and understand visual interfaces
- Execute complex GUI automation tasks autonomously

## When to Use

Use Agent-S when you need to:
- Automate GUI-based tasks that don't have CLI alternatives
- Interact with desktop applications programmatically
- Complete workflows that require visual understanding
- Perform actions across multiple applications
- Test GUI interfaces

## How to Invoke

Call the Agent-S wrapper via bash from the OpenClaw skills directory:

```bash
./agent_s_task "task description"
```

Or if installed in the default OpenClaw skills location:

```bash
~/.openclaw/workspace/skills/agent-s/agent_s_task "task description"
```

**Note**: Agent-S tasks can take 2-5 minutes to complete (up to 15 steps by default). The wrapper will wait for completion.

## Parameters

- `task` (required): Natural language description of the GUI task to complete
- `max_steps` (optional): Maximum steps the agent can take (default: 15)
- `enable_reflection` (optional): Enable self-reflection for better performance (default: true)

## Examples

```python
# Basic navigation
agent_s_task(task="Open Finder and create a new folder called 'Reports'")

# Form filling
agent_s_task(task="Open TextEdit, create a new document, and type 'Hello World'")

# Multi-step workflows
agent_s_task(task="Open Chrome, search for 'Python tutorials', and bookmark the first result")

# Application interaction
agent_s_task(task="Open System Preferences and check the current display resolution")
```

## Technical Details

Agent-S uses:
- **Main Model**: Claude Sonnet for reasoning and planning, through the `claude` CLI on the user's Claude subscription (no API key)
- **Grounding Model**: Claude as well by default, or UI-TARS-1.5-7B when `AGENT_S_GROUND_URL` is set
- **Screen Resolution**: Automatically scaled to 2400px max dimension
- **Platform Support**: macOS, Linux, Windows

## Safety

- Agent-S has full GUI control - only use for trusted tasks
- The agent will pause on Ctrl+C and can be resumed with Esc
- Each action is logged to `~/workspace/Agent-S/logs/`
- Tasks timeout after 15 steps by default

## Configuration

**Required:**
- The `claude` CLI installed and logged in with a Claude subscription (`claude auth status` shows `"loggedIn": true`). No API key is needed.

**Optional environment variables:**
- `AGENT_S_MODEL`: Claude model (default: sonnet)
- `AGENT_S_PROVIDER`: Another provider such as openai, which then needs its API key (default: claude_code)
- `AGENT_S_GROUND_URL`: UI-TARS grounding endpoint URL, to use instead of Claude grounding
- `AGENT_S_GROUND_MODEL`: Grounding model name (default: ui-tars-1.5-7b)
- `AGENT_S_GROUNDING_WIDTH`: Output width (default: 1920)
- `AGENT_S_GROUNDING_HEIGHT`: Output height (default: 1080)
- `AGENT_S_GROUND_API_KEY`: API key for grounding endpoint

See the README.md in this directory for detailed setup instructions.

## Limitations

- Cannot interact with system-level dialogs requiring admin approval
- Performance depends on screen resolution and GUI complexity
- Some applications may have accessibility restrictions
- Voice/audio commands are not supported

## Source

Agent-S GitHub: https://github.com/simular-ai/Agent-S
Installation: `pip install git+https://github.com/KanishkThakar/Agent-S.git`
