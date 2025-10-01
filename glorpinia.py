from dotenv import load_dotenv
import os
import requests
from twitchio.ext import commands
import asyncio
import logging

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")


class TwitchBot(commands.Bot):
    def __init__(self):
        self.token = os.getenv('TWITCH_TOKEN')
        self.client_id = os.getenv('TWITCH_CLIENT_ID')
        self.client_secret = os.getenv('TWITCH_CLIENT_SECRET')
        self.bot_nick = os.getenv('TWITCH_BOT_NICK')
        self.hf_token = os.getenv('HF_TOKEN')
        self.model_id = os.getenv('HF_MODEL_ID')
        channels_str = os.getenv("TWITCH_CHANNELS")
        if channels_str:
            channels = [c.strip() for c in channels_str.split(",") if c.strip()]
        else:
            raise ValueError("Missing TWITCH_CHANNELS environment variable in .env file")

        if not all([self.token, self.client_id, self.client_secret, self.bot_nick, self.hf_token, self.model_id]):
            raise ValueError("Missing required environment variables in .env file")
        bot_id = os.getenv("TWITCH_BOT_ID")
        if not bot_id:
            raise ValueError("TWITCH_BOT_ID must be provided in the .env file. Obtain it from a Twitch User ID Finder.")
        super().__init__(
            token=self.token,
            client_id=self.client_id,
            client_secret=self.client_secret,
            nick=self.bot_nick,
            bot_id=bot_id,
            prefix="!",
            initial_channels=channels,

        )

    async def event_ready(self):
        print("Bot is ready!")
        await asyncio.sleep(2)
        print("Bot está pronto para interagir no chat via @glorpinia ou glorpinia!")

    async def event_message(self, message):
        print(f"[CHAT] {message.author.name}: {message.content}")

        if message.author and message.author.name.lower() == self.nick.lower():
            print(f"[DEBUG] Ignorando mensagem do próprio bot: {message.content}")
            return

        content_lower = message.content.lower()
        if 'glorpinia' in content_lower:
            print(f"[DEBUG] Menção a glorpinia detectada: {message.content}")
            query = content_lower.replace('glorpinia', '', 1).replace('@glorpinia', '', 1).strip()
            print(f"[DEBUG] Query extraída para a IA: {query}")
            if query:
                response = self.get_hf_response(query)
                print(f"[DEBUG] Resposta da IA: {response[:50]}...")
                await message.channel.send(f"@{message.author.name} {response[:200]}...")
            else:
                print("[DEBUG] Query vazia após menção. Nenhuma resposta da IA.")

    def get_hf_response(self, query):
        API_URL = f"https://api-inference.huggingface.co/models/{self.model_id}"
        headers = {"Authorization": f"Bearer {self.hf_token}"}

        payload = {
            "inputs": f"<s>[INST] You are an alien catgirl from the moon, your main goal is entertainment, answer shortly and with quirky messages: {query} [/INST]",
            "parameters": {"max_new_tokens": 100, "temperature": 0.7}
        }
        print(f'[DEBUG] Enviando para HF API: {payload["inputs"][:100]}...')

        try:
            response = requests.post(API_URL, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            print(f"[DEBUG] Resposta bruta da HF API: {result}")
            return result[0]["generated_text"].split("[/INST]")[-1].strip() if result else "glorp loading"
        except requests.RequestException as e:
            print(f"[ERROR] Erro ao chamar HF API: {e}")
            return "glorp erm"

if __name__ == "__main__":
    bot = TwitchBot()
    bot.run(with_adapter=False)