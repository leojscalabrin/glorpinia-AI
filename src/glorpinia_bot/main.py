import time
import logging
import signal
import sys
import re
import threading
import os
from datetime import datetime
from collections import deque
from .twitch_auth import TwitchAuth
# HFClient and MemoryManager are imported lazily inside TwitchIRC to allow
# running in capture-only mode without pulling heavy ML dependencies.

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

class TwitchIRC:
    def __init__(self):
        # Instancia componentes modulares
        self.auth = TwitchAuth()  # Carrega env, tokens, profile, channels

        # Support capture-only mode where we don't need HF client or embeddings.
        self.capture_only = os.environ.get('GLORPINIA_CAPTURE_ONLY') == '1'
        # Skip loading the ML model entirely for quick import/startup checks or CI
        self.skip_model_load = os.environ.get('GLORPINIA_SKIP_MODEL_LOAD') == '1'

        if self.capture_only:
            print('[INFO] Running in capture-only mode; HFClient and MemoryManager will not be instantiated.')
            self.hf_client = None
            self.memory_mgr = None
        elif self.skip_model_load:
            print('[INFO] GLORPINIA_SKIP_MODEL_LOAD=1 set; skipping HFClient and MemoryManager instantiation.')
            # Keep attributes present but don't load heavy ML deps.
            self.hf_client = None
            self.memory_mgr = None
        else:
            # Instantiate heavy components lazily when needed.
            from .hf_client import HFClient
            from .memory_manager import MemoryManager

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

        # Estados das funcionalidades
        self.chat_enabled = True  # Para respostas a menções
        self.listen_enabled = False  # Para transcrição de áudio (OFF por default)
        self.comment_enabled = False  # Para comentários periódicos (OFF por default)

        # Lista de admins
        self.admin_nicks = ["felinomascarado"]

        self.ws = None
        self.running = False

        # Valida e renova token se necessário (usa auth)
        self.auth.validate_and_refresh_token()

        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

    # Inicia thread para timer de comentários periódicos (se comment_enabled)
        self.comment_timer_running = True
        self.comment_thread = threading.Thread(target=self._periodic_comment_thread, daemon=True)
        self.comment_thread.start()

        # Inicia thread para transcrição de áudio se listen_enabled
        self.audio_comment_running = True
        self.audio_comment_thread = threading.Thread(target=self._periodic_audio_comment_thread, daemon=True)
        self.audio_comment_thread.start()

    # websocket is optional for capture-only mode; import at run-time

    def _periodic_comment_thread(self):
        """Thread em background: A cada 30 min, checa contexto e envia comentário se aplicável (se comment_enabled)."""
        while self.comment_timer_running:
            if not self.comment_enabled:
                time.sleep(10)  # Espera curta se desabilitado, checa periodicamente
                continue
            time.sleep(1800)

            for channel in self.auth.channels:
                recent_msgs = self.recent_messages.get(channel, deque())
                now = time.time()
                
                # Filtra msgs das últimas 2 min
                recent_context = [msg for msg in recent_msgs if now - msg['timestamp'] <= 120]
                
                if len(recent_context) == 0:
                    print(f"[DEBUG] Nenhuma mensagem nas últimas 2 min em {channel}. Pulando comentário.")
                    continue  # Ignora se vazio
                
                # Cria contexto como string
                context_str = "\n".join([f"{msg['author']}: {msg['content']}" for msg in recent_context])
                
                # Gera comentário via HF (prompt temático)
                comment_query = f"Comente de forma natural e divertida sobre essa conversa recente no chat da live: {context_str[:500]}..."  # Limita pra tokens
                try:
                    comment = self.hf_client.get_response(
                        query=comment_query,
                        channel=channel,
                        author="system",  # Genérico, sem user específico
                        memory_mgr=self.memory_mgr
                    )
                    if len(comment) > 0 and len(comment) <= 200:  # Filtra respostas válidas/curtas
                        self.send_message(channel, comment)
                        print(f"[DEBUG] Comentário enviado em {channel}: {comment[:50]}...")
                except Exception as e:
                    print(f"[ERROR] Falha ao gerar comentário para {channel}: {e}")

    def _periodic_audio_comment_thread(self):
        """Thread em background: A cada 30 min, transcreve áudio e comenta se relevante (se listen_enabled)."""
        while self.audio_comment_running:
            if not self.listen_enabled:
                time.sleep(10)  # Espera curta se desabilitado, checa periodicamente
                continue
            time.sleep(1800)  # 30 minutos em segundos

            for channel in self.auth.channels:
                # Captura áudio da stream por 60s
                transcription = self._transcribe_stream(channel, duration=60)
                
                if not transcription or len(transcription) < 10:  # Ignora se vazio ou curto
                    print(f"[DEBUG] Transcrição vazia ou curta em {channel}. Pulando comentário.")
                    continue
                
                # Gera comentário via HF com contexto de áudio
                comment_query = f"Comente de forma natural e divertida sobre o que foi dito na live: {transcription[:500]}..."  # Limita pra tokens
                try:
                    comment = self.hf_client.get_response(
                        query=comment_query,
                        channel=channel,
                        author="system",  # Genérico
                        memory_mgr=self.memory_mgr
                    )
                    if 0 < len(comment) <= 200:  # Filtra válidas/curtas
                        self.send_message(channel, comment)
                        print(f"[DEBUG] Comentário de áudio enviado em {channel}: {comment[:50]}...")
                except Exception as e:
                    print(f"[ERROR] Falha ao gerar comentário de áudio para {channel}: {e}")

    def _shutdown_handler(self, signum, frame):
        """Handler para shutdown gracioso com mensagem de despedida."""
        print("[INFO] Sinal de shutdown recebido. Enviando mensagem de despedida...")
        self.comment_timer_running = False  # Para o thread de comentários
        self.audio_comment_running = False  # Para o thread de áudio
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
        print(f"[IRC] RAW: {message.strip()}")
        if message.startswith("PING"):
            ws.send("PONG :tmi.twitch.tv\r\n")
            print("[PONG] Enviado para manter conexão viva.")
            return

        if "PRIVMSG" in message:
            # Extrai autor e conteúdo da mensagem IRC
            parts = message.split(":", 2)
            if len(parts) < 3:
                print(f"[DEBUG] Mensagem PRIVMSG inválida: {message}")
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

            # Capture-only mode: append sanitized record to training_data.jsonl and skip heavy model calls
            capture_only = os.environ.get('GLORPINIA_CAPTURE_ONLY') == '1'
            if capture_only:
                try:
                    self._append_training_record(channel, author_part, content, None)
                except Exception as e:
                    print(f"[ERROR] Falha ao salvar registro de captura: {e}")
                return

            if author_part.lower() == self.auth.bot_nick.lower():
                print(f"[DEBUG] Ignorando mensagem do próprio bot: {content}")
                return

            # Check para palavra EXATA "glorp"
            if re.search(r'\bglorp\b', content_lower):
                glorp_response = "glorp"
                print(f"[DEBUG] 'glorp' (exato) detectado em {content}. Respondendo...")
                self.send_message(channel, glorp_response)

            # Check para menção ao bot (queries IA, só se chat_enabled)
            bot_nick_lower = self.auth.bot_nick.lower()
            print(f"[DEBUG] Verificando menção: content_lower='{content_lower}', bot_nick='{bot_nick_lower}', chat_enabled={self.chat_enabled}")
            if self.chat_enabled and re.search(r'\b@?' + re.escape(bot_nick_lower) + r'\b', content_lower):
                print(f"[DEBUG] Menção a {self.auth.bot_nick} detectada: {content}")
                query = re.sub(r'\b@?' + re.escape(bot_nick_lower) + r'\b', '', content_lower).strip()
                print(f"[DEBUG] Query extraída para a IA: {query}")

                if query:
                    # If HFClient wasn't instantiated (skip or capture-only), skip generation gracefully.
                    if self.hf_client is None:
                        print('[INFO] HFClient not available (capture-only or skip-model-load); skipping generation.')
                        try:
                            # Still attempt to log the interaction for later fine-tuning
                            self._append_training_record(channel, author_part, content, None)
                        except Exception as ee:
                            print(f"[ERROR] Falha ao salvar registro: {ee}")
                        return

                    try:
                        print(f"[DEBUG] Calling HFClient.get_response with query='{query[:120]}'")
                        response = self.hf_client.get_response(
                            query=query,
                            channel=channel,
                            author=author_part,
                            memory_mgr=self.memory_mgr
                        )
                        print(f"[DEBUG] Resposta da IA (len={len(response) if response else 0}): {str(response)[:120]}")
                        
                        # Divide resposta se > 333 chars e envia com delay de 5s
                        if len(response) > 333:
                            chunks = [response[i:i+333] for i in range(0, len(response), 333)]
                            for i, chunk in enumerate(chunks):
                                if i == 0:
                                    self.send_message(channel, f"@{author_part} {chunk}")
                                else:
                                    self.send_message(channel, chunk)
                                if i < len(chunks) - 1:
                                    time.sleep(5)
                        else:
                            self.send_message(channel, f"@{author_part} {response}")
                    except Exception as e:
                        print(f"[ERROR] Falha ao gerar resposta da IA para {channel}: {e}")
                    # Always try to save the interaction (bot_response may be missing on error)
                    try:
                        bot_resp = locals().get('response', None)
                        self._append_training_record(channel, author_part, content, bot_resp)
                    except Exception as ee:
                        print(f"[ERROR] Falha ao salvar registro: {ee}")
                else:
                    print("[DEBUG] Query vazia após menção. Nenhuma resposta da IA.")

            # Checa se é comando de toggle ou check
            if content_lower.startswith("!toggle ") or content_lower == "!check":
                if author_part.lower() not in [nick.lower() for nick in self.admin_nicks]:
                    self.send_message(channel, f"@{author_part}, arnoldHalt comando apenas para os chegados")
                    print(f"[DEBUG] Tentativa de comando por não-admin: {author_part}")
                    return
                if content_lower.startswith("!toggle "):
                    parts = content_lower.split(" ")
                    if len(parts) != 3 or parts[1] not in ["chat", "listen", "comment"] or parts[2] not in ["on", "off"]:
                        self.send_message(channel, "glorp use !toggle [chat|listen|comment] [on/off]")
                        return
                    feature, state = parts[1], parts[2]
                    if feature == "chat":
                        self.chat_enabled = (state == "on")
                        status_msg = "glorp pronta pra bater um papinho | Chat [ON]" if self.chat_enabled else "glorp a mimir | Chat [OFF]"
                    elif feature == "listen":
                        self.listen_enabled = (state == "on")
                        status_msg = "glorp 📡 Sinal recebido | Listen [ON]" if self.listen_enabled else "glorp 📡Sinal interrompido | Chat [OFF]"
                    else:
                        self.comment_enabled = (state == "on")
                        status_msg = "PopNemo Comment [ON]" if self.comment_enabled else "Shush Comment [OFF]"
                    self.send_message(channel, status_msg)
                    print(f"[DEBUG] {feature.capitalize()} toggled {state} por {author_part}")
                elif content_lower == "!check":
                    status = f"glorp chat[{ 'ON' if self.chat_enabled else 'OFF' }] | listen [{ 'ON' if self.listen_enabled else 'OFF' }] | comment [{ 'ON' if self.comment_enabled else 'OFF' }]"
                    self.send_message(channel, status)
                    print(f"[DEBUG] Status check por {author_part}")

    def _transcribe_stream(self, channel, duration=60):
        """Captura e transcreve áudio da stream por 'duration' segundos."""
        stream_url = f"https://twitch.tv/{channel}"
        try:
            # Imports locais para dependências opcionais
            try:
                import streamlink
            except Exception:
                print("[WARNING] streamlink não instalado — transcrição desabilitada. Instale 'streamlink' para habilitar.")
                return ""

            streams = streamlink.streams(stream_url)
            if "audio_only" in streams:
                audio_stream = streams["audio_only"]
            elif "worst" in streams:
                audio_stream = streams["worst"]
            else:
                print(f"[ERROR] Nenhum stream encontrado para {channel}")
                return ""

            # Captura áudio temporariamente
            audio_file = f"temp_audio_{channel}.mp3"
            with open(audio_file, "wb") as f:
                start_time = time.time()
                for chunk in audio_stream.open():
                    f.write(chunk)
                    if time.time() - start_time > duration:
                        break

            # Converte pra WAV e transcreve
            try:
                from pydub import AudioSegment
            except Exception:
                print("[WARNING] pydub não instalado — transcrição desabilitada. Instale 'pydub' e suas dependências.")
                return ""

            audio = AudioSegment.from_mp3(audio_file)
            wav_file = audio_file + ".wav"
            audio.export(wav_file, format="wav")
            try:
                # Suporte a whisper local (openai-whisper) — se não presente, pula
                if not hasattr(self, 'whisper_model') or self.whisper_model is None:
                    try:
                        import whisper
                        self.whisper_model = whisper.load_model("small")
                    except Exception:
                        print("[WARNING] whisper não disponível — instale 'openai-whisper' para transcrição local.")
                        return ""

                transcription = self.whisper_model.transcribe(wav_file)["text"]
            except Exception as e:
                print(f"[ERROR] Falha na transcrição via whisper: {e}")
                return ""

            # Limpa arquivos temp
            os.remove(audio_file)
            os.remove(wav_file)

            return transcription
        except Exception as e:
            print(f"[ERROR] Falha na transcrição para {channel}: {e}")
            return ""

    def _append_training_record(self, channel, author, text, bot_response):
        """Append a sanitized JSONL record to training_data.jsonl for later fine-tuning.

        The record format is minimal and anonymized.
        """
        import json
        from datetime import datetime
        user_hash = f"u{abs(hash(author)) % 1000000}"
        rec = {
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "channel": channel,
            "user_hash": user_hash,
            "text": text,
            "bot_response": bot_response,
            "source": "twitch"
        }
        file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'training_data.jsonl')
        # Append safely
        try:
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"[ERROR] Could not append training record: {e}")

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
        # Import websocket lazily so capture-only mode can instantiate the bot without this dependency
        try:
            import websocket
        except Exception:
            print('[ERROR] websocket package not installed; run() cannot start the IRC client.')
            return

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