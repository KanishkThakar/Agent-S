import asyncio
import base64
import io
import json
import logging
import os
import sys
import threading

from PIL import Image
from websockets.asyncio.server import serve

logger = logging.getLogger("desktopenv.agent")

EXTENSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extension")
with open(os.path.join(EXTENSION_DIR, "manifest.json"), encoding="utf-8") as f:
    EXTENSION_VERSION = json.load(f)["version"]
DEFAULT_PORT = 8765
# Call id for the reload request, which no caller waits on
RELOAD_CALL_ID = 0

MODIFIER_BITS = {
    "alt": 1,
    "option": 1,
    "ctrl": 2,
    "control": 2,
    "command": 4,
    "cmd": 4,
    "meta": 4,
    "win": 4,
    "super": 4,
    "shift": 8,
}
# The modifier for select all, copy and paste on this computer
EDIT_MODIFIER = "command" if sys.platform == "darwin" else "ctrl"


class ChromeBridge:
    """Drives Agent S's own Chrome tab through the Agent S extension.

    agent_s runs a WebSocket server on 127.0.0.1; the extension connects to it and
    runs each action in a tab inside the "Agent S" tab group with the Chrome
    DevTools protocol. The real mouse and keyboard are never used, so you can keep
    working in other tabs and apps while the agent runs.

    The methods here are what BrowserACI's action code calls, as `browser.<method>`.
    """

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self._loop = asyncio.new_event_loop()
        self._connection = None
        self._connected = threading.Event()
        self._pending = {}
        self._next_id = 0
        self._started = threading.Event()
        self._start_error = None
        self._reload_requested = False
        # What happened that the agent cannot see in a screenshot, such as downloads
        self.notes = []
        threading.Thread(target=self._run, daemon=True).start()
        self._started.wait()
        if self._start_error:
            raise OSError(
                f"Could not listen on 127.0.0.1:{port} for the Agent S extension "
                f"({self._start_error}). Is another agent_s --browser running? "
                "Pick another port with --browser_port and set the same port in the extension's popup."
            )

    # ---- Connection ----------------------------------------------------------------

    def _run(self):
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            self._start_error = e
            self._started.set()
            return
        self._started.set()
        self._loop.run_forever()

    async def _serve(self):
        self._server = await serve(
            self._handle,
            "127.0.0.1",
            self.port,
            process_request=self._check_origin,
            max_size=None,
        )

    @staticmethod
    def _check_origin(connection, request):
        # Only the extension may connect: web pages can open sockets to localhost too,
        # but browsers do not let them claim an extension origin.
        origin = request.headers.get("Origin", "")
        if not origin.startswith("chrome-extension://"):
            return connection.respond(403, "Only the Agent S extension may connect.\n")

    async def _handle(self, connection):
        if self._connection is not None:
            await self._connection.close()
        self._connection = connection
        try:
            async for raw in connection:
                message = json.loads(raw)
                if message.get("type") == "hello":
                    version = message.get("version")
                    if version != EXTENSION_VERSION and not self._reload_requested:
                        # The loaded extension is older than this repository's copy;
                        # it reconnects with the new files after reloading itself.
                        self._reload_requested = True
                        logger.info("Updating the Agent S extension from %s", version)
                        await connection.send(
                            json.dumps(
                                {
                                    "type": "call",
                                    "id": RELOAD_CALL_ID,
                                    "method": "reload",
                                    "params": {},
                                }
                            )
                        )
                        continue
                    logger.info("Agent S extension %s connected", version)
                    self._connected.set()
                elif message.get("id") == RELOAD_CALL_ID:
                    if message.get("error"):
                        # Versions before 0.1.1 cannot reload themselves
                        print(
                            "The Agent S extension in Chrome is out of date. Click its "
                            "reload button in chrome://extensions to update it."
                        )
                        self._connected.set()
                elif message.get("type") == "result":
                    future = self._pending.pop(message["id"], None)
                    if future is None or future.done():
                        continue
                    if message.get("error"):
                        future.set_exception(RuntimeError(message["error"]))
                    else:
                        future.set_result(message.get("result"))
        finally:
            if self._connection is connection:
                self._connection = None
                self._connected.clear()
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(
                            ConnectionError("The Agent S extension disconnected.")
                        )
                self._pending.clear()

    def wait_for_extension(self, timeout=None):
        """Block until the extension connects; returns False on timeout."""
        return self._connected.wait(timeout)

    @property
    def connected(self):
        return self._connected.is_set()

    async def _call(self, method, params):
        self._next_id += 1
        call_id = self._next_id
        future = self._loop.create_future()
        self._pending[call_id] = future
        await self._connection.send(
            json.dumps(
                {"type": "call", "id": call_id, "method": method, "params": params}
            )
        )
        return await future

    def call(self, method: str, timeout: float = 120, **params):
        if not self._connected.is_set() or self._connection is None:
            raise ConnectionError(
                "The Agent S Chrome extension is not connected. Open Chrome and check "
                "that the extension is turned on."
            )
        return asyncio.run_coroutine_threadsafe(
            self._call(method, params), self._loop
        ).result(timeout)

    # ---- Session ------------------------------------------------------------------

    def start(self, url: str = "about:blank"):
        """Open the agent's tab, in the background, inside the "Agent S" tab group."""
        return self.call("start", url=url)

    def stop(self, status: str = "stopped"):
        """Hand the tab back to you; status ("done", "failed") is shown on the group."""
        if self.connected:
            self.call("stop", status=status)

    def screenshot(self):
        """Return (png_bytes, width, height) of the agent's tab, in CSS pixels."""
        result = self.call("screenshot")
        self.notes.extend(result.get("notes") or [])
        width, height = result["width"], result["height"]
        image = Image.open(io.BytesIO(base64.b64decode(result["data"])))
        if image.size != (width, height):
            image = image.resize((width, height), Image.LANCZOS)
        buffered = io.BytesIO()
        image.convert("RGB").save(buffered, format="PNG")
        return buffered.getvalue(), width, height

    def take_notes(self):
        """Return and clear what happened that a screenshot does not show."""
        notes, self.notes = self.notes, []
        return notes

    # ---- Actions (called by BrowserACI's code) ------------------------------------

    def open_url(self, url: str):
        self.call("navigate", url=url)

    def download(self, url: str):
        result = self.call("download", url=url, timeout=330)
        note = f"Downloaded {url} to {result['filename']} ({result['bytes']} bytes)."
        print(note)
        self.notes.append(note)

    def go_back(self):
        self.call("goBack")

    def click(self, x, y, clicks=1, button="left", hold_keys=()):
        self.call(
            "click",
            x=x,
            y=y,
            clicks=clicks,
            button=button,
            modifiers=_modifiers(hold_keys),
        )

    def drag(self, x1, y1, x2, y2, hold_keys=()):
        self.call("drag", x1=x1, y1=y1, x2=x2, y2=y2, modifiers=_modifiers(hold_keys))

    def scroll(self, x, y, clicks, shift=False):
        # Positive clicks scroll up, like pyautogui; one click is about 100 pixels.
        delta = -int(clicks) * 100
        self.call(
            "scroll", x=x, y=y, dx=delta if shift else 0, dy=0 if shift else delta
        )

    def type_text(self, text: str):
        self.call("typeText", text=text)

    def press(self, key: str):
        self.call("keys", keys=[key])

    def hotkey(self, keys):
        self.call("keys", keys=list(keys))

    def hold_and_press(self, hold_keys, press_keys):
        for key in press_keys:
            self.hotkey(list(hold_keys) + [key])

    def select_all(self):
        self.hotkey([EDIT_MODIFIER, "a"])


def _modifiers(keys):
    bits = 0
    for key in keys:
        bits |= MODIFIER_BITS.get(str(key).lower(), 0)
    return bits
