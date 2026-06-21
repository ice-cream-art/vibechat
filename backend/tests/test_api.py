from fastapi.testclient import TestClient

from app.main import app, settings, store


client = TestClient(app)
settings.llm_provider = "demo"


def reset_store() -> None:
    store.tickets.clear()
    store.conversations.clear()
    store.connections.clear()


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


def test_demo_guide_replies_to_user_question_without_repeating_template() -> None:
    reset_store()
    ticket = join("今天有点累，想安静聊一会儿")
    demo = client.post(
        f"/api/matches/{ticket['ticket_id']}/demo",
        params={"access_token": ticket["access_token"]},
    )
    assert demo.status_code == 200
    conversation_id = demo.json()["conversation_id"]

    first = client.post(
        f"/api/conversations/{conversation_id}/messages",
        params={"access_token": ticket["access_token"]},
        json={"content": "你是谁"},
    )
    assert first.status_code == 200
    second = client.post(
        f"/api/conversations/{conversation_id}/messages",
        params={"access_token": ticket["access_token"]},
        json={"content": "你知道我说什么吗"},
    )
    assert second.status_code == 200

    conversation = client.get(
        f"/api/conversations/{conversation_id}",
        params={"access_token": ticket["access_token"]},
    )
    assert conversation.status_code == 200
    guide_replies = [
        message["content"]
        for message in conversation.json()["messages"]
        if message["sender_alias"].startswith("同频向导")
    ]
    assert len(guide_replies) == 2
    assert "同频向导" in guide_replies[0]
    assert "模板" in guide_replies[1] or "接住" in guide_replies[1]
    assert guide_replies[0] != guide_replies[1]
