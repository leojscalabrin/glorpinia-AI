import torch
from langchain.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel, PeftConfig
from transformers import BitsAndBytesConfig

class HFClient:
    def __init__(self, hf_token, model_id, personality_profile):
        self.hf_token = hf_token
        self.model_id = model_id  # Não usado mais, mas mantido por compatibilidade
        self.personality_profile = personality_profile
        
        # Memória short-term: Buffer simples (últimas trocas)
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True,
            max_token_limit=1000  # Limita pra caber no prompt
        )
        
        # Caminho do modelo tunado local
        self.model_path = "./glorpinia-lora"
        
        # Carrega o modelo tunado
        self._load_tuned_model()

    def _load_tuned_model(self):
        """Carrega o modelo tunado localmente de ./glorpinia-lora."""
        import os
        os.environ["TORCH_COMPILE"] = "0"  # Desativa torch.compile para evitar conflitos
        
        config = PeftConfig.from_pretrained(self.model_path)
        
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True
        )
        
        base_model = AutoModelForCausalLM.from_pretrained(
            config.base_model_name_or_path,
            quantization_config=quant_config,
            trust_remote_code=True,
            token=self.hf_token
        )
        
        self.model = PeftModel.from_pretrained(base_model, self.model_path)
        self.model = self.model.to("cuda:0")
        
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        
        print(f"[DEBUG] Modelo tunado carregado localmente de {self.model_path} em cuda:0")

    def get_response(self, query, channel, author, memory_mgr):
        """Gera resposta usando o modelo local tunado, integrando memória short/long-term."""
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

        input_text = f"### Instruction:\n{system_prompt}\n\n### Response:\n{query}"
        inputs = self.tokenizer(input_text, return_tensors="pt").to("cuda:0")

        # Gera a resposta
        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=100,
                do_sample=True,
                temperature=0.7,
                pad_token_id=self.tokenizer.eos_token_id
            )

        generated = self.tokenizer.decode(outputs[0], skip_special_tokens=True).split("### Response:\n")[-1].strip()
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