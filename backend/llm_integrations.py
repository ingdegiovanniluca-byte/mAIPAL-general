"""Drop-in replacement for the `emergentintegrations` interface used across this codebase,
backed directly by the Anthropic and OpenAI SDKs so the app runs independently of the
Emergent platform. Keeps the same class/function names and call signatures so callers
(server.py, telegram_bot.py) don't need to change.
"""
import os
from dataclasses import dataclass, field
from typing import List, Optional

import anthropic
import openai

MAX_TOKENS = 4096


@dataclass
class TextDelta:
    content: str


@dataclass
class StreamDone:
    pass


@dataclass
class ImageContent:
    image_base64: str


@dataclass
class UserMessage:
    text: str
    file_contents: List[ImageContent] = field(default_factory=list)


def _image_media_type(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG"):
        return "image/png"
    if raw.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.startswith(b"GIF8"):
        return "image/gif"
    return "image/jpeg"


def _user_content(msg: UserMessage):
    if not msg.file_contents:
        return msg.text
    blocks = []
    for img in msg.file_contents:
        import base64
        raw = base64.b64decode(img.image_base64)
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": _image_media_type(raw), "data": img.image_base64},
        })
    blocks.append({"type": "text", "text": msg.text})
    return blocks


class LlmChat:
    def __init__(self, api_key: Optional[str] = None, session_id: Optional[str] = None,
                 system_message: str = "", initial_messages: Optional[list] = None):
        self.session_id = session_id
        self.system_message = system_message
        self.messages = []
        for m in (initial_messages or []):
            if m.get("role") == "system":
                self.system_message = m.get("content", self.system_message)
            else:
                self.messages.append({"role": m["role"], "content": m["content"]})
        self.model = "claude-sonnet-5"
        self._client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def with_model(self, provider: str, model: str) -> "LlmChat":
        self.model = model
        return self

    async def send_message(self, user_message: UserMessage) -> str:
        self.messages.append({"role": "user", "content": _user_content(user_message)})
        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self.system_message,
            messages=self.messages,
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        self.messages.append({"role": "assistant", "content": text})
        return text

    async def stream_message(self, user_message: UserMessage):
        self.messages.append({"role": "user", "content": _user_content(user_message)})
        full = []
        async with self._client.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self.system_message,
            messages=self.messages,
        ) as stream:
            async for text in stream.text_stream:
                full.append(text)
                yield TextDelta(content=text)
        self.messages.append({"role": "assistant", "content": "".join(full)})
        yield StreamDone()


class OpenAISpeechToText:
    def __init__(self, api_key: Optional[str] = None):
        self._client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    async def transcribe(self, file, model: str = "whisper-1", response_format: str = "json",
                          language: Optional[str] = None):
        kwargs = {"model": model, "file": file, "response_format": response_format}
        if language:
            kwargs["language"] = language
        return await self._client.audio.transcriptions.create(**kwargs)
