import random
import time
import asyncio
import logging

class Slots:
    def __init__(self, bot):
        print("[Feature] Slots Initialized.")
        self.bot = bot
        self.cooldowns = {}
        
        # Configuração dos Símbolos
        self.symbols = {
            # Especiais
            "glorp":        {"weight": 8,   "multiplier": 1000}, # Jackpot (Muito Raro)
            "WhySoSerious": {"weight": 20,  "multiplier": 500},  # Wild (Coringa)
            
            # Alto Valor
            "PartyParrot":     {"weight": 40,  "multiplier": 250}, # Triplo Sete
            "AYAYAjam":     {"weight": 55,  "multiplier": 150}, # 3x BAR
            "nanaAYAYA":    {"weight": 70,  "multiplier": 100}, # 2x BAR
            "AYAYA":        {"weight": 90,  "multiplier": 75},  # 1x BAR
            
            # Médio/Baixo Valor
            "EZ":     {"weight": 110, "multiplier": 50},  # Sino
            "AlienDance":     {"weight": 140, "multiplier": 30},  # Melancia
            "gachiGASM":         {"weight": 170, "multiplier": 20},  # Laranja
            "Gayge":       {"weight": 210, "multiplier": 10},  # Limão
            "peepoSad":        {"weight": 300, "multiplier": 5},   # Cereja
        }
        
        self.symbol_keys = list(self.symbols.keys())
        self.symbol_weights = [s["weight"] for s in self.symbols.values()]

    async def _is_stream_online(self, channel_name):
        """Verifica na API da Twitch se o canal está ao vivo."""
        try:
            # Busca o ID do usuário pelo nome do canal
            users = await self.bot.fetch_users(names=[channel_name])
            if not users:
                return False
            
            channel_id = users[0].id
            
            # Busca streams ativas para esse ID
            streams = await self.bot.fetch_streams(user_ids=[channel_id])
            
            # Se a lista 'streams' não estiver vazia, está online.
            return len(streams) > 0
            
        except Exception as e:
            logging.error(f"[Slots] Erro ao checar status da stream: {e}")
            return False
        
    async def play(self, channel, user, bet_amount):
        """
        Executa uma rodada de slots
        """
        if not self.bot.cookie_system:
            return "O sistema de cookies está offline. Sadge"

        # Verifica se a Stream está Online
        is_online = await self._is_stream_online(channel)
        if is_online:
            return f"@{user}, o KASSINÃO só abre quando a live está OFFLINE! Volte mais tarde. glorp"

        now = time.time()
        last_used = self.cooldowns.get(user, 0)
        cooldown_time = 600
        
        if (now - last_used) < cooldown_time:
            remaining = int(cooldown_time - (now - last_used))
            minutes = remaining // 60
            seconds = remaining % 60
            return f"@{user}, o cassino está limpando as máquinas! Volte em {minutes}m {seconds}s. GAMBA"

        # Valida a Aposta
        try:
            bet_amount = int(bet_amount)
            if bet_amount < 10:
                return f"@{user}, a aposta mínima é 10 cookies! glorp"
        except ValueError:
            return f"@{user}, valor de aposta inválido! Use: !glorp slots [valor]"

        # Verifica Saldo
        user_balance = self.bot.cookie_system.get_cookies(user)
        if user_balance < bet_amount:
            return f"@{user}, você não tem cookies suficientes! Saldo: {user_balance} 🍪. poor"

        
        # Atualiza o cooldown
        self.cooldowns[user] = now

        # Deduz a Aposta
        self.bot.cookie_system.remove_cookies(user, bet_amount)

        # Gira os Slots
        result = random.choices(self.symbol_keys, weights=self.symbol_weights, k=3)
        s1, s2, s3 = result
        
        display_result = f"[ {s1} | {s2} | {s3} ]"
        
        # Calcula o Prêmio
        multiplier = 0
        
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

        # Processa o Resultado
        if multiplier > 0:
            prize = int(bet_amount * multiplier)
            self.bot.cookie_system.add_cookies(user, prize)
            
            if multiplier >= 100:
                return f"{display_result} JACKPOT!! @{user} GANHOU {prize} 🍪 ({multiplier}x)!!! NOWAYING"
            elif multiplier >= 50:
                return f"{display_result} UAU! @{user} ganhou {prize} 🍪 ({multiplier}x)! Pog"
            else:
                return f"{display_result} @{user} ganhou {prize} 🍪! EZ"
        else:
            return f"{display_result} @{user} perdeu {bet_amount} cookies. GAMBA"