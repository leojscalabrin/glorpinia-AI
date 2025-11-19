import random
import logging

class Slots:
    def __init__(self, bot):
        print("[Feature] Slots Initialized.")
        self.bot = bot
        
        # Configuração dos Símbolos
        self.symbols = {
            # Especiais
            "glorp":        {"weight": 5,   "multiplier": 1000}, # Jackpot (Muito Raro)
            "WhySoSerious": {"weight": 15,  "multiplier": 500},  # Wild (Coringa)
            
            # Alto Valor
            "PartyParrot":     {"weight": 30,  "multiplier": 250}, # Triplo Sete
            "AYAYAjam":     {"weight": 45,  "multiplier": 150}, # 3x BAR
            "nanaAYAYA":    {"weight": 60,  "multiplier": 100}, # 2x BAR
            "AYAYA":        {"weight": 80,  "multiplier": 75},  # 1x BAR
            
            # Médio/Baixo Valor
            "EZ":     {"weight": 100, "multiplier": 50},  # Sino
            "AlienDance":     {"weight": 130, "multiplier": 30},  # Melancia
            "gachiGASM":         {"weight": 160, "multiplier": 20},  # Laranja
            "Gayge":       {"weight": 200, "multiplier": 10},  # Limão
            "peepoSad":        {"weight": 300, "multiplier": 5},   # Cereja
        }
        
        self.symbol_keys = list(self.symbols.keys())
        self.symbol_weights = [s["weight"] for s in self.symbols.values()]

    def play(self, channel, user, bet_amount):
        """
        Executa uma rodada de slots.
        """
        if not self.bot.cookie_system:
            return "O sistema de cookies está offline. Sadge"

        # 1. Valida a Aposta
        try:
            bet_amount = int(bet_amount)
            if bet_amount < 10:
                return f"@{user}, a aposta mínima é 10 cookies! glorp"
        except ValueError:
            return f"@{user}, valor de aposta inválido! Use: !glorp slots [valor]"

        # 2. Verifica Saldo
        user_balance = self.bot.cookie_system.get_cookies(user)
        if user_balance < bet_amount:
            return f"@{user}, você não tem cookies suficientes! Saldo: {user_balance} 🍪. Sadge"

        # 3. Deduz a Aposta do Usuário 
        self.bot.cookie_system.remove_cookies(user, bet_amount)

        # 4. Gira os Slots
        result = random.choices(self.symbol_keys, weights=self.symbol_weights, k=3)
        s1, s2, s3 = result
        
        display_result = f"[ {s1} | {s2} | {s3} ]"
        
        # 5. Calcula o Prêmio
        multiplier = 0
        
        # Lógica do WILD
        if s1 == "WhySoSerious" and s2 == "WhySoSerious" and s3 == "WhySoSerious":
            multiplier = self.symbols["WhySoSerious"]["multiplier"]
            
        elif s1 == s2 == s3:
            multiplier = self.symbols[s1]["multiplier"]
            
        else:
            wilds = result.count("WhySoSerious")
            if wilds > 0:
                others = [s for s in result if s != "WhySoSerious"]
                if len(others) == 0: 
                    pass
                elif len(set(others)) == 1: 
                    symbol_type = others[0]
                    multiplier = self.symbols[symbol_type]["multiplier"]

        # 6. Processa o Resultado
        if multiplier > 0:
            prize = int(bet_amount * multiplier)
            self.bot.cookie_system.add_cookies(user, prize)
            
            if multiplier >= 100:
                return f"{display_result} JACKPOT!! @{user} GANHOU {prize} 🍪 ({multiplier}x)!!! NOWAYING"
            elif multiplier >= 50:
                return f"{display_result} DING! @{user} ganhou {prize} 🍪 ({multiplier}x)! Pog"
            else:
                return f"{display_result} @{user} ganhou {prize} 🍪! EZ"
        else:
            return f"{display_result} @{user} perdeu {bet_amount} cookies. Mais fundos para o império EZ Clap"