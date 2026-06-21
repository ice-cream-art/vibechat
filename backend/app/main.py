import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .llm import LLMProviderError, get_provider
from .models import (
    ConversationResponse,
    EmotionRequest,
    EmotionResult,
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
        await send_demo_reply(conversation, access_token, request.content)
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
            await store.add_message(conversation, token, content)
            if store.has_demo_partner(conversation, token):
                asyncio.create_task(send_demo_reply(conversation, token, content))
    except WebSocketDisconnect:
        store.disconnect(conversation_id, token)


async def send_demo_reply(conversation, user_token: str, content: str) -> None:
    await asyncio.sleep(0.8)
    demo_token = next(key for key in conversation.demo_tokens if key != user_token)
    if any(word in content for word in ["你好", "嗨", "在吗"]):
        reply = "我在。看到我们此刻的情绪很同频，你愿意多说一点发生了什么吗？"
    elif "比赛" in content or "来不及" in content:
        reply = "时间压力确实会让人一下子绷紧。先抓住最重要的一件事，也许会轻一点。"
    elif len(content) <= 6:
        reply = "嗯，我听见了。这里不用急着组织得很完整，想到哪里就说到哪里。"
    else:
        reply = "谢谢你把这些说出来。被这种情绪拉扯着一定不轻松，我会认真听。"
    await store.add_message(conversation, demo_token, reply)
