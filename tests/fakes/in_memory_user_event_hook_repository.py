"""`UserEventHookRepository` 的内存替身。"""

from typing import Optional

from ushareiplay.modules.room.domain import HookCommand
from ushareiplay.modules.room.ports import UserEventHookRepository
from ushareiplay.modules.room.registry import Resolution, spec_for
from ushareiplay.modules.user.ports import UserRepository
from tests.fakes.in_memory_user_repository import InMemoryUserRepository


class InMemoryUserEventHookRepository(UserEventHookRepository):
    def __init__(self, users: Optional[UserRepository] = None):
        self._users = users or InMemoryUserRepository()
        self._rows: list[tuple[int, str, int, str]] = []  # id, event_type, user_id, command
        self._next_id = 1

    async def _owner(self, user_id: int) -> str:
        user = await self._users.get_by_id(user_id)
        return user.username.value

    async def _user_filter(self, event_type: str, username: str) -> set[int]:
        spec = spec_for(event_type)
        if spec.resolution is Resolution.ALIAS_GROUP:
            return set(await self._users.get_all_associated_user_ids(username))
        canonical = await self._users.get_or_create(username)
        return {canonical.id}

    async def create(self, event_type: str, username: str, command: str) -> HookCommand:
        user = await self._users.get_or_create(username)
        row = (self._next_id, event_type, user.id, command)
        self._next_id += 1
        self._rows.append(row)
        return HookCommand(id=row[0], command=row[3], owner=user.username.value)

    async def get_by_username(self, event_type: str, username: str) -> list[HookCommand]:
        allowed = await self._user_filter(event_type, username)
        return [
            HookCommand(id=row_id, command=command, owner=await self._owner(user_id))
            for row_id, row_event, user_id, command in self._rows
            if row_event == event_type and user_id in allowed
        ]

    async def get_all_ordered(self, event_type: str) -> list[HookCommand]:
        return [
            HookCommand(id=row_id, command=command, owner=await self._owner(user_id))
            for row_id, row_event, user_id, command in self._rows
            if row_event == event_type
        ]

    async def get_by_id(self, event_type: str, command_id: int) -> Optional[HookCommand]:
        for row_id, row_event, user_id, command in self._rows:
            if row_event == event_type and row_id == command_id:
                return HookCommand(
                    id=row_id, command=command, owner=await self._owner(user_id)
                )
        return None

    async def delete_by_id(self, event_type: str, command_id: int) -> bool:
        before = len(self._rows)
        self._rows = [
            row
            for row in self._rows
            if not (row[1] == event_type and row[0] == command_id)
        ]
        return len(self._rows) != before

    async def delete_all_by_username(self, event_type: str, username: str) -> int:
        allowed = await self._user_filter(event_type, username)
        before = len(self._rows)
        self._rows = [
            row
            for row in self._rows
            if not (row[1] == event_type and row[2] in allowed)
        ]
        return before - len(self._rows)
