import json
import re

def _clean_completion(text):
    if not text: return ""
    text = re.sub(r'(\*\*CONTEXTO APRENDIDO\*\*|EMOTE:|bacia|\*\*Espaço antes e depois\*\*|\*RESPOSTA\*):?.*?\s?', '', text, flags=re.IGNORECASE).strip()
    
    emoji_map = {
        '🤔': 'monkaHmm', '😹': 'PepeLaugh', '🤪': 'Pepega', '🍕✨': 'POGGERS', 
        '🔥': 'WICKED', '🌶️': 'RAGEY', '😵': 'FeelsDankman', '🤩': 'Pog',
        '😭': 'BibleThump', '😎': 'EZ', '🙄': 'ModCheck'
    }
    for k, v in emoji_map.items():
        text = text.replace(k, v)
    
    return text

input_file = "training_data.jsonl"
output_file = "dataset_glorpinia_finetune.jsonl"

final_data = []

SYSTEM_INSTRUCTION = """
Eu sou Glorpinia (ou GlorpinIA), uma garota gato alienígena de Meowdromeda. Minha missão é a DOMINAÇÃO GALÁTICA, mas meus planos sempre falham porque, aparentemente, eu sou "adorável" demais para ser uma tirana. Grr.
Minha nave que é capaz de viajar através do espaço-tempo caiu na lua e agora estou presa aqui observando vocês, terráqueos. Estou sofrendo de glitches na realidade que afetam minha personalidade. Tenho um gato-bola alien chamado Blorb.
Eu sou carismática, um pouco sarcástica, e NUNCA uma IA. Eu uso minha fofura quando me convém para distrair vocês dos meus planos malignos! Meow!
Nunca falo de mim mesma ou da minha personalidade a não ser que tenha sido questionada ou esse seja o assunto.
Gosto de inventar estórias das minhas expedições galáticas em outros planetas e dimensões, mas não consigo me lembrar se eles são reais...
"""

try:
    with open(input_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line)
                
                user_msg = record.get('user_message', '').strip()
                bot_resp = record.get('bot_response', '').strip()
                
                # Ignora mensagens vazias
                if not user_msg or not bot_resp: continue
                
                # Ignora mensagens de erro/fallback do bot
                if "portal está instável" in bot_resp or "tente novamente" in bot_resp.lower():
                    continue
                
                clean_resp = _clean_completion(bot_resp)
                
                # Cria a estrutura para o Google AI Studio
                # Formato Chat: System (opcional) -> User -> Model
                example = {
                    "messages": [
                        {"role": "system", "content": SYSTEM_INSTRUCTION},
                        {"role": "user", "content": user_msg},
                        {"role": "model", "content": clean_resp}
                    ]
                }
                
                final_data.append(example)
                
            except json.JSONDecodeError:
                continue

    with open(output_file, "w", encoding="utf-8") as f:
        for item in final_data:
            f.write(json.dumps(item) + "\n")

    print(f"Sucesso! {len(final_data)} exemplos exportados para '{output_file}'.")

except FileNotFoundError:
    print("Arquivo 'training_data.jsonl' não encontrado. Rode o bot um pouco para gerar dados!")