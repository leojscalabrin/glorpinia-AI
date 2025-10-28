from dotenv import load_dotenv
import os
import requests
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

class TwitchAuth:
    """
    Gerencia a autenticacao e configuracao base da Twitch, e carrega o perfil de personalidade.
    """
    def __init__(self):
        load_dotenv()

        # Configurações Twitch
        self.access_token = os.getenv("TWITCH_TOKEN").replace("oauth:", "") if os.getenv("TWITCH_TOKEN") else None
        self.refresh_token_value = os.getenv("TWITCH_REFRESH_TOKEN")
        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")
        self.bot_nick = os.getenv("TWITCH_BOT_NICK")

        # Carrega Perfil e Canais
        self.personality_profile = self._load_personality_profile()
        self._load_channels()

        self._check_required_vars()

    def _load_channels(self):
        """Extrai canais da variavel de ambiente TWITCH_CHANNELS."""
        channels_str = os.getenv("TWITCH_CHANNELS")
        if channels_str:
            self.channels = [c.strip() for c in channels_str.split(",") if c.strip()]
        else:
            raise ValueError("Missing TWITCH_CHANNELS environment variable in .env file")

    def _load_personality_profile(self, file_path="glorpinia_profile.txt"):
        """Carrega o perfil de personalidade do arquivo de texto."""
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception as e:
                logging.error(f"Falha ao ler o perfil de personalidade em {file_path}: {e}")
                return "Você é uma garota gato alienígena. Responda de forma fofa."
        else:
            logging.warning(f"Arquivo de perfil '{file_path}' não encontrado. Usando perfil básico.")
            return "Você é uma garota gato alienígena. Responda de forma fofa."

    def _check_required_vars(self):
        """Verifica se as variáveis Twitch essenciais estão presentes."""
        required = {
            "TWITCH_TOKEN": self.access_token,
            "TWITCH_REFRESH_TOKEN": self.refresh_token_value,
            "TWITCH_CLIENT_ID": self.client_id,
            "TWITCH_CLIENT_SECRET": self.client_secret,
            "TWITCH_BOT_NICK": self.bot_nick,
        }
        missing = [key for key, value in required.items() if not value]
        
        capture_only = os.environ.get("GLORPINIA_CAPTURE_ONLY") == '1'
        
        if missing and not capture_only:
            raise ValueError(f"As seguintes variáveis de ambiente essenciais estão faltando no .env: {', '.join(missing)}")
        
        if not self.channels:
            raise ValueError("A lista de canais TWITCH_CHANNELS está vazia.")
            
        logging.info(f"Bot '{self.bot_nick}' carregado para canais: {', '.join(self.channels)}")

    def validate_and_refresh_token(self):
        """Valida o token e tenta renová-lo se necessário ou expirado."""
        if not self.access_token or not self.client_id or not self.client_secret:
            logging.error("Dados de autenticação incompletos. Não é possível validar ou renovar o token.")
            return None

        # Validação (Testa se o token atual é válido)
        try:
            validation_url = "https://id.twitch.tv/oauth2/validate"
            headers = {"Authorization": f"OAuth {self.access_token}"}
            response = requests.get(validation_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                logging.info(f"[AUTH] Token Twitch é válido.")
                return self.access_token
            else:
                logging.warning(f"[AUTH] Token inválido ou expirado. Status: {response.status_code}. Tentando renovação...")
                return self._refresh_token()
                
        except requests.RequestException as e:
            logging.error(f"[ERROR] Erro na validação do token: {e}. Tentando renovação...")
            return self._refresh_token()

    def _refresh_token(self):
        """Renova o token usando o refresh token."""
        if not self.refresh_token_value:
            logging.error("Refresh Token não encontrado. Não é possível renovar.")
            return None
            
        old_access_token = self.access_token
        old_refresh_token = self.refresh_token_value

        try:
            refresh_url = "https://id.twitch.tv/oauth2/token"
            data = {
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token_value,
                "client_id": self.client_id,
                "client_secret": self.client_secret
            }
            response = requests.post(refresh_url, data=data, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                self.access_token = data["access_token"]
                new_refresh_token = data.get("refresh_token") # Pode vir nulo

                if new_refresh_token:
                    self.refresh_token_value = new_refresh_token
                
                logging.info(f"[AUTH] Token renovado com sucesso. Novo Access Token: {self.access_token[:10]}...")

                if self.access_token != old_access_token or new_refresh_token != old_refresh_token:
                    self.update_env_file(self.access_token, new_refresh_token or self.refresh_token_value)
                return self.access_token
            else:
                logging.error(f"[ERROR] Falha na renovação: {response.status_code} - {response.text}")
                return None
        except requests.RequestException as e:
            logging.error(f"[ERROR] Erro na renovação: {e}")
            return None

    def update_env_file(self, new_access_token, new_refresh_token):
        """Atualiza o arquivo .env com os novos tokens."""
        if not os.path.exists(".env"):
             logging.warning("Arquivo .env não encontrado. Não foi possível salvar os novos tokens.")
             return
             
        try:
            with open(".env", "r", encoding="utf-8") as f:
                lines = f.readlines()

            lines = [line for line in lines if not line.strip().startswith("TWITCH_TOKEN=") and not line.strip().startswith("TWITCH_REFRESH_TOKEN=")]
            lines = [line.rstrip("\r\n") + "\n" for line in lines if line.strip()]

            # Adiciona novos tokens
            lines.append(f"TWITCH_TOKEN=oauth:{new_access_token}\n")
            lines.append(f"TWITCH_REFRESH_TOKEN={new_refresh_token}\n")
            lines.append("\n") # Garante uma linha final vazia

            with open(".env", "w", encoding="utf-8", newline='\n') as f:
                f.writelines(lines)
            
            logging.info("[AUTH] Arquivo .env atualizado com sucesso.")
            
        except Exception as e:
            logging.error(f"[ERROR] Falha ao atualizar o arquivo .env: {e}")