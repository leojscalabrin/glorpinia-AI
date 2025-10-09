## AI Assistant with Twitch Integration

Ensure you have Python 3.8+ installed. Then, run the following command to install all dependencies:
pip install python-dotenv requests websocket-client langchain langchain-community langchain-huggingface faiss-cpu

for fine-tuning:
pip install transformers datasets peft trl accelerate bitsandbytes hf_xet --upgrade
pip install torch --index-url https://download.pytorch.org/whl/cu121

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

### Execution
python -m src.glorpinia_bot.main