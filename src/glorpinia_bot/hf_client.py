import os
import torch
import logging

# Inicialize variáveis fora dos try-except para evitar UnboundLocalError
ConversationBufferMemory = None
HumanMessage = None
AIMessage = None
BitsAndBytesConfig = None

try:
    from langchain.memory import ConversationBufferMemory
except Exception:
    try:
        from langchain.chains.conversation.memory import ConversationBufferMemory
    except Exception:
        ConversationBufferMemory = None

try:
    from langchain.schema import HumanMessage, AIMessage
except Exception:
    try:
        from langchain_core.messages import HumanMessage, AIMessage
    except Exception:
        HumanMessage = None
        AIMessage = None

from transformers import AutoModelForCausalLM, AutoTokenizer

try:
    from transformers import BitsAndBytesConfig
except Exception:
    BitsAndBytesConfig = None

# Bloco de fallback no nível do módulo
# ... (end of your import try-except blocks)

# Bloco de fallback no nível do módulo
if ConversationBufferMemory is None:
    logging.error("Não foi possível importar ConversationBufferMemory do LangChain. Verifique a instalação do pacote 'langchain' / 'langchain-core'.")
    # Optional override to allow running without langchain in minimal/test environments
    if os.environ.get('GLORPINIA_ALLOW_NO_LANGCHAIN') == '1':
        print('[INFO] GLORPINIA_ALLOW_NO_LANGCHAIN=1 — using SimpleMemory fallback')
        class SimpleChatMemory:
            def __init__(self):
                self.messages = []  # Lista simples para armazenar mensagens

            def add_user_message(self, message):
                self.messages.append(("human", message.content if hasattr(message, 'content') else message))

            def add_ai_message(self, message):
                self.messages.append(("ai", message.content if hasattr(message, 'content') else message))

            # Simule load_memory_variables para compatibilidade
            def load_memory_variables(self, inputs):
                return {"chat_history": self.messages[-10:]}  # Últimas 10 mensagens, por exemplo

        class SimpleMemoryInit:
            def __init__(self, *args, **kwargs):
                self.chat_memory = SimpleChatMemory()

        ConversationBufferMemory = SimpleMemoryInit
    else:
        raise RuntimeError("LangChain memory not available. Install langchain or set GLORPINIA_ALLOW_NO_LANGCHAIN=1 to use fallback.")

class HFClient:
    def __init__(self, hf_token, model_id, personality_profile):
        self.hf_token = hf_token
        self.model_id = model_id  # Não usado mais, mas mantido por compatibilidade
        self.personality_profile = personality_profile
        # Smoke-test / CI opt-out: if set, skip heavy model loading so we can
        # import/instantiate HFClient without downloading or loading large models.
        # Use: set environment variable GLORPINIA_SKIP_MODEL_LOAD=1
        if os.environ.get("GLORPINIA_SKIP_MODEL_LOAD") == "1":
            print("[INFO] GLORPINIA_SKIP_MODEL_LOAD=1 — skipping model load (smoke test mode)")
            # Create minimal attributes so other code can introspect without failing.
            self.memory = None
            self.model = None
            self.tokenizer = None
            self.model_path = "./glorpinia-lora"
            return

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
        import json, types

        # Import PEFT lazily and handle missing peft gracefully
        try:
            from peft import PeftModel, PeftConfig
        except Exception as _peft_err:
            PeftModel = None
            PeftConfig = None
            print(f"[WARNING] PEFT not available or failed to import: {_peft_err}")

        # Try to discover base model name from the adapter config (PEFT config or adapter_config.json)
        base_model_name_or_path = None
        config = None
        if PeftConfig is not None:
            try:
                config = PeftConfig.from_pretrained(self.model_path)
                base_model_name_or_path = getattr(config, 'base_model_name_or_path', None)
            except Exception as _cfg_err:
                print(f"[WARNING] Failed to load PeftConfig.from_pretrained: {_cfg_err}")

        if not base_model_name_or_path:
            try:
                cfg_path = os.path.join(self.model_path, 'adapter_config.json')
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        base_model_name_or_path = data.get('base_model_name_or_path') or data.get('base_model')
                        config = types.SimpleNamespace(**data)
            except Exception as _ac_err:
                print(f"[WARNING] Failed to read adapter_config.json: {_ac_err}")

        if not base_model_name_or_path:
            # Last resort: assume model_path points to a model repo
            base_model_name_or_path = self.model_path

        # Prepare quantization config if available
        quant_config = None
        if BitsAndBytesConfig is not None and os.environ.get('GLORPINIA_DISABLE_QUANTIZATION') != '1':
            try:
                quant_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.bfloat16,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True
                )
            except Exception as e:
                print(f"[WARNING] Could not initialize BitsAndBytesConfig: {e}; loading without quantization")

        # Load base model (use quant_config if available)
        try:
            if quant_config is not None:
                base_model = AutoModelForCausalLM.from_pretrained(
                    base_model_name_or_path,
                    quantization_config=quant_config,
                    trust_remote_code=True,
                    token=self.hf_token
                )
            else:
                base_model = AutoModelForCausalLM.from_pretrained(
                    base_model_name_or_path,
                    trust_remote_code=True,
                    token=self.hf_token
                )
        except Exception as e:
            print(f"[ERROR] Failed to load base model '{base_model_name_or_path}': {e}")
            raise

        # If PEFT is available, try to wrap the base model with the adapter
        if PeftModel is not None:
            try:
                self.model = PeftModel.from_pretrained(base_model, self.model_path)
            except Exception as e:
                print(f"[WARNING] Failed to apply PEFT adapter ({e}). Falling back to base model.")
                self.model = base_model
        else:
            self.model = base_model

        # Move model to CPU (respect GLORPINIA_CPU_ONLY)
        try:
            if os.environ.get('GLORPINIA_CPU_ONLY') == '1':
                self.model = self.model.to('cpu')
        except Exception:
            pass

        # Load tokenizer (try adapter path first, then base model)
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        except Exception:
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(base_model_name_or_path)
            except Exception as e:
                print(f"[ERROR] Failed to load tokenizer: {e}")
                raise

        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        print(f"[DEBUG] Modelo tunado carregado localmente de {self.model_path}")

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
        # Tokenize (keep tensors on CPU initially) and then move to the model's device
        inputs = self.tokenizer(input_text, return_tensors="pt")

        # Determine model device (fallback to cpu)
        try:
            model_device = next(self.model.parameters()).device
        except Exception:
            model_device = torch.device('cpu')

        # Move inputs to the same device as the model to avoid mismatches
        try:
            inputs = {k: v.to(model_device) for k, v in inputs.items()}
        except Exception as e:
            print(f"[WARNING] Could not move input tensors to model device {model_device}: {e}")

        print(f"[DEBUG] Model device: {model_device}; input_ids device: {list(inputs.values())[0].device if len(inputs)>0 else 'N/A'}")

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
            print(f"[DEBUG] Saving interaction to memory_mgr for user={author} channel={channel}")
            memory_mgr.save_user_memory(channel, author, query, generated)
            return generated
        else:
            print("[DEBUG] Texto gerado vazio – fallback loading")
            fallback = "glorp carregando cérebro . exe"
            self.memory.chat_memory.add_ai_message(AIMessage(content=fallback))
            memory_mgr.save_user_memory(channel, author, query, fallback)
            return fallback