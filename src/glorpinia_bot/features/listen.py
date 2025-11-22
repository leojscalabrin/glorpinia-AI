import time
import threading
import subprocess
import os
import io
import logging
from google.cloud import speech

class Listen:
    def __init__(self, bot, speech_client):
        """
        Inicializa a feature de escuta (periódica e manual).
        'bot' é a instância principal do TwitchIRC.
        'speech_client' é o cliente inicializado do Google Speech.
        """
        print("[Feature] Listen Initialized.")
        self.bot = bot
        self.speech_client = speech_client
        self.enabled = False
        self.last_audio_comment_time = 0
        self.loop_sleep_interval = 10
        self.timer_running = True
        
        self.thread = threading.Thread(target=self._periodic_thread, daemon=True)
        self.thread.start()

    def set_enabled(self, state: bool):
        """Ativa ou desativa o timer PERIÓDICO."""
        self.enabled = state

    def get_status(self):
        """Retorna o status formatado para o comando !glorp check."""
        return "ATIVADO" if self.enabled else "DESATIVADO"

    def stop_thread(self):
        """Sinaliza para o thread parar (usado no shutdown)."""
        self.timer_running = False

    def trigger_manual_scan(self, channel):
        """
        Inicia a escuta manual (comando !glorp scan).
        Roda em um novo thread para não bloquear o bot.
        """
        print(f"[Listen] Gatilho manual ativado para {channel}.")
        scan_thread = threading.Thread(target=self._manual_listen_trigger, args=(channel,))
        scan_thread.daemon = True
        scan_thread.start()

    def _periodic_thread(self):
        """
        Thread em background: A cada 30 min, transcreve audio e comenta 
        se relevante (se self.enabled for True).
        """
        self.last_audio_comment_time = time.time()
        
        while self.timer_running:
            time.sleep(self.loop_sleep_interval)

            if not self.enabled:
                continue

            now = time.time()
            if now - self.last_audio_comment_time < 1800:  # 30 min
                continue
            
            self.last_audio_comment_time = now

            for channel in self.bot.auth.channels:
                logging.info(f"[Listen] Iniciando ciclo de escuta periódica para {channel}...")
                
                transcription = self._transcribe_stream(channel, duration=15) 

                if not transcription or len(transcription) < 10:
                    logging.info(f"[Listen] Transcricao periódica vazia ou curta em {channel}. Pulando.")
                    continue
                
                t = threading.Thread(target=self._generate_comment_thread, 
                                     args=(transcription, channel, self.bot.memory_mgr))
                t.daemon = True
                t.start()

    def _transcribe_stream(self, channel, duration=15):
        """
        Captura audio da stream (via streamlink/ffmpeg) e transcreve (via Google Speech-to-Text).
        """
        if not self.speech_client:
            logging.error("[Listen] Google Speech Client não foi inicializado.")
            return ""
            
        logging.info(f"[Listen] Iniciando captura de áudio para: {channel}")
        temp_audio_file = f"/tmp/glorpinia_audio_{channel}.wav"
        stream_url = ""
        
        # Pega o token para autenticar o streamlink (evita ads)
        token = self.bot.auth.access_token

        try:
            # 1. Obter a URL do áudio da stream
            logging.info(f"[Listen] Buscando URL da stream para twitch.tv/{channel}...")
            
            streamlink_cmd = [
                "streamlink", 
                f"twitch.tv/{channel}", 
                "audio_only", 
                "--stream-url",
                "--twitch-disable-ads",
                "--http-header", f"Authorization=OAuth {token}"
            ]
            
            result = subprocess.run(streamlink_cmd, capture_output=True, text=True, timeout=15)
            
            if result.returncode != 0:
                logging.error(f"[Listen] Erro no streamlink: {result.stderr}")
                return ""

            stream_url = result.stdout.strip()

            if not stream_url:
                logging.warning(f"[Listen] Stream offline ou URL vazia.")
                return ""
            
            logging.info(f"[Listen] URL da stream obtida. Gravando {duration}s com FFMPEG...")

            # 2. Capturar o áudio com ffmpeg
            ffmpeg_cmd = [
                "ffmpeg", 
                "-i", stream_url, 
                "-t", str(duration), 
                "-vn", 
                "-c:a", "pcm_s16le", 
                "-ar", "16000", 
                "-ac", "1", 
                temp_audio_file, 
                "-y"
            ]
            
            # Aumentei o timeout do ffmpeg para dar margem (duration + 15s)
            subprocess.run(ffmpeg_cmd, timeout=duration + 15, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            logging.info(f"[Listen] Captura concluída. Arquivo: {temp_audio_file}")

            # 3. Enviar para Google Speech-to-Text
            if not os.path.exists(temp_audio_file):
                logging.error("[Listen] Arquivo de áudio não foi criado pelo FFMPEG.")
                return ""

            with open(temp_audio_file, "rb") as audio_file:
                content = audio_file.read()
            
            audio = speech.RecognitionAudio(content=content)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code="pt-BR",
                audio_channel_count=1,
            )

            logging.info(f"[Listen] Enviando áudio para a API Google Speech...")
            response = self.speech_client.recognize(config=config, audio=audio)

            # 4. Extrair transcrição
            transcription = "".join([result.alternatives[0].transcript for result in response.results])
            
            if transcription:
                logging.info(f"[Listen] Transcrição recebida: {transcription[:50]}...")
            else:
                logging.info(f"[Listen] API não retornou nenhuma transcrição (silêncio?).")
                
            return transcription

        except subprocess.TimeoutExpired:
            logging.error(f"[Listen] Timeout ao capturar áudio (Streamlink ou FFMPEG demorou demais).")
            return ""
        except Exception as e:
            logging.error(f"[Listen] Erro inesperado na transcrição: {e}")
            return ""
        
        finally:
            # 5. Limpeza
            if os.path.exists(temp_audio_file):
                os.remove(temp_audio_file)
                logging.debug(f"[Listen] Arquivo temporário removido.")

    def _manual_listen_trigger(self, channel):
        """
        Gatilho manual para a função Listen (!glorp scan).
        """
        try:
            self.bot.send_message(channel, f"glorp 📡 Fala que eu te escuto, @{channel}...")
            
            transcription = self._transcribe_stream(channel, duration=15)
            
            if not transcription or len(transcription) < 10:
                logging.info(f"[Listen] Transcricao manual vazia em {channel}.")
                self.bot.send_message(channel, f"@{channel}, não consegui ouvir nada. Sadge")
                return

            t = threading.Thread(target=self._generate_comment_thread, 
                                 args=(transcription, channel, self.bot.memory_mgr))
            t.daemon = True
            t.start()

        except Exception as e:
            logging.error(f"[Listen] Falha ao gerar comentario de audio manual: {e}")
            self.bot.send_message(channel, f"@{channel}, o portal está instável. Sadge")

    def _generate_comment_thread(self, transcription: str, channel: str, memory_mgr):
        """
        Thread que chama a IA (2 passagens), para não travar a 'on_message'.
        """
        try:
            # 1. Sumarizar a transcrição
            logging.info(f"[Listen] Passagem 1: Sumarizando a transcrição...")
            topic = self.bot.gemini_client.summarize_chat_topic(transcription) 

            if not topic or topic == "assuntos aleatórios":
                logging.info(f"[Listen] Tópico do áudio não é interessante ('{topic}'). Cancelando.")
                return

            # 2. Criar um prompt limpo e comentar sobre o tópico
            logging.info(f"[Listen] Passagem 2: Gerando comentário sobre '{topic}'...")
            comment_query = f"O streamer estava falando sobre: '{topic}'. Faça um comentário curto (1-2 frases), divertido e com sua personalidade sobre esse assunto."

            comment, cookie_feedback = self.bot.gemini_client.get_response(
                query=comment_query,
                channel=channel,
                author="system",
                memory_mgr=memory_mgr
            )
            
            if 0 < len(comment) <= 200:
                formatted_comment = f"@{channel}, {comment}"
                self.bot.send_long_message(channel, formatted_comment)
                if cookie_feedback:
                    self.bot.send_message(channel, f"glorp {cookie_feedback}")
                
                logging.info(f"[Listen] Comentario de audio enviado em {channel}: {comment[:50]}...")
        except Exception as e:
            logging.error(f"[Listen] Falha ao gerar comentario de 2 passagens: {e}")