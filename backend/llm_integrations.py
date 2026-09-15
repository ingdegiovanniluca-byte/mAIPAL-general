"""Drop-in replacement for the `emergentintegrations` interface used across this codebase,
backed directly by the Anthropic and OpenAI SDKs so the app runs independently of the
Emergent platform. Keeps the same class/function names and call signatures so callers
(server.py, telegram_bot.py) don't need to change.

LlmChat supports both providers via with_model("anthropic"|"openai", model_id) - callers
pick the provider per call, so different features can use different providers/models.
"""
import base64
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


def _user_content_anthropic(msg: UserMessage):
    if not msg.file_contents:
        return msg.text
    blocks = []
    for img in msg.file_contents:
        raw = base64.b64decode(img.image_base64)
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": _image_media_type(raw), "data": img.image_base64},
        })
    blocks.append({"type": "text", "text": msg.text})
    return blocks


def _user_content_openai(msg: UserMessage):
    if not msg.file_contents:
        return msg.text
    blocks = []
    for img in msg.file_contents:
        raw = base64.b64decode(img.image_base64)
        media_type = _image_media_type(raw)
        blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{img.image_base64}"},
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
        self.provider = "openai"
        self.model = "gpt-4o"
        self._anthropic_client = None
        self._openai_client = None

    def with_model(self, provider: str, model: str) -> "LlmChat":
        self.provider = provider
        self.model = model
        return self

    def _anthropic(self):
        if self._anthropic_client is None:
            self._anthropic_client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        return self._anthropic_client

    def _openai(self):
        if self._openai_client is None:
            self._openai_client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        return self._openai_client

    async def send_message(self, user_message: UserMessage) -> str:
        if self.provider == "openai":
            self.messages.append({"role": "user", "content": _user_content_openai(user_message)})
            oa_messages = [{"role": "system", "content": self.system_message}] + self.messages
            resp = await self._openai().chat.completions.create(
                model=self.model,
                max_completion_tokens=MAX_TOKENS,
                messages=oa_messages,
            )
            text = resp.choices[0].message.content or ""
        else:
            self.messages.append({"role": "user", "content": _user_content_anthropic(user_message)})
            resp = await self._anthropic().messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.system_message,
                messages=self.messages,
            )
            text = "".join(block.text for block in resp.content if block.type == "text")
        self.messages.append({"role": "assistant", "content": text})
        return text

    async def stream_message(self, user_message: UserMessage):
        full = []
        if self.provider == "openai":
            self.messages.append({"role": "user", "content": _user_content_openai(user_message)})
            oa_messages = [{"role": "system", "content": self.system_message}] + self.messages
            stream = await self._openai().chat.completions.create(
                model=self.model,
                max_completion_tokens=MAX_TOKENS,
                messages=oa_messages,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    full.append(delta)
                    yield TextDelta(content=delta)
        else:
            self.messages.append({"role": "user", "content": _user_content_anthropic(user_message)})
            async with self._anthropic().messages.stream(
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
