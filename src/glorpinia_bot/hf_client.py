import requests
import time
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage

class HFClient:
    def __init__(self, hf_token, model_id, personality_profile):
        self.hf_token = hf_token
        self.model_id = model_id
        self.personality_profile = personality_profile
        
        # Memória short-term: Buffer simples (últimas trocas)
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True,
            max_token_limit=1000  # Limita pra caber no prompt
        )
        
        self.API_URL = "https://router.huggingface.co/v1/chat/completions"

    def get_response(self, query, channel, author, memory_mgr):
        """Gera resposta via HF API, integrando memória short/long-term."""
        headers = {
            "Authorization": f"Bearer {self.hf_token}",
            "Content-Type": "application/json"
        }

        # Carrega memória long-term específica do usuário/canal (via memory_mgr)
        memory_mgr.load_user_memory(channel, author)
        vectorstore = memory_mgr.vectorstore  # Acessa o carregado
        
        # Adiciona mensagem atual ao short-term
        self.memory.chat_memory.add_user_message(HumanMessage(content=query))
        self.memory.chat_memory.add_ai_message(AIMessage(content=""))  # Placeholder

        # Recupera contexto relevante (short + long-term via RAG)
        relevant_history = self.memory.load_memory_variables({})["chat_history"][-5:]  # Últimas 5 trocas
        long_term_context = ""
        if vectorstore:
            retriever = vectorstore.as_retriever(search_kwargs={"k": 3})  # Top 3 chunks antigos
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
                response = requests.post(self.API_URL, headers=headers, json=payload, timeout=30)
                response.raise_for_status()
                result = response.json()
                print(f"[DEBUG] Resposta bruta da HF API: {result}")
                
                if 'choices' in result and len(result['choices']) > 0:
                    generated = result['choices'][0]['message']['content'].strip()
                    if generated:
                        # Atualiza memória short-term
                        self.memory.chat_memory.add_ai_message(AIMessage(content=generated))
                        # Salva para long-term (via memory_mgr)
                        memory_mgr.save_user_memory(channel, author, query, generated)
                        return generated
                    else:
                        print("[DEBUG] Texto gerado vazio – fallback loading")
                        fallback = "glorp carregando cérebro . exe"
                        self.memory.chat_memory.add_ai_message(AIMessage(content=fallback))
                        memory_mgr.save_user_memory(channel, author, query, fallback)
                        return fallback
                else:
                    print("[DEBUG] Resultado inválido ou vazio – fallback loading")
                    fallback = "glorp carregando cérebro . exe"
                    self.memory.chat_memory.add_ai_message(AIMessage(content=fallback))
                    memory_mgr.save_user_memory(channel, author, query, fallback)
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
                    memory_mgr.save_user_memory(channel, author, query, fallback)
                    return fallback

        # Fallback final
        fallback = "glorp deu ruim"
        self.memory.chat_memory.add_ai_message(AIMessage(content=fallback))
        memory_mgr.save_user_memory(channel, author, query, fallback)
        return fallback