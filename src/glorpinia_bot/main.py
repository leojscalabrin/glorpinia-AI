import os
os.environ['GLORPINIA_ALLOW_NO_LANGCHAIN'] = '1'

import time
import logging
import signal
import sys
import re
import threading
from datetime import datetime
from collections import deque
from .twitch_auth import TwitchAuth
from .ollama_client import OllamaClient 
from .memory_manager import MemoryManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

class TwitchIRC:
    def __init__(self):
        # Instancia componentes modulares
        self.auth = TwitchAuth()  # Carrega env, tokens, profile, channels

        # Suporte ao modo capture-only (mantido)
        self.capture_only = os.environ.get('GLORPINIA_CAPTURE_ONLY') == '1'

        # Logica de skip_model_load e HFClient/MemoryManager atualizada para Ollama
        if self.capture_only:
            print('[INFO] Running in capture-only mode; OllamaClient and MemoryManager will not be instantiated.')
            self.hf_client = None # Mantido 'hf_client' como nome do atributo para simplificar as chamadas subsequentes
            self.memory_mgr = None
        else:
            # Instancia componentes pesados
            # NOVO: Importa o cliente Ollama
            from .ollama_client import OllamaClient 
            from .memory_manager import MemoryManager

            # NOVO: Instancia o OllamaClient (nao precisa de token ou model_id HF)
            self.hf_client = OllamaClient(
                personality_profile=self.auth.personality_profile
            )
            self.memory_mgr = MemoryManager()  # DB e embeddings

        # Inicializa cache para log anti-spam
        self.last_logged_content = {}  # Por canal
        self.processed_message_ids = deque(maxlen=500) # Armazena IDs de mensagens processadas para deduplicação

        # Armazenamento de mensagens recentes por canal (deque com timestamp)
        self.recent_messages = {channel: deque(maxlen=100) for channel in self.auth.channels}  # Limite de 100 msgs por canal

        # Estados das funcionalidades
        self.chat_enabled = True  # Para respostas a menções
        self.listen_enabled = False  # Para transcrição de áudio (OFF por default)
        self.comment_enabled = False  # Para comentários periódicos (OFF por default)

        # Lista de admins
        self.admin_nicks = ["felinomascarado"]

        self.ws = None
        self.running = False

        # Valida e renova token se necessario (usa auth)
        self.auth.validate_and_refresh_token()

        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

    # Inicia thread para timer de comentarios periodicos (se comment_enabled)
        self.comment_timer_running = True
        self.comment_thread = threading.Thread(target=self._periodic_comment_thread, daemon=True)
        self.comment_thread.start()

        # Inicia thread para transcricao de audio se listen_enabled
        self.audio_comment_running = True
        self.audio_comment_thread = threading.Thread(target=self._periodic_audio_comment_thread, daemon=True)
        self.audio_comment_thread.start()

    def _periodic_comment_thread(self):
        """Thread em background: A cada 30 min, checa contexto e envia comentario se aplicavel (se comment_enabled)."""
        while self.comment_timer_running:
            if not self.comment_enabled:
                time.sleep(10)  # Espera curta se desabilitado, checa periodicamente
                continue
            time.sleep(1800)

            for channel in self.auth.channels:
                recent_msgs = self.recent_messages.get(channel, deque())
                now = time.time()
                
                # Filtra msgs das ultimas 2 min
                recent_context = [msg for msg in recent_msgs if now - msg['timestamp'] <= 120]
                
                if len(recent_context) == 0:
                    print(f"[DEBUG] Nenhuma mensagem nas ultimas 2 min em {channel}. Pulando comentario.")
                    continue  # Ignora se vazio
                
                # Cria contexto como string
                context_str = "\n".join([f"{msg['author']}: {msg['content']}" for msg in recent_context])
                
                # Gera comentario via cliente LLM
                comment_query = f"Comente de forma natural e divertida sobre essa conversa recente no chat da live: {context_str[:500]}..."
                try:
                    comment = self.hf_client.get_response( # Chamada mantida
                        query=comment_query,
                        channel=channel,
                        author="system",  # Generico, sem user especifico
                        memory_mgr=self.memory_mgr
                    )
                    if len(comment) > 0 and len(comment) <= 200:  # Filtra respostas validas/curtas
                        self.send_message(channel, comment)
                        print(f"[DEBUG] Comentario enviado em {channel}: {comment[:50]}...")
                except Exception as e:
                    print(f"[ERROR] Falha ao gerar comentario para {channel}: {e}")

    def _periodic_audio_comment_thread(self):
        """Thread em background: A cada 30 min, transcreve audio e comenta se relevante (se listen_enabled)."""
        while self.audio_comment_running:
            if not self.listen_enabled:
                time.sleep(10)  # Espera curta se desabilitado, checa periodicamente
                continue
            time.sleep(1800)

            for channel in self.auth.channels:
                # Captura audio da stream por 60s
                transcription = self._transcribe_stream(channel, duration=60)
                
                if not transcription or len(transcription) < 10:  # Ignora se vazio ou curto
                    print(f"[DEBUG] Transcricao vazia ou curta em {channel}. Pulando comentario.")
                    continue
                
                # Gera comentario via cliente LLM com contexto de audio
                comment_query = f"Comente de forma natural e divertida sobre o que foi dito na live: {transcription[:500]}..."  # Limita pra tokens
                try:
                    comment = self.hf_client.get_response(
                        query=comment_query,
                        channel=channel,
                        author="system",  # Generico
                        memory_mgr=self.memory_mgr
                    )
                    if 0 < len(comment) <= 200:  # Filtra validas/curtas
                        self.send_message(channel, comment)
                        print(f"[DEBUG] Comentario de audio enviado em {channel}: {comment[:50]}...")
                except Exception as e:
                    print(f"[ERROR] Falha ao gerar comentario de audio para {channel}: {e}")

    def _shutdown_handler(self, signum, frame):
        """Handler para shutdown gracioso com mensagem de despedida."""
        print("[INFO] Sinal de shutdown recebido. Enviando mensagem de despedida...")
        self.comment_timer_running = False  # Para o thread de comentarios
        self.audio_comment_running = False  # Para o thread de audio
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
            print(f"[ERROR] WebSocket nao conectado. Nao foi possivel enviar: {message}")

    def on_message(self, ws, message):
        """Handler de mensagens IRC (usa o cliente LLM)."""
        print(f"[IRC] RAW: {message.strip()}")
        if message.startswith("PING"):
            ws.send("PONG :tmi.twitch.tv\r\n")
            print("[PONG] Enviado para manter conexao viva.")
            return

        if "PRIVMSG" in message:

            # Extrai autor e conteudo da mensagem IRC
            parts = message.split(":", 2)
            if len(parts) < 3:
                print(f"[DEBUG] Mensagem PRIVMSG invalida: {message}")
                return
            author_part = parts[1].split("!")[0]
            content = parts[2].strip()
            channel = message.split("#")[1].split(" :")[0] if "#" in message else self.auth.channels[0]

            print(f"[CHAT] Parsed - author={author_part}, channel={channel}, content={content}")
            # Extra debug: recent messages snapshot
            try:
                print(f"[DEBUG] recent_messages_count={len(self.recent_messages.get(channel, []))}")
            except Exception:
                pass
            content_lower = content.lower()
            print(f"[DEBUG] content_lower='{content_lower}'")

            # Adiciona TODAS mensagens recentes ao deque (pra contexto do timer)
            anon_author = f"User{hash(author_part) % 1000}"
            msg_data = {
                'timestamp': time.time(),
                'author': anon_author,
                'content': content
            }
            if channel in self.recent_messages:
                self.recent_messages[channel].append(msg_data)

            # SIMULACAO DE MENSAGEM DUPLICADA PARA TESTE
            if content == "!test_duplicate":
                print("[DEBUG] Simulando mensagem duplicada para teste...")
                # Simula o recebimento da mesma mensagem novamente
                self.on_message(ws, message)
                return

            # Capture-only mode: append sanitized record to training_data.jsonl and skip heavy model calls
            capture_only = os.environ.get('GLORPINIA_CAPTURE_ONLY') == '1'
            if capture_only:
                try:
                    self._append_training_record(channel, author_part, content, None)
                except Exception as e:
                    print(f"[ERROR] Falha ao salvar registro de captura: {e}")
                return

            if author_part.lower() == self.auth.bot_nick.lower():
                print(f"[DEBUG] Ignorando mensagem do proprio bot: {content}")
                return

            unique_message_identifier = f"{author_part}-{channel}-{content}"
            message_hash = hash(unique_message_identifier)

            if message_hash in self.processed_message_ids:
                print(f"[INFO] Mensagem duplicada detectada e ignorada: {content}")
                return
            self.processed_message_ids.append(message_hash)
            print(f"[DEBUG] Mensagem processada e ID adicionado ao cache: {message_hash}")

            # Processamento de comandos de admin (sempre ativo)
            if author_part.lower() in self.admin_nicks and content.startswith("!glorpinia"):
                self.handle_admin_command(content, channel)
                return

            # Processamento de chat geral (respostas a mencoes)
            if self.chat_enabled and self.auth.bot_nick.lower() in content.lower():
                print(f"[DEBUG] Bot mencionado por {author_part}. Gerando resposta...")
                try:
                    response = self.hf_client.get_response(content, channel, author_part, self.memory_mgr) # Chamada mantida
                    if response:
                        self.send_message(channel, response)
                except Exception as e:
                    print(f"[ERROR] Falha ao gerar resposta: {e}")

    def _append_training_record(self, channel, author, user_message, bot_response):
        """Salva um registro de interacao em formato JSONL para futuro treinamento do modelo."""
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "channel": channel,
            "author": author,
            "user_message": user_message,
            "bot_response": bot_response
        }
        try:
            with open("training_data.jsonl", "a", encoding="utf-8") as f:
                f.write(f"{str(record)}\n")
            
            # Log com menos frequencia para evitar spam
            last_log_time = self.last_logged_content.get(channel, 0)
            if time.time() - last_log_time > 60:
                print(f"[INFO] Registro de treinamento salvo para a mensagem: {user_message[:30]}...")
                self.last_logged_content[channel] = time.time()
        except Exception as e:
            print(f"[ERROR] Falha ao escrever no arquivo de treinamento: {e}")

    def handle_admin_command(self, command, channel):
        """Processa comandos de admin (ex: !glorpinia chat on/off)."""
        parts = command.split()
        if len(parts) < 3:
            self.send_message(channel, "Comando invalido. Use: !glorpinia <feature> <on|off>")
            return

        feature = parts[1].lower()
        state = parts[2].lower()

        if feature == "chat":
            self.chat_enabled = (state == "on")
            status = "ATIVADO" if self.chat_enabled else "DESATIVADO"
            self.send_message(channel, f"O modo CHAT foi {status}.")
        elif feature == "listen":
            self.listen_enabled = (state == "on")
            status = "ATIVADO" if self.listen_enabled else "DESATIVADO"
            self.send_message(channel, f"O modo LISTEN foi {status}.")
        elif feature == "comment":
            self.comment_enabled = (state == "on")
            status = "ATIVADO" if self.comment_enabled else "DESATIVADO"
            self.send_message(channel, f"O modo COMMENT foi {status}.")
        else:
            self.send_message(channel, f"Funcionalidade desconhecida: {feature}")

    def run(self):
        """Inicia a conexao WebSocket e o loop de mensagens."""
        import websocket

        self.running = True
        while self.running:
            try:
                self.ws = websocket.WebSocketApp(
                    "wss://irc-ws.chat.twitch.tv:443",
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                    on_open=self.on_open
                )
                self.ws.run_forever()
            except Exception as e:
                print(f"[ERROR] WebSocket encontrou um erro: {e}")
                print("[INFO] Tentando reconectar em 10 segundos...")
                time.sleep(10)

    def on_open(self, ws):
        """Handler para quando a conexao WebSocket é aberta."""
        token_for_send = self.auth.access_token
        ws.send(f"PASS oauth:{token_for_send}\r\n")
        ws.send(f"NICK {self.auth.bot_nick}\r\n")
        print(f"[AUTH] Autenticando como {self.auth.bot_nick} com token...")
        for channel in self.auth.channels:
            ws.send(f"JOIN #{channel}\r\n")
            print(f"[JOIN] Tentando juntar ao canal: #{channel}")
            time.sleep(2) # Adiciona um delay de 2s entre joins
            self.send_message(channel, "Wokege")

    def on_error(self, ws, error):
        """Handler para erros do WebSocket."""
        print(f"[ERROR] WebSocket error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        """Handler para quando a conexao WebSocket é fechada."""
        print(f"[INFO] Conexao WebSocket fechada. Codigo: {close_status_code}, Msg: {close_msg}")


if __name__ == "__main__":
    bot = TwitchIRC()
    bot.run()