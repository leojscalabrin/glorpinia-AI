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
                logging.debug(f"[Listen] Iniciando ciclo de escuta periódica para {channel}...")
                
                transcription = self._transcribe_stream(channel, duration=15) 

                if not transcription or len(transcription) < 10:
                    logging.debug(f"[Listen] Transcricao periódica vazia em {channel}. Pulando.")
                    continue
                
                comment_query = f"Comente de forma natural e divertida sobre o que foi dito na live: {transcription[:500]}..."
                
                try:
                    comment = self.bot.gemini_client.get_response(
                        query=comment_query,
                        channel=channel,
                        author="system",
                        memory_mgr=self.bot.memory_mgr
                    )
                    
                    if 0 < len(comment) <= 200:
                        formatted_comment = f"@{channel}, {comment}"
                        self.bot.send_long_message(channel, formatted_comment)
                        logging.debug(f"[Listen] Comentario de audio periódico enviado em {channel}.")
                except Exception as e:
                    logging.error(f"[Listen] Falha ao gerar comentario de audio periódico: {e}")

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

        try:
            # Obter a URL do áudio da stream
            logging.debug(f"[Listen] Buscando URL da stream para twitch.tv/{channel}...")
            streamlink_cmd = ["streamlink", f"twitch.tv/{channel}", "audio_only", "--stream-url"]
            result = subprocess.run(streamlink_cmd, capture_output=True, text=True, timeout=10, check=True)
            stream_url = result.stdout.strip()

            if not stream_url:
                logging.warning(f"[Listen] Stream offline ou não foi possível obter a URL (streamlink).")
                return ""
            
            logging.debug(f"[Listen] URL da stream obtida com sucesso.")

            # Capturar o áudio com ffmpeg
            logging.debug(f"[Listen] Gravando áudio por {duration} segundos...")
            ffmpeg_cmd = [
                "ffmpeg", "-i", stream_url, "-t", str(duration), "-vn", 
                "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1", 
                temp_audio_file, "-y"
            ]
            subprocess.run(ffmpeg_cmd, timeout=duration + 10, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logging.debug(f"[Listen] Captura de áudio salva em: {temp_audio_file}")

            # Enviar para Google Speech-to-Text
            with open(temp_audio_file, "rb") as audio_file:
                content = audio_file.read()
            
            audio = speech.RecognitionAudio(content=content)
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code="pt-BR",
                audio_channel_count=1,
            )

            logging.debug(f"[Listen] Enviando áudio para a API Google Speech...")
            response = self.speech_client.recognize(config=config, audio=audio)

            # Extrair transcrição
            transcription = "".join([result.alternatives[0].transcript for result in response.results])
            
            if transcription:
                logging.debug(f"[Listen] Transcrição recebida: {transcription[:50]}...")
            else:
                logging.debug(f"[Listen] API não retornou nenhuma transcrição.")
                
            return transcription

        except subprocess.CalledProcessError as e:
            logging.error(f"[Listen] Falha no subprocesso (streamlink/ffmpeg): {e}")
            return ""
        except subprocess.TimeoutExpired:
            logging.error(f"[Listen] Timeout ao capturar áudio.")
            return ""
        except Exception as e:
            logging.error(f"[Listen] Erro inesperado na transcrição: {e}")
            return ""
        
        finally:
            # Limpeza
            if os.path.exists(temp_audio_file):
                os.remove(temp_audio_file)
                logging.debug(f"[Listen] Arquivo temporário removido: {temp_audio_file}")

    def _manual_listen_trigger(self, channel):
        """
        Gatilho manual para a função Listen (!glorp scan).
        """
        try:
            self.bot.send_message(channel, f"glorp 📡 Fala que eu te escuto, @{channel}...")
            
            transcription = self._transcribe_stream(channel, duration=15)
            
            if not transcription or len(transcription) < 10:
                logging.debug(f"[Listen] Transcricao manual vazia em {channel}.")
                self.bot.send_message(channel, f"@{channel}, não consegui ouvir nada. Sadge")
                return

            comment_query = f"Comente de forma natural e divertida sobre o que foi dito na live: {transcription[:500]}..."
            
            comment = self.bot.gemini_client.get_response(
                query=comment_query,
                channel=channel,
                author="system",
                memory_mgr=self.bot.memory_mgr
            )
            
            if comment:
                self.bot.send_long_message(channel, f"@{channel}, {comment}")
            else:
                self.bot.send_message(channel, f"@{channel}, minhas anteninhas não captaram nenhum sinal. Sadge")

        except Exception as e:
            logging.error(f"[Listen] Falha ao gerar comentario de audio manual: {e}")
            self.bot.send_message(channel, f"@{channel}, o portal está instável. Eu não consigo me comunicar. Sadge")