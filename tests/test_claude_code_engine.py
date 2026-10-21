import base64
import io
import json
import os
import unittest
from unittest.mock import patch, MagicMock

from PIL import Image

from gui_agents.s3.core.engine import LMMEngineClaudeCode, check_claude_code_login
from gui_agents.s3.core.mllm import LMMAgent


def png_bytes(width, height):
    buffered = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffered, format="PNG")
    return buffered.getvalue()


def cli_result(text, is_error=False):
    events = [
        {"type": "system", "subtype": "init"},
        {"type": "result", "subtype": "success", "is_error": is_error, "result": text},
    ]
    return MagicMock(
        returncode=1 if is_error else 0,
        stdout="\n".join(json.dumps(e) for e in events),
        stderr="",
    )


class TestClaudeCodeEngine(unittest.TestCase):
    def setUp(self):
        patcher = patch(
            "gui_agents.s3.core.engine.shutil.which", return_value="/usr/bin/claude"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_agent(self, agent, response="ok"):
        """Run get_response with a mocked CLI and return (response, cmd, prompt, kwargs)."""
        captured = {}

        def fake_run(cmd, **kwargs):
            with open(
                cmd[cmd.index("--system-prompt-file") + 1], encoding="utf-8"
            ) as f:
                captured["system_prompt"] = f.read()
            return cli_result(response)

        with patch(
            "gui_agents.s3.core.engine.subprocess.run", side_effect=fake_run
        ) as run:
            result = agent.get_response()
        cmd, kwargs = run.call_args.args[0], run.call_args.kwargs
        prompt = json.loads(kwargs["input"])
        return result, cmd, prompt, kwargs, captured["system_prompt"]

    def test_engine_type_is_registered(self):
        agent = LMMAgent(engine_params={"engine_type": "claude_code", "model": "opus"})
        self.assertIsInstance(agent.engine, LMMEngineClaudeCode)
        self.assertEqual(agent.engine.model, "opus")

    def test_runs_cli_without_tools_and_without_api_key(self):
        agent = LMMAgent(
            engine_params={"engine_type": "claude_code"}, system_prompt="Be brief."
        )
        agent.add_message("Hello", role="user")
        env = {"ANTHROPIC_API_KEY": "sk-test", "CLAUDECODE": "1", "HOME": "/tmp"}
        with patch.dict(os.environ, env):
            result, cmd, prompt, kwargs, system_prompt = self.run_agent(agent, "Hi")

        self.assertEqual(result, "Hi")
        self.assertEqual(cmd[cmd.index("--model") + 1], "sonnet")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertIn("--no-session-persistence", cmd)
        self.assertEqual(system_prompt, "Be brief.")
        self.assertNotIn("ANTHROPIC_API_KEY", kwargs["env"])
        self.assertNotIn("CLAUDECODE", kwargs["env"])
        self.assertEqual(
            prompt["message"]["content"], [{"type": "text", "text": "Hello"}]
        )

    def test_history_is_flattened_into_one_turn(self):
        agent = LMMAgent(engine_params={"engine_type": "claude_code"})
        agent.add_message("Step 1", image_content=png_bytes(100, 50), role="user")
        agent.add_message("I clicked the button.", role="assistant")
        agent.add_message("Step 2", role="user")
        _, _, prompt, _, _ = self.run_agent(agent)

        content = prompt["message"]["content"]
        self.assertEqual(prompt["message"]["role"], "user")
        self.assertEqual(
            [block["type"] for block in content],
            ["text", "text", "image", "text", "text"],
        )
        self.assertIn(
            "<your_previous_reply>\nI clicked the button.", content[3]["text"]
        )
        self.assertEqual(content[4]["text"], "Step 2")

    def test_large_images_are_downscaled(self):
        agent = LMMAgent(engine_params={"engine_type": "claude_code"})
        agent.add_message("Look", image_content=png_bytes(2400, 1500), role="user")
        _, _, prompt, _, _ = self.run_agent(agent)

        data = prompt["message"]["content"][1]["source"]["data"]
        image = Image.open(io.BytesIO(base64.b64decode(data)))
        self.assertEqual(max(image.size), LMMEngineClaudeCode.MAX_IMAGE_EDGE)

    def test_grounding_mode_resizes_to_grounding_size(self):
        agent = LMMAgent(
            engine_params={
                "engine_type": "claude_code",
                "grounding_width": 1280,
                "grounding_height": 800,
            }
        )
        agent.add_message(
            "Query: the OK button", image_content=png_bytes(1440, 900), role="user"
        )
        result, _, prompt, _, system_prompt = self.run_agent(agent, "640, 400")

        self.assertEqual(result, "640, 400")
        self.assertIn("exactly 1280x800 pixels", system_prompt)
        data = prompt["message"]["content"][1]["source"]["data"]
        image = Image.open(io.BytesIO(base64.b64decode(data)))
        self.assertEqual(image.size, (1280, 800))

    def test_openai_style_messages_are_accepted(self):
        engine = LMMEngineClaudeCode()
        b64 = base64.b64encode(png_bytes(10, 10)).decode("utf-8")
        messages = [
            {"role": "system", "content": "Judge the runs."},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    }
                ],
            },
        ]
        with patch(
            "gui_agents.s3.core.engine.subprocess.run", return_value=cli_result("A")
        ) as run:
            self.assertEqual(engine.generate(messages), "A")
        content = json.loads(run.call_args.kwargs["input"])["message"]["content"]
        self.assertEqual(content[0]["type"], "image")

    def test_cli_error_is_raised(self):
        agent = LMMAgent(engine_params={"engine_type": "claude_code"})
        agent.add_message("Hello", role="user")
        with patch(
            "gui_agents.s3.core.engine.subprocess.run",
            return_value=cli_result("Not logged in", is_error=True),
        ):
            with self.assertRaises(RuntimeError) as cm:
                agent.get_response()
        self.assertIn("Not logged in", str(cm.exception))

    def test_missing_cli_is_reported(self):
        with patch("gui_agents.s3.core.engine.shutil.which", return_value=None):
            with patch.dict(os.environ, {}, clear=True):
                ok, message = check_claude_code_login()
        self.assertFalse(ok)
        self.assertIn("not found", message)

    def test_login_status(self):
        status = {"loggedIn": False}
        with patch(
            "gui_agents.s3.core.engine.subprocess.run",
            return_value=MagicMock(stdout=json.dumps(status)),
        ):
            ok, message = check_claude_code_login()
        self.assertFalse(ok)
        self.assertIn("not logged in", message)


if __name__ == "__main__":
    unittest.main()
