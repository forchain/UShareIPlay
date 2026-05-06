import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_post_party_create_latch_party_then_ready_fires_once():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.post_party_create_automation import PostPartyCreateAutomation

    class C:
        config = {
            "soul": {
                "post_party_create": {
                    "enabled": True,
                    "wait_for_command_ready": True,
                    "commands": [":radio", ":seat"],
                }
            }
        }
        logger = None
        obs = None

    q = MessageQueue.instance()
    _run(q.clear_queue())

    auto = PostPartyCreateAutomation(C())

    # Party created first: should not enqueue until ready
    _run(auto.on_party_created_new())
    assert q.get_queue_size() == 0

    # Ready arrives: should enqueue commands
    _run(auto.on_command_ready())
    msgs = _run(q.get_all_messages())
    assert [m.content for m in msgs.values()] == [":radio", ":seat"]

    # Repeated ready should not fire again
    _run(auto.on_command_ready())
    assert q.get_queue_size() == 0


def test_post_party_create_latch_ready_then_party_fires_once():
    from ushareiplay.core.message_queue import MessageQueue
    from ushareiplay.core.post_party_create_automation import PostPartyCreateAutomation

    class C:
        config = {
            "soul": {
                "post_party_create": {
                    "enabled": True,
                    "wait_for_command_ready": True,
                    "commands": [":radio"],
                }
            }
        }
        logger = None
        obs = None

    q = MessageQueue.instance()
    _run(q.clear_queue())

    auto = PostPartyCreateAutomation(C())

    # Ready first: should not enqueue until party created
    _run(auto.on_command_ready())
    assert q.get_queue_size() == 0

    # Party created: now should fire
    _run(auto.on_party_created_new())
    msgs = _run(q.get_all_messages())
    assert [m.content for m in msgs.values()] == [":radio"]

