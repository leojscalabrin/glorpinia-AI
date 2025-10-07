import os
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
from peft import LoraConfig, get_peft_model, TaskType
from trl import SFTTrainer
from datasets import load_dataset

# Configs
model_name = "google/gemma-2-2b-it"
dataset_path = "training_data.jsonl"
output_dir = "./glorpinia-lora"
hf_token = os.getenv("HF_TOKEN_WRITE")
repo_name = "felinomascarado/glorpinia-custom"

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
    load_in_4bit=True,
    trust_remote_code=True
)

# LoRA config
lora_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj"]  # Módulos Gemma
)
model = get_peft_model(model, lora_config)

# Args de treino
training_args = TrainingArguments(
    output_dir=output_dir,
    num_train_epochs=3,  # 1-5 pra teste; mais pra produção
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,
    warmup_steps=100,
    logging_steps=10,
    save_steps=500,
    evaluation_strategy="no",
    report_to=None
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

trainer.train()

# Salva local e push pro HF
model.save_pretrained(output_dir)
model.push_to_hub(repo_name, token=hf_token)
tokenizer.push_to_hub(repo_name, token=hf_token)

print(f"Modelo tunado salvo em {output_dir} e pushado pra {repo_name}!")