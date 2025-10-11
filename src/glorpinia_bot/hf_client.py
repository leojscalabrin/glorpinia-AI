import os
import torch
import logging
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

# Do not import PEFT at module import time because some peft versions
# import transformers symbols that may not exist with the installed
# transformers package. Import PEFT lazily inside _load_tuned_model
# and handle its absence
try:
    from transformers import BitsAndBytesConfig
except Exception:
    BitsAndBytesConfig = None

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
        if ConversationBufferMemory is None:
            logging.error("Não foi possível importar ConversationBufferMemory do LangChain. Verifique a instalação do pacote 'langchain' / 'langchain-core'.")
            # Optional override to allow running without langchain in minimal/test environments
            if os.environ.get('GLORPINIA_ALLOW_NO_LANGCHAIN') == '1':
                print('[INFO] GLORPINIA_ALLOW_NO_LANGCHAIN=1 — using SimpleMemory fallback')
                class SimpleMemoryInit:
                    def __init__(self):
                        self.chat_history = []
                        class ChatMem:
                            def __init__(self, outer):
                                self.outer = outer
                            def add_user_message(self, msg):
                                content = getattr(msg, 'content', str(msg))
                                self.outer.chat_history.append(type('Msg', (), {'content': content}))
                            def add_ai_message(self, msg):
                                content = getattr(msg, 'content', str(msg))
                                self.outer.chat_history.append(type('Msg', (), {'content': content}))
                        self.chat_memory = ChatMem(self)
                    def load_memory_variables(self, _):
                        return {'chat_history': self.chat_history}

                self.memory = SimpleMemoryInit()
            else:
                raise ImportError("ConversationBufferMemory não disponível — instale uma versão compatível do LangChain.")
        else:
            self.memory = ConversationBufferMemory(
                memory_key="chat_history",
                return_messages=True,
                max_token_limit=1000  # Limita pra caber no prompt
            )

        # Caminho do modelo tunado local
        # Default to local adapter directory, but allow overriding via env var HF_MODEL_ID
        self.model_path = os.environ.get('HF_MODEL_ID', "./glorpinia-lora")
        # If a path-like env var was provided, normalize relative paths
        try:
            if isinstance(self.model_path, str) and self.model_path.startswith('./'):
                self.model_path = os.path.abspath(self.model_path)
        except Exception:
            pass

        # Carrega o modelo tunado
        self._load_tuned_model()

    def _load_tuned_model(self):
        """Carrega o modelo tunado localmente de ./glorpinia-lora."""
        import os
        import json
        import types
        os.environ["TORCH_COMPILE"] = "0"  # Desativa torch.compile para evitar conflitos

        # Determine runtime device: allow forcing CPU-only for cloud hosting
        cpu_only = os.environ.get('GLORPINIA_CPU_ONLY') == '1'
        if cpu_only:
            preferred_device = torch.device('cpu')
        else:
            preferred_device = torch.device('cuda:0') if torch.cuda.is_available() else torch.device('cpu')
        
        # Import PEFT lazily to avoid top-level import errors for incompatible
        # transformers/peft combinations. If PEFT isn't available, we'll try
        # to read adapter_config.json directly to discover the base model.
        try:
            from peft import PeftModel, PeftConfig
        except Exception as _peft_err:
            PeftModel = None
            PeftConfig = None
            print(f"[WARNING] PEFT not available or failed to import: {_peft_err}")

        config = None
        base_model_name_or_path = None
        if PeftConfig is not None:
            try:
                config = PeftConfig.from_pretrained(self.model_path)
                base_model_name_or_path = getattr(config, 'base_model_name_or_path', None)
            except Exception as _cfg_err:
                print(f"[WARNING] Failed to load PeftConfig.from_pretrained: {_cfg_err}")

        # If we still don't have a base model name, try reading adapter_config.json
        if not base_model_name_or_path:
            try:
                cfg_path = os.path.join(self.model_path, 'adapter_config.json')
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r', encoding='utf-8') as _f:
                        data = json.load(_f)
                        base_model_name_or_path = data.get('base_model_name_or_path') or data.get('base_model')
                        # Create a minimal config-like object for later fallbacks
                        config = types.SimpleNamespace(**data)
            except Exception as _ac_err:
                print(f"[WARNING] Failed to read adapter_config.json: {_ac_err}")

        # Final fallback: use model_path directly
        if not base_model_name_or_path:
            base_model_name_or_path = self.model_path
        
        quant_config = None
        # Allow forcing no-quantization mode via environment variable to avoid bitsandbytes on Windows
        if os.environ.get('GLORPINIA_DISABLE_QUANTIZATION') == '1':
            print('[INFO] GLORPINIA_DISABLE_QUANTIZATION=1 — forcing non-quantized model load')
            quant_config = None
        else:
            if BitsAndBytesConfig is not None:
                try:
                    quant_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.bfloat16,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_use_double_quant=True
                    )
                except Exception as e:
                    print(f"[WARNING] Não foi possível inicializar BitsAndBytesConfig (bnb ausente ou incompatível): {e}. Carregando sem quantização.")

        # Carrega o base model — usa quant_config apenas se disponível
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
        # On Windows, bitsandbytes may try to access torch.compiler.is_compiling or
        # torch._C._has_xpu which aren't present in some torch builds. Add a small
        # shim to avoid AttributeError during import of bitsandbytes/peft.
        try:
            import sys as _sys
            if _sys.platform == 'win32':
                import types as _types
                try:
                    if not hasattr(torch, 'compiler') or not hasattr(torch.compiler, 'is_compiling'):
                        # ensure a callable exists
                        torch.compiler = getattr(torch, 'compiler', _types.SimpleNamespace())
                        setattr(torch.compiler, 'is_compiling', lambda: False)
                    # torch._C is a C-extension module; adding attributes is allowed
                    if not hasattr(torch._C, '_has_xpu'):
                        setattr(torch._C, '_has_xpu', False)
                    print('[INFO] Applied Windows shims for torch.compiler/is_compiling and torch._C._has_xpu')
                except Exception as _shim_exc:
                    print(f'[WARNING] Could not apply Windows bitsandbytes shims: {_shim_exc}')
        except Exception:
            pass

        # Try to apply PEFT adapter if available
        if 'PeftModel' in locals() and PeftModel is not None:
            try:
                self.model = PeftModel.from_pretrained(base_model, self.model_path)
                # Move model to preferred device
                try:
                    self.model = self.model.to(preferred_device)
                except Exception:
                    # fallback to cpu
                    self.model = self.model.to(torch.device('cpu'))
            except Exception as e:
                print(f"[WARNING] Failed to apply PEFT adapter ({e}). Falling back to base model without adapter.")
                self.model = base_model
                try:
                    self.model = self.model.to(preferred_device)
                except Exception:
                    self.model = self.model.to(torch.device('cpu'))
        else:
            print('[INFO] PEFT not installed — using base model without adapter')
            self.model = base_model
            try:
                self.model = self.model.to(preferred_device)
            except Exception:
                self.model = self.model.to(torch.device('cpu'))

        # Expose the device for callers
        try:
            params = next(self.model.parameters())
            self.device = params.device
        except StopIteration:
            self.device = torch.device('cpu')
        
        # Try loading tokenizer from adapter path; fall back to base model tokenizer
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        except Exception as e_tok:
            print(f"[WARNING] Failed to load tokenizer from adapter path ({e_tok}); trying base model tokenizer")
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(config.base_model_name_or_path)
            except Exception as e_tok2:
                print(f"[WARNING] Failed to load base model tokenizer ({e_tok2}); falling back to gpt2 tokenizer")
                self.tokenizer = AutoTokenizer.from_pretrained('gpt2')

        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        
        print(f"[DEBUG] Modelo tunado carregado localmente de {self.model_path} em cuda:0")

    def get_response(self, query, channel, author, memory_mgr):
        """Gera resposta usando o modelo local tunado, integrando memória short/long-term."""
        # Carrega memória long-term específica do usuário/canal (via memory_mgr)
        memory_mgr.load_user_memory(channel, author)
        vectorstore = memory_mgr.vectorstore  # Acessa o carregado

        # If client was instantiated in skip-model-load mode self.memory may be None.
        # Provide a minimal in-memory fallback so get_response can run in tests.
        if self.memory is None:
            class SimpleMemory:
                def __init__(self):
                    self.chat_history = []
                    class ChatMem:
                        def __init__(self, outer):
                            self.outer = outer
                        def add_user_message(self, msg):
                            content = getattr(msg, 'content', str(msg))
                            self.outer.chat_history.append(type('Msg', (), {'content': content}))
                        def add_ai_message(self, msg):
                            content = getattr(msg, 'content', str(msg))
                            self.outer.chat_history.append(type('Msg', (), {'content': content}))
                    self.chat_memory = ChatMem(self)
                def load_memory_variables(self, _):
                    return {'chat_history': self.chat_history}
            self.memory = SimpleMemory()

        # Helper to construct message objects compatible with or without langchain types
        def _make_human_msg(text):
            if HumanMessage is not None:
                try:
                    return HumanMessage(content=text)
                except Exception:
                    pass
            return type('Msg', (), {'content': text})

        def _make_ai_msg(text):
            if AIMessage is not None:
                try:
                    return AIMessage(content=text)
                except Exception:
                    pass
            return type('Msg', (), {'content': text})

        # Adiciona mensagem atual ao short-term
        self.memory.chat_memory.add_user_message(_make_human_msg(query))
        self.memory.chat_memory.add_ai_message(_make_ai_msg(""))  # Placeholder
        
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
        # Place inputs on the same device as the model (fallback to cpu)
        device = torch.device('cpu')
        if hasattr(self, 'model') and self.model is not None:
            try:
                params = next(self.model.parameters())
                device = params.device
            except StopIteration:
                # model has no parameters? keep cpu
                pass

        inputs = self.tokenizer(input_text, return_tensors="pt")
        try:
            inputs = {k: v.to(device) for k, v in inputs.items()}
        except Exception:
            # fallback: move whole batch if .to on dict not supported
            try:
                inputs = inputs.to(device)
            except Exception:
                pass

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
            # Atualiza memória short-term (use safe constructor when AIMessage may be missing)
            self.memory.chat_memory.add_ai_message(_make_ai_msg(generated))
            # Salva para long-term (via memory_mgr)
            memory_mgr.save_user_memory(channel, author, query, generated)
            return generated
        else:
            print("[DEBUG] Texto gerado vazio – fallback loading")
            fallback = "glorp carregando cérebro . exe"
            self.memory.chat_memory.add_ai_message(_make_ai_msg(fallback))
            memory_mgr.save_user_memory(channel, author, query, fallback)
            return fallback