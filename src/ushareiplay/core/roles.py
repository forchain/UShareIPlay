from typing import Any, Iterable, Optional, Set


DEFAULT_ROOM_OWNER = "Joyer"
DEFAULT_ADMIN_USERS = frozenset({"Outlier", "Chainer"})
DEFAULT_SYSTEM_USERS = frozenset({"Timer", "Agent"})
CONSOLE_USER = "console"


def _normalize_set(values: Optional[Iterable[Any]]) -> Set[str]:
    if values is None:
        return set()
    result = set()
    for item in values:
        if isinstance(item, str):
            s = item.strip()
            if s:
                result.add(s.lower())
    return result


def _find_config_value(soul_cfg: dict, raw_cfg: dict, keys: Iterable[str]) -> Any:
    for k in keys:
        if k in soul_cfg and soul_cfg[k] is not None:
            return soul_cfg[k]
    for k in keys:
        if k in raw_cfg and raw_cfg[k] is not None:
            return raw_cfg[k]
    return None


class RolePolicy:
    """
    统一角色与权限判定策略。
    
    分类：
    1. 房主 (Room Owner): 配置的 room_owner，同时合并 Console (Console 具备房主身份)。
    2. 管理员 (Admin Users): 配置的 admin_users (含房主与 Console)。
    3. 系统角色 (System Roles): 配置的 system_users (如 Timer, Agent)，自动化执行角色。
    4. 人工操作者 (Human Operators): 具备主观判断能力的人工角色 (房主、Console、管理员)。
    """

    def __init__(self, config: Optional[dict] = None):
        self._raw_config = config or {}
        soul_cfg = self._raw_config.get("soul", {})
        if not isinstance(soul_cfg, dict):
            soul_cfg = {}

        # 1. 房主 (Room Owner)
        owner_raw = _find_config_value(soul_cfg, self._raw_config, ["room_owner", "owner_username"])
        if isinstance(owner_raw, str) and owner_raw.strip():
            self._room_owner = owner_raw.strip()
        elif config is not None and ("room_owner" in soul_cfg or "room_owner" in self._raw_config):
            self._room_owner = ""
        else:
            self._room_owner = DEFAULT_ROOM_OWNER

        # 2. 管理员 (Admin Users)
        admins_raw = _find_config_value(soul_cfg, self._raw_config, ["admin_users", "admins"])
        if admins_raw is not None:
            self._admin_users = _normalize_set(admins_raw)
        else:
            self._admin_users = _normalize_set(DEFAULT_ADMIN_USERS)

        # 3. 系统自动化角色 (System Users)
        sys_raw = _find_config_value(soul_cfg, self._raw_config, ["system_users"])
        if sys_raw is not None:
            self._system_users = _normalize_set(sys_raw)
        else:
            self._system_users = _normalize_set(DEFAULT_SYSTEM_USERS)

    @property
    def room_owner(self) -> str:
        return self._room_owner

    @property
    def admin_users(self) -> Set[str]:
        return set(self._admin_users)

    @property
    def system_users(self) -> Set[str]:
        return set(self._system_users)

    def is_room_owner(self, username: Optional[str]) -> bool:
        """检查用户是否为房主。Console 与房主合并，Console 始终视为房主。"""
        if not username:
            return False
        normalized = username.strip().lower()
        if normalized == CONSOLE_USER:
            return True
        if self._room_owner and normalized == self._room_owner.lower():
            return True
        return False

    def is_admin(self, username: Optional[str]) -> bool:
        """检查用户是否为管理员（房主与 Console 均具备管理员身份）。"""
        if not username:
            return False
        if self.is_room_owner(username):
            return True
        normalized = username.strip().lower()
        return normalized in self._admin_users

    def is_system_user(self, username: Optional[str]) -> bool:
        """检查用户是否为系统自动化角色（如 Timer, Agent）。"""
        if not username:
            return False
        normalized = username.strip().lower()
        return normalized in self._system_users

    def is_human_operator(self, username: Optional[str]) -> bool:
        """
        检查是否为人工操作者（房主、Console、管理员）。
        人工触发的操作具备人工判断能力，在保护策略上：
        1. 播放中无需保护（不锁定他人播放）。
        2. 能够突破保护（他人歌单守护、睡眠保护）。
        """
        return self.is_admin(username)

    def is_privileged(self, username: Optional[str]) -> bool:
        """
        检查是否为特权用户（包含人工操作者与系统角色）。
        用于无需受普通用户等级约束或播放中无需加锁的场景。
        """
        return self.is_human_operator(username) or self.is_system_user(username)
