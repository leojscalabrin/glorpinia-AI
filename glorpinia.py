import os
import requests
from dotenv import load_dotenv
from twitchio.ext import commands
import json

load_dotenv()

class TwitchBot(commands.Bot):
    def __init__(self):
        self.token = os.getenv('TWITCH_TOKEN')
        self.client_id = os.getenv('TWITCH_CLIENT_ID')
        self.client_secret = os.getenv('TWITCH_CLIENT_SECRET')
        self.bot_nick = os.getenv('TWITCH_BOT_NICK')
        self.bot_id = os.getenv('TWITCH_BOT_ID')
        self.hf_token = os.getenv('HF_TOKEN')
        self.model_id = os.getenv('HF_MODEL_ID')

        if not self.bot_id:
            self.bot_id = self.get_twitch_user_id(self.bot_nick)

        super().__init__(
            token=self.token,
            client_id=self.client_id,
            client_secret=self.client_secret,
            bot_id=self.bot_id,
            nick=self.bot_nick,
            prefix="!",
            initial_channels=[os.getenv('TWITCH_CHANNEL')]
        )

    def get_twitch_user_id(self, username):
        """Fetch Twitch User ID for the given username using Twitch API."""
        url = f"https://api.twitch.tv/helix/users?login={username}"
        headers = {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self.token.replace('oauth:', '')}"
        }
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            if data['data']:
                return data['data'][0]['id']
            else:
                raise ValueError(f"No user found for username: {username}")
        except requests.RequestException as e:
            print(f"Error fetching bot_id: {e}")
            return None

    async def event_ready(self):
        print(f'glorp SIGNAL RECEIVED | Connected as {self.nick}')

    async def event_message(self, message):

        if message.author and message.author.name.lower() == self.nick.lower():
            return

        if '@glorpinia' in message.content.lower():
            query = message.content.replace('@glorpinia', '', 1).strip()
            if query:
                response = self.get_hf_response(query)
                await message.channel.send(f"@{message.author.name} {response[:200]}...")

    def get_hf_response(self, query):
        API_URL = f"https://api-inference.huggingface.co/models/{self.model_id}"
        headers = {"Authorization": f"Bearer {self.hf_token}"}

        payload = {
            "inputs": f"<s>[INST] You are an alien catgirl from another galaxy which happens to capture signals from earth and answers shortly and with quirky messages on Twitch chat, your main goal is entertainment: {query} [/INST]",
            "parameters": {"max_new_tokens": 100, "temperature": 0.7}
        }

        try:
            response = requests.post(API_URL, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            return result[0]['generated_text'].split('[/INST]')[-1].strip() if result else "glorp loading"
        except requests.RequestException as e:
            print(f"Error calling HF API: {e}")
            return "glorp erm"

if __name__ == "__main__":
    bot = TwitchBot()
    bot.run()