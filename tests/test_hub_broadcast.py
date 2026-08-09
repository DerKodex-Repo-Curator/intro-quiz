"""Hub.broadcast must survive a socket being removed underneath it (#77).

broadcast awaits inside its send loop, so the disconnect handler — or a second
broadcast — can drop the same socket in the gap. Removing it positionally then
raised ValueError out of broadcast and killed the handler driving the game.

Driven by calling Hub.broadcast directly with fake sockets: a real websocket adds
nothing here, and TestClient would fire the app's startup hooks.
"""
import asyncio

import pytest

from app import main


@pytest.fixture(autouse=True)
def no_display_names(monkeypatch):
    """broadcast asks the cast layer for display names on every call."""
    monkeypatch.setattr(main.board_cast, "display_names", lambda: [])


class FakeSocket:
    """Sends fine, counts what it got."""

    def __init__(self, slow=False):
        self.slow = slow
        self.sent = 0

    async def send_json(self, snap):
        if self.slow:
            await asyncio.sleep(0)   # let the loop suspend mid-broadcast
        self.sent += 1


class VanishingSocket:
    """Fails to send AND removes itself, as the disconnect handler would."""

    def __init__(self, hub):
        self.hub = hub
        self.sent = 0

    async def send_json(self, snap):
        if self in self.hub.sockets:
            self.hub.sockets.remove(self)
        raise RuntimeError("client gone")


def make_hub():
    hub = main.Hub()
    hub.game = None          # snapshot() is skipped for an idle hub
    return hub


def test_broadcast_survives_socket_removed_mid_send():
    hub = make_hub()
    good_a = FakeSocket(slow=True)
    gone = VanishingSocket(hub)
    good_b = FakeSocket()
    hub.sockets = [good_a, gone, good_b]

    asyncio.run(hub.broadcast())

    assert gone not in hub.sockets
    assert hub.sockets == [good_a, good_b]
    assert good_a.sent == 1 and good_b.sent == 1


def test_overlapping_broadcasts_share_a_dead_socket():
    hub = make_hub()
    good = FakeSocket(slow=True)
    dead = VanishingSocket(hub)
    hub.sockets = [good, dead]

    async def both():
        await asyncio.gather(hub.broadcast(), hub.broadcast())

    asyncio.run(both())          # neither call may raise

    assert hub.sockets == [good]


def test_healthy_sockets_are_untouched():
    hub = make_hub()
    socks = [FakeSocket(), FakeSocket()]
    hub.sockets = list(socks)

    asyncio.run(hub.broadcast())

    assert hub.sockets == socks
    assert all(s.sent == 1 for s in socks)
