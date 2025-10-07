import os
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
from peft import LoraConfig, get_peft_model, TaskType
from trl import SFTTrainer
from datasets import load_dataset

# Configs (ajuste pro seu HF)
model_name = "google/gemma-2-2b-it"  # Seu modelo base
dataset_path = "training_data.jsonl"  # Do export acima
output_dir = "./glorpinia-lora"  # Pasta local pro modelo tunado
hf_token = os.getenv("HF_TOKEN")  # Seu token do .env
repo_name = "seu-username/glorpinia-custom"  # Repo HF privado (crie em huggingface.co)

# Carrega dataset (formato JSONL: [{"prompt": "...", "completion": "..."}])
dataset = load_dataset("json", data_files=dataset_path, split="train")

# Formata pro estilo Alpaca/Gemma (instrução + resposta)
def formatting_prompts_func(example):
    return f"### Instruction:\nComo Glorpinia, responda: {example['prompt']}\n\n### Response:\n{example['completion']}<|endoftext|>"

dataset = dataset.map(lambda x: {"text": formatting_prompts_func(x)})

# Tokenizer
tokenizer = AutoTokenizer.from_pretrained(model_name)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

# Model com quantização 4-bit (eficiente)
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    device_map="auto",
    load_in_4bit=True,  # QLoRA pra poupar memória
    trust_remote_code=True
)

# LoRA config (treina só adapters leves)
lora_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=16,  # Rank baixo pra eficiência
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj"]  # Módulos Gemma
)
model = get_peft_model(model, lora_config)

# Args de treino (ajuste epochs/batch pro seu hardware)
training_args = TrainingArguments(
    output_dir=output_dir,
    num_train_epochs=3,  # 1-5 pra teste; mais pra produção
    per_device_train_batch_size=4,  # Ajuste se OOM
    gradient_accumulation_steps=4,
    warmup_steps=100,
    logging_steps=10,
    save_steps=500,
    evaluation_strategy="no",  # Sem eval pra simplicidade
    report_to=None  # Sem wandb
)

# Trainer
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",  # Campo formatado
    max_seq_length=512,  # Limite tokens por amostra
    args=training_args,
    packing=True  # Otimiza batches
)

# Treina!
trainer.train()

# Salva local e push pro HF
model.save_pretrained(output_dir)
model.push_to_hub(repo_name, token=hf_token)
tokenizer.push_to_hub(repo_name, token=hf_token)

print(f"Modelo tunado salvo em {output_dir} e pushado pra {repo_name}!")