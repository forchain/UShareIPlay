"""Pure domain tests for modules.playback.domain (ADR-0007 & Playlist Guard)."""

import pytest

from ushareiplay.modules.playback.domain import (
    NextQueue,
    PlaybackMutingPolicy,
    PlaybackMutingSettings,
    PlaybackMode,
    PlaybackOutcome,
    PlaybackRequest,
    PlaybackResult,
    PlaybackStatus,
    PlaybackTrack,
    PlaybackVariant,
    PlaylistContext,
    PlaylistGuard,
    matches_expected_song,
    primary_topic,
)
from ushareiplay.modules.shared.config import ConfigView
from ushareiplay.modules.shared.roles import RolePolicy


def _role_policy(owner="BotOwner", admins=(), system_users=("Timer", "Agent")):
    return RolePolicy(
        ConfigView(
            {
                "room_owner": owner,
                "admin_users": list(admins),
                "system_users": list(system_users),
            }
        )
    )


def test_playback_request_expected_song_only_for_single_song():
    assert PlaybackRequest.song("晴天", requester="Alice").expected_song == "晴天"
    assert PlaybackRequest.favorites(requester="Alice").expected_song is None
    assert PlaybackRequest.radar(requester="Alice").expected_song is None
    assert PlaybackRequest(mode=PlaybackMode.SINGER, query="周杰伦", requester="Alice").expected_song is None


def test_playback_track_queue_line_and_primary_topic():
    assert PlaybackTrack(song="Lo-Fi", singer="Artist").queue_line == "Lo-Fi - Artist"
    assert primary_topic("Lo-Fi - Artist") == "Lo-Fi"
    assert primary_topic("  ") == ""
    assert primary_topic(None) == ""


def test_playback_result_as_response_contract():
    started = PlaybackResult(
        status=PlaybackStatus.STARTED,
        track=PlaybackTrack(song="晴天", singer="周杰伦", album="叶惠美"),
        playlist=None,
        extra={"release_date": "2003-07-31"},
    )
    assert started.as_response() == {
        "song": "晴天",
        "singer": "周杰伦",
        "album": "叶惠美",
        "playlist": "",
        "release_date": "2003-07-31",
    }

    rejected = PlaybackResult(status=PlaybackStatus.REJECTED, error="Alice 正在播放歌单，请等待")
    assert rejected.as_response() == {"error": "Alice 正在播放歌单，请等待"}


def test_next_queue_lifecycle():
    nq = NextQueue()
    assert nq.record_next("Alice") is True  # was_empty
    assert nq.record_next("Bob") is False
    assert nq.pending_count == 2
    assert nq.contributors == {"Alice", "Bob"}

    assert nq.consume_track() is False
    assert nq.pending_count == 1
    assert nq.contributors == {"Alice", "Bob"}

    assert nq.consume_track() is True  # emptied
    assert nq.pending_count == 0
    assert nq.contributors == set()

    # Clamp at 0
    assert nq.consume_track() is False
    assert nq.pending_count == 0


def test_playlist_context_adopt_skips_single_song():
    ctx = PlaylistContext()
    ctx.next_queue.record_next("Alice")

    ctx.apply_adoption("Bob", PlaybackMode.SONG.value, playlist="ignored")
    assert ctx.player_name == "Joyer"
    assert ctx.list_mode == "unknown"
    assert ctx.current_playlist_name is None
    assert ctx.next_queue.pending_count == 1

    ctx.apply_adoption("Bob", PlaybackMode.PLAYLIST.value, playlist="流行热歌")
    assert ctx.player_name == "Bob"
    assert ctx.list_mode == "playlist"
    assert ctx.current_playlist_name == "流行热歌"
    assert ctx.next_queue.pending_count == 0
    assert ctx.get_playlist_info() == {"type": "playlist", "name": "流行热歌"}


def test_playlist_guard_single_song_exemption():
    policy = _role_policy()
    guard = PlaylistGuard()

    assert guard.should_exempt_single_song("Alice", PlaybackMode.SONG.value, policy) is True
    assert guard.should_exempt_single_song("Timer", PlaybackMode.SONG.value, policy) is False
    assert guard.should_exempt_single_song("Alice", PlaybackMode.PLAYLIST.value, policy) is False


def test_playlist_guard_blocks_when_regular_player_online():
    policy = _role_policy(admins=("AdminUser",))
    guard = PlaylistGuard()

    # Online regular player blocks another regular user
    err = guard.check_protection(
        caller_nickname="Bob",
        player_name="Alice",
        player_avatars={"Alice", "AliceAlt"},
        online_users={"AliceAlt"},
        next_queue=NextQueue(),
        contributor_avatars={},
        role_policy=policy,
    )
    assert err == "Alice 正在播放歌单，请等待"

    # Avatar of player is allowed
    assert (
        guard.check_protection(
            caller_nickname="AliceAlt",
            player_name="Alice",
            player_avatars={"Alice", "AliceAlt"},
            online_users={"Alice"},
            next_queue=NextQueue(),
            contributor_avatars={},
            role_policy=policy,
        )
        is None
    )

    # Admin (human operator) breaks guard
    assert (
        guard.check_protection(
            caller_nickname="AdminUser",
            player_name="Alice",
            player_avatars={"Alice"},
            online_users={"Alice"},
            next_queue=NextQueue(),
            contributor_avatars={},
            role_policy=policy,
        )
        is None
    )


def test_playlist_guard_next_queue_protection():
    policy = _role_policy()
    guard = PlaylistGuard()
    nq = NextQueue()
    nq.record_next("Charlie")

    err = guard.check_protection(
        caller_nickname="Bob",
        player_name="BotOwner",
        player_avatars={"BotOwner"},
        online_users={"BotOwner", "Charlie"},
        next_queue=nq,
        contributor_avatars={"Charlie": {"Charlie"}},
        role_policy=policy,
    )
    assert err == "Charlie 正在点歌，请等待"


def test_playback_muting_policy_and_settings():
    config = ConfigView(
        {
            "room_owner": "BotOwner",
            "playback_mute": {
                "enabled": False,
                "guest_room_only": True,
                "auto_enable_on_mic": True,
                "ignore_users": ["SystemBot"],
                "timeout": 3.5,
                "settling_delay": 0.2,
            },
        }
    )
    settings = PlaybackMutingSettings.from_config(config)
    assert settings.enabled is False
    assert settings.guest_room_only is True
    assert settings.timeout == 3.5
    assert settings.settling_delay == 0.2

    policy = PlaybackMutingPolicy()
    assert policy.should_engage(settings, is_guest_room=True) is False

    # Own account & ignored user do not arm
    assert policy.arm_on_mic("BotOwner", settings, room_owner="BotOwner") is False
    assert policy.arm_on_mic("systembot", settings, room_owner="BotOwner") is False
    assert policy.dynamically_enabled is False

    # Regular user arms muting and overrides disabled config
    assert policy.arm_on_mic("GuestUser", settings, room_owner="BotOwner") is True
    assert policy.dynamically_enabled is True
    assert policy.should_engage(settings, is_guest_room=False) is True

    # Reset clears dynamic enable
    assert policy.reset() is True
    assert policy.dynamically_enabled is False


def test_matches_expected_song():
    assert matches_expected_song("真的爱你", None) is True
    assert matches_expected_song("晴天 (Live)", "晴天 周杰伦") is True
    assert matches_expected_song("真的爱你", "爱") is False
