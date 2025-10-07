from dotenv import load_dotenv
import os
import requests

class TwitchAuth:
    def __init__(self):
        load_dotenv()

        self.access_token = os.getenv("TWITCH_TOKEN").replace("oauth:", "") if os.getenv("TWITCH_TOKEN") else None
        self.refresh_token_value = os.getenv("TWITCH_REFRESH_TOKEN")
        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")
        self.bot_nick = os.getenv("TWITCH_BOT_NICK")
        self.hf_token = os.getenv("HF_TOKEN_READ")
        self.model_id = os.getenv("HF_MODEL_ID")

        # Extrai canais
        channels_str = os.getenv("TWITCH_CHANNELS")
        if channels_str:
            self.channels = [c.strip() for c in channels_str.split(",") if c.strip()]
        else:
            raise ValueError("Missing TWITCH_CHANNELS environment variable in .env file")

        # Checks de vars requeridas (presença básica)
        if not all([self.access_token, self.bot_nick, self.hf_token, self.model_id]):
            raise ValueError("Missing required environment variables in .env file")

        # Warning só pra refresh
        if not all([self.client_id, self.client_secret, self.refresh_token_value]):
            self._refresh_warning = True  # Flag pra usar em refresh
        else:
            self._refresh_warning = False

        # Carrega perfil de personalidade
        self.personality_profile = self.load_personality_profile()

    def load_personality_profile(self):
        """Carrega o perfil de personalidade de um arquivo TXT separado."""
        try:
            with open("glorpinia_profile.txt", "r", encoding="utf-8") as f:
                profile = f.read().strip()
            print("[INFO] Perfil de personalidade carregado de glorpinia_profile.txt.")
            return profile
        except FileNotFoundError:
            print("[WARNING] Arquivo glorpinia_profile.txt não encontrado. Usando perfil vazio.")
            return ""

    def validate_and_refresh_token(self):
        """Valida o access token e renova se inválido ou expirado."""
        if self._refresh_warning:
            print("[WARNING] Client ID, Secret ou Refresh Token ausentes. Renovação automática pode falhar.")
        
        if not self.validate_token():
            print("[INFO] Token inválido ou expirado. Renovando...")
            if self.refresh_token_value:
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
        if not self.refresh_token_value:
            print("[ERROR] Sem refresh_token no .env. Gere um novo.")
            return None

        old_access_token = self.access_token
        old_refresh_token = self.refresh_token_value

        url = "https://id.twitch.tv/oauth2/token"
        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token_value,
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        try:
            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                new_tokens = response.json()
                self.access_token = new_tokens["access_token"]
                new_refresh_token = new_tokens["refresh_token"]
                print(f"[INFO] Token renovado! Expira em {new_tokens['expires_in']}s. Novo token: {self.access_token[:10]}...")

                if self.access_token != old_access_token or new_refresh_token != old_refresh_token:
                    self.update_env_file(self.access_token, new_refresh_token)
                return self.access_token
            else:
                print(f"[ERROR] Falha na renovação: {response.status_code} - {response.text}")
                return None
        except requests.RequestException as e:
            print(f"[ERROR] Erro na renovação: {e}")
            return None

    def update_env_file(self, new_access_token, new_refresh_token):
        """Atualiza o arquivo .env com os novos tokens."""
        try:
            with open(".env", "r", encoding="utf-8") as f:
                lines = f.readlines()

            lines = [line for line in lines if not line.strip().startswith("TWITCH_TOKEN=") and not line.strip().startswith("TWITCH_REFRESH_TOKEN=")]
            lines = [line.rstrip('\r\n') + '\n' for line in lines if line.strip()]

            lines.append(f"TWITCH_TOKEN=oauth:{new_access_token}\n")
            lines.append(f"TWITCH_REFRESH_TOKEN={new_refresh_token}\n")
            lines.append("\n")

            with open(".env", "w", encoding="utf-8", newline='\n') as f:
                f.writelines(lines)

            print("[INFO] Arquivo .env atualizado com novos tokens.")
        except Exception as e:
            print(f"[ERROR] Falha ao atualizar .env: {e}. Tokens renovados, mas .env não foi modificado.")