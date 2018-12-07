import subprocess
from datetime import datetime

import urwid

import sender
import emoji
import config


class Message(urwid.AttrMap):
    """A formatted message built from a message dict belonging to a `Sender`."""

    def __init__(self, msg_dict, host):
        self.sender = msg_dict['sender']
        self.body = msg_dict['body']
        self.date = msg_dict['date']

        s = urwid.Text((self._set_style(host), self.sender.name + ": "))

        b = urwid.Text(emoji.deemoji(self.body))

        d = urwid.Text(self.format_date(), align='right')

        msg = [('fixed', len(s.text), s), b, ('fixed', len(d.text) + 1, d)]
        msg = urwid.Columns(msg)

        super().__init__(msg, None, focus_map={None: 'highlighted',
                                               'host_name': 'highlighted',
                                               'buddy_name': 'highlighted'})

    def _set_style(self, host):
        if self.sender is host:
            return 'host_name'
        else:
            return 'buddy_name'

    def from_same_day(self, msg):
        """Return true if `self` and `msg` have dates <24 hours of each other."""
        return abs(self.date - msg.date) < 60 * 60 * 24

    def format_date(self):
        return datetime.fromtimestamp(self.date).strftime("%b %d, %I:%M %p")


class ContactButton(urwid.Button):
    def __init__(self, buddy, callback):
        self.buddy = buddy
        urwid.connect_signal(self, 'click', callback)
        super().__init__(self.buddy.name)

        self._w = urwid.AttrMap(urwid.SelectableIcon(["- ", self.buddy.name],
                                                     cursor_position=len(buddy.name) + 3),
                                None, focus_map='highlighted')


class MessagesView(urwid.ListBox):
    def __init__(self, callbacks):
        super().__init__(urwid.SimpleListWalker([]))

        urwid.register_signal(self.__class__, 'copy_text')
        urwid.connect_signal(self, 'copy_text', callbacks['on_copy_text'])

    def refresh(self, host, buddy):
        """Clear and repopulate the message view."""
        if buddy is None:
            return

        self.body.clear()
        for message in host.get_messages(buddy):
            self.body.append(Message(message, host))

        if len(self.body) > 0:
            self.focus_position = len(self.body) - 1

    def step_focus(self, increment):
        try:
            new_pos = self.get_focus()[1] + increment
            self.set_focus(new_pos)
        except (TypeError, IndexError):
            return

    def copy_message(self):
        """Copy the text of the focused message to the clipboard."""
        copied_text = self.get_focus()[0].original_widget[1].text
        urwid.emit_signal(self, 'copy_text', copied_text)

    def keypress(self, size, key):
        """Handle user keypresses."""
        key = key.lower()
        if key in config.KEYMAP['move_up']:
            self.step_focus(-1)
        elif key in config.KEYMAP['move_down']:
            self.step_focus(+1)
        elif key in config.KEYMAP['move_left']:
            return 'left'
        elif key in config.KEYMAP['move_right']:
            return 'right'
        elif key in config.KEYMAP['write_message']:
            return 'down'
        elif key in config.KEYMAP['copy_text']:
            self.copy_message()
        else:
            return key


class ContactMenu(urwid.ListBox):
    def __init__(self, host, callbacks):
        contact_list = [ContactButton(buddy, callback=callbacks['on_click'])
                        for buddy in host.contacts]
        super().__init__(urwid.SimpleListWalker(contact_list))

    def keypress(self, size, key):
        if key in config.KEYMAP['move_up']:
            super().keypress(size, 'up')
        elif key in config.KEYMAP['move_down']:
            super().keypress(size, 'down')
        elif key in config.KEYMAP['move_left']:
            return 'left'
        elif key in config.KEYMAP['move_right']:
            return 'right'
        elif key in config.KEYMAP['activate']:
            super().keypress(size, key)
        elif key in config.KEYMAP['write_message']:
            return 'down'
        else:
            return key


class InputBox(urwid.WidgetWrap):
    """The input box used for composing messages.
    """
    def __init__(self, callbacks, prompt=">> "):
        input_prompt = ('fixed', len(prompt), urwid.Text(('input_prompt', prompt)))
        text_field = urwid.Edit(multiline=True, allow_tab=True)
        super().__init__(urwid.Columns([input_prompt, text_field]))
        self.text_field = self._w[1]

        urwid.register_signal(self.__class__, 'send_message')
        urwid.connect_signal(self, 'send_message', callbacks['on_send_message'])

        urwid.register_signal(self.__class__, 'paste_text')
        urwid.connect_signal(self, 'paste_text', callbacks['on_paste_text'])

    def send(self):
        urwid.emit_signal(self, 'send_message', self.text_field)

    def paste(self):
        urwid.emit_signal(self, 'paste_text', self.text_field)

    def keypress(self, size, key):
        if key in config.KEYMAP['cancel']:
            return 'up'
        elif key in config.KEYMAP['send_message']:
            self.send()
        elif key in config.KEYMAP['paste_text']:
            self.paste()
        else:
            super().keypress(size, key)


class Controller:
    """The main controller for the `pyMessage` application.

    The Controller provides interfacing between UI components,
    signal handling, preferences, layout, and core functionality
    of sending and reading messages.
    """
    def __init__(self, host, buddy=None):
        self.preferences = {'input_allow_tabs': True,
                            'display_emojis': False,
                            'contact_menu_width': 32, }
        self.HOST = host
        self.buddy = buddy
        self.clipboard = ""

        # Callbacks
        self.message_callbacks = {'on_copy_text': self.handle_copy_text}
        self.input_callbacks = {'on_send_message': self.handle_send,
                                'on_paste_text': self.handle_paste}
        self.contact_callbacks = {'on_click': self.handle_contact_click}

        # UI
        self.contact_menu = ContactMenu(self.HOST,
                                        callbacks=self.contact_callbacks)
        self.message_frame = MessagesView(callbacks=self.message_callbacks)
        self.input_box = InputBox(callbacks=self.input_callbacks)
        self.window = self._build_window()

    def _build_window(self):
        """Assemble the main user interface."""
        left = urwid.Frame(self.contact_menu,
                           header=urwid.Pile([urwid.Text("Contacts"),
                                              urwid.Divider("-")]),
                           footer=None)
        left = ('fixed', self.preferences['contact_menu_width'], left)
        right = urwid.Frame(self.message_frame,
                            header=urwid.Pile([urwid.Text("Messages"),
                                               urwid.Divider("-")]),
                            footer=None)

        footer_label = ('fixed',
                        self.preferences['contact_menu_width'],
                        urwid.Text(('footer_label', "[iMessage]")))
        bottom = urwid.Columns([footer_label, self.input_box])

        window = urwid.Columns([left, right])
        window = urwid.Pile([window,
                             ('pack', urwid.Divider("=")),
                             ('pack', bottom)])

        return window

    def handle_contact_click(self, button):
        """Change the buddy being communicted with and refresh messages.
        Called upon receiving a contact button click signal.
        """
        self.buddy = button.buddy
        self.message_frame.refresh(self.HOST, self.buddy)
        self.window[0].focus_position = 1

    def handle_copy_text(self, copied_text):
        """Reassign `self.clipboard` upon receiving a `copy_text`
        signal from `self.message_frame`.
        """
        self.clipboard = copied_text

    def handle_paste(self, text_field):
        """Insert the contents of `self.clipboard` into the
        text field that emitted a `paste_text` signal.
        """
        text_field.insert_text(self.clipboard)

    def handle_send(self, text_field):
        """Send the text contents of `self.input_box` to `self.buddy`.
        """
        message = emoji.emojify(text_field.get_edit_text())
        text_field.set_edit_text("")
        cmd = ["osascript", "./applescript/send.scpt", self.buddy.number, message]
        subprocess.call(cmd, shell=False)
        self.message_frame.refresh(self.HOST, self.buddy)

    def handle_key(self, key):
        if key in config.KEYMAP['quit']:
            raise urwid.ExitMainLoop()
        elif key in config.KEYMAP['refresh']:
            self.message_frame.refresh(self.HOST, self.buddy)


def main():
    me = sender.Sender(config.USER_INFO['phone_number'])
    a = Controller(me)
    try:
        urwid.MainLoop(a.window, config.PALETTE, unhandled_input=a.handle_key).run()
    except KeyboardInterrupt:
        urwid.ExitMainLoop


if __name__ == '__main__':
    main()
