import argparse
import asyncio
import json
import threading
import random
from collections import deque

import requests

import discord
import sentencepiece
from discord.ext import tasks

from utils.sanitiser import Sanitiser


class Chatbot:
    def __init__(self, config_file, llm_host="localhost:5000"):
        self.llm_host = f"http://{llm_host}/v1/completions"
        try:
            self.sp = sentencepiece.SentencePieceProcessor(model_file='./tokenizer.model')
        except OSError:
            print("ERROR: \ttokeniser.model file not found. Include the tokenizer.model file of your LLM in the same folder as this .py file.")
            print("\tFor GGUF users, look for the original model repository (pre-GGUF quantisation).")
            exit(0)

        self.config_file = config_file
        self.load()

        # Admins & channel arguments are never reloaded for safety & sync reasons
        self.admins = self.args["admins"]
        self.channel = self.args["channel_id"]
        self.bot_token = self.args["bot_token"]

        self.message_history = deque()
        self.reset_message_history()

        self.request_mutex = threading.Lock()
        self.request_thread = None
        self.next_message = None
        self.HEADERS = {"Content-Type": "application/json"}

        # Debug / morbid curiosity purposes only
        self.last_summary = None

    def reset_message_history(self):
        self.message_history.clear()
        # Most LLMs seem to work better when given a starting message. Edit or remove this if you will.
        self.message_history.appendleft("%s:\nHello" % self.name)

    def _count_tokens(self, prompt):
        prompt_tokens = self.sp.encode_as_ids(prompt)
        return len(prompt_tokens)

    def load(self):
        # Reloads config
        with open(self.config_file, "r") as f:
            self.args = json.load(f)

        with open(self.args["context"], "r") as f:
            self.context = json.load(f)["context"]

        with open(self.args["persona"], "r") as f:
            j = json.load(f)
            self.name = j["name"]
            self.persona = j["persona"]

        with open(self.args["chat_format"], "r") as f:
            j = json.load(f)
            self.chat_format = j["format"]
            self.chat_format = self.chat_format.replace(j["context_sub"], self.context)
            self.chat_format = self.chat_format.replace(j["persona_sub"], self.persona)
            self.chat_format = self.chat_format.replace(j["char_sub"], self.name)
            self.chat_sub = j["chat_sub"]
            self.summary_sub = j["summary_sub"]
            self.input_prefix = j["input_prefix"]
            self.response_prefix = j["response_prefix"]

        self.summary_format = None
        if "summary_format" in self.args:
            with open(self.args["summary_format"], "r") as f:
                j = json.load(f)
                self.summary_format = j["format"]
                self.summary_format = self.summary_format.replace(j["persona_sub"], self.persona)
                self.summary_format = self.summary_format.replace(j["char_sub"], self.name)
                self.summary_chat_sub = j["chat_sub"]

        self.chat_params = dict(self.args["chat_params"])
        self.summary_params = dict(self.args["summary_params"])

        self.args["banned_substrings_full"] = set(self.args["banned_substrings"])
        self.args["banned_substrings_full"].add(self.chat_sub)
        self.args["banned_substrings_full"].add(self.summary_sub)
        self.args["banned_substrings_full"].add(self.input_prefix)
        self.args["banned_substrings_full"].add(self.response_prefix)
        if "summary_format" in self.args:
            self.args["banned_substrings_full"].add(self.summary_chat_sub)
        self.args["banned_substrings_full"].discard("")
        self.args["banned_substrings_full"].discard("\n")

        self.sanitiser = Sanitiser(self.name, self.args["banned_substrings_full"])

        if self.summary_format is None:
            format_tokens = self._count_tokens(self.chat_format)
        else:
            format_tokens = self._count_tokens(self.summary_format)
        self.max_tokens = self.args["max_tokens"] - format_tokens

    def _create_chat_prompt(self, summary=None):
        message_outputs = []
        n_tokens = 0
        for msg in self.message_history:
            if msg.startswith("%s:" % self.name):
                # msg_ = msg[len("%s: " % self.name):]
                # msg_ = self.response_prefix + msg_
                msg_ = self.response_prefix + msg
            else:
                msg_ = self.input_prefix + msg

            n_tokens += self._count_tokens(msg_) + 1

            if n_tokens >= self.max_tokens:
                break

            message_outputs.append(msg_)

            if summary is not None and len(message_outputs) > 8:
                break

        # Remove excess message history (given max context length)
        if summary is None:
            n_remove = len(self.message_history) - len(message_outputs)
            for _ in range(n_remove):
                self.message_history.pop()

        prompt = self.chat_format.replace(self.chat_sub, "\n".join(reversed(message_outputs)))
        if summary is None:
            prompt = prompt.replace(self.summary_sub, "")
        else:
            prompt = prompt.replace(self.summary_sub, summary)
        return prompt

    def _create_summary_prompt(self):
        message_outputs = []
        n_tokens = 0
        for msg in self.message_history:
            n_tokens += self._count_tokens(msg) + 1

            if n_tokens >= self.max_tokens:
                break

            message_outputs.append(msg)

        # Remove excess message history (given max context length)
        n_remove = len(self.message_history) - len(message_outputs)
        for _ in range(n_remove):
            self.message_history.pop()

        return self.summary_format.replace(self.summary_chat_sub, "\n".join(reversed(message_outputs)))

    def _get_names(self):
        names = {self.name}
        for msg in self.message_history:
            names.add(msg.split(":", 1)[0])
        return list(names)

    def get_next_message(self):
        summary = None

        # Disallow the response to include "User: " for existing user names. May result in empty evaluations.
        stop_names = [name + ":" for name in self._get_names()]
        stop_names.remove("%s:" % self.name)

        # SUMMARY REQUEST
        # Only begin using summary when >8 messages. Most LLMs don't have repetition issues before that.
        if len(self.message_history) > 8 and self.summary_format is not None:
            summary_prompt = self._create_summary_prompt()
            body = dict(self.summary_params)
            body["prompt"] = summary_prompt
            body["stop"].extend(stop_names)
            # Max 4 retries for summary generation. (This usually should not be an issue for most LLMs)
            for _ in range(4):
                response = requests.post(self.llm_host, headers=self.HEADERS, json=body, timeout=120)
                if response.status_code == 200:
                    summary = self.sanitiser.sanitise_output(response.json()["choices"][0]["text"])
                    self.last_summary = summary
                    if summary is not None:
                        print("Summary:\n%s" % summary)
                        break
            if summary is None:
                print("Summary generation failed. Continuing without summary.")

        # CHAT REQUEST
        chat_prompt = self._create_chat_prompt(summary=summary)
        body = dict(self.chat_params)
        body["prompt"] = chat_prompt
        body["stop"].extend(stop_names)

        # Max 4 retries for chat generation. If this is a recurring issue, turn up the heat
        # (or, check your prompt settings and make sure it's not beginning its responses with a stop word)
        # (response may also be containing words in your banned_substrings list)
        for _ in range(4):
            response = requests.post(self.llm_host, headers=self.HEADERS, json=body, timeout=120)
            if response.status_code == 200:
                output = self.sanitiser.sanitise_output(response.json()["choices"][0]["text"])
                if output is not None:
                    print("Response:\n%s\n" % output)
                    return output
        print("Response generation failed.\n")
        return None

    def thread_request(self):
        # Threaded non-blocking LLM request.
        if self.request_mutex.locked():
            return
        with self.request_mutex:
            if len(self.message_history) <= 0:
                return
            if self.next_message is not None:
                return
            if self.message_history[0].startswith("%s:" % self.name):
                return

            self.next_message = self.get_next_message()

    def handle_message(self, name, message, is_admin=False):
        SYSTEM_PREFIX = "[SYSTEM]"
        if name == self.name and message.startswith(SYSTEM_PREFIX):
            # Ignore command feedback
            return None
        if message.startswith("!"):
            # Bot commands
            if is_admin and message == "!reset":
                with self.request_mutex:
                    self.reset_message_history()
                    self.load()
                    self.last_summary = None
                return "%s Reset to initial state. Settings reloaded." % SYSTEM_PREFIX

            if is_admin and message == "!reload":
                self.load()
                return "%s Settings reloaded." % SYSTEM_PREFIX

            if is_admin and message == "!summary":
                return "%s Previous summary:\n%s" % (SYSTEM_PREFIX, self.last_summary)

        new_message = self.sanitiser.sanitise_message(name, message)
        if new_message is not None:
            self.message_history.appendleft(new_message)
        return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", required=True, help="Bot configuration JSON file")
    parser.add_argument("-s", "--server", default="localhost:5000", help="LLM API server address, including port. e.g. \"localhost:5000\"")

    args = parser.parse_args()
    chatbot = Chatbot(args.config, args.server)

    intents = discord.Intents.all()
    intents.members = True
    bot = discord.Client(intents=intents)

    @bot.event
    async def on_ready():
        step.start()
        send_message.start()
        print("Logged on as {0}!".format(bot.user))

    @bot.event
    async def on_message(message):
        # Handle incoming messages from Discord channel
        if message.channel.id == chatbot.channel:
            name = message.author.display_name
            if message.author == bot.user:
                name = chatbot.name
            content = message.content

            # Adds name referral when message replies to another message
            if message.reference and message.reference.resolved and isinstance(message.reference.resolved,
                                                                               discord.Message):
                reply = message.reference.resolved.author.display_name
                content = reply + ", " + content

            res = chatbot.handle_message(name, content, is_admin=(message.author.id in chatbot.admins))
            if res is not None:
                # Sends command feedback
                channel = bot.get_channel(chatbot.channel)
                await channel.send(res)

    @tasks.loop(seconds=5)
    async def step():
        # Start LLM eval at random intervals.
        timer = random.randint(3, 6)
        step.change_interval(seconds=timer)
        thread = threading.Thread(target=chatbot.thread_request)
        thread.start()
        # Check if LLM eval returns early, i.e. LLM eval not currently necessary. If not, send typing signal.
        # Correctness not guaranteed, but whatever, it's a minor feature
        await asyncio.sleep(1)
        if thread is not None and thread.is_alive():
            channel = bot.get_channel(chatbot.channel)
            await channel.typing()

    @tasks.loop(seconds=1)
    async def send_message():
        # Check if new LLM message ready every second.
        channel = bot.get_channel(chatbot.channel)
        if chatbot.request_mutex.locked():
            return
        with chatbot.request_mutex:
            if chatbot.next_message is None:
                return
            else:
                async with channel.typing():
                    await channel.send(chatbot.next_message)
                    chatbot.next_message = None

    # chatbot.get_next_message()
    bot.run(chatbot.bot_token)
