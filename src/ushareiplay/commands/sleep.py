from __future__ import annotations

from ushareiplay.core.base_command import BaseCommand
from ushareiplay.managers.sleep_manager import SleepManager


class SleepCommand(BaseCommand):
    async def do_process(self, message_info, parameters):
        keyword = (parameters[0].strip().lower() if parameters else "status")

        manager = SleepManager.instance()

        if keyword == "on":
            manager.set_override(True)
            return {"message": "Sleep: ON (override)"}

        if keyword == "off":
            manager.set_override(False)
            return {"message": "Sleep: OFF (override)"}

        if keyword != "status":
            return {"error": "Usage: :sleep on|off|status"}

        default_enabled = manager.get_default_enabled()
        override = manager.get_override()
        effective_enabled = manager.effective_enabled

        override_text = "None"
        if override is True:
            override_text = "on"
        elif override is False:
            override_text = "off"

        effective = "ON" if effective_enabled else "OFF"
        in_window = "YES" if manager.is_in_configured_window() else "NO"
        window_text = manager.get_window_display()

        return {
            "message": (
                f"Sleep: {effective} | window: {window_text} | in_window_now: {in_window} | "
                f"default_enabled: {default_enabled} | override: {override_text} | effective_enabled: {effective_enabled}"
            )
        }
