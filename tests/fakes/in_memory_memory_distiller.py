"""`MemoryDistiller` 的内存替身：记录每次调用并返回预设结果。"""

from ushareiplay.modules.user.ports import MemoryDistiller


class InMemoryMemoryDistiller(MemoryDistiller):
    def __init__(self, result: tuple[bool, list[str], str] = (True, [], "")):
        self.result = result
        self.calls: list[dict] = []

    async def distill(
        self,
        user_name: str,
        existing_directives: list[str],
        existing_profile: str,
        new_messages: list[str],
    ) -> tuple[bool, list[str], str]:
        self.calls.append(
            {
                "user_name": user_name,
                "existing_directives": list(existing_directives),
                "existing_profile": existing_profile,
                "new_messages": list(new_messages),
            }
        )
        return self.result
