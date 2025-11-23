import time
import threading
import subprocess
import os
import io
import logging
import sys
from google.cloud import speech

class Listen:
    def __init__(self, bot, speech_client):
        """
        Inicializa a feature de escuta (periódica e manual).
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
        """
        print(f"[Listen] Gatilho manual ativado para {channel}.")
        scan_thread = threading.Thread(target=self._manual_listen_trigger, args=(channel,))
        scan_thread.daemon = True
        scan_thread.start()

    def _periodic_thread(self):
        """
        Thread em background: A cada 30 min, transcreve audio e comenta.
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
        Captura audio da stream e transcreve.
        """
        if not self.speech_client:
            logging.error("[Listen] Google Speech Client não foi inicializado.")
            return ""
            
        logging.info(f"[Listen] Iniciando captura de áudio para: {channel}")
        temp_audio_file = f"/tmp/glorpinia_audio_{channel}.wav"
        stream_url = ""
        
        # Caminho Absoluto do Streamlink
        venv_bin = os.path.dirname(sys.executable)
        streamlink_exec = os.path.join(venv_bin, "streamlink")

        try:
            # Obter a URL do áudio da stream
            logging.info(f"[Listen] Buscando URL da stream para twitch.tv/{channel}...")
            
            streamlink_cmd = [
                streamlink_exec, 
                f"twitch.tv/{channel}", 
                "audio_only", 
                "--stream-url",
                "--twitch-disable-ads"
            ]
            
            result = subprocess.run(streamlink_cmd, capture_output=True, text=True, timeout=15)
            
            if result.returncode != 0:
                error_msg = result.stderr + result.stdout
                if "No playable streams found" in error_msg:
                    logging.info(f"[Listen] O canal {channel} parece estar offline.")
                    return ""
                
                logging.error(f"[Listen] Erro no streamlink. Código: {result.returncode}. Log: {error_msg.strip()[:200]}...")
                return ""

            stream_url = result.stdout.strip()

            if not stream_url:
                return ""
            
            logging.info(f"[Listen] URL obtida. Gravando {duration}s...")

            # Capturar o áudio com ffmpeg
            ffmpeg_cmd = [
                "ffmpeg", 
                "-i", stream_url, 
                "-t", str(duration), 
                "-vn", 
                "-c:a", "pcm_s16le", 
                "-ar", "16000", 
                "-ac", "1", 
                temp_audio_file, 
                "-y",
                "-hide_banner", 
                "-loglevel", "error"
            ]
            
            subprocess.run(ffmpeg_cmd, timeout=duration + 15, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            
            logging.info(f"[Listen] Captura concluída.")

            # Enviar para Google Speech-to-Text
            if not os.path.exists(temp_audio_file):
                logging.error("[Listen] Arquivo de áudio não encontrado após ffmpeg.")
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

            # Extrair transcrição
            transcription = "".join([result.alternatives[0].transcript for result in response.results])
            
            if transcription:
                logging.info(f"[Listen] Transcrição recebida: {transcription[:50]}...")
            else:
                logging.info(f"[Listen] API retornou silêncio/vazio.")
                
            return transcription

        except subprocess.TimeoutExpired:
            logging.error(f"[Listen] Timeout: Processo demorou demais.")
            return ""
        except Exception as e:
            logging.error(f"[Listen] Erro inesperado: {e}")
            return ""
        
        finally:
            if os.path.exists(temp_audio_file):
                os.remove(temp_audio_file)

    def _manual_listen_trigger(self, channel):
        """
        Gatilho manual (!glorp scan).
        """
        try:
            self.bot.send_message(channel, f"glorp 📡 Fala que eu te escuto, @{channel}...")
            
            transcription = self._transcribe_stream(channel, duration=15)
            
            if not transcription or len(transcription) < 10:
                logging.info(f"[Listen] Transcricao manual vazia.")
                self.bot.send_message(channel, f"@{channel}, não consegui ouvir nada. angrybird")
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
        Thread que chama a IA (2 passagens).
        """
        try:
            # Sumarizar
            logging.info(f"[Listen] Passagem 1: Sumarizando...")
            topic = self.bot.gemini_client.summarize_chat_topic(transcription) 

            # Comentar
            logging.info(f"[Listen] Passagem 2: Gerando comentário sobre '{topic}'...")
            comment_query = f"O streamer disse algo sobre: '{topic}'. Faça um comentário curto (1-2 frases), divertido e com sua personalidade sobre isso."

            comment = self.bot.gemini_client.get_response(
                query=comment_query,
                channel=channel,
                author="system",
                memory_mgr=memory_mgr
            )
            
            if 0 < len(comment) <= 200:
                formatted_comment = f"@{channel}, {comment}"
                self.bot.send_long_message(channel, formatted_comment)
                logging.info(f"[Listen] Comentario enviado em {channel}.")
                
                logging.info(f"[Listen] Comentario enviado em {channel}.")
        except Exception as e:
            logging.error(f"[Listen] Falha ao gerar comentario: {e}")