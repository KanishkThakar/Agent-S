# Agent-S OpenClaw Integration

This integration enables [OpenClaw](https://github.com/openclaw/openclaw) to use [Agent-S](https://github.com/simular-ai/Agent-S) for autonomous GUI automation tasks.

## Overview

Agent-S is a powerful autonomous agent that can control your computer's graphical interface to complete complex tasks. This integration provides a simple wrapper that allows OpenClaw agents to invoke Agent-S for GUI automation.

## Prerequisites

### Required Software

1. **Agent-S**: Install the gui-agents package from this repository (the PyPI release does not have the `claude_code` provider yet)
   ```bash
   pip install git+https://github.com/KanishkThakar/Agent-S.git
   ```

2. **Tesseract**: Required for OCR functionality
   ```bash
   brew install tesseract  # macOS
   # or
   sudo apt install tesseract-ocr  # Linux
   ```

3. **Claude Code**: Agent-S runs Claude through the `claude` CLI on your Claude Pro or Max subscription. Install it and log in once:
   ```bash
   curl -fsSL https://claude.ai/install.sh | bash
   claude   # run /login inside if needed, then exit
   ```

4. **OpenClaw**: This integration is designed to work with OpenClaw

### No API Key Needed

By default the wrapper uses the `claude_code` provider with Claude Sonnet, for both planning and grounding (finding where to click). Every call goes through your logged-in `claude` CLI, so you do not need `ANTHROPIC_API_KEY`, and the wrapper never bills one even if it is set.

Optional settings:

- **`AGENT_S_MODEL`**: Claude model for the `claude_code` provider (default: "sonnet"; "opus" and "haiku" also work)
- **`AGENT_S_PROVIDER`**: Use a different provider, such as "openai" with `OPENAI_API_KEY` (default: "claude_code")

### Grounding Model Configuration (Optional)

Claude does the grounding unless you set `AGENT_S_GROUND_URL`. To use [UI-TARS-1.5-7B](https://huggingface.co/ByteDance-Seed/UI-TARS-1.5-7B) instead:

- **`AGENT_S_GROUND_URL`**: Grounding model endpoint URL
- **`AGENT_S_GROUND_MODEL`**: Model name (default: "ui-tars-1.5-7b")
- **`AGENT_S_GROUNDING_WIDTH`**: Output coordinate width (default: "1920")
- **`AGENT_S_GROUNDING_HEIGHT`**: Output coordinate height (default: "1080")
- **`AGENT_S_GROUND_API_KEY`**: API key for grounding endpoint

Example configuration:
```bash
export AGENT_S_GROUND_URL="http://localhost:8080"
export AGENT_S_GROUND_API_KEY="your-grounding-api-key"
export AGENT_S_GROUND_MODEL="ui-tars-1.5-7b"
export AGENT_S_GROUNDING_WIDTH="1920"
export AGENT_S_GROUNDING_HEIGHT="1080"
```

See the [Agent-S documentation](https://github.com/simular-ai/Agent-S#grounding-models-required) for details on setting up grounding models.

## Installation

1. **Clone or copy this directory** to your OpenClaw skills folder:
   ```bash
   cp -r integrations/openclaw ~/.openclaw/workspace/skills/agent-s
   ```

2. **Make scripts executable**:
   ```bash
   chmod +x ~/.openclaw/workspace/skills/agent-s/agent_s_task
   chmod +x ~/.openclaw/workspace/skills/agent-s/agent_s_wrapper.py
   ```

3. **Verify installation**:
   ```bash
   which agent_s
   # Should show the path to agent_s executable
   ```

## Usage

### From OpenClaw Agent

The OpenClaw agent can invoke Agent-S by reading the SKILL.md file and using the bash tool:

```bash
~/.openclaw/workspace/skills/agent-s/agent_s_task "Open Safari and go to google.com"
```

### From Command Line

You can test the integration directly:

```bash
# Basic usage
./agent_s_task "Open System Preferences"

# Using the Python wrapper with options
./agent_s_wrapper.py "Open TextEdit and type Hello World" --max-steps 10 --json
```

### Advanced Options

```bash
# Custom max steps
./agent_s_wrapper.py "complex task" --max-steps 30

# Disable reflection (faster but less accurate)
./agent_s_wrapper.py "simple task" --no-reflection

# Enable local code environment (WARNING: executes arbitrary code)
./agent_s_wrapper.py "task requiring code execution" --enable-local-env

# JSON output (for programmatic use)
./agent_s_wrapper.py "task" --json
```

## Testing

### Quick Test

Verify the integration works:

```bash
# Test 1: Check help
./agent_s_wrapper.py --help

# Test 2: Simple task (will actually execute)
./agent_s_task "Open Calculator"
```

### Testing with OpenClaw Agent

1. **Start OpenClaw**:
   ```bash
   openclaw
   ```

2. **Ask your agent** to use Agent-S:
   - "Can you use Agent-S to open the Calculator app?"
   - "I need you to use the Agent-S skill to open Safari and navigate to github.com"
   - "Read the Agent-S skill documentation and then use it to open System Preferences"

3. **Expected behavior**:
   - Agent reads `SKILL.md` in the skills directory
   - Agent executes `agent_s_task` command via bash tool
   - Agent-S launches and completes the GUI task
   - Results are returned to OpenClaw agent

### Verification Checklist

- [ ] `agent_s` executable is in PATH
- [ ] `claude auth status` reports `"loggedIn": true`
- [ ] Scripts are executable
- [ ] OpenClaw agent can read skill files
- [ ] Test task executes successfully

## Configuration

All configuration is done via environment variables (see Prerequisites section above).

### Customizing the Provider and Model

By default, the wrapper uses Claude Sonnet on your Claude subscription. To use a different model or provider, set environment variables:

```bash
# A different Claude model on your subscription
export AGENT_S_MODEL="opus"

# OpenAI with an API key
export AGENT_S_PROVIDER="openai"
export AGENT_S_MODEL="gpt-5-2025-08-07"
export OPENAI_API_KEY="your-api-key-here"
```

See the [Agent-S models documentation](https://github.com/simular-ai/Agent-S/blob/main/models.md) for all supported providers and models.

### Logs

Agent-S logs are stored in: `~/workspace/Agent-S/logs/`

Check these logs if something goes wrong:
```bash
ls -lt ~/workspace/Agent-S/logs/ | head -5
tail -f ~/workspace/Agent-S/logs/debug-*.log
```

## Safety

- Agent-S has full GUI control access
- Only use for trusted automation tasks
- All actions are logged
- Can be paused with Ctrl+C and resumed with Esc
- Timeout: 10 minutes per task by default

## Troubleshooting

### Agent-S not found

Check that agent_s is in your PATH:
```bash
which agent_s
```

If not found, install gui-agents:
```bash
pip install git+https://github.com/KanishkThakar/Agent-S.git
```

### Permission errors

Ensure scripts are executable:
```bash
chmod +x ./agent_s_task
chmod +x ./agent_s_wrapper.py
```

### Claude login errors

Agent-S stops at startup if the `claude` CLI is missing or logged out. Check:
```bash
which claude
claude auth status
```

If `loggedIn` is false, run `claude`, log in with `/login` using your Claude subscription, and exit. If you hit your plan's usage limit, Agent-S reports the CLI's message; wait for the limit to reset or switch to a smaller model with `AGENT_S_MODEL="haiku"`.

### Task failures

1. Check the logs in `~/workspace/Agent-S/logs/` for detailed error messages
2. Verify grounding configuration if using custom endpoint
3. Ensure task description is clear and specific
4. Try with `--no-reflection` for simpler tasks

### Grounding model issues

If clicks land in the wrong place with the default Claude grounding, describe the target element more specifically in the task. If you use a UI-TARS endpoint:
- Verify `AGENT_S_GROUND_URL` is accessible
- Check `AGENT_S_GROUND_API_KEY` is correct
- Ensure grounding dimensions match your model's output resolution

## Files

- **`README.md`** - This file
- **`SKILL.md`** - Skill documentation for the OpenClaw agent
- **`agent_s_wrapper.py`** - Python wrapper for invoking Agent-S
- **`agent_s_task`** - Simple bash entry point for task execution

## Support

- **Agent-S**: https://github.com/simular-ai/Agent-S
- **OpenClaw**: https://github.com/openclaw/openclaw
- **Report issues**: Use the Agent-S repository issue tracker for integration-specific issues

## License

This integration follows the same license as Agent-S. See the main repository for details.
