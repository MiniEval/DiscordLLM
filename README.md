# DiscordLLM
 Simple LLM bridge between OpenAI-based APIs and Discord's bot API. Comes with built-in summarisation functionality to prevent loops.
 
 Usage: `python chatbot.py -c [Character config file] -s [LLM API IP:Port]`

 Example character/config files are provided for an AI assistant prompted with Alpaca. See [this](https://github.com/oobabooga/text-generation-webui/blob/main/extensions/openai/typing.py) for a full list of LLM generation params.

 A universal chat prompt is also included. Recommended for any LLM checkpoint that is trained or merged with an Alpaca fine-tune.

 Requirements:
 - [discord.py](https://github.com/Rapptz/discord.py)
 - [emoji](https://github.com/carpedm20/emoji/)
 - [sentencepiece](https://github.com/google/sentencepiece)
 - Recommended for local LLM API: [text-generation-webui](https://github.com/oobabooga/text-generation-webui)
