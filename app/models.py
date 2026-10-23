"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

AIMode = Literal["default", "vision", "manual"]
ButtonName = Literal["up", "down", "left", "right", "a", "b", "start", "select"]
InputAction = Literal["press", "down", "up"]
ControlAction = Literal["take_control", "handover", "pause", "resume"]


class AISettingsPatch(BaseModel):
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False
    model: str | None = Field(default=None, min_length=1, max_length=200)
    poll_interval: float | None = Field(default=None, ge=0.5, le=120)
    max_context_turns: int | None = Field(default=None, ge=1, le=40)
    image_history: int | None = Field(default=None, ge=0, le=8)
    max_actions: int | None = Field(default=None, ge=1, le=24)
    max_frames: int | None = Field(default=None, ge=1, le=1200)
    temperature: float | None = Field(default=None, ge=0, le=2)
    timeout: float | None = Field(default=None, ge=1, le=600)

    @field_validator("base_url", "model")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    def to_updates(self) -> dict:
        data = self.model_dump(exclude_none=True, exclude={"clear_api_key"})
        if self.clear_api_key:
            data["api_key"] = ""
        return data


class GameSettingsPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    ai_mode: AIMode | None = None
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=500)
    clear_api_key: bool = False
    model: str | None = Field(default=None, max_length=200)
    poll_interval: float | None = Field(default=None, ge=0.5, le=120)
    clear_overrides: bool = False

    @field_validator("name", "base_url", "model", "api_key")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    def overrides(self) -> dict:
        """Per-game endpoint overrides.

        Blank strings are treated as "remove this override" rather than as a
        literal empty endpoint, so they are returned as empty values for the
        repository to delete.
        """
        values = self.model_dump(
            exclude_none=True,
            exclude={"name", "ai_mode", "clear_api_key", "clear_overrides"},
        )
        if self.clear_api_key:
            values["api_key"] = ""
        return values


class InputRequest(BaseModel):
    button: ButtonName
    action: InputAction = "press"
    frames: int = Field(default=4, ge=1, le=120)


class ControlRequest(BaseModel):
    action: ControlAction


class ConnectionTestRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
