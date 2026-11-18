from ushareiplay.core.base_command import BaseCommand
from ushareiplay.modules.playback.domain import PlaybackRequest, PlaybackVariant


class FavCommand(BaseCommand):
    """`:fav` —— 收藏的三个入口，统一走 `PlaySong`。"""

    handler_attr = "music_handler"

    async def do_process(self, message_info, parameters):
        if len(parameters) == 0:
            return await self._play(
                PlaybackRequest.favorites(requester=message_info.nickname)
            )

        subcmd = str(parameters[0]).lower()
        arg = " ".join(parameters[1:]).strip()
        if not arg:
            return {"error": "参数错误，使用方式: :fav 或 :fav type 关键字 或 :fav 2 关键字"}

        if subcmd in ["0", "type"]:
            return await self._play(
                PlaybackRequest.favorites(
                    arg,
                    variant=PlaybackVariant.FILTER,
                    requester=message_info.nickname,
                )
            )

        if subcmd in ["2", "search"]:
            return await self._play(
                PlaybackRequest.favorites(
                    arg,
                    variant=PlaybackVariant.SEARCH,
                    requester=message_info.nickname,
                )
            )

        return {"error": f"第一个参数必须是 0/type 或 2/search，当前为: {parameters[0]}"}

    async def _play(self, request: PlaybackRequest):
        result = await self.controller.play_song.execute(request)
        return result.as_response()
