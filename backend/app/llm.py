import json
import re
from abc import ABC, abstractmethod

import httpx

from .config import Settings
from .models import EmotionResult


SYSTEM_PROMPT = """你是 VibeChat 的情绪分析引擎。分析用户此刻的情绪，严格只返回 JSON，不要 Markdown。
字段必须是：
primary_emotion: 开心/兴奋/期待/平静/焦虑/难过/孤独/愤怒/疲惫/复杂之一；
secondary_emotions: 最多3个上述情绪；
valence: -1到1；arousal: 0到1；intensity: 0到1；
keywords: 最多6个短词；explanation: 15到60字的温和解释；
safety_level: normal 或 concern。
若文本透露自伤或轻生风险，safety_level 必须为 concern。不要诊断疾病。"""

ALLOWED_EMOTIONS = {"开心", "兴奋", "期待", "平静", "焦虑", "难过", "孤独", "愤怒", "疲惫", "复杂"}
EMOTION_ALIASES = {
    "快乐": "开心",
    "高兴": "开心",
    "激动": "兴奋",
    "希望": "期待",
    "安心": "平静",
    "放松": "平静",
    "紧张": "焦虑",
    "担忧": "焦虑",
    "不安": "焦虑",
    "害怕": "焦虑",
    "悲伤": "难过",
    "失落": "难过",
    "孤单": "孤独",
    "生气": "愤怒",
    "累": "疲惫",
    "困惑": "复杂",
    "纠结": "复杂",
    "矛盾": "复杂",
}


class LLMProviderError(RuntimeError):
    pass


class EmotionProvider(ABC):
    name: str

    @abstractmethod
    async def analyze(self, text: str) -> EmotionResult:
        raise NotImplementedError

    def parse_result(self, raw: str) -> EmotionResult:
        cleaned = raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            payload = json.loads(cleaned)
            primary = str(payload.get("primary_emotion", "复杂")).strip()
            payload["primary_emotion"] = EMOTION_ALIASES.get(
                primary, primary if primary in ALLOWED_EMOTIONS else "复杂"
            )
            secondary = payload.get("secondary_emotions", [])
            payload["secondary_emotions"] = list(
                dict.fromkeys(
                    normalized
                    for item in secondary
                    if (normalized := EMOTION_ALIASES.get(str(item).strip(), str(item).strip()))
                    in ALLOWED_EMOTIONS
                    and normalized != payload["primary_emotion"]
                )
            )[:3]
            payload["provider"] = self.name
            return EmotionResult.model_validate(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            raise LLMProviderError("模型返回的情绪格式无效") from exc


class OpenAIProvider(EmotionProvider):
    name = "openai"

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise LLMProviderError("缺少 OPENAI_API_KEY")
        self.api_key = settings.openai_api_key
        self.base_url = settings.openai_base_url.rstrip("/")
        self.model = settings.openai_model

    async def analyze(self, text: str) -> EmotionResult:
        payload = {
            "model": self.model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                raw = response.json()["choices"][0]["message"]["content"]
                return self.parse_result(raw)
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("OpenAI 标准接口暂时不可用") from exc


class AnthropicProvider(EmotionProvider):
    name = "anthropic"

    def __init__(self, settings: Settings):
        if not settings.anthropic_api_key:
            raise LLMProviderError("缺少 ANTHROPIC_API_KEY")
        self.api_key = settings.anthropic_api_key
        self.base_url = settings.anthropic_base_url.rstrip("/")
        self.model = settings.anthropic_model

    async def analyze(self, text: str) -> EmotionResult:
        payload = {
            "model": self.model,
            "max_tokens": 600,
            "temperature": 0.2,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": text}],
        }
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{self.base_url}/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json=payload,
                )
                response.raise_for_status()
                content = response.json()["content"]
                raw = next(item["text"] for item in content if item.get("type") == "text")
                return self.parse_result(raw)
        except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("Anthropic 标准接口暂时不可用") from exc


EMOTION_RULES: dict[str, dict[str, object]] = {
    "开心": {
        "words": ["开心", "高兴", "快乐", "幸福", "好棒", "顺利", "笑"],
        "valence": 0.8,
        "arousal": 0.55,
    },
    "兴奋": {
        "words": ["兴奋", "激动", "太棒", "迫不及待", "冲", "燃"],
        "valence": 0.75,
        "arousal": 0.9,
    },
    "期待": {
        "words": ["期待", "希望", "想要", "盼", "未来", "比赛"],
        "valence": 0.45,
        "arousal": 0.65,
    },
    "平静": {
        "words": ["平静", "放松", "安稳", "还好", "慢慢", "安心"],
        "valence": 0.25,
        "arousal": 0.25,
    },
    "焦虑": {
        "words": ["焦虑", "紧张", "担心", "害怕", "来不及", "压力", "不安"],
        "valence": -0.5,
        "arousal": 0.82,
    },
    "难过": {
        "words": ["难过", "伤心", "失落", "哭", "痛苦", "委屈"],
        "valence": -0.75,
        "arousal": 0.45,
    },
    "孤独": {
        "words": ["孤独", "孤单", "没人", "一个人", "不被理解", "想聊聊"],
        "valence": -0.6,
        "arousal": 0.35,
    },
    "愤怒": {
        "words": ["生气", "愤怒", "烦死", "讨厌", "气死", "不公平"],
        "valence": -0.75,
        "arousal": 0.9,
    },
    "疲惫": {
        "words": ["累", "疲惫", "困", "没力气", "熬夜", "撑不住"],
        "valence": -0.4,
        "arousal": 0.18,
    },
}


class DemoProvider(EmotionProvider):
    name = "demo"

    async def analyze(self, text: str) -> EmotionResult:
        scored: list[tuple[int, str, list[str]]] = []
        for emotion, rule in EMOTION_RULES.items():
            hits = [word for word in rule["words"] if word in text]
            scored.append((len(hits), emotion, hits))
        scored.sort(reverse=True)
        top_score, primary, hits = scored[0]
        if top_score == 0:
            primary = "复杂"
            hits = [word for word in re.split(r"[，。！？、\s]+", text) if len(word) >= 2][:3]
            valence, arousal = 0.0, 0.5
        else:
            rule = EMOTION_RULES[primary]
            valence = float(rule["valence"])
            arousal = float(rule["arousal"])

        secondary = [
            emotion for score, emotion, _ in scored[1:4] if score > 0 and emotion != primary
        ]
        punctuation_boost = min(text.count("!") + text.count("！"), 3) * 0.06
        intensity = min(0.96, 0.5 + top_score * 0.12 + punctuation_boost)
        concern_words = ["自杀", "不想活", "结束生命", "伤害自己", "轻生"]
        safety_level = "concern" if any(word in text for word in concern_words) else "normal"

        explanations = {
            "开心": "文字里有轻盈和满足感，你似乎正想分享这份好心情。",
            "兴奋": "你正处在高能量的兴奋状态，很想让这份激动被接住。",
            "期待": "你对接下来抱有期待，也希望有人理解这份在意。",
            "平静": "你的表达舒缓而稳定，像是在寻找一段不费力的陪伴。",
            "焦虑": "你似乎正被不确定和时间压力拉扯，希望有人同频理解。",
            "难过": "文字里有明显的失落感，此刻你可能更需要被安静听见。",
            "孤独": "你想要的也许不是答案，而是一个真正在线的倾听者。",
            "愤怒": "你正承受较强的挫败与不公平感，需要一个安全出口。",
            "疲惫": "你的能量已经偏低，像是撑了很久，想暂时卸下一点重量。",
            "复杂": "你的情绪不止一种，既有牵挂也有犹豫，值得慢慢说开。",
        }
        if safety_level == "concern":
            explanations[primary] = "你正在经历很重的情绪。请先联系可信任的人；若有即时危险，请联系当地紧急援助。"

        return EmotionResult(
            primary_emotion=primary,
            secondary_emotions=secondary,
            valence=valence,
            arousal=arousal,
            intensity=intensity,
            keywords=(hits or [primary])[:6],
            explanation=explanations[primary],
            safety_level=safety_level,
            provider="demo",
        )


def get_provider(settings: Settings) -> EmotionProvider:
    provider = settings.llm_provider.lower().strip()
    if provider == "openai":
        return OpenAIProvider(settings)
    if provider == "anthropic":
        return AnthropicProvider(settings)
    if provider == "demo":
        return DemoProvider()
    raise LLMProviderError(f"不支持的 LLM_PROVIDER：{settings.llm_provider}")
