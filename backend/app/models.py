from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


EmotionName = Literal[
    "开心",
    "兴奋",
    "期待",
    "平静",
    "焦虑",
    "难过",
    "孤独",
    "愤怒",
    "疲惫",
    "复杂",
]


class EmotionRequest(BaseModel):
    text: str = Field(min_length=2, max_length=500)

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("请至少写下两个字")
        return value


class EmotionResult(BaseModel):
    primary_emotion: EmotionName
    secondary_emotions: list[EmotionName] = Field(default_factory=list, max_length=3)
    valence: float = Field(ge=-1, le=1)
    arousal: float = Field(ge=0, le=1)
    intensity: float = Field(ge=0, le=1)
    keywords: list[str] = Field(default_factory=list, max_length=6)
    explanation: str = Field(min_length=4, max_length=160)
    safety_level: Literal["normal", "concern"] = "normal"
    provider: Literal["demo", "openai", "anthropic"] = "demo"


class MatchJoinRequest(BaseModel):
    emotion: EmotionResult
    source_text: str = Field(default="", max_length=500)


class MatchJoinResponse(BaseModel):
    ticket_id: str
    access_token: str
    alias: str
    status: Literal["waiting", "matched"]


class MatchStatusResponse(BaseModel):
    ticket_id: str
    status: Literal["waiting", "matched", "cancelled"]
    waited_seconds: int = 0
    conversation_id: str | None = None
    access_token: str | None = None
    alias: str | None = None
    partner_alias: str | None = None
    match_score: float | None = None
    match_reason: str | None = None
    demo_available: bool = False


class MessageRecord(BaseModel):
    id: str
    sender_alias: str
    sender_token: str = Field(exclude=True)
    content: str = Field(min_length=1, max_length=1000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationResponse(BaseModel):
    id: str
    self_alias: str
    partner_alias: str
    match_score: float
    match_reason: str
    messages: list[MessageRecord]

