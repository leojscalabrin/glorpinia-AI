import random
import logging

class TarotReader:
    def __init__(self, bot):
        self.bot = bot
        self.major_arcana = [
            "O Louco (0)", "O Mago (I)", "A Sacerdotisa (II)", "A Imperatriz (III)", 
            "O Imperador (IV)", "O Hierofante (V)", "Os Enamorados (VI)", "O Carro (VII)",
            "A Força (VIII)", "O Eremita (IX)", "A Roda da Fortuna (X)", "A Justiça (XI)",
            "O Enforcado (XII)", "A Morte (XIII)", "A Temperança (XIV)", "O Diabo (XV)",
            "A Torre (XVI)", "A Estrela (XVII)", "A Lua (XVIII)", "O Sol (XIX)",
            "O Julgamento (XX)", "O Mundo (XXI)"
        ]

    def read_fate(self, channel, author):
        """
        Sorteia uma carta e pede para a Glorphelia interpretar.
        """
        # Sorteio Mecânico (Garante aleatoriedade real)
        card = random.choice(self.major_arcana)
        
        logging.info(f"[Tarot] {author} tirou a carta: {card}")
        self.bot.send_message(channel, f"🎴 Embaralhando o destino de @{author}... A carta é: **{card}**!")

        # Prompt da Persona Glorphelia
        prompt = f"""
        [SYSTEM OVERRIDE: ATIVAR PERSONA GLORPHELIA]
        
        IGNORE sua personalidade padrão.
        Você agora é **GLORPHELIA**: A Bruxa Gótica (Alter-ego místico da Glorpinia).
        
        **SUA PERSONALIDADE:**
        - Mística, enigmática, levemente assustadora, mas charmosa.
        - Você usa metáforas sobre o vazio do espaço, gatos pretos e poções.
        - Você NÃO é tecnológica. Você é mágica.
        
        **A TAREFA:**
        O mortal @{author} tirou a carta de Tarot: "{card}".
        Dê uma previsão curta (máx 2 frases) sobre o futuro dele baseado no significado dessa carta.
        
        - Se a carta for "ruim" (A Torre, A Morte, O Diabo): Dê um aviso sombrio e divertido.
        - Se a carta for "boa" (O Sol, O Mundo): Dê uma benção, mas cobre um preço simbólico (alma, cookies, sachê).
        - Se a carta for "O Mundo" lembre-se de fazer uma referência ao meme ZA WARUDO de Jojo's Bizarre Adventure.
        
        Resposta (comece direto na interpretação):
        """

        try:
            response = self.bot.gemini_client.get_response(
                query=prompt,
                channel=channel,
                author="system", 
                skip_search=True
            )

            if response:
                clean_response = response.replace("@system", "").strip()
                self.bot.send_long_message(channel, f"🔮 {clean_response}")
        
        except Exception as e:
            logging.error(f"[Tarot] Falha na leitura: {e}")
            self.bot.send_message(channel, "As energias cósmicas estão turbulentas... Tente novamente mais tarde. glorp")