import asyncio
import re
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .auth import authenticate, clear_session_cookie, read_session, set_session_cookie
from .config import get_settings
from .llm import LLMProviderError, generate_companion_reply, get_provider
from .models import (
    AuthResponse,
    ConversationResponse,
    EmotionRequest,
    EmotionResult,
    LoginRequest,
    MatchJoinRequest,
    MatchJoinResponse,
    MatchStatusResponse,
    MessageCreateRequest,
    MessageRecord,
)
from .store import Store


settings = get_settings()
store = Store(
    threshold=settings.match_threshold,
    redis_url=settings.redis_url,
    redis_token=settings.redis_token,
)
demo_reply_locks: dict[str, asyncio.Lock] = {}
assistant_reply_locks: dict[str, asyncio.Lock] = {}
ASSISTANT_MENTION_PATTERN = re.compile(r"[@＠]\s*(飞行雪绒|AI|同频向导|助手)", re.IGNORECASE)


def mentions_assistant(content: str) -> bool:
    return bool(ASSISTANT_MENTION_PATTERN.search(content))


def strip_assistant_mention(content: str) -> str:
    cleaned = ASSISTANT_MENTION_PATTERN.sub("", content).strip()
    return cleaned.strip(" ，,。.!！?？:：") or "我想听听你的看法。"

app = FastAPI(
    title="VibeChat API",
    version="1.0.0",
    description="AI 驱动的情绪匿名社交 API",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "provider": settings.llm_provider,
        "storage": store.storage_name,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/auth/login", response_model=AuthResponse)
async def login(request: Request, response: Response, payload: LoginRequest) -> AuthResponse:
    user = authenticate(settings, payload.account, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="账号或密码不正确")
    set_session_cookie(settings, request, response, user)
    return AuthResponse(user=user)


@app.get("/api/auth/me", response_model=AuthResponse)
async def me(request: Request) -> AuthResponse:
    return AuthResponse(user=read_session(settings, request))


@app.post("/api/auth/logout", response_model=dict[str, bool])
async def logout(request: Request, response: Response) -> dict[str, bool]:
    clear_session_cookie(request, response)
    return {"ok": True}


@app.post("/api/emotions/analyze", response_model=EmotionResult)
async def analyze_emotion(request: EmotionRequest) -> EmotionResult:
    try:
        provider = get_provider(settings)
        return await provider.analyze(request.text)
    except LLMProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/matches/join", response_model=MatchJoinResponse)
async def join_match(request: MatchJoinRequest) -> MatchJoinResponse:
    ticket = await store.join(request.emotion, request.source_text)
    return MatchJoinResponse(
        ticket_id=ticket.id,
        access_token=ticket.access_token,
        alias=ticket.alias,
        status=ticket.status,
    )


async def status_payload(ticket) -> MatchStatusResponse:
    waited = int((datetime.now(timezone.utc) - ticket.created_at).total_seconds())
    if ticket.status != "matched" or not ticket.conversation_id:
        return MatchStatusResponse(
            ticket_id=ticket.id,
            status=ticket.status,
            waited_seconds=waited,
            alias=ticket.alias,
            demo_available=waited >= 8,
        )
    conversation = await store.get_conversation(ticket.conversation_id, ticket.access_token)
    if not conversation:
        return MatchStatusResponse(
            ticket_id=ticket.id,
            status="waiting",
            waited_seconds=waited,
            alias=ticket.alias,
            demo_available=waited >= 8,
        )
    return MatchStatusResponse(
        ticket_id=ticket.id,
        status="matched",
        waited_seconds=waited,
        conversation_id=conversation.id,
        access_token=ticket.access_token,
        alias=ticket.alias,
        partner_alias=store.partner_alias(conversation, ticket.access_token),
        match_score=conversation.match_score,
        match_reason=conversation.match_reason,
        partner_is_demo=store.has_demo_partner(conversation, ticket.access_token),
    )


@app.get("/api/matches/{ticket_id}", response_model=MatchStatusResponse)
async def match_status(ticket_id: str, access_token: str = Query(min_length=12)) -> MatchStatusResponse:
    ticket = await store.get_ticket(ticket_id, access_token)
    if not ticket:
        raise HTTPException(status_code=404, detail="匹配凭证无效")
    return await status_payload(ticket)


@app.post("/api/matches/{ticket_id}/demo", response_model=MatchStatusResponse)
async def match_demo(ticket_id: str, access_token: str = Query(min_length=12)) -> MatchStatusResponse:
    ticket = await store.get_ticket(ticket_id, access_token)
    if not ticket:
        raise HTTPException(status_code=404, detail="匹配凭证无效")
    await store.match_demo(ticket)
    ticket = await store.get_ticket(ticket_id, access_token)
    if not ticket:
        raise HTTPException(status_code=404, detail="匹配凭证无效")
    return await status_payload(ticket)


@app.post("/api/matches/{ticket_id}/cancel", response_model=MatchStatusResponse)
async def cancel_match(ticket_id: str, access_token: str = Query(min_length=12)) -> MatchStatusResponse:
    ticket = await store.get_ticket(ticket_id, access_token)
    if not ticket:
        raise HTTPException(status_code=404, detail="匹配凭证无效")
    ticket = await store.cancel_ticket(ticket)
    return await status_payload(ticket)


@app.get("/api/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: str, access_token: str = Query(min_length=12)) -> ConversationResponse:
    conversation = await store.get_conversation(conversation_id, access_token)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在或凭证无效")
    return ConversationResponse(
        id=conversation.id,
        self_alias=conversation.participants[access_token],
        partner_alias=store.partner_alias(conversation, access_token),
        match_score=conversation.match_score,
        match_reason=conversation.match_reason,
        messages=conversation.messages,
        partner_is_demo=store.has_demo_partner(conversation, access_token),
    )


@app.post("/api/conversations/{conversation_id}/messages", response_model=MessageRecord)
async def post_message(
    conversation_id: str,
    request: MessageCreateRequest,
    access_token: str = Query(min_length=12),
) -> MessageRecord:
    conversation = await store.get_conversation(conversation_id, access_token)
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在或凭证无效")
    message = await store.add_message(conversation, access_token, request.content)
    if store.has_demo_partner(conversation, access_token):
        asyncio.create_task(send_demo_reply(conversation, access_token, message))
    elif mentions_assistant(request.content):
        asyncio.create_task(send_mention_reply(conversation.id, access_token, message))
    return message


@app.websocket("/ws/conversations/{conversation_id}")
async def conversation_socket(websocket: WebSocket, conversation_id: str, token: str = Query(min_length=12)) -> None:
    conversation = await store.get_conversation(conversation_id, token)
    if not conversation:
        await websocket.close(code=4404, reason="会话不存在或凭证无效")
        return
    await store.connect(conversation_id, token, websocket)
    await websocket.send_json({"type": "ready", "conversation_id": conversation_id})
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") != "message":
                continue
            content = str(data.get("content", "")).strip()
            if not content or len(content) > 1000:
                await websocket.send_json({"type": "error", "message": "消息需为 1-1000 个字符"})
                continue
            message = await store.add_message(conversation, token, content)
            if store.has_demo_partner(conversation, token):
                asyncio.create_task(send_demo_reply(conversation, token, message))
            elif mentions_assistant(content):
                asyncio.create_task(send_mention_reply(conversation.id, token, message))
    except WebSocketDisconnect:
        store.disconnect(conversation_id, token)


async def send_demo_reply(conversation, user_token: str, trigger_message: MessageRecord) -> None:
    lock = demo_reply_locks.setdefault(conversation.id, asyncio.Lock())
    async with lock:
        await asyncio.sleep(0.35)
        current_conversation = await store.get_conversation(conversation.id, user_token)
        if not current_conversation:
            return
        try:
            trigger_index = next(
                index for index, message in enumerate(current_conversation.messages)
                if message.id == trigger_message.id
            )
        except StopIteration:
            return
        demo_token = next(key for key in current_conversation.demo_tokens if key != user_token)
        recent_messages = [
            {
                "role": "assistant" if message.sender_token in current_conversation.demo_tokens else "user",
                "content": message.content,
            }
            for message in current_conversation.messages[max(0, trigger_index - 8):trigger_index]
        ]
        reply = await generate_companion_reply(settings, trigger_message.content, recent_messages)
        latest_conversation = await store.get_conversation(conversation.id, user_token)
        if not latest_conversation:
            return
        await store.add_message(latest_conversation, demo_token, reply)


async def send_mention_reply(conversation_id: str, user_token: str, trigger_message: MessageRecord) -> None:
    lock = assistant_reply_locks.setdefault(conversation_id, asyncio.Lock())
    async with lock:
        await asyncio.sleep(0.35)
        current_conversation = await store.get_conversation(conversation_id, user_token)
        if not current_conversation or store.has_demo_partner(current_conversation, user_token):
            return
        try:
            trigger_index = next(
                index for index, message in enumerate(current_conversation.messages)
                if message.id == trigger_message.id
            )
        except StopIteration:
            return
        recent_messages = [
            {
                "role": "assistant" if message.sender_kind == "assistant" else "user",
                "content": (
                    message.content
                    if message.sender_kind == "assistant"
                    else f"{message.sender_alias}: {message.content}"
                ),
            }
            for message in current_conversation.messages[max(0, trigger_index - 10):trigger_index]
        ]
        reply = await generate_companion_reply(
            settings,
            strip_assistant_mention(trigger_message.content),
            recent_messages,
        )
        await store.add_assistant_message(conversation_id, reply)
