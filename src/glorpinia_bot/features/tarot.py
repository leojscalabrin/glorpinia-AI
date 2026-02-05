import random
import logging
import time

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

    def read_fate(self, channel, requester, target_user=None):
        """
        Sorteia uma carta (podendo ser invertida) e pede para a Glorphelia interpretar.
        """
        subject = target_user.replace("@", "") if target_user else requester
        
        cost = 20
        if self.bot.cookie_system:
            if self.bot.cookie_system.get_cookies(requester) < cost:
                self.bot.send_message(channel, f"@{requester}, os espíritos exigem pagamento. Custa {cost} cookies! Stare")
                return
            self.bot.cookie_system.remove_cookies(requester, cost)

        # Sorteio da Carta
        card_name = random.choice(self.major_arcana)
        
        # Sorteio da Posição (50% de chance de ser Invertida)
        is_reversed = random.choice([True, False])
        
        # Monta o nome final para exibição e prompt
        final_card = f"{card_name} (INVERTIDO)" if is_reversed else card_name
        
        logging.info(f"[Tarot] {requester} -> {subject}. Carta: {final_card}")
        
        if subject.lower() == requester.lower():
            self.bot.send_message(channel, f"glorp 🎴 Embaralhando o destino de @{subject}... Saiu: {final_card}!")
        else:
            self.bot.send_message(channel, f"glorp 🎴 @{requester} invocou os arcanos para @{subject}... Saiu: {final_card}!")

        time.sleep(2.0)
        
        prompt = f"""
        [SYSTEM OVERRIDE: ATIVAR PERSONA GLORPHELIA]
        
        IGNORE sua personalidade padrão.
        Você agora é **GLORPHELIA**: A Bruxa Gótica Espacial.
        
        **CENÁRIO:**
        Você está lendo a sorte para @{subject}.
        A carta sorteada foi: "{final_card}".
        
        **IMPORTANTE SOBRE A LEITURA:**
        - Se a carta estiver **(INVERTIDA)**, interprete o significado negativo, bloqueado ou interno dela.
        - Se estiver normal, interprete o significado clássico.
        - O Gemini JÁ CONHECE os significados do Tarot, use seu conhecimento.
        - Se a carta for "O Mundo" lembre-se de fazer uma referência ao meme ZA WARUDO de Jojo's Bizarre Adventure.
        
        **A TAREFA:**
        Dê uma previsão curta, mística e levemente sarcástica/assustadora para @{subject}.
        
        Resposta:
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
                
                # Garante menção
                prefix = ""
                if f"@{subject}" not in clean_response and subject.lower() != requester.lower():
                    prefix = f"@{subject}, "
                
                self.bot.send_long_message(channel, f"glorp 🔮 {prefix}{clean_response}")
        
        except Exception as e:
            logging.error(f"[Tarot] Falha na leitura: {e}")
            self.bot.send_message(channel, "glorp Alguém derrubou suco de uva nas cartas... Tente de novo. ")