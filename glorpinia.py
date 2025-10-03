from dotenv import load_dotenv
import os
import requests
import websocket
import threading
import time
import logging
import re  # Para parsing simples de logs

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

class TwitchIRC:
    def __init__(self):
        self.access_token = os.getenv("TWITCH_TOKEN").replace("oauth:", "")  # Remove prefixo se presente
        self.refresh_token = os.getenv("TWITCH_REFRESH_TOKEN")
        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")
        self.bot_nick = os.getenv("TWITCH_BOT_NICK")
        self.hf_token = os.getenv("HF_TOKEN")
        self.model_id = os.getenv("HF_MODEL_ID")

        channels_str = os.getenv("TWITCH_CHANNELS")
        if channels_str:
            self.channels = [c.strip() for c in channels_str.split(",") if c.strip()]
        else:
            raise ValueError("Missing TWITCH_CHANNELS environment variable in .env file")

        if not all([self.access_token, self.bot_nick, self.hf_token, self.model_id]):
            raise ValueError("Missing required environment variables in .env file")

        if not all([self.client_id, self.client_secret, self.refresh_token]):
            print("[WARNING] Client ID, Secret ou Refresh Token ausentes. Renovação automática pode falhar.")

        # Memória: Histórico das últimas 10 trocas (usuário + resposta)
        self.conversation_history = []
        self.max_history = 10

        # Carrega o perfil de personalidade de um arquivo separado
        self.personality_profile = self.load_personality_profile()

        self.ws = None
        self.running = False

        # Valida e renova token se necessário antes de iniciar
        self.validate_and_refresh_token()

    def load_personality_profile(self):
        """Carrega o perfil de personalidade de um arquivo TXT separado."""
        try:
            with open("glorpinia_profile.txt", "r", encoding="utf-8") as f:
                profile = f.read().strip()
            print("[INFO] Perfil de personalidade carregado de glorpinia_profile.txt.")
            return profile
        except FileNotFoundError:
            print("[WARNING] Arquivo glorpinia_profile.txt não encontrado. Usando perfil vazio.")
            return ""  # Perfil vazio se o arquivo não existir

    def validate_and_refresh_token(self):
        """Valida o access token e renova se inválido ou expirado."""
        # Valida o token atual
        if not self.validate_token():
            print("[INFO] Token inválido ou expirado. Renovando...")
            if self.refresh_token:
                self.refresh_token()
            else:
                raise ValueError("Refresh token ausente no .env. Gere um novo token manualmente.")

    def validate_token(self):
        """Valida o access token via endpoint /validate."""
        url = "https://id.twitch.tv/oauth2/validate"
        headers = {"Authorization": f"OAuth {self.access_token}"}
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                print(f"[INFO] Token válido. Usuário: {data.get('login')}, Escopos: {data.get('scopes')}")
                return True
            else:
                print(f"[ERROR] Validação falhou: {response.status_code} - {response.text}")
                return False
        except requests.RequestException as e:
            print(f"[ERROR] Erro na validação: {e}")
            return False

    def refresh_token(self):
        """Renova o access token usando o refresh token."""
        if not self.refresh_token:
            print("[ERROR] Sem refresh_token no .env. Gere um novo.")
            return None

        url = "https://id.twitch.tv/oauth2/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        try:
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                new_tokens = response.json()
                self.access_token = new_tokens["access_token"]  # Sem oauth:
                self.refresh_token = new_tokens["refresh_token"]  # Atualiza o refresh também
                print(f"[INFO] Token renovado! Expira em {new_tokens['expires_in']}s. Novo token: {self.access_token[:10]}...")
                # Opcional: Salve no .env (requer cuidado com segurança)
                # with open('.env', 'a') as f: f.write(f"\nTWITCH_TOKEN=oauth:{self.access_token}\nTWITCH_REFRESH_TOKEN={self.refresh_token}")
                return self.access_token
            else:
                print(f"[ERROR] Falha na renovação: {response.status_code} - {response.text}")
                return None
        except requests.RequestException as e:
            print(f"[ERROR] Erro na renovação: {e}")
            return None

    def get_hf_response(self, query):
        API_URL = "https://router.huggingface.co/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.hf_token}",
            "Content-Type": "application/json"
        }

        # Constrói histórico para memória (últimas trocas)
        history_str = ""
        if self.conversation_history:
            history_str = "Histórico recente:\n" + "\n".join(self.conversation_history[-self.max_history:]) + "\n"

        # Prompt completo: Perfil de personalidade + histórico + query
        system_prompt = f"""Você é Glorpinia, uma garota gato alienígena da lua. Siga rigorosamente o perfil de personalidade abaixo para todas as respostas. Responda preferencialmente em português a não ser que o usuário interaja em inglês.

Perfil de Personalidade:
{self.personality_profile}

{history_str}Agora responda à query do usuário de forma consistente com o histórico."""

        user_message = f"{system_prompt} Query: {query}"
        messages = [{"role": "user", "content": user_message}]

        payload = {
            "model": self.model_id,
            "messages": messages,
            "max_tokens": 100,
            "temperature": 0.7,
            "stream": False
        }
        print(f'[DEBUG] Enviando para HF API (com memória e treinamento): {user_message[:100]}...')

        # Retry simples para erros transitórios (até 3 tentativas)
        for attempt in range(3):
            try:
                response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                result = response.json()
                print(f"[DEBUG] Resposta bruta da HF API: {result}")
                
                if 'choices' in result and len(result['choices']) > 0:
                    generated = result['choices'][0]['message']['content'].strip()
                    if generated:
                        # Adiciona à memória: query do usuário + resposta
                        self.conversation_history.append(f"Usuário: {query} | Glorpinia: {generated}")
                        # Limpa histórico antigo se exceder limite
                        if len(self.conversation_history) > self.max_history:
                            self.conversation_history = self.conversation_history[-self.max_history:]
                        return generated
                    else:
                        print("[DEBUG] Texto gerado vazio – fallback loading")
                        return "glorp carregando cérebro . exe"
                else:
                    print("[DEBUG] Resultado inválido ou vazio – fallback loading")
                    return "glorp carregando cérebro . exe"
                    
            except requests.RequestException as e:
                print(f"[ERROR] Erro ao chamar HF API (tentativa {attempt + 1}): {e}")
                if attempt < 2:  # Espera 2s antes de retry
                    time.sleep(2)
                    continue
                else:
                    print("[DEBUG] Todas tentativas falharam – fallback erm")
                    return "glorp sinal com a nave-mãe perdido"  # Fallback temático e fofo

        return "glorp deu ruim"  # Fallback final

    def send_message(self, channel, message):
        if self.ws and self.ws.sock and self.ws.sock.connected:
            full_msg = f"PRIVMSG #{channel} :{message}\r\n"
            self.ws.send(full_msg)
            print(f"[SEND] {channel}: {message}")
        else:
            print(f"[ERROR] WebSocket não conectado. Não foi possível enviar: {message}")

    def on_message(self, ws, message):
        print(f"[IRC] {message.strip()}")
        if message.startswith("PING"):
            ws.send("PONG :tmi.twitch.tv\r\n")
            print("[PONG] Enviado para manter conexão viva.")
            return

        if "PRIVMSG" in message and "glorpinia" in message.lower():
            # Extrai autor e conteúdo da mensagem IRC
            parts = message.split(":", 2)
            if len(parts) >= 3:
                author_part = parts[1].split("!")[0]
                content = parts[2].strip()
                channel = message.split("#")[1].split(" :")[0] if "#" in message else self.channels[0]

                print(f"[CHAT] {author_part}: {content}")

                if author_part.lower() == self.bot_nick.lower():
                    print(f"[DEBUG] Ignorando mensagem do próprio bot: {content}")
                    return

                content_lower = content.lower()
                query = content_lower.replace("glorpinia", "", 1).replace("@glorpinia", "", 1).strip()
                print(f"[DEBUG] Menção a glorpinia detectada: {content}")
                print(f"[DEBUG] Query extraída para a IA: {query}")

                if query:
                    response = self.get_hf_response(query)
                    print(f"[DEBUG] Resposta da IA: {response[:50]}...")
                    
                    # Divide resposta se > 200 chars e envia com delay de 6s
                    if len(response) > 200:
                        chunks = [response[i:i+200] for i in range(0, len(response), 200)]
                        for i, chunk in enumerate(chunks):
                            if i == 0:
                                self.send_message(channel, f"@{author_part} {chunk}")
                            else:
                                self.send_message(channel, chunk)  # Sem @ nas continuações
                            if i < len(chunks) - 1:  # Delay só entre chunks
                                time.sleep(5)
                    else:
                        self.send_message(channel, f"@{author_part} {response}")
                else:
                    print("[DEBUG] Query vazia após menção. Nenhuma resposta da IA.")

    def on_error(self, ws, error):
        print(f"[ERROR] WebSocket error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print(f"[CLOSE] Conexão fechada: {close_status_code} - {close_msg}")
        self.running = False

    def on_open(self, ws):
        print("[OPEN] Conexão WebSocket aberta!")
        # Autentica com o token atual (pode ser renovado)
        ws.send(f"PASS oauth:{self.access_token}\r\n")
        ws.send(f"NICK {self.bot_nick}\r\n")
        print(f"[AUTH] Autenticando como {self.bot_nick} com token...")
        # Junta aos canais
        for channel in self.channels:
            ws.send(f"JOIN #{channel}\r\n")
            print(f"[JOIN] Tentando juntar ao canal: #{channel}")
        # Envia mensagem inicial após 2s
        time.sleep(2)
        for channel in self.channels:
            self.send_message(channel, "Wokege")

    def run(self):
        self.running = True
        websocket.enableTrace(True)  # Para depuração detalhada (opcional, remova se quiser menos logs)
        self.ws = websocket.WebSocketApp(
            "wss://irc-ws.chat.twitch.tv:443",
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        self.ws.run_forever()

if __name__ == "__main__":
    bot = TwitchIRC()
    bot.run()