from ushareiplay.core.base_command import BaseCommand


class VolumeCommand(BaseCommand):
    """`:vol [0..15]` —— 查询/调节媒体音量，交给 `AdjustVolume` 用例。"""

    async def do_process(self, message_info, parameters):
        target_volume = None
        if len(parameters) > 0:
            target_volume, err = self.coerce_int(
                parameters[0], error="Invalid parameter, must be a number"
            )
            if err:
                return {"error": err}
            if target_volume < 0 or target_volume > 15:
                return {"error": "Volume must be between 0 and 15"}

        result = self.controller.adjust_volume.execute(target_volume)

        if "error" in result:
            return result

        if result.get("current", False):
            message = f"Current volume: {result['volume']}"
        else:
            message = f"Adjusted volume to {result['volume']}"

        return {"message": message}
