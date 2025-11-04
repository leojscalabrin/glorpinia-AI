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
from .gemini_client import GeminiClient
from .memory_manager import MemoryManager
import subprocess
from google.cloud import speech

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

class TwitchIRC:
    def __init__(self):
        # Instancia componentes modulares
        self.auth = TwitchAuth()  # Carrega env, tokens, profile, channels

        self.capture_only = os.environ.get('GLORPINIA_CAPTURE_ONLY') == '1'

        if self.capture_only:
            print('[INFO] Running in capture-only mode; OllamaClient and MemoryManager will not be instantiated.')
            self.gemini_client = None
            self.memory_mgr = None
        else:
            # Instancia componentes pesados
            from .memory_manager import MemoryManager

            self.gemini_client = GeminiClient(
                personality_profile=self.auth.personality_profile
            )
            self.memory_mgr = MemoryManager()

        # Inicializa cache para log anti-spam
        self.last_logged_content = {}  # Por canal
        self.processed_message_ids = deque(maxlen=500) # Armazena IDs de mensagens processadas para deduplicação

        # Armazenamento de mensagens recentes por canal (deque com timestamp)
        self.recent_messages = {channel: deque(maxlen=100) for channel in self.auth.channels}  # Limite de 100 msgs por canal

        # Estados das funcionalidades
        self.chat_enabled = True  # Para respostas a menções
        self.listen_enabled = False  # Para transcrição de áudio (OFF por default)
        self.comment_enabled = False  # Para comentários periódicos (OFF por default)

        # Adiciona timestamps para controlar os timers sem block
        self.last_comment_time = 0
        self.last_audio_comment_time = 0
        self.loop_sleep_interval = 10 # Intervalo de verificação (10 segundos)

        admin_nicks_str = os.getenv("ADMIN_NICKS") 
        self.admin_nicks = [nick.strip().lower() for nick in admin_nicks_str.split(',')]
        print(f"[AUTH] Admins carregados: {self.admin_nicks}")

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
        self.last_comment_time = time.time() # Inicializa o timer

        while self.comment_timer_running:
            time.sleep(self.loop_sleep_interval) 
            
            if not self.comment_enabled:
                continue 

            now = time.time()
            if now - self.last_comment_time < 1800:
                continue
            
            self.last_comment_time = now 

            for channel in self.auth.channels:
                recent_msgs = self.recent_messages.get(channel, deque())
                
                recent_context = [msg for msg in recent_msgs if now - msg['timestamp'] <= 120]
                
                if len(recent_context) == 0:
                    print(f"[DEBUG] Nenhuma mensagem nas ultimas 2 min em {channel}. Pulando comentario.")
                    continue  
                
                context_str = "\n".join([f"{msg['author']}: {msg['content']}" for msg in recent_context])
                
                comment_query = f"Comente de forma natural e divertida sobre essa conversa recente no chat da live: {context_str[:500]}..."
                try:
                    comment = self.gemini_client.get_response(
                        query=comment_query,
                        channel=channel,
                        author="system",
                        memory_mgr=self.memory_mgr
                    )
                    if len(comment) > 0 and len(comment) <= 200:
                        self.send_message(channel, comment)
                        print(f"[DEBUG] Comentario enviado em {channel}: {comment[:50]}...")
                except Exception as e:
                    print(f"[ERROR] Falha ao gerar comentario para {channel}: {e}")

    def _periodic_audio_comment_thread(self):
        """Thread em background: A cada 30 min, transcreve audio e comenta se relevante (se listen_enabled)."""
        self.last_audio_comment_time = time.time() # Inicializa o timer

        while self.audio_comment_running:
            time.sleep(self.loop_sleep_interval)

            if not self.listen_enabled:
                continue 

            now = time.time()
            if now - self.last_audio_comment_time < 1800:
                continue 
            
            self.last_audio_comment_time = now 

            for channel in self.auth.channels:
                
                transcription = self._transcribe_stream(channel, duration=60)

                if not transcription or len(transcription) < 10:  # Ignora se vazio ou curto
                    print(f"[DEBUG] Transcricao vazia ou curta em {channel}. Pulando comentario.")
                    continue
                
                comment_query = f"Comente de forma natural e divertida sobre o que foi dito na live: {transcription[:500]}..."
                try:
                    comment = self.gemini_client.get_response(
                        query=comment_query,
                        channel=channel,
                        author="system",
                        memory_mgr=self.memory_mgr
                    )
                    if 0 < len(comment) <= 200:
                        self.send_message(channel, comment)
                        print(f"[DEBUG] Comentario de audio enviado em {channel}: {comment[:50]}...")
                except Exception as e:
                    print(f"[ERROR] Falha ao gerar comentario de audio para {channel}: {e}")

    def _transcribe_stream(self, channel, duration=60):
        """
        Captura audio da stream (via streamlink/ffmpeg) e transcreve (via Google Speech-to-Text).
        """
        print(f"[LISTEN] Iniciando captura de áudio para o canal: {channel}")
        temp_audio_file = f"/tmp/glorpinia_audio_{channel}.wav" 
        stream_url = ""

        try:
            # Obter a URL do áudio da stream
            print(f"[LISTEN] Buscando URL da stream para twitch.tv/{channel}...")
            streamlink_cmd = [
                "streamlink", 
                f"twitch.tv/{channel}", 
                "audio_only", 
                "--stream-url"
            ]
            
            result = subprocess.run(streamlink_cmd, capture_output=True, text=True, timeout=10, check=True)
            stream_url = result.stdout.strip()

            if not stream_url:
                print(f"[LISTEN ERROR] Stream offline ou não foi possível obter a URL (streamlink).")
                return ""
            
            print(f"[LISTEN] URL da stream obtida com sucesso.")

            # Passo 2: Capturar o áudio com ffmpeg
            print(f"[LISTEN] Gravando áudio por {duration} segundos...")
            ffmpeg_cmd = [
                "ffmpeg",
                "-i", stream_url,
                "-t", str(duration), # Duração da gravação
                "-vn",               # Sem vídeo
                "-c:a", "pcm_s16le", # Codec WAV (LINEAR16)
                "-ar", "16000",      # Sample rate de 16kHz
                "-ac", "1",          # Mono
                temp_audio_file,
                "-y"                 # Sobrescrever arquivo
            ]

            subprocess.run(ffmpeg_cmd, timeout=duration + 10, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[LISTEN] Captura de áudio salva em: {temp_audio_file}")

            # Enviar para Google Speech-to-Text
            client = speech.SpeechClient()

            with open(temp_audio_file, "rb") as audio_file:
                content = audio_file.read()
            
            audio = speech.RecognitionAudio(content=content)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code="pt-BR",
                audio_channel_count=1,
            )

            print(f"[LISTEN] Enviando áudio para a API Google Speech...")
            response = client.recognize(config=config, audio=audio)

            # Extrair transcrição
            transcription = "".join([result.alternatives[0].transcript for result in response.results])
            
            if transcription:
                print(f"[LISTEN] Transcrição recebida: {transcription[:50]}...")
            else:
                print(f"[LISTEN] API não retornou nenhuma transcrição.")
                
            return transcription

        except subprocess.CalledProcessError as e:
            print(f"[LISTEN ERROR] Falha no subprocesso (streamlink/ffmpeg): {e}")
            return ""
        except subprocess.TimeoutExpired:
            print(f"[LISTEN ERROR] Timeout ao capturar áudio.")
            return ""
        except Exception as e:
            print(f"[LISTEN ERROR] Erro inesperado na transcrição: {e}")
            return ""
        
        finally:
            # Limpeza
            if os.path.exists(temp_audio_file):
                os.remove(temp_audio_file)
                print(f"[LISTEN] Arquivo temporário removido: {temp_audio_file}")

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
    
    def _send_message_part(self, channel, part, delay):
        """[HELPER] Espera (em um thread) e envia uma parte da mensagem."""
        try:
            time.sleep(delay)
            self.send_message(channel, part)
        except Exception as e:
            print(f"[ERROR] Falha ao enviar parte da mensagem no thread: {e}")

    def send_long_message(self, channel, message, max_length=450, split_delay_sec=3):
        """
        Envia uma mensagem para o canal, dividindo-a em partes se exceder 
        'max_length'. Usa threads para os delays não bloquearem o bot.
        """
        if len(message) <= max_length:
            self.send_message(channel, message)
            return

        print(f"[INFO] Resposta longa detectada ({len(message)} chars). Dividindo em partes...")
        
        words = message.split()
        parts = []
        current_part = ""

        for word in words:
            if len(current_part) + len(word) + 1 > max_length:
                if current_part: 
                    parts.append(current_part.strip())
                current_part = word + " "
            else:
                current_part += word + " "
        
        if current_part:
            parts.append(current_part.strip())

        current_delay = 0
        for i, part in enumerate(parts):
            part_with_indicator = f"({i+1}/{len(parts)}) {part}"
            
            if len(part_with_indicator) > max_length:
                part_with_indicator = part[:max_length-10] + "..."

            t = threading.Thread(target=self._send_message_part, 
                                 args=(channel, part_with_indicator, current_delay))
            t.daemon = True
            t.start()
            
            current_delay += split_delay_sec

    def on_message(self, ws, message):
        """Handler de mensagens IRC (usa o cliente LLM)."""
        print(f"[IRC] RAW: {message.strip()}")
        if message.startswith("PING"):
            ws.send("PONG :tmi.twitch.tv\r\n")
            print("[PONG] Enviado para manter conexao viva.")
            return

        if "PRIVMSG" in message:

            parts = message.split(":", 2)
            if len(parts) < 3:
                print(f"[DEBUG] Mensagem PRIVMSG invalida: {message}")
                return
            author_part = parts[1].split("!")[0]
            content = parts[2].strip()
            channel = message.split("#")[1].split(" :")[0] if "#" in message else self.auth.channels[0]

            print(f"[CHAT] Parsed - author={author_part}, channel={channel}, content={content}")
            try:
                print(f"[DEBUG] recent_messages_count={len(self.recent_messages.get(channel, []))}")
            except Exception:
                pass
            content_lower = content.lower()
            print(f"[DEBUG] content_lower='{content_lower}'")

            anon_author = f"User{hash(author_part) % 1000}"
            msg_data = {
                'timestamp': time.time(),
                'author': anon_author,
                'content': content
            }
            if channel in self.recent_messages:
                self.recent_messages[channel].append(msg_data)

            if content == "!test_duplicate":
                print("[DEBUG] Simulando mensagem duplicada para teste...")
                self.on_message(ws, message)
                return

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

            if author_part.lower() in self.admin_nicks and content.startswith("!glorp"):
                self.handle_admin_command(content, channel)
                return

            # Processamento de chat geral (respostas a mencoes)
            if self.chat_enabled and self.auth.bot_nick.lower() in content.lower():
                print(f"[DEBUG] Bot mencionado por {author_part}. Gerando resposta...")
                try:
                    response = self.gemini_client.get_response(content, channel, author_part, self.memory_mgr) # Chamada mantida
                    if response:
                        self.send_long_message(channel, response)
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
            
            last_log_time = self.last_logged_content.get(channel, 0)
            if time.time() - last_log_time > 60:
                print(f"[INFO] Registro de treinamento salvo para a mensagem: {user_message[:30]}...")
                self.last_logged_content[channel] = time.time()
        except Exception as e:
            print(f"[ERROR] Falha ao escrever no arquivo de treinamento: {e}")

    def handle_admin_command(self, command, channel):
        """Processa comandos de admin (ex: !glorp chat on/off)."""
        parts = command.split()
        
        if len(parts) == 2:
            command_name = parts[1].lower()

            if command_name == "check":
                chat_status = "ATIVADO" if self.chat_enabled else "DESATIVADO"
                listen_status = "ATIVADO" if self.listen_enabled else "DESATIVADO"
                comment_status = "ATIVADO" if self.comment_enabled else "DESATIVADO"
                
                status_msg = (
                    f"Status: "
                    f"Chat peepoChat  {chat_status} | "
                    f"Listen glorp 📡  {listen_status} | "
                    f"Comment peepoTalk {comment_status}"
                )
                self.send_message(channel, status_msg)
                return
            
            elif command_name == "commands":
                self.send_message(channel, "glorp pergunta para o felino")
                return
        
        if len(parts) < 3:
            # Mensagem de ajuda atualizada
            self.send_message(channel, "Comando invalido. Use: !glorp <feature> <on|off>, !glorp check, ou !glorp commands")
            return

        feature = parts[1].lower()
        state = parts[2].lower()

        if feature == "chat":
            self.chat_enabled = (state == "on")
            status = "ATIVADO" if self.chat_enabled else "DESATIVADO"
            self.send_message(channel, f"peepoChat O modo CHAT foi {status}.")
        elif feature == "listen":
            self.listen_enabled = (state == "on")
            status = "ATIVADO" if self.listen_enabled else "DESATIVADO"
            self.send_message(channel, f"glorp 📡 O modo LISTEN foi {status}.")
        elif feature == "comment":
            self.comment_enabled = (state == "on")
            status = "ATIVADO" if self.comment_enabled else "DESATIVADO"
            self.send_message(channel, f"peepoTalk O modo COMMENT foi {status}.")
        else:
            self.send_message(channel, f"glorp Funcionalidade desconhecida: {feature}")

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