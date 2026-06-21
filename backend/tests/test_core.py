import asyncio

from app.config import Settings
from app.llm import AnthropicProvider, DemoProvider, OpenAIProvider
from app.models import EmotionResult
from app.store import Store, emotion_score


def emotion(name: str, valence: float, arousal: float, intensity: float) -> EmotionResult:
    return EmotionResult(
        primary_emotion=name,
        secondary_emotions=[],
        valence=valence,
        arousal=arousal,
        intensity=intensity,
        keywords=[name],
        explanation="这是用于测试的情绪解释。",
        provider="demo",
    )


def test_similar_emotions_score_higher() -> None:
    anxious_a = emotion("焦虑", -0.5, 0.8, 0.8)
    anxious_b = emotion("焦虑", -0.45, 0.75, 0.72)
    calm = emotion("平静", 0.3, 0.2, 0.3)
    assert emotion_score(anxious_a, anxious_b) > emotion_score(anxious_a, calm)
    assert emotion_score(anxious_a, anxious_b) >= 0.8


def test_demo_provider_detects_anxiety() -> None:
    result = asyncio.run(DemoProvider().analyze("比赛快开始了，我好焦虑，担心来不及"))
    assert result.primary_emotion == "焦虑"
    assert result.intensity > 0.6
    assert result.safety_level == "normal"


def test_store_matches_two_similar_users() -> None:
    async def scenario() -> None:
        store = Store(threshold=0.56)
        first = await store.join(emotion("焦虑", -0.5, 0.8, 0.8), "我很紧张")
        second = await store.join(emotion("焦虑", -0.45, 0.75, 0.7), "我也很焦虑")
        assert first.status == "matched"
        assert second.status == "matched"
        assert first.conversation_id == second.conversation_id

    asyncio.run(scenario())


def test_provider_adapters_share_one_schema() -> None:
    raw = """{
      "primary_emotion": "期待",
      "secondary_emotions": ["焦虑"],
      "valence": 0.3,
      "arousal": 0.7,
      "intensity": 0.8,
      "keywords": ["比赛"],
      "explanation": "你对接下来抱有期待，也感受到一点压力。",
      "safety_level": "normal"
    }"""
    openai = OpenAIProvider(Settings(openai_api_key="test"))
    anthropic = AnthropicProvider(Settings(anthropic_api_key="test"))
    assert openai.parse_result(raw).provider == "openai"
    assert anthropic.parse_result(f"```json\n{raw}\n```").provider == "anthropic"

