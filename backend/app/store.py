import asyncio
import random
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import WebSocket

from .models import EmotionResult, MessageRecord


ADJECTIVES = ["安静", "柔软", "清醒", "闪光", "慢热", "勇敢", "自由", "温暖"]
NOUNS = ["海獭", "鲸鱼", "狐狸", "云朵", "星球", "小鹿", "灯塔", "飞鸟"]


def anonymous_alias() -> str:
    return f"{random.choice(ADJECTIVES)}{random.choice(NOUNS)}·{random.randint(10, 99)}"


@dataclass
class Ticket:
    id: str
    access_token: str
    alias: str
    emotion: EmotionResult
    source_text: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "waiting"
    conversation_id: str | None = None


@dataclass
class Conversation:
    id: str
    participants: dict[str, str]
    match_score: float
    match_reason: str
    messages: list[MessageRecord] = field(default_factory=list)
    demo_tokens: set[str] = field(default_factory=set)


def emotion_score(a: EmotionResult, b: EmotionResult) -> float:
    a_labels = {a.primary_emotion, *a.secondary_emotions}
    b_labels = {b.primary_emotion, *b.secondary_emotions}
    overlap = len(a_labels & b_labels)
    label_score = 1.0 if a.primary_emotion == b.primary_emotion else min(0.72, overlap * 0.45)
    intensity_score = 1 - abs(a.intensity - b.intensity)
    valence_score = 1 - abs(a.valence - b.valence) / 2
    arousal_score = 1 - abs(a.arousal - b.arousal)
    score = 0.55 * label_score + 0.25 * intensity_score + 0.12 * valence_score + 0.08 * arousal_score
    return round(max(0, min(1, score)), 2)


def match_reason(a: EmotionResult, b: EmotionResult, score: float) -> str:
    if a.primary_emotion == b.primary_emotion:
        common = f"你们都带着{a.primary_emotion}"
    else:
        common = f"{a.primary_emotion}与{b.primary_emotion}彼此靠近"
    if abs(a.intensity - b.intensity) <= 0.2:
        return f"{common}，情绪强度也很接近"
    return f"{common}，此刻的情绪节奏相似"


class Store:
    def __init__(self, threshold: float = 0.56):
        self.threshold = threshold
        self.tickets: dict[str, Ticket] = {}
        self.conversations: dict[str, Conversation] = {}
        self.connections: dict[str, dict[str, WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def join(self, emotion: EmotionResult, source_text: str) -> Ticket:
        async with self.lock:
            ticket = Ticket(
                id=str(uuid.uuid4()),
                access_token=secrets.token_urlsafe(24),
                alias=anonymous_alias(),
                emotion=emotion,
                source_text=source_text,
            )
            self.tickets[ticket.id] = ticket

            candidates = [item for item in self.tickets.values() if item.status == "waiting" and item.id != ticket.id]
            ranked = sorted(
                ((emotion_score(ticket.emotion, item.emotion), item) for item in candidates),
                key=lambda pair: pair[0],
                reverse=True,
            )
            if ranked and ranked[0][0] >= self.threshold:
                score, partner = ranked[0]
                self._create_conversation(ticket, partner, score)
            return ticket

    def _create_conversation(self, a: Ticket, b: Ticket, score: float) -> Conversation:
        conversation = Conversation(
            id=str(uuid.uuid4()),
            participants={a.access_token: a.alias, b.access_token: b.alias},
            match_score=score,
            match_reason=match_reason(a.emotion, b.emotion, score),
        )
        self.conversations[conversation.id] = conversation
        for ticket in (a, b):
            ticket.status = "matched"
            ticket.conversation_id = conversation.id
        return conversation

    async def match_demo(self, ticket: Ticket) -> Conversation:
        async with self.lock:
            if ticket.status == "matched" and ticket.conversation_id:
                return self.conversations[ticket.conversation_id]
            demo = Ticket(
                id=str(uuid.uuid4()),
                access_token=secrets.token_urlsafe(24),
                alias="同频向导·07",
                emotion=ticket.emotion,
                source_text="演示伙伴",
            )
            self.tickets[demo.id] = demo
            conversation = self._create_conversation(ticket, demo, 0.94)
            conversation.demo_tokens.add(demo.access_token)
            return conversation

    def get_ticket(self, ticket_id: str, access_token: str) -> Ticket | None:
        ticket = self.tickets.get(ticket_id)
        return ticket if ticket and secrets.compare_digest(ticket.access_token, access_token) else None

    def get_conversation(self, conversation_id: str, token: str) -> Conversation | None:
        conversation = self.conversations.get(conversation_id)
        return conversation if conversation and token in conversation.participants else None

    def partner_alias(self, conversation: Conversation, token: str) -> str:
        return next(alias for key, alias in conversation.participants.items() if key != token)

    async def connect(self, conversation_id: str, token: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.setdefault(conversation_id, {})[token] = websocket

    def disconnect(self, conversation_id: str, token: str) -> None:
        self.connections.get(conversation_id, {}).pop(token, None)

    async def add_message(self, conversation: Conversation, token: str, content: str) -> MessageRecord:
        message = MessageRecord(
            id=str(uuid.uuid4()),
            sender_alias=conversation.participants[token],
            sender_token=token,
            content=content.strip(),
        )
        conversation.messages.append(message)
        payload = {"type": "message", "message": message.model_dump(mode="json")}
        stale: list[str] = []
        for participant_token, websocket in self.connections.get(conversation.id, {}).items():
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                stale.append(participant_token)
        for participant_token in stale:
            self.disconnect(conversation.id, participant_token)
        return message

    def has_demo_partner(self, conversation: Conversation, token: str) -> bool:
        return any(key in conversation.demo_tokens for key in conversation.participants if key != token)

