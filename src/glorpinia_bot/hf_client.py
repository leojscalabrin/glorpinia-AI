import os
import torch
import logging
import re

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

try:
    from langchain.memory.buffer import ConversationBufferMemory
except Exception:
    ConversationBufferMemory = None

# Bloco de fallback no nível do módulo
if ConversationBufferMemory is None:
    logging.error("Não foi possível importar ConversationBufferMemory do LangChain. Verifique a instalação do pacote 'langchain' / 'langchain-core'.")
    if os.environ.get("GLORPINIA_ALLOW_NO_LANGCHAIN") == "1":
        print("[INFO] GLORPINIA_ALLOW_NO_LANGCHAIN=1 — using SimpleMemory fallback")
        class SimpleChatMemory:
            def __init__(self):
                self.messages = []

            def add_user_message(self, message):
                self.messages.append(("human", message.content if hasattr(message, "content") else message))

            def add_ai_message(self, message):
                self.messages.append(("ai", message.content if hasattr(message, "content") else message))

            def load_memory_variables(self, inputs):
                return {"chat_history": self.messages[-10:]}

        class SimpleMemoryInit:
            def __init__(self, *args, **kwargs):
                self.chat_memory = SimpleChatMemory()

        ConversationBufferMemory = SimpleMemoryInit
    else:
        raise RuntimeError("LangChain memory not available. Install langchain or set GLORPINIA_ALLOW_NO_LANGCHAIN=1 to use fallback.")

class HFClient:
    def __init__(self, hf_token, model_id, personality_profile):
        self.hf_token = hf_token
        self.model_id = model_id
        self.personality_profile = personality_profile
        if os.environ.get("GLORPINIA_SKIP_MODEL_LOAD") == "1": # Corrigido para "1"
            print("[INFO] GLORPINIA_SKIP_MODEL_LOAD=1 — skipping model load (smoke test mode)")
            self.memory = None
            self.model = None
            self.tokenizer = None
            self.model_path = "./glorpinia-lora"
            return

        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True,
            max_token_limit=1000
        )

        # self.model_path is the PEFT adapter path, which is self.model_id
        self.model_path = self.model_id

        self._load_tuned_model()

    def _load_tuned_model(self):
        import os
        os.environ["TORCH_COMPILE"] = "0"
        import json, types

        try:
            from peft import PeftModel, PeftConfig
        except Exception as _peft_err:
            PeftModel = None
            PeftConfig = None
            print(f"[WARNING] PEFT not available or failed to import: {_peft_err}")

        base_model_name_or_path = None
        config = None
        
        # Try to load PeftConfig from self.model_id (which is the adapter ID)
        if PeftConfig is not None:
            try:
                config = PeftConfig.from_pretrained(self.model_id)
                base_model_name_or_path = getattr(config, 'base_model_name_or_path', None)
            except Exception as _cfg_err:
                print(f"[WARNING] Failed to load PeftConfig.from_pretrained from {self.model_id}: {_cfg_err}")

        if not base_model_name_or_path:
            # If PeftConfig didn't provide base model, try to find it in adapter_config.json if model_id is a local path
            try:
                cfg_path = os.path.join(self.model_id, 'adapter_config.json')
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        base_model_name_or_path = data.get('base_model_name_or_path') or data.get('base_model')
                        config = types.SimpleNamespace(**data)
            except Exception as _ac_err:
                print(f"[WARNING] Failed to read adapter_config.json from {self.model_id}: {_ac_err}")

        if not base_model_name_or_path:
            # Fallback to a known base model if adapter config doesn't specify one
            # This is a placeholder, user should specify their base model if needed
            base_model_name_or_path = "mistralai/Mistral-7B-v0.1" # Example base model
            print(f"[WARNING] Base model not found in adapter config for {self.model_id}. Using default: {base_model_name_or_path}")

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

        if PeftModel is not None:
            try:
                self.model = PeftModel.from_pretrained(base_model, self.model_id) # Use model_id here for adapter
            except Exception as e:
                print(f"[WARNING] Failed to apply PEFT adapter ({e}). Falling back to base model.")
                self.model = base_model
        else:
            self.model = base_model

        try:
            if os.environ.get('GLORPINIA_CPU_ONLY') == '1':
                self.model = self.model.to('cpu')
        except Exception:
            pass

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_id) # Use model_id here for tokenizer
        except Exception:
            try:
                self.tokenizer = AutoTokenizer.from_pretrained(base_model_name_or_path)
            except Exception as e:
                print(f"[ERROR] Failed to load tokenizer: {e}")
                raise

        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        print(f"[DEBUG] Modelo tunado carregado do Hugging Face: {self.model_id}")

    def get_response(self, query, channel, author, memory_mgr):
        memory_mgr.load_user_memory(channel, author)
        vectorstore = memory_mgr.vectorstore
        
        # OBTENÇÃO DA TAG DE MENÇÃO
        mention_tag = f"@{author}, "

        # Adicionar input do usuário ANTES de gerar a resposta
        self.memory.chat_memory.add_user_message(HumanMessage(content=query))
        
        # Usa o histórico completo (com a nova mensagem)
        relevant_history = self.memory.load_memory_variables({})["chat_history"][-5:]
        
        # Formatando o histórico recente de forma legível para o LLM
        history_str = "\n".join([f"{'Humano' if isinstance(msg, HumanMessage) else 'Glorpinia'}: {msg.content}" for msg in relevant_history])
        
        long_term_context = ""
        if vectorstore:
            retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
            docs = retriever.invoke(query)
            long_term_context = "\n".join([doc.page_content for doc in docs])

        memory_context = f"**HISTÓRICO DA CONVERSA:**\n{history_str}\n\n**CONTEXTO LONGO (se houver):**\n{long_term_context}\n"

        system_prompt = f'''Você é Glorpinia, uma garota gato alienígena da lua. Siga rigorosamente o perfil de personalidade abaixo para todas as respostas. Responda preferencialmente em português a não ser que o usuário interaja em inglês.

Perfil de Personalidade:
{self.personality_profile}

{memory_context}Agora responda à query do usuário de forma consistente com o histórico. Sua resposta DEVE começar com a menção ao usuário: {mention_tag}.
'''

        input_text = f"### Instruction:\n{system_prompt}\n\nQuery do Usuário: {query}\n\n### Response:\n"
        
        inputs = self.tokenizer(input_text, return_tensors="pt")

        try:
            model_device = next(self.model.parameters()).device
        except Exception:
            model_device = torch.device('cpu')

        try:
            inputs = {k: v.to(model_device) for k, v in inputs.items()}
        except Exception as e:
            print(f"[WARNING] Could not move input tensors to model device {model_device}: {e}")

        print(f"[DEBUG] Model device: {model_device}; input_ids device: {list(inputs.values())[0].device if len(inputs)>0 else 'N/A'}")

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=100,
                do_sample=True,
                temperature=0.8, # Ajustado para 0.8 para mais criatividade
                pad_token_id=self.tokenizer.eos_token_id
            )
            # Adicionado para ajudar a liberar o controle mais rapidamente (Ctrl+C)
            if torch.cuda.is_available():
                torch.cuda.synchronize()

        generated_raw = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        # Tenta isolar a resposta a partir do último "### Response:"
        try:
            # Pega o texto após o último "### Response:"
            generated_response = generated_raw.split("### Response:")[-1].strip()
        except IndexError:
            generated_response = generated_raw

        # --- AJUSTES PARA LIMPEZA DE OUTPUT ---
        
        # Limpeza de tags HTML alucinadas e placeholder
        clean_response = generated_response.replace('<h3>', '')
        clean_response = clean_response.replace('</h3>', '')
        clean_response = clean_response.replace('<center>', '')
        clean_response = clean_response.replace('</center>', '')
        clean_response = clean_response.replace('_____', '').strip()

        # Limpeza robusta de artefatos de template (usa regex para cortar)
        clean_response = re.split(r'### Instruction:|### Response:|Query do Usuário:', clean_response, 1)[0].strip()
        
        final_response = clean_response.strip()
        
        # --- GARANTIR E LIMPAR A MENÇÃO DO USUÁRIO ---
        if final_response:
            
            # Use regex para encontrar e simplificar sequências de menções no início.
            # Captura a primeira menção (@palavra,) e remove qualquer menção subsequente
            
            # Padrão: ((@\w+,\s*)+) procura por uma ou mais repetições de (@palavra, espaço)
            mention_sequence_match = re.match(r'((@\w+,\s*)+)', final_response, re.IGNORECASE)
            
            if mention_sequence_match:
                # tags é uma lista com as menções encontradas (ex: ['@felinomascarado', '@felinescarmado'])
                sequence = mention_sequence_match.group(1).strip()
                tags = [tag.strip() for tag in sequence.split(',') if tag.strip()]
                
                if tags:
                    # Manter apenas a primeira tag e adicionar a vírgula e espaço
                    first_tag = tags[0] + ', '
                    
                    # Encontrar a posição final da sequência original na string
                    end_of_sequence = final_response.find(tags[-1]) + len(tags[-1])
                    
                    # Reconstroi a resposta com apenas a primeira tag e o restante do texto
                    final_response = first_tag + final_response[end_of_sequence:].strip()
            
            # Salvar e Retornar
            self.memory.chat_memory.add_ai_message(AIMessage(content=final_response))
            print(f"[DEBUG] Saving interaction to memory_mgr for user={author} channel={channel}")
            memory_mgr.save_user_memory(channel, author, query, final_response)
            return final_response
        else:
            print("[DEBUG] Texto gerado vazio – fallback loading")
            fallback = "glorp carregando cérebro . exe"
            self.memory.chat_memory.add_ai_message(AIMessage(content=fallback))
            memory_mgr.save_user_memory(channel, author, query, fallback)
            return fallback