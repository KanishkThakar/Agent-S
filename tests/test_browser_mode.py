import base64
import contextlib
import io
import json
import socket
import threading
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from gui_agents.s3.browser.aci import BrowserACI
from gui_agents.s3.browser.bridge import EXTENSION_VERSION, ChromeBridge
from gui_agents.s3.memory.procedural_memory import PROCEDURAL_MEMORY


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def png_b64(width, height):
    buffered = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


class FakeExtension:
    """Plays the Agent S extension: says hello, then answers calls with `handler`."""

    def __init__(self, port, handler, version=EXTENSION_VERSION):
        self.calls = []
        self.handler = handler
        self.stack = contextlib.ExitStack()
        self.ws = self.stack.enter_context(
            connect(f"ws://127.0.0.1:{port}", origin="chrome-extension://agent-s-test")
        )
        self.ws.send(json.dumps({"type": "hello", "version": version}))
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        try:
            for raw in self.ws:
                message = json.loads(raw)
                self.calls.append(message)
                result, error = self.handler(message)
                reply = {"type": "result", "id": message["id"], "result": result}
                if error:
                    reply["error"] = error
                self.ws.send(json.dumps(reply))
        except Exception:
            pass

    def close(self):
        self.stack.close()


class TestBrowserACI(unittest.TestCase):
    def setUp(self):
        params = {"engine_type": "claude_code", "model": "sonnet"}
        grounding = dict(params, grounding_width=1280, grounding_height=800)
        with patch("gui_agents.s3.core.engine.shutil.which", return_value="claude"):
            self.aci = BrowserACI(params, grounding, width=1280, height=800)
        self.aci.generate_coords = MagicMock(return_value=[640, 400])
        self.aci.assign_screenshot({"screenshot": b"png"})

    def test_prompt_offers_browser_actions_only(self):
        prompt = PROCEDURAL_MEMORY.construct_simple_worker_procedural_memory(
            BrowserACI, skipped_actions=[]
        )
        for action in ["open_url", "go_back", "click", "type", "scroll", "done"]:
            self.assertIn(f"def {action}(", prompt)
        for action in ["open", "switch_applications", "set_cell_values"]:
            self.assertNotIn(f"def {action}(", prompt)

    def test_actions_call_the_browser(self):
        self.assertEqual(
            self.aci.click("The search button", 2),
            "browser.click(640, 400, clicks=2, button='left', hold_keys=[])",
        )
        self.assertEqual(
            self.aci.type("The search box", "Alan Turing", overwrite=True, enter=True),
            "browser.click(640, 400); browser.select_all(); browser.press('backspace'); "
            "browser.type_text('Alan Turing'); browser.press('enter')",
        )
        self.assertEqual(
            self.aci.open_url("https://example.com"),
            "browser.open_url('https://example.com')",
        )
        self.assertEqual(
            self.aci.scroll("The page", -3), "browser.scroll(640, 400, -3, shift=False)"
        )
        self.assertEqual(
            self.aci.hotkey(["command", "a"]), "browser.hotkey(['command', 'a'])"
        )

    def test_desktop_actions_are_refused(self):
        with self.assertRaises(NotImplementedError):
            self.aci.open("Calculator")


class TestChromeBridge(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.bridge = ChromeBridge(port=self.port)

    def test_rejects_connections_that_are_not_the_extension(self):
        with self.assertRaises(InvalidStatus):
            connect(f"ws://127.0.0.1:{self.port}", origin="https://evil.example")

    def test_calls_reach_the_extension(self):
        def handler(message):
            if message["method"] == "screenshot":
                return {"data": png_b64(200, 100), "width": 100, "height": 50}, None
            return None, None

        extension = FakeExtension(self.port, handler)
        self.addCleanup(extension.close)
        self.assertTrue(self.bridge.wait_for_extension(5))

        self.bridge.click(10, 20, clicks=2, hold_keys=["shift", "command"])
        call = extension.calls[-1]
        self.assertEqual(call["method"], "click")
        self.assertEqual(
            call["params"],
            {"x": 10, "y": 20, "clicks": 2, "button": "left", "modifiers": 12},
        )

        self.bridge.scroll(5, 5, -3)
        self.assertEqual(extension.calls[-1]["params"]["dy"], 300)

        png, width, height = self.bridge.screenshot()
        self.assertEqual((width, height), (100, 50))
        self.assertEqual(Image.open(io.BytesIO(png)).size, (100, 50))

    def test_extension_errors_are_raised(self):
        extension = FakeExtension(self.port, lambda m: (None, "the tab was closed"))
        self.addCleanup(extension.close)
        self.bridge.wait_for_extension(5)
        with self.assertRaises(RuntimeError) as cm:
            self.bridge.open_url("https://example.com")
        self.assertIn("the tab was closed", str(cm.exception))

    def test_outdated_extension_is_asked_to_reload(self):
        extension = FakeExtension(self.port, lambda m: (None, None), version="0.0.1")
        self.addCleanup(extension.close)
        self.assertFalse(self.bridge.wait_for_extension(1))
        self.assertEqual(extension.calls[0]["method"], "reload")

        # After reloading, the extension reconnects with the current version
        updated = FakeExtension(self.port, lambda m: (None, None))
        self.addCleanup(updated.close)
        self.assertTrue(self.bridge.wait_for_extension(5))

    def test_not_connected_is_reported(self):
        with self.assertRaises(ConnectionError):
            self.bridge.click(1, 1)


class TestRunBrowserAgent(unittest.TestCase):
    def test_runs_actions_until_done(self):
        from gui_agents.s3.cli_app import run_browser_agent

        browser = MagicMock()
        browser.screenshot.return_value = (b"png", 1024, 700)
        agent = MagicMock()
        agent.predict.side_effect = [
            ({}, ["browser.open_url('https://example.com')"]),
            ({}, ["DONE"]),
        ]
        grounding_agent = MagicMock()

        with patch("gui_agents.s3.cli_app.subprocess.run"), patch(
            "gui_agents.s3.cli_app.time.sleep"
        ):
            status = run_browser_agent(agent, grounding_agent, browser, "Open it", 5)

        self.assertEqual(status, "done")
        browser.open_url.assert_called_once_with("https://example.com")
        browser.stop.assert_called_once_with("done")
        self.assertEqual((grounding_agent.width, grounding_agent.height), (1024, 700))


if __name__ == "__main__":
    unittest.main()
