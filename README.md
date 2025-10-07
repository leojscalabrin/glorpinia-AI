Ensure you have Python 3.8+ installed. Then, run the following command to install all dependencies:
pip install python-dotenv requests websocket-client langchain langchain-community langchain-huggingface faiss-cpu

para fine-tuning:
pip install transformers peft trl datasets accelerate bitsandbytes torch
pip install torch --index-url https://download.pytorch.org/whl/cu121

### Environment Setup
Create a `.env` file in the project root with the following variables:
TWITCH_TOKEN=oauth:your_token_here
TWITCH_BOT_NICK=glorpinia
TWITCH_CHANNEL=your_channel_name
TWITCH_CLIENT_ID=your_client_id_here
TWITCH_CLIENT_SECRET=your_client_secret_here
REFRESH_TOKEN=your_refresh_token_here
TWITCH_BOT_ID=your_bot_user_id_here
HF_TOKEN=hf_your_hf_token_here
HF_MODEL_ID=your_model_of_choice_here

Obtain tokens from:
- Twitch: [Twitch Token Generator](https://twitchtokengenerator.com) (scopes: `chat:read`, `chat:edit`)
- Twitch Client ID/Secret: [Twitch Developer Console](https://dev.twitch.tv/console)
- Hugging Face: [Hugging Face Tokens](https://huggingface.co/settings/tokens)
