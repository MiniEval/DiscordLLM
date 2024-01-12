# DiscordLLM
 Simple LLM bridge between OpenAI-based APIs and Discord's bot API. Comes with built-in summarisation functionality to prevent loops.
 
 Usage: `python chatbot.py -c [Character file] -s [LLM API IP:Port]`

 Example character/format files are provided for an AI assistant prompted with Alpaca. See [this](https://github.com/oobabooga/text-generation-webui/blob/main/extensions/openai/typing.py) for a full list of LLM generation params.

 Requirements:
 - [discord.py](https://github.com/Rapptz/discord.py)
 - [emoji](https://github.com/carpedm20/emoji/)
 - [sentencepiece](https://github.com/google/sentencepiece)
 - Recommended for local LLM API: [text-generation-webui](https://github.com/oobabooga/text-generation-webui)
