from wsapp_gui.chat_manager import ChatManager


class DummyApp:
    def __init__(self):
        self.messages = []

    def _append_chat(self, text: str):
        self.messages.append(text)


def test_chatmanager_append_chat_delegates_to_app():
    app = DummyApp()
    cm = ChatManager(app)
    cm._append_chat("Hello")
    assert app.messages == ["Hello\n"]


def test_chatmanager_append_chat_fallback_txt_widget():
    class FakeText:
        def __init__(self):
            self.state = 'disabled'
            self.buffer = []
            self.seen = False

        def configure(self, state=None, **_k):
            if state is not None:
                self.state = state

        def insert(self, where, text):  # noqa: ARG002
            self.buffer.append(text)

        def see(self, where):  # noqa: ARG002
            self.seen = True

    class DummyAppNoAppend:
        def __init__(self):
            self.txt_chat = FakeText()

    app = DummyAppNoAppend()
    cm = ChatManager(app)
    cm._append_chat("Hello")

    # Text appended with newline, widget scrolled into view, and set back to disabled
    assert app.txt_chat.buffer and app.txt_chat.buffer[-1] == "Hello\n"
    assert app.txt_chat.seen is True
    assert app.txt_chat.state == 'disabled'
