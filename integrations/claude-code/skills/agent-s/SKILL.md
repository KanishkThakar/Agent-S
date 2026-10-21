---
name: agent-s
description: Operate websites in the user's own Chrome (its own tab group and cursor, without touching their mouse) or the desktop GUI of this computer with Agent S, using the user's Claude subscription. Use when the user asks to do something in a desktop or web app that has no CLI or API, such as "open Calculator", "click through this settings dialog" or "fill in this form in Safari".
---

# Agent S: GUI tasks on this computer

Agent S looks at the screen, then clicks, types and scrolls until a task is done. It calls Claude through the `claude` CLI, so it runs on the Claude subscription the CLI is logged in with. It needs no API key and no grounding endpoint.

## Before the first run

1. Check that the CLI is installed: `command -v agent_s`. If it is missing, install it with Python 3.9 to 3.12, from the user's clone (`pip install -e <path to Agent-S>`) or with `pip install git+https://github.com/KanishkThakar/Agent-S.git`. The PyPI `gui-agents` release does not have the Claude subscription support. Also make sure `tesseract` is installed (`brew install tesseract` on macOS).
2. Check that `claude auth status` reports `"loggedIn": true`. If it does not, ask the user to run `claude` and log in.
3. On macOS, the terminal that runs `agent_s` needs Screen Recording and Accessibility permission (System Settings → Privacy & Security). If screenshots come back blank or clicks do nothing, ask the user to grant both.

## Running a task

There are two modes. Run either one in the background, because a task can take several minutes.

**Website tasks: use `--browser`.** Agent S works in the user's own signed-in Chrome, in a purple "Agent S" tab group, with its own cursor, and never touches their mouse or keyboard, so they can keep working. It needs the Agent S extension: if `agent_s` prints "Waiting for the Agent S Chrome extension", ask the user to open `chrome://extensions`, turn on Developer mode, click Load unpacked and choose `gui_agents/s3/browser/extension` in the repository.

```bash
agent_s --browser --task "Search Wikipedia for Alan Turing and open his article" --max_steps 15
```

**Desktop apps: no flag.** Agent S then drives the real mouse and keyboard. Tell the user it will take over both until it finishes, that they should not type meanwhile, and that pressing Ctrl+C in the terminal pauses it.

```bash
agent_s --task "Open Calculator and compute 12 * 34" --max_steps 15
```

- Write the task as one clear instruction that names the app and the end state.
- `--max_steps` caps the number of actions (15 by default). Use about 5 for a one-click task and up to 30 for a long one.
- `--model opus` uses Opus instead of the default Sonnet. It uses more of the subscription's limits.
- `--enable_local_env` lets Agent S run Python and Bash code for tasks such as spreadsheet edits. Use it only when the user agrees, since the code runs unsandboxed on their machine.

When the run ends, read its output (the last plan and action), check the result yourself where you can (for example a file it should have written), and tell the user what happened. Logs are written to `logs/` in the folder you ran the command from.

## Limits

- Desktop mode: one monitor only, and on macOS a "Task Completed" dialog appears at the end and waits for the user to click OK.
- Browser mode: web pages only. The agent acts in the user's logged-in sessions, so do not give it tasks the user has not asked for. Never put the user's passwords in a task; if a site needs a sign-in, ask the user to sign in in Chrome first.
- Each step makes three or four Claude calls and takes about 10 to 30 seconds, and all of them count against the user's subscription usage limits.
