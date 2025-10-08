import os
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments
from peft import LoraConfig, get_peft_model, TaskType
from trl import SFTTrainer
from datasets import load_dataset

# Configs
model_name = "google/gemma-2-2b-it"
dataset_path = "training_data.jsonl"
output_dir = "./glorpinia-lora"
hf_token = os.getenv("HF_TOKEN_WRITE")  # Opcional: Só pra push

# Carrega dataset
dataset = load_dataset("json", data_files=dataset_path, split="train")

# Formata pro estilo Gemma
def formatting_prompts_func(example):
    return f"### Instruction:\nComo Glorpinia, responda: {example['prompt']}\n\n### Response:\n{example['completion']}<|endoftext|>"

dataset = dataset.map(lambda x: {"text": formatting_prompts_func(x)})

# Tokenizer
tokenizer = AutoTokenizer.from_pretrained(model_name)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

# Model com quantização 4-bit
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    device_map="cuda",
    load_in_4bit=True,
    torch_dtype=torch.bfloat16,
    trust_remote_code=True
)

# LoRA config
lora_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj", "v_proj", "k_proj", "o_proj"]
)
model = get_peft_model(model, lora_config)

# Args de treino
training_args = TrainingArguments(
    output_dir=output_dir,
    num_train_epochs=3,
    per_device_train_batch_size=4,
    gradient_accumulation_steps=4,
    warmup_steps=50,
    logging_steps=10,
    save_steps=50,
    save_total_limit=2,
    evaluation_strategy="no",
    report_to=None,
    fp16=True,
    optim="adamw_torch_fused",
    learning_rate=2e-5
)

# Trainer
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=512,
    args=training_args,
    packing=True
)

trainer.train()

# Salva localmente
model.save_pretrained(output_dir)
tokenizer.save_pretrained(output_dir)

# Opcional: Push pro HF
if hf_token:
    model.push_to_hub("felinomascarado/glorpinia-custom", token=hf_token)
    tokenizer.push_to_hub("felinomascarado/glorpinia-custom", token=hf_token)

print(f"Modelo tunado salvo em {output_dir}!")

# Teste local após treino
def test_model():
    print("\n[TESTE] Verificando modelo tunado...")
    prompt = "Oi Glorpinia, me conte uma piada"
    inputs = tokenizer(f"### Instruction:\nComo Glorpinia, responda: {prompt}\n\n### Response:\n", return_tensors="pt").to("cuda")
    outputs = model.generate(**inputs, max_new_tokens=100, do_sample=True, temperature=0.7)
    print(tokenizer.decode(outputs[0], skip_special_tokens=True))

test_model()