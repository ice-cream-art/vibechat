import asyncio
import json
import random
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import WebSocket

from .models import EmotionResult, MessageRecord


WAITING_ACTIVE_SECONDS = 6
ASSISTANT_ALIAS = "飞行雪绒"
ASSISTANT_TOKEN = "__vibechat_assistant__"


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
    def __init__(
        self,
        threshold: float = 0.56,
        redis_url: str = "",
        redis_token: str = "",
    ):
        self.threshold = threshold
        self.redis_url = redis_url.rstrip("/")
        self.redis_token = redis_token
        self.redis_enabled = bool(self.redis_url and self.redis_token)
        self.tickets: dict[str, Ticket] = {}
        self.conversations: dict[str, Conversation] = {}
        self.connections: dict[str, dict[str, WebSocket]] = {}
        self.lock = asyncio.Lock()

    @property
    def storage_name(self) -> str:
        return "redis" if self.redis_enabled else "memory"

    @staticmethod
    def _ticket_key(ticket_id: str) -> str:
        return f"vibechat:ticket:{ticket_id}"

    @staticmethod
    def _conversation_key(conversation_id: str) -> str:
        return f"vibechat:conversation:{conversation_id}"

    async def _redis(self, *command: object) -> Any:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.post(
                self.redis_url,
                headers={"Authorization": f"Bearer {self.redis_token}"},
                json=[str(item) for item in command],
            )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(f"Redis error: {payload['error']}")
        return payload.get("result")

    async def _acquire_redis_lock(self) -> str:
        token = secrets.token_urlsafe(16)
        for _ in range(50):
            result = await self._redis("SET", "vibechat:lock", token, "NX", "PX", 5000)
            if result == "OK":
                return token
            await asyncio.sleep(0.05)
        raise RuntimeError("VibeChat storage is busy")

    async def _release_redis_lock(self, token: str) -> None:
        script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        await self._redis("EVAL", script, 1, "vibechat:lock", token)

    @staticmethod
    def _ticket_dump(ticket: Ticket) -> str:
        return json.dumps(
            {
                "id": ticket.id,
                "access_token": ticket.access_token,
                "alias": ticket.alias,
                "emotion": ticket.emotion.model_dump(mode="json"),
                "source_text": ticket.source_text,
                "created_at": ticket.created_at.isoformat(),
                "status": ticket.status,
                "conversation_id": ticket.conversation_id,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _ticket_load(raw: str) -> Ticket:
        data = json.loads(raw)
        return Ticket(
            id=data["id"],
            access_token=data["access_token"],
            alias=data["alias"],
            emotion=EmotionResult.model_validate(data["emotion"]),
            source_text=data.get("source_text", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            status=data.get("status", "waiting"),
            conversation_id=data.get("conversation_id"),
        )

    @staticmethod
    def _conversation_dump(conversation: Conversation) -> str:
        return json.dumps(
            {
                "id": conversation.id,
                "participants": conversation.participants,
                "match_score": conversation.match_score,
                "match_reason": conversation.match_reason,
                "messages": [
                    {
                        **message.model_dump(mode="json"),
                        "sender_token": message.sender_token,
                    }
                    for message in conversation.messages
                ],
                "demo_tokens": list(conversation.demo_tokens),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _conversation_load(raw: str) -> Conversation:
        data = json.loads(raw)
        return Conversation(
            id=data["id"],
            participants=data["participants"],
            match_score=data["match_score"],
            match_reason=data["match_reason"],
            messages=[
                MessageRecord(
                    id=item["id"],
                    sender_alias=item["sender_alias"],
                    sender_token=item.get("sender_token", ""),
                    sender_kind=item.get("sender_kind", "user"),
                    content=item["content"],
                    created_at=item["created_at"],
                )
                for item in data.get("messages", [])
            ],
            demo_tokens=set(data.get("demo_tokens", [])),
        )

    async def _save_ticket(self, ticket: Ticket) -> None:
        await self._redis("SET", self._ticket_key(ticket.id), self._ticket_dump(ticket), "EX", 3600)

    async def _load_ticket(self, ticket_id: str) -> Ticket | None:
        raw = await self._redis("GET", self._ticket_key(ticket_id))
        return self._ticket_load(raw) if raw else None

    async def _save_conversation(self, conversation: Conversation) -> None:
        await self._redis(
            "SET",
            self._conversation_key(conversation.id),
            self._conversation_dump(conversation),
            "EX",
            7200,
        )

    async def _load_conversation(self, conversation_id: str) -> Conversation | None:
        raw = await self._redis("GET", self._conversation_key(conversation_id))
        return self._conversation_load(raw) if raw else None

    async def join(self, emotion: EmotionResult, source_text: str) -> Ticket:
        if self.redis_enabled:
            return await self._join_redis(emotion, source_text)
        async with self.lock:
            ticket = self._new_ticket(emotion, source_text)
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

    def _new_ticket(self, emotion: EmotionResult, source_text: str) -> Ticket:
        return Ticket(
            id=str(uuid.uuid4()),
            access_token=secrets.token_urlsafe(24),
            alias=anonymous_alias(),
            emotion=emotion,
            source_text=source_text,
        )

    async def _join_redis(self, emotion: EmotionResult, source_text: str) -> Ticket:
        lock_token = await self._acquire_redis_lock()
        try:
            ticket = self._new_ticket(emotion, source_text)
            cutoff = datetime.now(timezone.utc).timestamp() - WAITING_ACTIVE_SECONDS
            await self._redis("ZREMRANGEBYSCORE", "vibechat:waiting", "-inf", cutoff)
            waiting_ids = await self._redis(
                "ZRANGEBYSCORE", "vibechat:waiting", cutoff, "+inf", "LIMIT", 0, 100
            )
            ranked: list[tuple[float, Ticket]] = []
            for ticket_id in waiting_ids or []:
                candidate = await self._load_ticket(ticket_id)
                if not candidate or candidate.status != "waiting":
                    await self._redis("ZREM", "vibechat:waiting", ticket_id)
                    continue
                ranked.append((emotion_score(ticket.emotion, candidate.emotion), candidate))
            ranked.sort(key=lambda pair: pair[0], reverse=True)
            if ranked and ranked[0][0] >= self.threshold:
                score, partner = ranked[0]
                conversation = self._create_conversation(ticket, partner, score, cache=False)
                await self._save_ticket(ticket)
                await self._save_ticket(partner)
                await self._save_conversation(conversation)
                await self._redis("ZREM", "vibechat:waiting", partner.id)
            else:
                await self._save_ticket(ticket)
                await self._redis("ZADD", "vibechat:waiting", ticket.created_at.timestamp(), ticket.id)
            return ticket
        finally:
            await self._release_redis_lock(lock_token)

    def _create_conversation(self, a: Ticket, b: Ticket, score: float, cache: bool = True) -> Conversation:
        conversation = Conversation(
            id=str(uuid.uuid4()),
            participants={a.access_token: a.alias, b.access_token: b.alias},
            match_score=score,
            match_reason=match_reason(a.emotion, b.emotion, score),
        )
        if cache:
            self.conversations[conversation.id] = conversation
        for ticket in (a, b):
            ticket.status = "matched"
            ticket.conversation_id = conversation.id
        return conversation

    async def match_demo(self, ticket: Ticket) -> Conversation:
        if self.redis_enabled:
            lock_token = await self._acquire_redis_lock()
            try:
                current = await self._load_ticket(ticket.id)
                if not current or not secrets.compare_digest(current.access_token, ticket.access_token):
                    raise KeyError("invalid ticket")
                if current.status == "matched" and current.conversation_id:
                    existing = await self._load_conversation(current.conversation_id)
                    if existing:
                        return existing
                demo = self._demo_ticket(current.emotion)
                conversation = self._create_conversation(current, demo, 0.94, cache=False)
                conversation.demo_tokens.add(demo.access_token)
                await self._save_ticket(current)
                await self._save_ticket(demo)
                await self._save_conversation(conversation)
                await self._redis("ZREM", "vibechat:waiting", current.id)
                return conversation
            finally:
                await self._release_redis_lock(lock_token)

        async with self.lock:
            if ticket.status == "matched" and ticket.conversation_id:
                return self.conversations[ticket.conversation_id]
            demo = self._demo_ticket(ticket.emotion)
            self.tickets[demo.id] = demo
            conversation = self._create_conversation(ticket, demo, 0.94)
            conversation.demo_tokens.add(demo.access_token)
            return conversation

    @staticmethod
    def _demo_ticket(emotion: EmotionResult) -> Ticket:
        return Ticket(
            id=str(uuid.uuid4()),
            access_token=secrets.token_urlsafe(24),
            alias="飞行雪绒",
            emotion=emotion,
            source_text="演示伙伴",
        )

    async def get_ticket(self, ticket_id: str, access_token: str) -> Ticket | None:
        ticket = await self._load_ticket(ticket_id) if self.redis_enabled else self.tickets.get(ticket_id)
        if not ticket or not secrets.compare_digest(ticket.access_token, access_token):
            return None
        if self.redis_enabled and ticket.status == "waiting":
            await self._redis(
                "ZADD", "vibechat:waiting", datetime.now(timezone.utc).timestamp(), ticket.id
            )
        return ticket

    async def cancel_ticket(self, ticket: Ticket) -> Ticket:
        if ticket.status != "waiting":
            return ticket
        ticket.status = "cancelled"
        if self.redis_enabled:
            await self._save_ticket(ticket)
            await self._redis("ZREM", "vibechat:waiting", ticket.id)
        return ticket

    async def get_conversation(self, conversation_id: str, token: str) -> Conversation | None:
        conversation = (
            await self._load_conversation(conversation_id)
            if self.redis_enabled
            else self.conversations.get(conversation_id)
        )
        return conversation if conversation and token in conversation.participants else None

    async def latest_message_from(self, conversation_id: str, token: str) -> MessageRecord | None:
        conversation = (
            await self._load_conversation(conversation_id)
            if self.redis_enabled
            else self.conversations.get(conversation_id)
        )
        if not conversation:
            return None
        return next(
            (message for message in reversed(conversation.messages) if message.sender_token == token),
            None,
        )

    def partner_alias(self, conversation: Conversation, token: str) -> str:
        return next(alias for key, alias in conversation.participants.items() if key != token)

    async def connect(self, conversation_id: str, token: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.setdefault(conversation_id, {})[token] = websocket

    def disconnect(self, conversation_id: str, token: str) -> None:
        self.connections.get(conversation_id, {}).pop(token, None)

    async def _broadcast_message(self, conversation_id: str, message: MessageRecord) -> None:
        payload = {"type": "message", "message": message.model_dump(mode="json")}
        stale: list[str] = []
        for participant_token, websocket in self.connections.get(conversation_id, {}).items():
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                stale.append(participant_token)
        for participant_token in stale:
            self.disconnect(conversation_id, participant_token)

    async def add_message(self, conversation: Conversation, token: str, content: str) -> MessageRecord:
        lock_token = ""
        if self.redis_enabled:
            lock_token = await self._acquire_redis_lock()
            current = await self._load_conversation(conversation.id)
            if not current or token not in current.participants:
                await self._release_redis_lock(lock_token)
                lock_token = ""
                raise KeyError("invalid conversation")
            conversation = current
        try:
            message = MessageRecord(
                id=str(uuid.uuid4()),
                sender_alias=conversation.participants[token],
                sender_token=token,
                content=content.strip(),
            )
            conversation.messages.append(message)
            if self.redis_enabled:
                await self._save_conversation(conversation)
            await self._broadcast_message(conversation.id, message)
            return message
        finally:
            if lock_token:
                await self._release_redis_lock(lock_token)

    async def add_assistant_message(self, conversation_id: str, content: str) -> MessageRecord:
        lock_token = ""
        conversation: Conversation | None
        if self.redis_enabled:
            lock_token = await self._acquire_redis_lock()
            conversation = await self._load_conversation(conversation_id)
        else:
            conversation = self.conversations.get(conversation_id)
        if not conversation:
            if lock_token:
                await self._release_redis_lock(lock_token)
            raise KeyError("invalid conversation")
        try:
            message = MessageRecord(
                id=str(uuid.uuid4()),
                sender_alias=ASSISTANT_ALIAS,
                sender_token=ASSISTANT_TOKEN,
                sender_kind="assistant",
                content=content.strip(),
            )
            conversation.messages.append(message)
            if self.redis_enabled:
                await self._save_conversation(conversation)
            await self._broadcast_message(conversation.id, message)
            return message
        finally:
            if lock_token:
                await self._release_redis_lock(lock_token)

    def has_demo_partner(self, conversation: Conversation, token: str) -> bool:
        return any(key in conversation.demo_tokens for key in conversation.participants if key != token)
