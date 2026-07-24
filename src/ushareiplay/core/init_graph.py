"""初始化图：集中管理 handlers、state 模块与 business managers 的创建顺序。

AppController 把初始化委托给本模块；每个 stage 独立可验证。
其他模块一律使用 .instance() 作为只读查找 API，不自行创建单例。
"""


class InitGraph:
    """Owns initialization ordering and dependencies for AppController."""

    def __init__(self, controller):
        self.controller = controller

    def run(self):
        """按依赖顺序执行全部初始化阶段。"""
        self.init_handlers()
        self.init_managers()
        self.init_events()

    def init_handlers(self):
        """Stage 1: UI handlers（依赖 driver 与 config）。"""
        from ushareiplay.handlers.qq_music_handler import QQMusicHandler
        from ushareiplay.handlers.soul_handler import SoulHandler

        c = self.controller
        c.soul_handler = SoulHandler.initialize(c.driver, c.config["soul"], c)
        c.register_driver_subscriber(c.soul_handler)
        c.music_handler = QQMusicHandler.initialize(c.driver, c.config["qq_music"], c)
        c.register_driver_subscriber(c.music_handler)
        c.logger = c.soul_handler.logger

    def init_managers(self):
        """Stage 2: state 模块与 business managers（依赖 handlers）。"""
        from ushareiplay.core.message_queue import MessageQueue
        from ushareiplay.core.message_dispatch import MessageDispatch
        from ushareiplay.core.post_party_create_automation import PostPartyCreateAutomation
        from ushareiplay.core.runtime_services import RuntimeQueueDrainer
        from ushareiplay.managers.admin_manager import AdminManager
        from ushareiplay.managers.command_manager import CommandManager
        from ushareiplay.managers.info_manager import InfoManager
        from ushareiplay.managers.keyword_manager import KeywordManager
        from ushareiplay.managers.message_manager import MessageManager
        from ushareiplay.managers.mic_manager import MicManager
        from ushareiplay.managers.music_manager import MusicManager
        from ushareiplay.managers.notice_manager import NoticeManager
        from ushareiplay.managers.party_manager import PartyManager
        from ushareiplay.managers.recovery_manager import RecoveryManager
        from ushareiplay.managers.room_name_manager import RoomNameManager
        from ushareiplay.managers.seat_manager import SeatManager
        from ushareiplay.managers.sleep_manager import SleepManager
        from ushareiplay.managers.theme_manager import ThemeManager
        from ushareiplay.managers.timer_manager import TimerManager
        from ushareiplay.managers.title_manager import TitleManager
        from ushareiplay.managers.topic_manager import TopicManager
        from ushareiplay.managers.user_manager import UserManager
        from ushareiplay.state.online_list_scraper import OnlineListScraper
        from ushareiplay.state.playback_broadcaster import PlaybackBroadcaster
        from ushareiplay.state.playlist_state import PlaylistState
        from ushareiplay.state.presence_tracker import PresenceTracker
        from ushareiplay.state.room_state import RoomState

        c = self.controller
        c.logger.info("创建 manager 实例...")
        c.seat_manager = SeatManager.get_instance(c.soul_handler)

        # Creation is deliberately centralized here. Every other module uses
        # .instance() as a lookup-only API.
        UserManager.initialize()
        SleepManager.initialize(c.config)
        MessageQueue.initialize()
        RecoveryManager.initialize()
        MessageManager.initialize()
        c.message_dispatch = MessageDispatch.initialize()
        c.topic_manager = TopicManager.initialize()
        c.mic_manager = MicManager.initialize()
        c.music_manager = MusicManager.initialize()
        c.register_driver_subscriber(c.music_manager)
        c.recovery_manager = RecoveryManager.instance()
        c.timer_manager = TimerManager.initialize()
        c.command_manager = CommandManager.initialize()
        c.command_manager.controller = c
        c.command_manager.configure_runtime(c.command_runtime_context)
        RoomState.initialize()
        PresenceTracker.initialize()
        PlaylistState.initialize()
        PlaybackBroadcaster.initialize()
        OnlineListScraper.initialize()
        c.info_manager = InfoManager.initialize()
        c.party_manager = PartyManager.initialize()
        c.notice_manager = NoticeManager.initialize()
        RoomNameManager.initialize()
        ThemeManager.initialize()
        TitleManager.initialize()
        AdminManager.initialize()
        KeywordManager.initialize()
        c.post_party_create_automation = PostPartyCreateAutomation(c)
        c._runtime_queue_drainer = RuntimeQueueDrainer(
            handler=c.soul_handler,
            command_manager=c.command_manager,
            send_screen_message=c.message_dispatch.send_screen_message,
            obs=c.obs,
            logger=c.logger,
        )
        c._status_reporter.soul_handler = c.soul_handler
        c._status_reporter.timer_manager = c.timer_manager

        c.logger.info("初始化命令解析器...")
        c.command_manager.initialize_parser(c.config["commands"])

    def init_events(self):
        """Stage 3: 事件管理器（依赖 managers 就绪）。"""
        from ushareiplay.managers.event_manager import EventManager

        c = self.controller
        c.logger.info("初始化事件管理器...")
        c.event_manager = EventManager.initialize()
        c.event_manager.configure_runtime(c.event_runtime_context)
        c.event_manager.initialize_events()
        c.logger.info("事件管理器初始化完成")
