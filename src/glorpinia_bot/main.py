import websocket
import time
import logging
import signal
import sys
import re
import threading
from datetime import datetime
from collections import deque
from .twitch_auth import TwitchAuth
from .hf_client import HFClient
from .memory_manager import MemoryManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

class TwitchIRC:
    def __init__(self):
        # Instancia componentes modulares
        self.auth = TwitchAuth()  # Carrega env, tokens, profile, channels
        self.hf_client = HFClient(
            hf_token=self.auth.hf_token,
            model_id=self.auth.model_id,
            personality_profile=self.auth.personality_profile
        )
        self.memory_mgr = MemoryManager()  # DB e embeddings

        # Inicializa cache para log anti-spam
        self.last_logged_content = {}  # Por canal

        # Armazenamento de mensagens recentes por canal (deque com timestamp)
        self.recent_messages = {channel: deque(maxlen=100) for channel in self.auth.channels}  # Limite de 100 msgs por canal

        self.ws = None
        self.running = False

        # Valida e renova token se necessário (usa auth)
        self.auth.validate_and_refresh_token()

        # Registra handler para shutdown gracioso
        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

        # Inicia thread para timer de comentários periódicos
        # self.comment_timer_running = True
        # self.comment_thread = threading.Thread(target=self._periodic_comment_thread, daemon=True)
        # self.comment_thread.start()

    # def _periodic_comment_thread(self):
    #     """Thread em background: A cada 30 min, checa contexto e envia comentário se aplicável."""
    #     while self.comment_timer_running:
    #         time.sleep(1800)

    #         for channel in self.auth.channels:
    #             recent_msgs = self.recent_messages.get(channel, deque())
    #             now = time.time()
                
    #             recent_context = [msg for msg in recent_msgs if now - msg['timestamp'] <= 120]
                
    #             if len(recent_context) == 0:
    #                 print(f"[DEBUG] Nenhuma mensagem nas últimas 2 min em {channel}. Pulando comentário.")
    #                 continue
                
    #             # Cria contexto como string
    #             context_str = "\n".join([f"{msg['author']}: {msg['content']}" for msg in recent_context])
                
    #             # Gera comentário via HF (prompt temático)
    #             comment_query = f"Comente de forma natural e divertida sobre essa conversa recente no chat da live: {context_str[:500]}..."  # Limita pra tokens
    #             try:
    #                 comment = self.hf_client.get_response(
    #                     query=comment_query,
    #                     channel=channel,
    #                     author="system",  # Genérico, sem user específico
    #                     memory_mgr=self.memory_mgr
    #                 )
    #                 if len(comment) > 0 and len(comment) <= 200:  # Filtra respostas válidas/curtas
    #                     self.send_message(channel, comment)
    #                     print(f"[DEBUG] Comentário enviado em {channel}: {comment[:50]}...")
    #             except Exception as e:
    #                 print(f"[ERROR] Falha ao gerar comentário para {channel}: {e}")

    def _shutdown_handler(self, signum, frame):
        """Handler para shutdown gracioso com mensagem de despedida."""
        print("[INFO] Sinal de shutdown recebido. Enviando mensagem de despedida...")
        self.comment_timer_running = False  # Para o thread
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

                # NOVO: Adiciona TODAS mensagens recentes ao deque (pra contexto do timer)
                # Anonimiza pro deque também (pra privacidade)
                anon_author = f"User{hash(author_part) % 1000}"
                msg_data = {
                    'timestamp': time.time(),
                    'author': anon_author,
                    'content': content
                }
                if channel in self.recent_messages:
                    self.recent_messages[channel].append(msg_data)

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
                    # Filtros recomendados
                    if (len(content) < 3 or
                        not content or
                        content.startswith('!') or
                        re.search(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', content) or
                        content == self.last_logged_content.get(channel, '')
                    ):
                        print(f"[DEBUG] Mensagem filtrada (ruído): {content}")
                    else:
                        # Anonimiza user
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

                # Check para palavra EXATA "glorp"
                if re.search(r'\bglorp\b', content_lower):
                    glorp_response = "glorp"
                    print(f"[DEBUG] 'glorp' (exato) detectado em {content}. Respondendo...")
                    self.send_message(channel, glorp_response)
                    return

                # Check para menção "glorpinia" (queries IA)
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