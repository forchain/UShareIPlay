import os
import yaml

#: config.local.yaml 不允许覆盖的元素定义（AGENTS.md：元素选择器的唯一事实源
#: 是 config.yaml）。本地覆盖会让不同版本的机器人用不同选择器，且无声无息。
_ELEMENT_DEFINITION_KEYS = ("elements", "risk_elements", "drawer_elements")


class LocalConfigOverrideRejected(ValueError):
    """config.local.yaml 试图覆盖 config.yaml 的元素定义。"""


def _reject_element_overrides(local_config: dict) -> None:
    """config.local.yaml 里出现元素定义就当场拒绝。

    元素选择器的唯一事实源是 config.yaml：本地覆盖会让机器人用上一版选择器
    却没有任何报错，行为与配置对不上（ADR-0012）。
    """
    offenders = []
    for scope in ("", "soul.", "qq_music."):
        payload = local_config if not scope else local_config.get(scope[:-1])
        if not isinstance(payload, dict):
            continue
        for key in _ELEMENT_DEFINITION_KEYS:
            if key in payload:
                offenders.append(f"{scope}{key}")
    if offenders:
        raise LocalConfigOverrideRejected(
            "config.local.yaml 不得覆盖元素定义："
            + "、".join(offenders)
            + "；UI 元素选择器的唯一事实源是 config.yaml。"
        )


def _deep_merge(base, override):
    """Recursively merge override into base. Dicts are merged; commands lists are merged by prefix; other types replace."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        elif (
            key == "commands"
            and isinstance(result.get(key), list)
            and isinstance(value, list)
            and any(isinstance(x, dict) and "prefix" in x for x in result[key])
        ):
            base_commands = [dict(c) if isinstance(c, dict) else c for c in result[key]]
            cmd_index_map = {
                cmd.get("prefix"): i
                for i, cmd in enumerate(base_commands)
                if isinstance(cmd, dict) and "prefix" in cmd
            }
            for override_cmd in value:
                if isinstance(override_cmd, dict) and "prefix" in override_cmd:
                    prefix = override_cmd["prefix"]
                    if prefix in cmd_index_map:
                        idx = cmd_index_map[prefix]
                        if isinstance(base_commands[idx], dict):
                            base_commands[idx] = _deep_merge(base_commands[idx], override_cmd)
                        else:
                            base_commands[idx] = override_cmd
                    else:
                        base_commands.append(override_cmd)
                        cmd_index_map[prefix] = len(base_commands) - 1
                else:
                    base_commands.append(override_cmd)
            result[key] = base_commands
        else:
            result[key] = value
    return result


class ConfigLoader:
    @staticmethod
    def load_config(config_path='config.yaml'):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        local_path = os.path.join(
            os.path.dirname(os.path.abspath(config_path)),
            'config.local.yaml'
        )
        if os.path.exists(local_path):
            with open(local_path, 'r', encoding='utf-8') as f:
                local_config = yaml.safe_load(f)
            if local_config:
                # 元素定义只能待在 config.yaml：本地覆盖当场拒绝，不静默合并。
                _reject_element_overrides(local_config)
                config = _deep_merge(config, local_config)

        return config
