import logging
import os
import yaml

logger = logging.getLogger(__name__)

#: config.local.yaml 覆盖的元素定义键
_ELEMENT_DEFINITION_KEYS = ("elements", "risk_elements", "drawer_elements")


class LocalConfigOverrideRejected(ValueError):
    """已废弃：保留该类以防外部旧引用破坏导入。"""


def _warn_element_overrides(local_config: dict) -> None:
    """检查 config.local.yaml 是否覆盖元素定义，若有则输出 WARNING 提醒。

    允许在 config.local.yaml 中覆盖元素选择器（用于快速应对 App 定位符变更而免于重新发版），
    但应尽快并入 config.yaml。
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
        logger.warning(
            f"检测到 config.local.yaml 中覆盖了元素定义: {', '.join(offenders)}。"
            "此覆盖仅用于紧急修复定位符，请尽快在下一个版本中并入 config.yaml！"
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
                _warn_element_overrides(local_config)
                config = _deep_merge(config, local_config)

        return config
