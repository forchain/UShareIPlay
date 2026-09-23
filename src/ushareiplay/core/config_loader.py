import os
import yaml


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
                config = _deep_merge(config, local_config)

        return config
