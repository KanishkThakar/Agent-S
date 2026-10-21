import base64
import json
import os
import shutil
import subprocess
import tempfile
from io import BytesIO

import backoff
from anthropic import Anthropic
from PIL import Image
from openai import (
    AzureOpenAI,
    APIConnectionError,
    APIError,
    AzureOpenAI,
    OpenAI,
    RateLimitError,
)


class LMMEngine:
    pass


class LMMEngineOpenAI(LMMEngine):
    def __init__(
        self,
        base_url=None,
        api_key=None,
        model=None,
        rate_limit=-1,
        temperature=None,
        organization=None,
        **kwargs,
    ):
        assert model is not None, "model must be provided"
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.organization = organization
        self.request_interval = 0 if rate_limit == -1 else 60.0 / rate_limit
        self.llm_client = None
        self.temperature = temperature  # Can force temperature to be the same (in the case of o3 requiring temperature to be 1)

    @backoff.on_exception(
        backoff.expo, (APIConnectionError, APIError, RateLimitError), max_time=60
    )
    def generate(self, messages, temperature=0.0, max_new_tokens=None, **kwargs):
        api_key = self.api_key or os.getenv("OPENAI_API_KEY")
        if api_key is None:
            raise ValueError(
                "An API Key needs to be provided in either the api_key parameter or as an environment variable named OPENAI_API_KEY"
            )
        organization = self.organization or os.getenv("OPENAI_ORG_ID")
        if not self.llm_client:
            if not self.base_url:
                self.llm_client = OpenAI(api_key=api_key, organization=organization)
            else:
                self.llm_client = OpenAI(
                    base_url=self.base_url, api_key=api_key, organization=organization
                )
        return (
            self.llm_client.chat.completions.create(
                model=self.model,
                messages=messages,
                # max_completion_tokens=max_new_tokens if max_new_tokens else 4096,
                temperature=(
                    temperature if self.temperature is None else self.temperature
                ),
                **kwargs,
            )
            .choices[0]
            .message.content
        )


class LMMEngineAnthropic(LMMEngine):
    def __init__(
        self,
        base_url=None,
        api_key=None,
        model=None,
        thinking=False,
        temperature=None,
        **kwargs,
    ):
        assert model is not None, "model must be provided"
        self.model = model
        self.thinking = thinking
        self.api_key = api_key
        self.llm_client = None
        self.temperature = temperature

    @backoff.on_exception(
        backoff.expo, (APIConnectionError, APIError, RateLimitError), max_time=60
    )
    def generate(self, messages, temperature=0.0, max_new_tokens=None, **kwargs):
        api_key = self.api_key or os.getenv("ANTHROPIC_API_KEY")
        if api_key is None:
            raise ValueError(
                "An API Key needs to be provided in either the api_key parameter or as an environment variable named ANTHROPIC_API_KEY"
            )
        self.llm_client = Anthropic(api_key=api_key)
        # Use the instance temperature if not specified in the call
        temp = self.temperature if temperature is None else temperature
        if self.thinking:
            full_response = self.llm_client.messages.create(
                system=messages[0]["content"][0]["text"],
                model=self.model,
                messages=messages[1:],
                max_tokens=8192,
                thinking={"type": "enabled", "budget_tokens": 4096},
                **kwargs,
            )
            thoughts = full_response.content[0].thinking
            return full_response.content[1].text
        return (
            self.llm_client.messages.create(
                system=messages[0]["content"][0]["text"],
                model=self.model,
                messages=messages[1:],
                max_tokens=max_new_tokens if max_new_tokens else 4096,
                temperature=temp,
                **kwargs,
            )
            .content[0]
            .text
        )

    @backoff.on_exception(
        backoff.expo, (APIConnectionError, APIError, RateLimitError), max_time=60
    )
    # Compatible with Claude-3.7 Sonnet thinking mode
    def generate_with_thinking(
        self, messages, temperature=0.0, max_new_tokens=None, **kwargs
    ):
        """Generate the next message based on previous messages, and keeps the thinking tokens"""
        api_key = self.api_key or os.getenv("ANTHROPIC_API_KEY")
        if api_key is None:
            raise ValueError(
                "An API Key needs to be provided in either the api_key parameter or as an environment variable named ANTHROPIC_API_KEY"
            )
        self.llm_client = Anthropic(api_key=api_key)
        full_response = self.llm_client.messages.create(
            system=messages[0]["content"][0]["text"],
            model=self.model,
            messages=messages[1:],
            max_tokens=8192,
            thinking={"type": "enabled", "budget_tokens": 4096},
            **kwargs,
        )

        thoughts = full_response.content[0].thinking
        answer = full_response.content[1].text
        full_response = (
            f"<thoughts>\n{thoughts}\n</thoughts>\n\n<answer>\n{answer}\n</answer>\n"
        )
        return full_response


class LMMEngineGemini(LMMEngine):
    def __init__(
        self,
        base_url=None,
        api_key=None,
        model=None,
        rate_limit=-1,
        temperature=None,
        **kwargs,
    ):
        assert model is not None, "model must be provided"
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.request_interval = 0 if rate_limit == -1 else 60.0 / rate_limit
        self.llm_client = None
        self.temperature = temperature

    @backoff.on_exception(
        backoff.expo, (APIConnectionError, APIError, RateLimitError), max_time=60
    )
    def generate(self, messages, temperature=0.0, max_new_tokens=None, **kwargs):
        api_key = self.api_key or os.getenv("GEMINI_API_KEY")
        if api_key is None:
            raise ValueError(
                "An API Key needs to be provided in either the api_key parameter or as an environment variable named GEMINI_API_KEY"
            )
        base_url = self.base_url or os.getenv("GEMINI_ENDPOINT_URL")
        if base_url is None:
            raise ValueError(
                "An endpoint URL needs to be provided in either the endpoint_url parameter or as an environment variable named GEMINI_ENDPOINT_URL"
            )
        if not self.llm_client:
            self.llm_client = OpenAI(base_url=base_url, api_key=api_key)
        # Use the temperature passed to generate, otherwise use the instance's temperature, otherwise default to 0.0
        temp = self.temperature if temperature is None else temperature
        return (
            self.llm_client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_new_tokens if max_new_tokens else 4096,
                temperature=temp,
                **kwargs,
            )
            .choices[0]
            .message.content
        )


class LMMEngineOpenRouter(LMMEngine):
    def __init__(
        self,
        base_url=None,
        api_key=None,
        model=None,
        rate_limit=-1,
        temperature=None,
        **kwargs,
    ):
        assert model is not None, "model must be provided"
        self.model = model
        self.base_url = base_url
        self.api_key = api_key
        self.request_interval = 0 if rate_limit == -1 else 60.0 / rate_limit
        self.llm_client = None
        self.temperature = temperature

    @backoff.on_exception(
        backoff.expo, (APIConnectionError, APIError, RateLimitError), max_time=60
    )
    def generate(self, messages, temperature=0.0, max_new_tokens=None, **kwargs):
        api_key = self.api_key or os.getenv("OPENROUTER_API_KEY")
        if api_key is None:
            raise ValueError(
                "An API Key needs to be provided in either the api_key parameter or as an environment variable named OPENROUTER_API_KEY"
            )
        base_url = self.base_url or os.getenv("OPEN_ROUTER_ENDPOINT_URL")
        if base_url is None:
            raise ValueError(
                "An endpoint URL needs to be provided in either the endpoint_url parameter or as an environment variable named OPEN_ROUTER_ENDPOINT_URL"
            )
        if not self.llm_client:
            self.llm_client = OpenAI(base_url=base_url, api_key=api_key)
        # Use self.temperature if set, otherwise use the temperature argument
        temp = self.temperature if self.temperature is not None else temperature
        return (
            self.llm_client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_new_tokens if max_new_tokens else 4096,
                temperature=temp,
                **kwargs,
            )
            .choices[0]
            .message.content
        )


class LMMEngineAzureOpenAI(LMMEngine):
    def __init__(
        self,
        base_url=None,
        api_key=None,
        azure_endpoint=None,
        model=None,
        api_version=None,
        rate_limit=-1,
        temperature=None,
        **kwargs,
    ):
        assert model is not None, "model must be provided"
        self.model = model
        self.api_version = api_version
        self.api_key = api_key
        self.azure_endpoint = azure_endpoint
        self.request_interval = 0 if rate_limit == -1 else 60.0 / rate_limit
        self.llm_client = None
        self.cost = 0.0
        self.temperature = temperature

    @backoff.on_exception(
        backoff.expo, (APIConnectionError, APIError, RateLimitError), max_time=60
    )
    def generate(self, messages, temperature=0.0, max_new_tokens=None, **kwargs):
        api_key = self.api_key or os.getenv("AZURE_OPENAI_API_KEY")
        if api_key is None:
            raise ValueError(
                "An API Key needs to be provided in either the api_key parameter or as an environment variable named AZURE_OPENAI_API_KEY"
            )
        api_version = self.api_version or os.getenv("OPENAI_API_VERSION")
        if api_version is None:
            raise ValueError(
                "api_version must be provided either as a parameter or as an environment variable named OPENAI_API_VERSION"
            )
        azure_endpoint = self.azure_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
        if azure_endpoint is None:
            raise ValueError(
                "An Azure API endpoint needs to be provided in either the azure_endpoint parameter or as an environment variable named AZURE_OPENAI_ENDPOINT"
            )
        if not self.llm_client:
            self.llm_client = AzureOpenAI(
                azure_endpoint=azure_endpoint,
                api_key=api_key,
                api_version=api_version,
            )
        # Use self.temperature if set, otherwise use the temperature argument
        temp = self.temperature if self.temperature is not None else temperature
        completion = self.llm_client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_new_tokens if max_new_tokens else 4096,
            temperature=temp,
            **kwargs,
        )
        total_tokens = completion.usage.total_tokens
        self.cost += 0.02 * ((total_tokens + 500) / 1000)
        return completion.choices[0].message.content


class LMMEnginevLLM(LMMEngine):
    def __init__(
        self,
        base_url=None,
        api_key=None,
        model=None,
        rate_limit=-1,
        temperature=None,
        **kwargs,
    ):
        assert model is not None, "model must be provided"
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.request_interval = 0 if rate_limit == -1 else 60.0 / rate_limit
        self.llm_client = None
        self.temperature = temperature

    @backoff.on_exception(
        backoff.expo, (APIConnectionError, APIError, RateLimitError), max_time=60
    )
    def generate(
        self,
        messages,
        temperature=0.0,
        top_p=0.8,
        repetition_penalty=1.05,
        max_new_tokens=512,
        **kwargs,
    ):
        api_key = self.api_key or os.getenv("vLLM_API_KEY")
        if api_key is None:
            raise ValueError(
                "A vLLM API key needs to be provided in either the api_key parameter or as an environment variable named vLLM_API_KEY"
            )
        base_url = self.base_url or os.getenv("vLLM_ENDPOINT_URL")
        if base_url is None:
            raise ValueError(
                "An endpoint URL needs to be provided in either the endpoint_url parameter or as an environment variable named vLLM_ENDPOINT_URL"
            )
        if not self.llm_client:
            self.llm_client = OpenAI(base_url=base_url, api_key=api_key)
        # Use self.temperature if set, otherwise use the temperature argument
        temp = self.temperature if self.temperature is not None else temperature
        completion = self.llm_client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_new_tokens if max_new_tokens else 4096,
            temperature=temp,
            top_p=top_p,
            extra_body={"repetition_penalty": repetition_penalty},
        )
        return completion.choices[0].message.content


class LMMEngineHuggingFace(LMMEngine):
    def __init__(self, base_url=None, api_key=None, rate_limit=-1, **kwargs):
        self.base_url = base_url
        self.api_key = api_key
        self.request_interval = 0 if rate_limit == -1 else 60.0 / rate_limit
        self.llm_client = None

    @backoff.on_exception(
        backoff.expo, (APIConnectionError, APIError, RateLimitError), max_time=60
    )
    def generate(self, messages, temperature=0.0, max_new_tokens=None, **kwargs):
        api_key = self.api_key or os.getenv("HF_TOKEN")
        if api_key is None:
            raise ValueError(
                "A HuggingFace token needs to be provided in either the api_key parameter or as an environment variable named HF_TOKEN"
            )
        base_url = self.base_url or os.getenv("HF_ENDPOINT_URL")
        if base_url is None:
            raise ValueError(
                "HuggingFace endpoint must be provided as base_url parameter or as an environment variable named HF_ENDPOINT_URL."
            )
        if not self.llm_client:
            self.llm_client = OpenAI(base_url=base_url, api_key=api_key)
        return (
            self.llm_client.chat.completions.create(
                model="tgi",
                messages=messages,
                max_tokens=max_new_tokens if max_new_tokens else 4096,
                temperature=temperature,
                **kwargs,
            )
            .choices[0]
            .message.content
        )


class LMMEngineParasail(LMMEngine):
    def __init__(
        self, base_url=None, api_key=None, model=None, rate_limit=-1, **kwargs
    ):
        assert model is not None, "Parasail model id must be provided"
        self.base_url = base_url
        self.model = model
        self.api_key = api_key
        self.request_interval = 0 if rate_limit == -1 else 60.0 / rate_limit
        self.llm_client = None

    @backoff.on_exception(
        backoff.expo, (APIConnectionError, APIError, RateLimitError), max_time=60
    )
    def generate(self, messages, temperature=0.0, max_new_tokens=None, **kwargs):
        api_key = self.api_key or os.getenv("PARASAIL_API_KEY")
        if api_key is None:
            raise ValueError(
                "A Parasail API key needs to be provided in either the api_key parameter or as an environment variable named PARASAIL_API_KEY"
            )
        base_url = self.base_url
        if base_url is None:
            raise ValueError(
                "Parasail endpoint must be provided as base_url parameter or as an environment variable named PARASAIL_ENDPOINT_URL"
            )
        if not self.llm_client:
            self.llm_client = OpenAI(
                base_url=base_url if base_url else "https://api.parasail.io/v1",
                api_key=api_key,
            )
        return (
            self.llm_client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_new_tokens if max_new_tokens else 4096,
                temperature=temperature,
                **kwargs,
            )
            .choices[0]
            .message.content
        )


CLAUDE_CODE_GROUNDING_PROMPT = """You are a GUI grounding model. You receive a screenshot of a computer screen that is exactly {width}x{height} pixels, and a description of one element on it.
Find that element and reply with the pixel coordinate of its center as two integers in the form `x, y`. x counts from the left edge (0 to {max_x}) and y counts from the top edge (0 to {max_y}).
Reply with the coordinate only: no words, no units and no other numbers."""


class LMMEngineClaudeCode(LMMEngine):
    """Runs Claude through the local Claude Code CLI (`claude -p`).

    Requests use the Claude subscription (Pro or Max) that the CLI is logged in
    with, so no ANTHROPIC_API_KEY is needed. Log in once by running `claude`.

    When grounding_width and grounding_height are given, the engine acts as the
    grounding model: screenshots are resized to exactly that size and Claude is
    asked for the pixel coordinate of the described element.
    """

    # Claude downsamples larger images anyway, so send them at this size at most.
    MAX_IMAGE_EDGE = 1568

    def __init__(
        self,
        model=None,
        cli_path=None,
        timeout=300,
        effort=None,
        grounding_width=None,
        grounding_height=None,
        temperature=None,
        **kwargs,
    ):
        self.model = model or "sonnet"
        self.cli_path = cli_path or os.getenv("CLAUDE_CODE_PATH")
        self.timeout = timeout
        self.effort = effort
        self.grounding_width = grounding_width
        self.grounding_height = grounding_height
        # The CLI has no temperature setting; kept so engine_params stay interchangeable.
        self.temperature = temperature
        # Run the CLI in an empty folder so no project files or CLAUDE.md are picked up.
        self.workdir = os.path.join(tempfile.gettempdir(), "agent_s_claude")
        os.makedirs(self.workdir, exist_ok=True)

    def generate(self, messages, temperature=0.0, max_new_tokens=None, **kwargs):
        cli_path = resolve_claude_cli(self.cli_path)

        system_prompt = _message_text(messages[0]) if messages else ""
        if self.grounding_width and self.grounding_height:
            system_prompt = CLAUDE_CODE_GROUNDING_PROMPT.format(
                width=self.grounding_width,
                height=self.grounding_height,
                max_x=self.grounding_width - 1,
                max_y=self.grounding_height - 1,
            )
        user_message = {
            "type": "user",
            "message": {"role": "user", "content": self._build_content(messages[1:])},
        }

        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", dir=self.workdir, delete=False, encoding="utf-8"
        ) as f:
            f.write(system_prompt or "You are a helpful assistant.")
            system_prompt_path = f.name

        cmd = [
            cli_path,
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            self.model,
            "--system-prompt-file",
            system_prompt_path,
            # Plain model calls: no tools, MCP servers, user settings, hooks or saved sessions.
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "",
            "--no-session-persistence",
        ]
        if self.effort:
            cmd += ["--effort", self.effort]

        try:
            proc = subprocess.run(
                cmd,
                input=json.dumps(user_message) + "\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.timeout,
                cwd=self.workdir,
                env=claude_cli_env(),
            )
        finally:
            os.remove(system_prompt_path)

        result = None
        for line in proc.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "result":
                result = event

        if result is None:
            raise RuntimeError(
                f"Claude Code CLI exited with code {proc.returncode} without a result. "
                f"stderr: {proc.stderr.strip()[-1000:]}"
            )
        if result.get("is_error"):
            raise RuntimeError(
                f"Claude Code CLI error: {result.get('result') or result.get('subtype')}. "
                "If you are not logged in, run `claude` once and log in with your Claude subscription."
            )
        return result.get("result", "")

    def generate_with_thinking(
        self, messages, temperature=0.0, max_new_tokens=None, **kwargs
    ):
        """The CLI does not return thinking text, so only the answer is filled in."""
        answer = self.generate(messages, temperature, max_new_tokens, **kwargs)
        return f"<thoughts>\n</thoughts>\n\n<answer>\n{answer}\n</answer>\n"

    def _build_content(self, messages):
        """Flatten the conversation into one user turn, since the CLI takes a single prompt."""
        content = []
        if any(m["role"] == "assistant" for m in messages):
            content.append(
                {
                    "type": "text",
                    "text": "This is the conversation so far. Your own earlier replies are inside <your_previous_reply> tags. Reply to the latest user turn.",
                }
            )
        for message in messages:
            if message["role"] == "assistant":
                content.append(
                    {
                        "type": "text",
                        "text": f"<your_previous_reply>\n{_message_text(message)}\n</your_previous_reply>",
                    }
                )
                continue
            blocks = message["content"]
            if isinstance(blocks, str):
                blocks = [{"type": "text", "text": blocks}]
            for block in blocks:
                if block.get("type") == "text":
                    if block["text"].strip():
                        content.append({"type": "text", "text": block["text"]})
                elif block.get("type") in ("image", "image_url"):
                    content.append(self._prepare_image(block))
        if not content:
            content.append({"type": "text", "text": "Continue."})
        return content

    def _prepare_image(self, block):
        """Decode an Anthropic- or OpenAI-style image block and resize it for Claude."""
        if block["type"] == "image":
            data = block["source"]["data"]
        else:
            data = block["image_url"]["url"].split(",", 1)[-1]
        image = Image.open(BytesIO(base64.b64decode(data)))

        if self.grounding_width and self.grounding_height:
            size = (self.grounding_width, self.grounding_height)
        else:
            scale = min(1.0, self.MAX_IMAGE_EDGE / max(image.size))
            size = (round(image.width * scale), round(image.height * scale))
        if image.size != size:
            image = image.resize(size, Image.LANCZOS)

        buffered = BytesIO()
        image.convert("RGB").save(buffered, format="PNG")
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(buffered.getvalue()).decode("utf-8"),
            },
        }


def _message_text(message):
    content = message["content"]
    if isinstance(content, str):
        return content
    return "\n".join(b["text"] for b in content if b.get("type") == "text")


def resolve_claude_cli(cli_path=None):
    """Return the path of the `claude` executable, or raise with install instructions."""
    path = cli_path or os.getenv("CLAUDE_CODE_PATH") or shutil.which("claude")
    if not path:
        raise ValueError(
            "The Claude Code CLI ('claude') was not found on PATH. Install it from "
            "https://claude.com/claude-code, run `claude` once and log in with your "
            "Claude subscription, or set CLAUDE_CODE_PATH to the executable."
        )
    return path


def claude_cli_env():
    """Environment for the CLI that keeps it on the logged-in Claude subscription."""
    env = os.environ.copy()
    # An API key in the environment would make the CLI bill it instead of the
    # subscription, and CLAUDECODE makes it refuse to start inside a Claude Code session.
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDECODE"):
        env.pop(name, None)
    return env


def check_claude_code_login(cli_path=None):
    """Return (ok, message) describing whether the CLI is logged in to a Claude subscription."""
    try:
        path = resolve_claude_cli(cli_path)
    except ValueError as e:
        return False, str(e)
    try:
        proc = subprocess.run(
            [path, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=30,
            env=claude_cli_env(),
        )
        status = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        # Older CLI versions have no `auth status`; the first model call will report problems.
        return True, "Could not read the Claude Code login status; continuing."
    if not status.get("loggedIn"):
        return False, (
            "The Claude Code CLI is not logged in. Run `claude` and log in with your "
            "Claude subscription, then start Agent-S again."
        )
    plan = status.get("subscriptionType") or status.get("authMethod") or "unknown plan"
    return (
        True,
        f"Using Claude Code logged in as {status.get('email', 'unknown')} ({plan}).",
    )
