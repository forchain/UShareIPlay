import os
import yaml


def _deep_merge(base, override):
    """Recursively merge override into base. Dicts are merged; other types replace."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
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
