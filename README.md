## Glorpinia AI Twitch Bot

AI-powered Twitch chat bot companion using Google Gemini API, designed for 24/7 server deployment.

### Environment Setup
Ensure you have Python 3.8+ installed. Check requirements.txt for all dependencies

Create a `.env` file in the project root with the following variables:

-Google API Key (from Google AI Studio)
GOOGLE_API_KEY=your_google_api_key

-Twitch Bot Credentials
TWITCH_BOT_NICK=your_bot_username
TWITCH_CLIENT_ID=your_client_id
TWITCH_CLIENT_SECRET=your_client_secret
TWITCH_ACCESS_TOKEN=oauth:your_access_token
TWITCH_REFRESH_TOKEN=your_refresh_token

-Bot Configuration
TWITCH_CHANNELS=channel_to_join

Obtain tokens from:
- Twitch: [Twitch Token Generator](https://twitchtokengenerator.com) (scopes: `chat:read`, `chat:edit`)
- Twitch Client ID/Secret: [Twitch Developer Console](https://dev.twitch.tv/console)

### Features
-Gemini-Powered CHAT: Responds to @bot_nick mentions using a defined personality (glorpinia_profile.txt) and conversation history (RAG).
-Proactive COMMENTARY: Periodically comments on the last 2 minutes of chat conversation (Default: Off).
-Audio LISTEN (Stub): A non-functional stub for listening to stream audio. Requires implementation of an STT service to work (Default: Off).

#### Admin Commands
Admin commands are restricted to users listed in the ADMIN_NICKS environment variable.

!glorp <feature> <on|off>: Toggles features. Features: chat, listen, comment.
!glorp check: Checks the status (On/Off) of all modules.
!glorp commands: Lists available commands.

### Local Execution

1. Create venv:
python3 -m venv venv
source venv/bin/activate

2. Install dependencies:
pip install -r requirements.txt

3. Run (as a module):
python -m src.glorpinia_bot.main

### Production Deployment (Linux VM)
This bot is designed to run as a systemd service on a Linux server.

1. Clone Project:
Place the project in /opt/glorpinia-AI.

2. Setup Environment:
Create the venv and install dependencies as shown in "Local Execution".
Create your .env and glorpinia_profile.txt files inside /opt/glorpinia-AI.
Set correct ownership: sudo chown -R your_user:your_user /opt/glorpinia-AI

3. Create Service File:
sudo nano /etc/systemd/system/glorpinia.service

Paste the following configuration (adjust User as needed):
[Unit]
Description=Glorpinia Twitch Bot
After=network.target

[Service]
User=user
WorkingDirectory=/opt/glorpinia-AI
Environment="PYTHONPATH=/opt/glorpinia-AI/src"
ExecStart=/opt/glorpinia-AI/venv/bin/python3 -m glorpinia_bot.main
Restart=always

[Install]
WantedBy=multi-user.target

4. Enable & Start Service:
sudo systemctl daemon-reload
sudo systemctl enable --now glorpinia.service

Service Management
-Check Status & Logs: sudo systemctl status glorpinia.service
-Stop Bot: sudo systemctl stop glorpinia.service
-Start Bot: sudo systemctl start glorpinia.service
-Restart: sudo systemctl restart glorpinia.service