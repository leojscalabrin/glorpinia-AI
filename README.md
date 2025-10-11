## AI Assistant with Twitch Integration

Ensure you have Python 3.8+ installed. Check requirements.txt for all dependencies

### Environment Setup
Create a `.env` file in the project root with the following variables:

TWITCH_BOT_NICK=twitch_user_nick
TWITCH_CLIENT_ID=your_client_ID
TWITCH_CLIENT_SECRET=your_client_Secret
TWITCH_BOT_ID=twitch_user_ID
TWITCH_CHANNELS=your_channel
HF_TOKEN_READ=hf_read_token
HF_MODEL_ID=your_model
TWITCH_TOKEN=oauth:your_token_here
TWITCH_REFRESH_TOKEN=your_refresh_token

Obtain tokens from:
- Twitch: [Twitch Token Generator](https://twitchtokengenerator.com) (scopes: `chat:read`, `chat:edit`)
- Twitch Client ID/Secret: [Twitch Developer Console](https://dev.twitch.tv/console)
- Hugging Face: [Hugging Face Tokens](https://huggingface.co/settings/tokens)

### Features
CHAT - She will answer on chat when mentioned based on her behavior (all interactions are saved for fine tuning)
COMMENTS - Every 30 minutes she will make a commentary on the last messages of the chat (about 2 mins of chat) (default: off)
LISTEN - Listens to the stream every 30 minutes and makes a commentary on chat (default: off) *NEEDS GPU

Use !toggle [chat|listen|comment] [on/off] to toggle commands. (admin only)
Use !check to check the commands status


### Execution
python -m src.glorpinia_bot.main