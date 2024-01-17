import re
import emoji


class Sanitiser:
    def __init__(self, char_name, banned_substrings=None):
        self.banned_substrings = banned_substrings
        self.char_name = char_name

        self.discord_emoji_regex = re.compile("<.*?>")
        self.space_regex = re.compile(" +")
        self.newline_regex = re.compile("\n+")
        self.ellipsis_regex = re.compile("(\\.\\.\\.)\\.+")

    def sanitise_message(self, name, message):
        for banned_substring in self.banned_substrings:
            if banned_substring in name.lower():
                return None
            if banned_substring in message.lower():
                return None

        name = emoji.replace_emoji(name)
        name = self.space_regex.sub(' ', name)
        name = name.replace(":", " ")
        name = name.strip()

        message = self.discord_emoji_regex.sub('', message)
        message = emoji.replace_emoji(message)
        message = self.space_regex.sub(' ', message)
        message = self.newline_regex.sub('\n', message)
        message = message.strip()

        if len(name) == 0 or len(message) == 0:
            return None

        return "%s:\n%s" % (name, message)

    def sanitise_output(self, message):
        for banned_substring in self.banned_substrings:
            if banned_substring in message.lower():
                return None

        message = message.replace(u'\uFFFD', "")
        message = message.replace("&lt;", "<")
        message = message.replace("&gt;", ">")
        message = message.replace("[%s]" % self.char_name, "")
        message = message.replace("%s: " % self.char_name, "")
        message = self.ellipsis_regex.sub('...', message)

        message = message.strip()

        message = emoji.emojize(message)
        message = emoji.replace_emoji(message)
        message = message.strip()

        if message.startswith("\"") and message.endswith("\"") and message.count("\"") == 2:
            message = message.strip("\" ")

        if len(message) == 0 or len(message.strip(".")) == 0:
            return None

        return message
