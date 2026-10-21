from typing import Dict, List, Optional

from gui_agents.s3.agents.grounding import OSWorldACI, agent_action
from gui_agents.s3.browser.bridge import EDIT_MODIFIER

# Shown to the worker in place of the operating system name.
BROWSER_PLATFORM = (
    "a Google Chrome tab of your own, inside the 'Agent S' tab group. The screenshot shows "
    "only the web page, without Chrome's address bar or tabs. Use agent.open_url() to go to "
    "a web address and agent.go_back() to go back; shortcuts for Chrome itself (new tab, "
    "address bar, closing tabs) do not work. To save a file such as a PDF to the computer, "
    "use agent.download() with its web address instead of opening it. Copy and paste with "
    f"agent.hotkey(['{EDIT_MODIFIER}', 'c']) and agent.hotkey(['{EDIT_MODIFIER}', 'v']). "
    "Messages about downloads and pages that could not be opened appear in the Current Text "
    "Buffer. Work through the whole task on your own, without asking for confirmation. "
    "You cannot use apps outside this tab"
)


class BrowserACI(OSWorldACI):
    """Agent actions that run in Agent S's own Chrome tab instead of on the desktop.

    Every action returns code that calls `browser`, a ChromeBridge, so clicks and keys
    go to the agent's tab through the Agent S extension and never move your mouse.
    Coordinates are CSS pixels of the tab; width and height are updated each step.
    """

    def __init__(
        self,
        engine_params_for_generation: Dict,
        engine_params_for_grounding: Dict,
        width: int,
        height: int,
    ):
        super().__init__(
            env=None,
            platform="browser",
            engine_params_for_generation=engine_params_for_generation,
            engine_params_for_grounding=engine_params_for_grounding,
            width=width,
            height=height,
        )

    def _coords(self, element_description: str):
        return self.resize_coordinates(
            self.generate_coords(element_description, self.obs)
        )

    @agent_action
    def open_url(self, url: str):
        """Open a web address in your Chrome tab
        Args:
            url:str, the web address to open, e.g. "https://www.google.com"
        """
        return f"browser.open_url({url!r})"

    @agent_action
    def go_back(self):
        """Go back to the previous page in your Chrome tab"""
        return "browser.go_back()"

    @agent_action
    def download(self, url: str):
        """Download a file (PDF, image, document, archive...) from a web address to the computer's Downloads folder
        Args:
            url:str, the web address of the file, e.g. "https://example.com/report.pdf"
        """
        return f"browser.download({url!r})"

    @agent_action
    def click(
        self,
        element_description: str,
        num_clicks: int = 1,
        button_type: str = "left",
        hold_keys: List = [],
    ):
        """Click on the element
        Args:
            element_description:str, a detailed descriptions of which element to click on. This description should be at least a full sentence.
            num_clicks:int, number of times to click the element
            button_type:str, which mouse button to press can be "left", "middle", or "right"
            hold_keys:List, list of keys to hold while clicking
        """
        x, y = self._coords(element_description)
        return f"browser.click({x}, {y}, clicks={num_clicks}, button={button_type!r}, hold_keys={list(hold_keys)!r})"

    @agent_action
    def type(
        self,
        element_description: Optional[str] = None,
        text: str = "",
        overwrite: bool = False,
        enter: bool = False,
    ):
        """Type text/unicode into a specific element
        Args:
            element_description:str, a detailed description of which element to enter text in. This description should be at least a full sentence.
            text:str, the text to type
            overwrite:bool, Assign it to True if the text should overwrite the existing text, otherwise assign it to False. Using this argument clears all text in an element.
            enter:bool, Assign it to True if the enter key should be pressed after typing the text, otherwise assign it to False.
        """
        commands = []
        if element_description is not None:
            x, y = self._coords(element_description)
            commands.append(f"browser.click({x}, {y})")
        if overwrite:
            commands += ["browser.select_all()", "browser.press('backspace')"]
        commands.append(f"browser.type_text({text!r})")
        if enter:
            commands.append("browser.press('enter')")
        return "; ".join(commands)

    @agent_action
    def drag_and_drop(
        self, starting_description: str, ending_description: str, hold_keys: List = []
    ):
        """Drag from the starting description to the ending description
        Args:
            starting_description:str, a very detailed description of where to start the drag action. This description should be at least a full sentence.
            ending_description:str, a very detailed description of where to end the drag action. This description should be at least a full sentence.
            hold_keys:List list of keys to hold while dragging
        """
        x1, y1 = self._coords(starting_description)
        x2, y2 = self._coords(ending_description)
        return f"browser.drag({x1}, {y1}, {x2}, {y2}, hold_keys={list(hold_keys)!r})"

    @agent_action
    def highlight_text_span(
        self, starting_phrase: str, ending_phrase: str, button: str = "left"
    ):
        """Highlight a text span between a provided starting phrase and ending phrase. Use this to highlight words, lines, and paragraphs.
        Args:
            starting_phrase:str, the phrase that denotes the start of the text span you want to highlight. If you only want to highlight one word, just pass in that single word.
            ending_phrase:str, the phrase that denotes the end of the text span you want to highlight. If you only want to highlight one word, just pass in that single word.
            button:str, the button to use to highlight the text span. Defaults to "left". Can be "left", "right", or "middle".
        """
        # OCR runs on the screenshot, which is already in the tab's CSS pixels
        x1, y1 = self.generate_text_coords(starting_phrase, self.obs, alignment="start")
        x2, y2 = self.generate_text_coords(ending_phrase, self.obs, alignment="end")
        return f"browser.drag({x1}, {y1}, {x2}, {y2})"

    @agent_action
    def scroll(self, element_description: str, clicks: int, shift: bool = False):
        """Scroll the element in the specified direction
        Args:
            element_description:str, a very detailed description of which element to enter scroll in. This description should be at least a full sentence.
            clicks:int, the number of clicks to scroll can be positive (up) or negative (down).
            shift:bool, whether to use shift+scroll for horizontal scrolling
        """
        x, y = self._coords(element_description)
        return f"browser.scroll({x}, {y}, {int(clicks)}, shift={bool(shift)})"

    @agent_action
    def hotkey(self, keys: List):
        """Press a hotkey combination inside the web page
        Args:
            keys:List the keys to press in combination in a list format (e.g. ['ctrl', 'c'])
        """
        return f"browser.hotkey({list(keys)!r})"

    @agent_action
    def hold_and_press(self, hold_keys: List, press_keys: List):
        """Hold a list of keys and press a list of keys
        Args:
            hold_keys:List, list of keys to hold
            press_keys:List, list of keys to press in a sequence
        """
        return f"browser.hold_and_press({list(hold_keys)!r}, {list(press_keys)!r})"

    # Desktop-only actions. Overriding them without @agent_action leaves them out of
    # the worker's prompt; calling one anyway makes the response fail validation.
    def switch_applications(self, app_code):
        raise NotImplementedError("Only the Chrome tab is available")

    def open(self, app_or_filename: str):
        raise NotImplementedError("Use open_url in the Chrome tab")

    def set_cell_values(self, cell_values, app_name, sheet_name):
        raise NotImplementedError("Only the Chrome tab is available")

    def call_code_agent(self, task: str = None):
        raise NotImplementedError("Only the Chrome tab is available")
