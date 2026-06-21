import asyncio
from collections import defaultdict

from app.models import EmotionResult
from app.store import Store


class FakeRedisStore(Store):
    values: dict[str, str] = {}
    sorted_sets: dict[str, dict[str, float]] = defaultdict(dict)

    async def _redis(self, *command: object):
        name = str(command[0]).upper()
        args = [str(item) for item in command[1:]]
        if name == "SET":
            key, value = args[:2]
            if "NX" in args and key in self.values:
                return None
            self.values[key] = value
            return "OK"
        if name == "GET":
            return self.values.get(args[0])
        if name == "EVAL":
            key, token = args[-2:]
            if self.values.get(key) == token:
                self.values.pop(key, None)
                return 1
            return 0
        if name == "ZADD":
            key, score, member = args
            self.sorted_sets[key][member] = float(score)
            return 1
        if name == "ZRANGE":
            key, start, end = args
            members = [item[0] for item in sorted(self.sorted_sets[key].items(), key=lambda item: item[1])]
            stop = len(members) if int(end) == -1 else int(end) + 1
            return members[int(start):stop]
        if name == "ZRANGEBYSCORE":
            key, minimum, maximum, _, offset, count = args
            lower = float("-inf") if minimum == "-inf" else float(minimum)
            upper = float("inf") if maximum == "+inf" else float(maximum)
            members = [
                item[0]
                for item in sorted(self.sorted_sets[key].items(), key=lambda item: item[1])
                if lower <= item[1] <= upper
            ]
            return members[int(offset):int(offset) + int(count)]
        if name == "ZREMRANGEBYSCORE":
            key, minimum, maximum = args
            lower = float("-inf") if minimum == "-inf" else float(minimum)
            upper = float("inf") if maximum == "+inf" else float(maximum)
            stale = [member for member, score in self.sorted_sets[key].items() if lower <= score <= upper]
            for member in stale:
                self.sorted_sets[key].pop(member, None)
            return len(stale)
        if name == "ZREM":
            key, member = args
            return int(self.sorted_sets[key].pop(member, None) is not None)
        raise AssertionError(f"Unsupported fake Redis command: {command}")


def emotion() -> EmotionResult:
    return EmotionResult(
        primary_emotion="焦虑",
        secondary_emotions=["期待"],
        valence=-0.2,
        arousal=0.7,
        intensity=0.7,
        keywords=["比赛"],
        explanation="既紧张又期待接下来会发生的事情。",
        provider="demo",
    )


def test_redis_store_shares_matches_and_messages_across_instances() -> None:
    async def scenario() -> None:
        FakeRedisStore.values.clear()
        FakeRedisStore.sorted_sets.clear()
        first_instance = FakeRedisStore(redis_url="https://redis.test", redis_token="test")
        second_instance = FakeRedisStore(redis_url="https://redis.test", redis_token="test")

        first = await first_instance.join(emotion(), "我有点紧张")
        second = await second_instance.join(emotion(), "我也有点紧张")
        first_status = await first_instance.get_ticket(first.id, first.access_token)
        assert first_status is not None
        assert first_status.status == "matched"
        assert first_status.conversation_id == second.conversation_id

        conversation = await second_instance.get_conversation(second.conversation_id or "", second.access_token)
        assert conversation is not None
        await second_instance.add_message(conversation, second.access_token, "我们一起慢慢来。")

        refreshed = await first_instance.get_conversation(first_status.conversation_id or "", first.access_token)
        assert refreshed is not None
        assert refreshed.messages[0].content == "我们一起慢慢来。"
        assert refreshed.messages[0].sender_token == second.access_token

    asyncio.run(scenario())


def test_redis_store_does_not_match_inactive_waiting_user() -> None:
    async def scenario() -> None:
        FakeRedisStore.values.clear()
        FakeRedisStore.sorted_sets.clear()
        store = FakeRedisStore(redis_url="https://redis.test", redis_token="test")

        inactive = await store.join(emotion(), "我先离开了")
        FakeRedisStore.sorted_sets["vibechat:waiting"][inactive.id] = 0
        active = await store.join(emotion(), "我正在等待")

        assert inactive.status == "waiting"
        assert active.status == "waiting"
        assert inactive.id not in FakeRedisStore.sorted_sets["vibechat:waiting"]

    asyncio.run(scenario())
