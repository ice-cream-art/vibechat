import asyncio
import json

from fastapi.testclient import TestClient

from app.main import (
    app,
    assistant_reply_locks,
    demo_reply_locks,
    send_demo_reply,
    send_mention_reply,
    settings,
    store,
)


client = TestClient(app)
settings.llm_provider = "demo"


def reset_store() -> None:
    store.tickets.clear()
    store.conversations.clear()
    store.connections.clear()
    assistant_reply_locks.clear()
    demo_reply_locks.clear()


def analyze(text: str) -> dict:
    response = client.post("/api/emotions/analyze", json={"text": text})
    assert response.status_code == 200
    return response.json()


def join(text: str) -> dict:
    emotion = analyze(text)
    response = client.post("/api/matches/join", json={"emotion": emotion, "source_text": text})
    assert response.status_code == 200
    return response.json()


def status(ticket: dict) -> dict:
    response = client.get(
        f"/api/matches/{ticket['ticket_id']}",
        params={"access_token": ticket["access_token"]},
    )
    assert response.status_code == 200
    return response.json()


def test_full_two_user_match_and_websocket_chat() -> None:
    reset_store()
    first = join("比赛快开始了，我很焦虑，担心来不及")
    second = join("我也很紧张，比赛让我焦虑，怕自己做不完")
    first_status = status(first)
    second_status = status(second)
    assert first_status["status"] == "matched"
    assert second_status["status"] == "matched"
    assert first_status["conversation_id"] == second_status["conversation_id"]
    assert first_status["match_score"] >= 0.8

    conversation_id = first_status["conversation_id"]
    with client.websocket_connect(
        f"/ws/conversations/{conversation_id}?token={first['access_token']}"
    ) as first_socket:
        with client.websocket_connect(
            f"/ws/conversations/{conversation_id}?token={second['access_token']}"
        ) as second_socket:
            assert first_socket.receive_json()["type"] == "ready"
            assert second_socket.receive_json()["type"] == "ready"
            first_socket.send_json({"type": "message", "content": "我有点紧张，你呢？"})
            assert first_socket.receive_json()["message"]["content"] == "我有点紧张，你呢？"
            received = second_socket.receive_json()
            assert received["type"] == "message"
            assert received["message"]["content"] == "我有点紧张，你呢？"


def test_auth_login_me_and_logout_flow() -> None:
    reset_store()
    auth_client = TestClient(app)
    login = auth_client.post(
        "/api/auth/login",
        json={"account": settings.auth_email.upper(), "password": settings.auth_password},
    )
    assert login.status_code == 200
    assert login.json()["user"]["email"] == settings.auth_email
    assert "vibechat_session" in login.cookies

    me = auth_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["display_name"] == settings.auth_display_name

    logout = auth_client.post("/api/auth/logout")
    assert logout.status_code == 200

    after_logout = auth_client.get("/api/auth/me")
    assert after_logout.status_code == 401


def test_auth_rejects_wrong_password() -> None:
    response = client.post(
        "/api/auth/login",
        json={"account": settings.auth_email, "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_auth_supports_multiple_configured_users() -> None:
    original_users = settings.auth_users
    settings.auth_users = json.dumps(
        [
            {
                "email": "first@example.com",
                "password": "first-password",
                "display_name": "第一位用户",
            },
            {
                "email": "second@example.com",
                "password": "second-password",
                "display_name": "第二位用户",
            },
        ],
        ensure_ascii=False,
    )
    try:
        auth_client = TestClient(app)
        login = auth_client.post(
            "/api/auth/login",
            json={"account": "SECOND@example.com", "password": "second-password"},
        )
        assert login.status_code == 200
        assert login.json()["user"] == {
            "email": "second@example.com",
            "display_name": "第二位用户",
        }

        me = auth_client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["email"] == "second@example.com"
    finally:
        settings.auth_users = original_users


def test_rest_message_fallback() -> None:
    reset_store()
    ticket = join("今天有点累，想安静聊一会儿")
    demo = client.post(
        f"/api/matches/{ticket['ticket_id']}/demo",
        params={"access_token": ticket["access_token"]},
    )
    assert demo.status_code == 200
    conversation_id = demo.json()["conversation_id"]

    sent = client.post(
        f"/api/conversations/{conversation_id}/messages",
        params={"access_token": ticket["access_token"]},
        json={"content": "你好，想聊聊今天的心情。"},
    )
    assert sent.status_code == 200
    assert sent.json()["content"] == "你好，想聊聊今天的心情。"

    conversation = client.get(
        f"/api/conversations/{conversation_id}",
        params={"access_token": ticket["access_token"]},
    )
    assert conversation.status_code == 200
    assert conversation.json()["messages"][0]["content"] == "你好，想聊聊今天的心情。"
    assert conversation.json()["messages"][0]["sender_kind"] == "user"


def test_two_user_room_can_mention_assistant_without_adding_participant() -> None:
    reset_store()
    first = join("比赛快开始了，我很焦虑，担心来不及")
    second = join("我也很紧张，比赛让我焦虑，怕自己做不完")
    first_status = status(first)
    assert first_status["status"] == "matched"
    conversation_id = first_status["conversation_id"]

    async def scenario() -> None:
        conversation = await store.get_conversation(conversation_id, first["access_token"])
        assert conversation is not None
        assert len(conversation.participants) == 2
        message = await store.add_message(conversation, first["access_token"], "@飞行雪绒 你怎么看？")
        await send_mention_reply(conversation_id, first["access_token"], message)
        refreshed = await store.get_conversation(conversation_id, first["access_token"])
        assert refreshed is not None
        assert len(refreshed.participants) == 2

    asyncio.run(scenario())

    conversation = client.get(
        f"/api/conversations/{conversation_id}",
        params={"access_token": second["access_token"]},
    )
    assert conversation.status_code == 200
    messages = conversation.json()["messages"]
    assistant_messages = [
        message
        for message in messages
        if message["sender_kind"] == "assistant"
    ]
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["sender_alias"] == "飞行雪绒"
    assert assistant_messages[0]["content"]


def test_demo_guide_replies_to_user_question_without_repeating_template() -> None:
    reset_store()
    ticket = join("今天有点累，想安静聊一会儿")
    demo = client.post(
        f"/api/matches/{ticket['ticket_id']}/demo",
        params={"access_token": ticket["access_token"]},
    )
    assert demo.status_code == 200
    conversation_id = demo.json()["conversation_id"]

    async def scenario() -> None:
        conversation = await store.get_conversation(conversation_id, ticket["access_token"])
        assert conversation is not None
        first = await store.add_message(conversation, ticket["access_token"], "你是谁")
        first_reply = asyncio.create_task(send_demo_reply(conversation, ticket["access_token"], first))
        await asyncio.sleep(0.1)
        second = await store.add_message(conversation, ticket["access_token"], "你知道我说什么吗")
        second_reply = asyncio.create_task(send_demo_reply(conversation, ticket["access_token"], second))
        await asyncio.gather(first_reply, second_reply)

    asyncio.run(scenario())

    conversation = client.get(
        f"/api/conversations/{conversation_id}",
        params={"access_token": ticket["access_token"]},
    )
    assert conversation.status_code == 200
    guide_replies = [
        message["content"]
        for message in conversation.json()["messages"]
        if message["sender_alias"] == "飞行雪绒"
    ]
    assert len(guide_replies) == 2
    assert "飞行雪绒" in guide_replies[0]
    assert "模板" in guide_replies[1] or "接住" in guide_replies[1]
    assert guide_replies[0] != guide_replies[1]


def test_demo_reply_does_not_skip_earlier_user_message() -> None:
    reset_store()
    ticket = join("今天有点累，想安静聊一会儿")
    demo = client.post(
        f"/api/matches/{ticket['ticket_id']}/demo",
        params={"access_token": ticket["access_token"]},
    )
    assert demo.status_code == 200
    conversation_id = demo.json()["conversation_id"]

    async def scenario() -> None:
        conversation = await store.get_conversation(conversation_id, ticket["access_token"])
        assert conversation is not None
        first = await store.add_message(conversation, ticket["access_token"], "第一个问题")
        task = asyncio.create_task(send_demo_reply(conversation, ticket["access_token"], first))
        await asyncio.sleep(0.1)
        await store.add_message(conversation, ticket["access_token"], "第二个问题")
        await task

        refreshed = await store.get_conversation(conversation_id, ticket["access_token"])
        assert refreshed is not None
        guide_replies = [
            message
            for message in refreshed.messages
            if message.sender_alias == "飞行雪绒"
        ]
        assert len(guide_replies) == 1
        assert guide_replies[0].content

    asyncio.run(scenario())
