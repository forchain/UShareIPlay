from typing import Optional


def get_playlist_text_and_first_song(playlist_info: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    if not isinstance(playlist_info, dict):
        return None, None, "Invalid playlist info"

    error = playlist_info.get("error")
    if error:
        return None, None, error

    playlist_text = (playlist_info.get("playlist") or "").strip()
    if not playlist_text:
        return None, None, "Playlist content is empty"

    first_song = playlist_text.splitlines()[0].strip() if playlist_text else None
    return playlist_text, first_song, None
