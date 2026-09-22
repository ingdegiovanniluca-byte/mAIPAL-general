"""Drop-in replacement for the `emergentintegrations` interface used across this codebase,
backed directly by the Anthropic and OpenAI SDKs so the app runs independently of the
Emergent platform. Keeps the same class/function names and call signatures so callers
(server.py, telegram_bot.py) don't need to change.

LlmChat supports both providers via with_model("anthropic"|"openai", model_id) - callers
pick the provider per call, so different features can use different providers/models.
"""
import base64
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

import anthropic
import openai

import usage_tracking as ut

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
                 system_message: str = "", initial_messages: Optional[list] = None,
                 user_id: Optional[str] = None, feature: Optional[str] = None,
                 channel: Optional[str] = None, trigger: Optional[str] = None,
                 org_id: Optional[str] = None):
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
        # Usage tracking (see usage_tracking.py) - optional: a caller that omits these just
        # doesn't get its calls recorded, it never breaks. Anthropic calls are never tracked
        # (OpenAI is the only provider being metered per the tracking spec).
        self._track_user_id = user_id
        self._track_feature = feature
        self._track_channel = channel
        self._track_trigger = trigger
        self._track_org_id = org_id
        # Snapshot of the last call's usage, kept regardless of whether eager tracking
        # kwargs were given - lets a caller that only learns the real feature AFTER the
        # call returns (e.g. an intent classifier whose own output determines which
        # feature this call belongs to) still record it via record_deferred().
        self._last_usage_snapshot = None

    def _record_usage(self, resp, endpoint: str, started_at: float, status: str = "ok"):
        if self.provider != "openai":
            return
        usage = getattr(resp, "usage", None) if resp is not None else None
        input_tokens = getattr(usage, "prompt_tokens", 0) or 0 if usage else 0
        output_tokens = getattr(usage, "completion_tokens", 0) or 0 if usage else 0
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None) if usage else None
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        model_actual = getattr(resp, "model", None) or self.model if resp is not None else self.model
        request_id = getattr(resp, "id", None) if resp is not None else None
        self._last_usage_snapshot = dict(
            model=model_actual, endpoint=endpoint, input_tokens=input_tokens, cached_input_tokens=cached,
            output_tokens=output_tokens, status=status, request_id=request_id,
            latency_ms=round((time.monotonic() - started_at) * 1000),
        )
        if self._track_user_id and self._track_feature:
            ut.fire_and_forget_llm_call(
                user_id=self._track_user_id, feature=self._track_feature, channel=self._track_channel,
                trigger=self._track_trigger, org_id=self._track_org_id, **self._last_usage_snapshot,
            )

    def record_deferred(self, user_id: Optional[str], feature: Optional[str], channel: Optional[str] = None,
                         trigger: Optional[str] = None, org_id: Optional[str] = None):
        """Records the last call's usage with a feature only known after send_message()
        returned. Use this INSTEAD OF (not in addition to) eager tracking kwargs at
        construction - it is a no-op if there is no snapshot yet (no OpenAI call made)."""
        if not self._last_usage_snapshot:
            return
        ut.fire_and_forget_llm_call(
            user_id=user_id, feature=feature, channel=channel, trigger=trigger, org_id=org_id,
            **self._last_usage_snapshot,
        )

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
            started_at = time.monotonic()
            self.messages.append({"role": "user", "content": _user_content_openai(user_message)})
            oa_messages = [{"role": "system", "content": self.system_message}] + self.messages
            try:
                resp = await self._openai().chat.completions.create(
                    model=self.model,
                    max_completion_tokens=MAX_TOKENS,
                    messages=oa_messages,
                )
            except Exception:
                self._record_usage(None, "chat.completions", started_at, status="errore")
                raise
            self._record_usage(resp, "chat.completions", started_at)
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
            started_at = time.monotonic()
            self.messages.append({"role": "user", "content": _user_content_openai(user_message)})
            oa_messages = [{"role": "system", "content": self.system_message}] + self.messages
            usage_chunk = None
            try:
                stream = await self._openai().chat.completions.create(
                    model=self.model,
                    max_completion_tokens=MAX_TOKENS,
                    messages=oa_messages,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                async for chunk in stream:
                    if getattr(chunk, "usage", None):
                        usage_chunk = chunk
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        full.append(delta)
                        yield TextDelta(content=delta)
            except Exception:
                self._record_usage(None, "chat.completions", started_at, status="errore")
                raise
            self._record_usage(usage_chunk, "chat.completions", started_at)
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
    def __init__(self, api_key: Optional[str] = None, user_id: Optional[str] = None,
                 feature: Optional[str] = None, channel: Optional[str] = None,
                 trigger: Optional[str] = None, org_id: Optional[str] = None):
        self._client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        # Usage tracking (see usage_tracking.py) - optional, same pattern as LlmChat. Whisper
        # bills per minute of audio, not tokens, so it needs `response_format="verbose_json"`
        # to get a `duration` back - with the default "json" format, cost is left null (no
        # duration to bill from), same graceful-degradation the tracking spec asks for.
        self._track_user_id = user_id
        self._track_feature = feature
        self._track_channel = channel
        self._track_trigger = trigger
        self._track_org_id = org_id
        # Same deferred-tracking snapshot as LlmChat - a voice transcription has no
        # feature of its own until the transcript is classified afterwards.
        self._last_stt_snapshot = None

    async def transcribe(self, file, model: str = "whisper-1", response_format: str = "json",
                          language: Optional[str] = None):
        kwargs = {"model": model, "file": file, "response_format": response_format}
        if language:
            kwargs["language"] = language
        started_at = time.monotonic()
        try:
            result = await self._client.audio.transcriptions.create(**kwargs)
        except Exception:
            self._record_stt_usage(None, model, started_at, status="errore")
            raise
        self._record_stt_usage(result, model, started_at)
        return result

    def _record_stt_usage(self, result, model: str, started_at: float, status: str = "ok"):
        duration = getattr(result, "duration", None) if result is not None else None
        self._last_stt_snapshot = dict(
            model=model, duration_seconds=duration, status=status,
            latency_ms=round((time.monotonic() - started_at) * 1000),
        )
        if self._track_user_id and self._track_feature:
            ut.fire_and_forget_stt_call(
                user_id=self._track_user_id, feature=self._track_feature, channel=self._track_channel,
                trigger=self._track_trigger, org_id=self._track_org_id, **self._last_stt_snapshot,
            )

    def record_deferred(self, user_id: Optional[str], feature: Optional[str], channel: Optional[str] = None,
                         trigger: Optional[str] = None, org_id: Optional[str] = None):
        """See LlmChat.record_deferred - same pattern, for a transcription whose feature is
        only known after transcribe() returned (e.g. classified from the transcript)."""
        if not self._last_stt_snapshot:
            return
        ut.fire_and_forget_stt_call(
            user_id=user_id, feature=feature, channel=channel, trigger=trigger, org_id=org_id,
            **self._last_stt_snapshot,
        )
