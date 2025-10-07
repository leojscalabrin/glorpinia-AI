import websocket
import time
import logging
import signal
import sys
import re
from datetime import datetime
from .twitch_auth import TwitchAuth
from .hf_client import HFClient
from .memory_manager import MemoryManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

class TwitchIRC:
    def __init__(self):
        self.auth = TwitchAuth()
        self.hf_client = HFClient(
            hf_token=self.auth.hf_token,
            model_id=self.auth.model_id,
            personality_profile=self.auth.personality_profile
        )
        self.memory_mgr = MemoryManager()  # DB e embeddings

        # Inicializa cache para log anti-spam
        self.last_logged_content = {}  # Por canal

        self.ws = None
        self.running = False

        # Valida e renova token se necessário (usa auth)
        self.auth.validate_and_refresh_token()

        # Registra handler para shutdown
        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

    def _shutdown_handler(self, signum, frame):
        """Handler para shutdown com mensagem de despedida."""
        print("[INFO] Sinal de shutdown recebido. Enviando mensagem de despedida...")
        goodbye_msg = "Bedge"
        for channel in self.auth.channels:
            self.send_message(channel, goodbye_msg)
            time.sleep(1)  # Delay de 1s por canal pra envio seguro
        print("[INFO] Mensagem enviada. Encerrando...")
        if self.ws:
            self.ws.close()
        sys.exit(0)

    def send_message(self, channel, message):
        """Envia mensagem via WebSocket."""
        if self.ws and self.ws.sock and self.ws.sock.connected:
            full_msg = f"PRIVMSG #{channel} :{message}\r\n"
            self.ws.send(full_msg)
            print(f"[SEND] {channel}: {message}")
        else:
            print(f"[ERROR] WebSocket não conectado. Não foi possível enviar: {message}")

    def on_message(self, ws, message):
        """Handler de mensagens IRC (usa hf_client e memory_mgr)."""
        print(f"[IRC] {message.strip()}")
        if message.startswith("PING"):
            ws.send("PONG :tmi.twitch.tv\r\n")
            print("[PONG] Enviado para manter conexão viva.")
            return

        if "PRIVMSG" in message:
            # Extrai autor e conteúdo da mensagem IRC
            parts = message.split(":", 2)
            if len(parts) >= 3:
                author_part = parts[1].split("!")[0]
                content = parts[2].strip()
                channel = message.split("#")[1].split(" :")[0] if "#" in message else self.auth.channels[0]

                print(f"[CHAT] {author_part}: {content}")

                if author_part.lower() == self.auth.bot_nick.lower():
                    print(f"[DEBUG] Ignorando mensagem do próprio bot: {content}")
                    return

                content_lower = content.lower()

                # Log geral de todas mensagens (com anonimato, filtros e ignore bots)
                ignored_bots = {
                    'pokemoncommunitygame', 'fossabot', 'supibot', 
                    'streamelements', 'nightbot'
                }
                if author_part.lower() in ignored_bots:
                    print(f"[DEBUG] Ignorando bot conhecido: {author_part}")
                else:
                    # Filtros
                    if (len(content) < 3 or
                        not content or
                        content.startswith('!') or
                        re.search(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', content) or
                        content == self.last_logged_content.get(channel, '')
                    ):
                        print(f"[DEBUG] Mensagem filtrada (ruído): {content}")
                    else:
                        anon_user = f"User{hash(author_part) % 1000}"
                        
                        # Atualiza cache anti-spam
                        self.last_logged_content[channel] = content
                        
                        log_entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {channel} | {anon_user}: {content}\n"
                        log_filename = f"chat_log_{datetime.now().strftime('%Y%m%d')}.txt"
                        try:
                            with open(log_filename, "a", encoding="utf-8") as f:
                                f.write(log_entry)
                            print(f"[DEBUG] Log geral salvo: {anon_user}: {content[:20]}...")
                        except Exception as e:
                            print(f"[ERROR] Falha no log geral: {e}")

                if re.search(r'\bglorp\b', content_lower):
                    glorp_response = "glorp"
                    print(f"[DEBUG] 'glorp' (exato) detectado em {content}. Respondendo...")
                    self.send_message(channel, glorp_response)
                    return

                if "glorpinia" in content_lower:
                    query = content_lower.replace("glorpinia", "", 1).replace("@glorpinia", "", 1).strip()
                    print(f"[DEBUG] Menção a glorpinia detectada: {content}")
                    print(f"[DEBUG] Query extraída para a IA: {query}")

                    if query:
                        response = self.hf_client.get_response(
                            query=query,
                            channel=channel,
                            author=author_part,
                            memory_mgr=self.memory_mgr
                        )
                        print(f"[DEBUG] Resposta da IA: {response[:50]}...")
                        
                        # Divide resposta se > 200 chars e envia com delay de 5s
                        if len(response) > 200:
                            chunks = [response[i:i+200] for i in range(0, len(response), 200)]
                            for i, chunk in enumerate(chunks):
                                if i == 0:
                                    self.send_message(channel, f"@{author_part} {chunk}")
                                else:
                                    self.send_message(channel, chunk)
                                if i < len(chunks) - 1:
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
        ws.send(f"PASS oauth:{self.auth.access_token}\r\n")
        ws.send(f"NICK {self.auth.bot_nick}\r\n")
        print(f"[AUTH] Autenticando como {self.auth.bot_nick} com token...")
        for channel in self.auth.channels:
            ws.send(f"JOIN #{channel}\r\n")
            print(f"[JOIN] Tentando juntar ao canal: #{channel}")
        time.sleep(2)
        for channel in self.auth.channels:
            self.send_message(channel, "Wokege")

    def run(self):
        self.running = True
        try:
            websocket.enableTrace(True)
        except AttributeError:
            print("[WARNING] enableTrace não disponível; desabilitando trace.")
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