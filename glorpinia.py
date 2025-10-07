from dotenv import load_dotenv
import os
import requests
import websocket
import time
import logging
import sqlite3
import signal
import sys
from langchain.memory import ConversationBufferMemory
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.messages import HumanMessage, AIMessage

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")

class TwitchIRC:
    def __init__(self):
        self.access_token = os.getenv("TWITCH_TOKEN").replace("oauth:", "")
        self.refresh_token_value = os.getenv("TWITCH_REFRESH_TOKEN")
        self.client_id = os.getenv("TWITCH_CLIENT_ID")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET")
        self.bot_nick = os.getenv("TWITCH_BOT_NICK")
        self.hf_token = os.getenv("HF_TOKEN_READ")
        self.model_id = os.getenv("HF_MODEL_ID")

        channels_str = os.getenv("TWITCH_CHANNELS")
        if channels_str:
            self.channels = [c.strip() for c in channels_str.split(",") if c.strip()]
        else:
            raise ValueError("Missing TWITCH_CHANNELS environment variable in .env file")

        if not all([self.access_token, self.bot_nick, self.hf_token, self.model_id]):
            raise ValueError("Missing required environment variables in .env file")

        if not all([self.client_id, self.client_secret, self.refresh_token_value]):
            print("[WARNING] Client ID, Secret ou Refresh Token ausentes. Renovação automática pode falhar.")

        self.personality_profile = self.load_personality_profile()
        self.ws = None
        self.running = False

        # Memória LangChain
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True,
            max_token_limit=1000
        )
        self.embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
        self.vectorstore = None
        self.db_path = "glorpinia_memory.db"
        self.init_memory_db()

        # Valida e renova token se necessário antes de iniciar
        self.validate_and_refresh_token()
        
        # Registra handler para shutdown
        signal.signal(signal.SIGINT, self._shutdown_handler)
        signal.signal(signal.SIGTERM, self._shutdown_handler)

    def init_memory_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS memories
                     (channel TEXT, user TEXT, vectorstore_path TEXT, last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        conn.close()

    def load_personality_profile(self):
        try:
            with open("glorpinia_profile.txt", "r", encoding="utf-8") as f:
                return f.read().strip()
        except FileNotFoundError:
            print("[WARNING] Arquivo glorpinia_profile.txt não encontrado. Usando perfil vazio.")
            return ""

    def validate_and_refresh_token(self):
        if not self.validate_token():
            print("[INFO] Token inválido ou expirado. Renovando...")
            if self.refresh_token_value:
                self.refresh_token()
            else:
                raise ValueError("Refresh token ausente no .env. Gere um novo token manualmente.")

    def validate_token(self):
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

    def load_user_memory(self, channel, user):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT vectorstore_path FROM memories WHERE channel=? AND user=?", (channel, user))
        result = c.fetchone()
        conn.close()
        if result:
            path = result[0]
            self.vectorstore = FAISS.load_local(path, self.embeddings, allow_dangerous_deserialization=True)
        else:
            self.vectorstore = None

    def save_user_memory(self, channel, user, query, response):
        doc = f"Usuário {user} em {channel}: {query} -> {response}"
        if self.vectorstore is None:
            self.vectorstore = FAISS.from_texts([doc], self.embeddings)
        else:
            self.vectorstore.add_texts([doc])
        path = f"memory_{channel}_{user}.faiss"
        self.vectorstore.save_local(path)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO memories (channel, user, vectorstore_path) VALUES (?, ?, ?)",
                  (channel, user, path))
        conn.commit()
        conn.close()

    def get_hf_response(self, query, channel, author):
        API_URL = "https://router.huggingface.co/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.hf_token}", "Content-Type": "application/json"}

        # Carrega memória específica do usuário/canal (long-term)
        self.load_user_memory(channel, author)
        
        # Adiciona mensagem atual ao short-term
        self.memory.chat_memory.add_user_message(HumanMessage(content=query))
        self.memory.chat_memory.add_ai_message(AIMessage(content=""))  # Placeholder; atualiza depois

        # Recupera contexto relevante (short + long-term via RAG)
        relevant_history = self.memory.load_memory_variables({})["chat_history"][-5:]  # Últimas 5 trocas
        long_term_context = ""
        if self.vectorstore:
            retriever = self.vectorstore.as_retriever(search_kwargs={"k": 3})  # Top 3 chunks antigos
            docs = retriever.invoke(query)
            long_term_context = "\n".join([doc.page_content for doc in docs])

        memory_context = f"Histórico recente: {' '.join([msg.content for msg in relevant_history])}\nContexto longo: {long_term_context}\n"

        # Prompt completo: Perfil de personalidade + memória + query
        system_prompt = f"""Você é Glorpinia, uma garota gato alienígena da lua. Siga rigorosamente o perfil de personalidade abaixo para todas as respostas. Responda preferencialmente em português a não ser que o usuário interaja em inglês.

Perfil de Personalidade:
{self.personality_profile}

{memory_context}Agora responda à query do usuário de forma consistente com o histórico."""

        user_message = f"{system_prompt} Query: {query}"
        messages = [{"role": "user", "content": user_message}]

        payload = {
            "model": self.model_id,
            "messages": messages,
            "max_tokens": 100,
            "temperature": 0.7,
            "stream": False
        }
        print(f'[DEBUG] Enviando para HF API (com memória): {user_message[:100]}...')

        # Retry simples para erros transitórios (até 3 tentativas)
        for attempt in range(3):
            try:
                response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                result = response.json()
                print(f"[DEBUG] Resposta bruta da HF API: {result}")
                
                if 'choices' in result and len(result['choices']) > 0:
                    generated = result['choices'][0]['message']['content'].strip()
                    if generated:
                        # Atualiza memória short-term
                        self.memory.chat_memory.add_ai_message(AIMessage(content=generated))
                        # Salva para long-term
                        self.save_user_memory(channel, author, query, generated)
                        return generated
                    else:
                        print("[DEBUG] Texto gerado vazio – fallback loading")
                        # Atualiza com fallback
                        self.memory.chat_memory.add_ai_message(AIMessage(content="glorp carregando cérebro . exe"))
                        self.save_user_memory(channel, author, query, "glorp carregando cérebro . exe")
                        return "glorp carregando cérebro . exe"
                else:
                    print("[DEBUG] Resultado inválido ou vazio – fallback loading")
                    fallback = "glorp carregando cérebro . exe"
                    self.memory.chat_memory.add_ai_message(AIMessage(content=fallback))
                    self.save_user_memory(channel, author, query, fallback)
                    return fallback
                    
            except requests.RequestException as e:
                print(f"[ERROR] Erro ao chamar HF API (tentativa {attempt + 1}): {e}")
                if attempt < 2:  # Espera 2s antes de retry
                    time.sleep(2)
                    continue
                else:
                    print("[DEBUG] Todas tentativas falharam – fallback erm")
                    fallback = "glorp sinal com a nave-mãe perdido"
                    self.memory.chat_memory.add_ai_message(AIMessage(content=fallback))
                    self.save_user_memory(channel, author, query, fallback)
                    return fallback

        fallback = "glorp deu ruim"
        self.memory.chat_memory.add_ai_message(AIMessage(content=fallback))
        self.save_user_memory(channel, author, query, fallback)
        return fallback

    def send_message(self, channel, message):
        if self.ws and self.ws.sock and self.ws.sock.connected:
            full_msg = f"PRIVMSG #{channel} :{message}\r\n"
            self.ws.send(full_msg)
            print(f"[SEND] {channel}: {message}")
        else:
            print(f"[ERROR] WebSocket não conectado. Não foi possível enviar: {message}")

    def on_message(self, ws, message):
        print(f"[IRC] {message.strip()}")
        if message.startswith("PING"):
            ws.send("PONG :tmi.twitch.tv\r\n")
            print("[PONG] Enviado para manter conexão viva.")
            return

        if "PRIVMSG" in message and "glorpinia" in message.lower():
            # Extrai autor e conteúdo da mensagem IRC
            parts = message.split(":", 2)
            if len(parts) >= 3:
                author_part = parts[1].split("!")[0]
                content = parts[2].strip()
                channel = message.split("#")[1].split(" :")[0] if "#" in message else self.channels[0]

                print(f"[CHAT] {author_part}: {content}")

                if author_part.lower() == self.bot_nick.lower():
                    print(f"[DEBUG] Ignorando mensagem do próprio bot: {content}")
                    return

                content_lower = content.lower()
                query = content_lower.replace("glorpinia", "", 1).replace("@glorpinia", "", 1).strip()
                print(f"[DEBUG] Menção a glorpinia detectada: {content}")
                print(f"[DEBUG] Query extraída para a IA: {query}")

                if query:
                    response = self.get_hf_response(query, channel, author_part)
                    print(f"[DEBUG] Resposta da IA: {response[:50]}...")
                    
                    # Divide resposta se > 200 chars e envia com delay de 5s
                    if len(response) > 200:
                        chunks = [response[i:i+200] for i in range(0, len(response), 200)]
                        for i, chunk in enumerate(chunks):
                            if i == 0:
                                self.send_message(channel, f"@{author_part} {chunk}")
                            else:
                                self.send_message(channel, chunk)  # Sem @ nas continuações
                            if i < len(chunks) - 1:  # Delay só entre chunks
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
        # Autentica com o token atual (pode ser renovado)
        ws.send(f"PASS oauth:{self.access_token}\r\n")
        ws.send(f"NICK {self.bot_nick}\r\n")
        print(f"[AUTH] Autenticando como {self.bot_nick} com token...")
        # Junta aos canais
        for channel in self.channels:
            ws.send(f"JOIN #{channel}\r\n")
            print(f"[JOIN] Tentando juntar ao canal: #{channel}")
        # Envia mensagem inicial após 2s
        time.sleep(2)
        for channel in self.channels:
            self.send_message(channel, "Wokege")
            
    def _shutdown_handler(self, signum, frame):
        print("[INFO] Sinal de shutdown recebido. Enviando mensagem de despedida...")
        goodbye_msg = "Bedge"
        for channel in self.channels:
            self.send_message(channel, goodbye_msg)
            time.sleep(1)  # Delay de 1s por canal pra envio seguro
        print("[INFO] Mensagem enviada. Encerrando...")
        self.ws.close()
        sys.exit(0)

    def run(self):
        self.running = True
        try:
            websocket.enableTrace(True)  # Para depuração detalhada (opcional, remova se quiser menos logs)
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