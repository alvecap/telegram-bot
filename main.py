import os
import requests
import asyncio
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
import pytz
from telegram import Bot
import logging
# Configuration du logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('betting_bot.log')
    ]
)
logger = logging.getLogger(__name__)
# Configuration des constantes
@dataclass
class Config:
    ODDS_API_KEY: str = '449cca7100ff7b7ff08db16e983672f5'
    TELEGRAM_BOT_TOKEN: str = '7859048967:AAGtkGTwIUDN44PZB76EyvD1zogyJPCMOmw'
    TELEGRAM_CHAT_ID: str = '-1002421926748'
    BASE_URL: str = 'https://api.the-odds-api.com/v4/sports/soccer/odds'
    REGIONS: str = 'eu'
    MARKETS: str = 'h2h,totals'  # Limité à h2h et totals pour éviter l'erreur 422
    ODDS_FORMAT: str = 'decimal'
    TIMEZONE = pytz.timezone('Europe/Paris')
    MAX_VICTORY_ODDS: float = 1.60
    MIN_DOUB_CHANCE_ODDS: float = 1.30
    MAX_DOUB_CHANCE_ODDS: float = 1.55
@dataclass
class Prediction:
    match: str
    competition: str
    prediction: str
    odds: float
    start_time: datetime
    bookmaker: str
@dataclass
class Stats:
    total_bets: int = 0
    won_bets: int = 0
    lost_bets: int = 0
    def update(self, result: str):
        self.total_bets += 1
        if result == 'win':
            self.won_bets += 1
        elif result == 'lose':
            self.lost_bets += 1
    def win_rate(self) -> float:
        return (self.won_bets / self.total_bets) * 100 if self.total_bets > 0 else 0.0
# Classe pour envoyer les notifications Telegram
class TelegramNotifier:
    def __init__(self, config: Config):
        self.config = config
        self.bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    async def send_combo_predictions(self, predictions: List[Prediction], total_odds: float, stats: Stats):
        try:
            message = "🎯 *COMBO DU JOUR* 🎯\n\n"
            for i, pred in enumerate(predictions, 1):
                message += (
                    f"*Match {i}:*\n"
                    f"🏆 {pred.competition}\n"
                    f"⚽ {pred.match}\n"
                    f"💫 *{pred.prediction}*\n"
                    f"📈 Cote: *{pred.odds:.2f}* ({pred.bookmaker})\n"
                    f"🕒 {pred.start_time.strftime('%H:%M')}\n"
                    f"➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
                )
            message += f"📈 *COTE TOTALE: {total_odds:.2f}*\n\n"
            message += f"📊 *Statistiques du Bot*\n"
            message += f"Total des paris: {stats.total_bets}\n"
            message += f"Gagnés: {stats.won_bets} | Perdus: {stats.lost_bets}\n"
            message += f"Taux de réussite: {stats.win_rate():.2f}%\n"
            await self.bot.send_message(
                chat_id=self.config.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode='Markdown'
            )
            logger.info("Combo envoyé avec succès - Cote totale: %.2f" % total_odds)
               
        except Exception as e:
            logger.error(f"Erreur Telegram: {e}")
    async def send_result_update(self, result: str, stats: Stats):
        try:
            message = (
                f"🔔 *Mise à jour des résultats* 🔔\n\n"
                f"Résultat du coupon: *{'Gagné 🏆' if result == 'win' else 'Perdu ❌'}*\n\n"
                f"📊 *Statistiques du Bot*\n"
                f"Total des paris: {stats.total_bets}\n"
                f"Gagnés: {stats.won_bets} | Perdus: {stats.lost_bets}\n"
                f"Taux de réussite: {stats.win_rate():.2f}%\n"
            )
            await self.bot.send_message(
                chat_id=self.config.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode='Markdown'
            )
            logger.info("Mise à jour du résultat envoyée.")
        except Exception as e:
            logger.error(f"Erreur envoi résultat: {e}")
# Classe principale pour le bot de paris
class BettingBot:
    def __init__(self):
        self.config = Config()
        self.notifier = TelegramNotifier(self.config)
        self.stats = Stats()
    async def fetch_odds(self) -> List[Dict]:
        try:
            url = (
                f"{self.config.BASE_URL}?apiKey={self.config.ODDS_API_KEY}"
                f"&regions={self.config.REGIONS}&markets={self.config.MARKETS}"
                f"&oddsFormat={self.config.ODDS_FORMAT}"
            )
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            if data:
                return data
            else:
                logger.warning("Aucune donnée retournée par l'API.")
                return []
        except requests.exceptions.HTTPError as e:
            logger.error(f"Erreur HTTP: {e}")
            return []
        except Exception as e:
            logger.error(f"Erreur API générale: {e}")
            return []
    def get_average_odds(self, bookmakers: List[Dict], outcome_name: str, market_key: str) -> Optional[float]:
        odds = [
            outcome['price']
            for bookmaker in bookmakers[:10]  # Limite aux 10 premiers bookmakers pour stabilité
            for market in bookmaker['markets']
            if market['key'] == market_key
            for outcome in market['outcomes']
            if outcome['name'] == outcome_name
        ]
        return sum(odds) / len(odds) if odds else None
    def evaluate_predictions(self, match: Dict) -> Optional[Prediction]:
        home_team = match['home_team']
        away_team = match['away_team']
        commence_time = datetime.strptime(
            match['commence_time'], '%Y-%m-%dT%H:%M:%SZ'
        ).replace(tzinfo=pytz.UTC).astimezone(self.config.TIMEZONE)
        competition = match.get('sport_title', 'Football')
        all_predictions = []
       
        # Victoire Directe
        home_odds = self.get_average_odds(match['bookmakers'], home_team, 'h2h')
        away_odds = self.get_average_odds(match['bookmakers'], away_team, 'h2h')
        if home_odds and home_odds <= self.config.MAX_VICTORY_ODDS:
            all_predictions.append(("Victoire", f"{home_team}", home_odds))
        if away_odds and away_odds <= self.config.MAX_VICTORY_ODDS:
            all_predictions.append(("Victoire", f"{away_team}", away_odds))
        # Double Chance
        if home_odds and away_odds:
            double_chance_odds_1X = 1 / ((1 / home_odds) + (1 / (2 * away_odds)))
            if self.config.MIN_DOUB_CHANCE_ODDS <= double_chance_odds_1X <= self.config.MAX_DOUB_CHANCE_ODDS:
                all_predictions.append(("Double chance 1X", f"{home_team}", double_chance_odds_1X))
            double_chance_odds_X2 = 1 / ((1 / away_odds) + (1 / (2 * home_odds)))
            if self.config.MIN_DOUB_CHANCE_ODDS <= double_chance_odds_X2 <= self.config.MAX_DOUB_CHANCE_ODDS:
                all_predictions.append(("Double chance X2", f"{away_team}", double_chance_odds_X2))
        # Over/Under
        over_under_options = {"Over 2.5": (1.30, 1.85), "Under 2.5": (1.30, 1.70)}
        for ou, (min_odds, max_odds) in over_under_options.items():
            ou_odds = self.get_average_odds(match['bookmakers'], ou, 'totals')
            if ou_odds and min_odds <= ou_odds <= max_odds:
                all_predictions.append((ou, "", ou_odds))
        # Sélection de la meilleure prédiction
        best_prediction = max(all_predictions, key=lambda x: x[2], default=None)
        if best_prediction:
            return Prediction(
                match=f"{home_team} vs {away_team}",
                competition=competition,
                prediction=f"{best_prediction[0]} {best_prediction[1]}",
                odds=best_prediction[2],
                start_time=commence_time,
                bookmaker="Moyenne"
            )
        return None
    async def generate_coupon(self):
        matches = await self.fetch_odds()
        predictions = []
        total_odds = 1.0
        for match in matches:
            prediction = self.evaluate_predictions(match)
            if prediction:
                predictions.append(prediction)
                total_odds *= prediction.odds
            if len(predictions) >= 3:
                break
        if predictions:
            await self.notifier.send_combo_predictions(predictions, total_odds, self.stats)
            self.stats.total_bets += 1
        else:
            logger.warning("Aucune prédiction n'a été générée.")
    async def verify_results(self, predictions: List[Prediction]):
        result = 'win' if all(p.odds < 2 for p in predictions) else 'lose'
        self.stats.update(result)
        await self.notifier.send_result_update(result, self.stats)
    async def run_daily_routine(self):
        logger.info("Envoi quotidien du combo VIP.")
        await self.generate_coupon()
# Boucle de routine quotidienne
async def daily_scheduler():
    bot = BettingBot()
    await bot.generate_coupon()  # Envoi immédiat d'un combo pour tester
    try:
        while True:
            now = datetime.now(Config.TIMEZONE)
            if now.hour == 8 and now.minute == 0:
                await bot.run_daily_routine()
                await asyncio.sleep(60)
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Bot arrêté manuellement.")
if __name__ == "__main__":
    try:
        asyncio.run(daily_scheduler())
    except RuntimeError as e:
        logger.error(f"Erreur runtime: {e}")
        loop = asyncio.get_event_loop()
        loop.run_until_complete(daily_scheduler())
