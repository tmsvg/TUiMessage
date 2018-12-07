import sqlite3
import os

CHAT_FILE = os.path.expanduser("~/Library/Messages/chat.db")
ADDRESS_BOOK = os.path.expanduser("~/Library/Application Support/AddressBook/AddressBook-v22.abcddb")

# The Apple epoch is different than Python's datetime epoch
_APPLE_TIME_DELTA = 978307200


class Buddy:

    def __init__(self, number, name=None):
        """
        Parameters: number: a string in the form '+11234567890'
                    name (opt.): a string representing the name Buddy.
        """
        self.number = number
        self.name = self.set_name() if name is None else name

    def set_name(self):
        """Fetch the name of the Texter using the SQL database file `ADDRESS_BOOK`
        """

        database = sqlite3.connect(ADDRESS_BOOK)
        d = database.cursor()
        fnumber = self.format_number("%")[2:]
        cmd = f"SELECT ZFIRSTNAME, ZLASTNAME FROM ZABCDCONTACTINDEX \
               LEFT OUTER JOIN ZABCDPHONENUMBER ON ZCONTACT = ZOWNER \
               LEFT OUTER JOIN ZABCDRECORD ON ZABCDRECORD.Z_PK = ZCONTACT \
               WHERE ZFULLNUMBER LIKE '%{fnumber}%'"
        d.execute(cmd)
        name = d.fetchone()

        if name is not None:
            name = " ".join(filter(None, name))
        else:
            name = self.format_number()[2:]

        database.close()

        return name

    def sender_of(self, message):
        """If the first element of the message dictionary is self.name,
        this texter is the sender of that message
        """
        return message['sender'] is self

    def format_number(self, separator_char="-"):
        """Generate a prettified representation of this buddy's phone number."""
        fnumber = format(int(self.number[:-1]), ",")
        fnumber = fnumber.replace(",", separator_char) + self.number[-1]
        return fnumber


class Sender(Buddy):

    def __init__(self, number):
        super().__init__(number)
        self.contacts = self.set_contacts()
        self.messages = []

    def get_messages(self, buddy, limit=0):
        """Generate a list of messages (dictionaries) in the form
        {'sender': sender, 'date': date, 'body' body}
        """

        fmessages = []
        database = sqlite3.connect(CHAT_FILE)
        d = database.cursor()

        cmd = "SELECT DISTINCT is_from_me, date, text \
               FROM message LEFT OUTER JOIN handle \
               ON handle.ROWID = message.handle_id \
               WHERE type = 0 AND handle.id=?"
        n = (buddy.number,)
        d.execute(cmd, n)

        messages = d.fetchall()

        # Iterate through the list of messages from most recent up to the
        # point at which `limit` number of messages have been processed
        for message in reversed(messages[-limit:]):
            sender = self if message[0] == 1 else buddy
            # As of MacOS 10.13.1, the date field in Chat.db is in nanoseconds
            date = (_APPLE_TIME_DELTA + message[1]) / 1000000000
            body = message[2]
            if body is None:
                body = ""
            else:
                body = body.replace("\N{OBJECT REPLACEMENT CHARACTER}",
                                    "(Cannot load image) ")
            f = {'sender': sender,
                 'date': date,
                 'body': body}
            fmessages.append(f)

        return reversed(fmessages)

    def set_contacts(self):
        """Set the list of known contacts for the sender.
        Done by searching the SQL `CHAT_FILE` for unique phone numbers.
        """
        contacts = []
        database = sqlite3.connect(CHAT_FILE)
        cmd = "SELECT DISTINCT handle.id FROM handle"

        for f in database.execute(cmd):
            try:
                int(f[0].replace("+", ""))
            except ValueError:
                continue
            new_buddy = Buddy(f[0])
            contacts.append(new_buddy)

        database.close()

        return contacts
