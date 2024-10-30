```python
from flask import Flask
import os
import requests
import json
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import pytz
from telegram import Bot, ParseMode
import logging
import threading
import pickle

app = Flask(__name__)

# Configuration du logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class Config:
    ODDS_API_KEY: str = '449cca7100ff7b7ff08db16e983672f5'
    TELEGRAM_BOT_TOKEN: str = '7859048967:AAGtkGTwIUDN44PZB76EyvD1zogyJPCMOmw'
    TELEGRAM_CHAT_ID: str = '-1002421926748'
    BASE_URL: str = 'https://api.the-odds-api.com/v4/sports/soccer/odds'
    REGIONS: str = 'eu'
    MARKETS: str = 'h2h,totals'
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
    result: str = None  # 'win', 'lose', ou None
    verified: bool = False

@dataclass
class Stats:
    total_bets: int = 0
    won_bets: int = 0
    lost_bets: int = 0
    total_odds_won: float = 0
    current_streak: int = 0  # positive pour les gains, negative pour les pertes
    best_streak: int = 0
    worst_streak: int = 0
    highest_odd_won: float = 0
    total_profit_percentage: float = 0

    def update(self, result: str, odds: float):
        self.total_bets += 1
        if result == 'win':
            self.won_bets += 1
            self.total_odds_won += odds
            self.current_streak = max(1, self.current_streak + 1)
            self.best_streak = max(self.best_streak, self.current_streak)
            self.highest_odd_won = max(self.highest_odd_won, odds)
            self.total_profit_percentage += (odds - 1) * 100
        else:
            self.lost_bets += 1
            self.current_streak = min(-1, self.current_streak - 1)
            self.worst_streak = min(self.worst_streak, self.current_streak)
            self.total_profit_percentage -= 100

    def win_rate(self) -> float:
        return (self.won_bets / self.total_bets * 100) if self.total_bets > 0 else 0

    def average_odds_won(self) -> float:
        return self.total_odds_won / self.won_bets if self.won_bets > 0 else 0

    def format_stats_message(self) -> str:
        return (
            f"📊 *STATISTIQUES GLOBALES DU BOT* 📊\n\n"
            f"🎯 *Performances Générales*\n"
            f"• Paris totaux: {self.total_bets}\n"
            f"• Paris gagnés: {self.won_bets}\n"
            f"• Paris perdus: {self.lost_bets}\n"
            f"• Taux de réussite: {self.win_rate():.1f}%\n\n"
            f"💰 *Analyse Financière*\n"
            f"• ROI total: {self.total_profit_percentage:.1f}%\n"
            f"• Cote moyenne gagnante: {self.average_odds_won():.2f}\n"
            f"• Meilleure cote gagnée: {self.highest_odd_won:.2f}\n\n"
            f"🔥 *Séries*\n"
            f"• Série actuelle: {abs(self.current_streak)} {'✅' if self.current_streak > 0 else '❌'}\n"
            f"• Meilleure série: {self.best_streak} ✅\n"
            f"• Pire série: {abs(self.worst_streak)} ❌"
        )

class TelegramNotifier:
    def __init__(self, config: Config):
        self.config = config
        self.bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

    def send_combo_predictions(self, predictions: List[Prediction], total_odds: float, stats: Stats):
        try:
            message = (
                f"🎯 *COMBO DU JOUR* 🎯\n\n"
                f"📅 Date: {datetime.now(self.config.TIMEZONE).strftime('%d/%m/%Y')}\n"
                f"⏰ Heure de génération: {datetime.now(self.config.TIMEZONE).strftime('%H:%M')}\n\n"
            )
            
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
            
            message += (
                f"📈 *COTE TOTALE: {total_odds:.2f}*\n\n"
                f"{stats.format_stats_message()}"
            )

            self.bot.send_message(
                chat_id=self.config.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Combo envoyé avec succès - Cote totale: {total_odds:.2f}")
                
        except Exception as e:
            logger.error(f"Erreur Telegram: {e}")

    def send_result_notification(self, predictions: List[Prediction], stats: Stats, won: bool):
        try:
            total_odds = 1.0
            for pred in predictions:
                total_odds *= pred.odds

            if won:
                message = (
                    f"🏆 *COMBO GAGNANT !* 🏆\n\n"
                    f"💰 Gains: {(total_odds - 1) * 100:.1f}% du mise\n"
                    f"📈 Cote totale: {total_odds:.2f}\n\n"
                    f"*Détails des paris:*\n"
                )
            else:
                message = (
                    f"❌ *COMBO PERDANT* ❌\n\n"
                    f"📉 Perte: 100% de la mise\n"
                    f"*Analyse des paris:*\n"
                )

            for pred in predictions:
                message += (
                    f"• {pred.match}\n"
                    f"  {pred.prediction} @ {pred.odds:.2f}\n"
                    f"  Résultat: {'✅' if pred.result == 'win' else '❌'}\n\n"
                )

            message += f"\n{stats.format_stats_message()}"

            self.bot.send_message(
                chat_id=self.config.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )

        except Exception as e:
            logger.error(f"Erreur envoi résultat: {e}")

class BettingBot:
    def __init__(self):
        self.config = Config()
        self.notifier = TelegramNotifier(self.config)
        self.stats = self.load_stats()
        self.current_predictions = []
        self.prediction_verified = False

    def save_stats(self):
        try:
            with open('bot_stats.pickle', 'wb') as f:
                pickle.dump(self.stats, f)
        except Exception as e:
            logger.error(f"Erreur sauvegarde stats: {e}")

    def load_stats(self) -> Stats:
        try:
            with open('bot_stats.pickle', 'rb') as f:
                return pickle.load(f)
        except:
            return Stats()

    def save_predictions(self):
        try:
            with open('current_predictions.pickle', 'wb') as f:
                pickle.dump(self.current_predictions, f)
        except Exception as e:
            logger.error(f"Erreur sauvegarde prédictions: {e}")

    def load_predictions(self) -> List[Prediction]:
        try:
            with open('current_predictions.pickle', 'rb') as f:
                return pickle.load(f)
        except:
            return []

    def fetch_odds(self) -> List[Dict]:
        try:
            url = (
                f"{self.config.BASE_URL}?apiKey={self.config.ODDS_API_KEY}"
                f"&regions={self.config.REGIONS}&markets={self.config.MARKETS}"
                f"&oddsFormat={self.config.ODDS_FORMAT}"
            )
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            return data if data else []
        except Exception as e:
            logger.error(f"Erreur API: {e}")
            return []

    def get_average_odds(self, bookmakers: List[Dict], outcome_name: str, market_key: str) -> Optional[float]:
        odds = [
            outcome['price']
            for bookmaker in bookmakers[:10]
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

        # Le reste du code evaluate_predictions reste identique...
        # [Code précédent conservé]

    def verify_results(self):
        """Vérifie les résultats des prédictions en cours"""
        if not self.current_predictions or self.prediction_verified:
            return

        now = datetime.now(self.config.TIMEZONE)
        first_match_time = min(p.start_time for p in self.current_predictions)
        
        # Vérifie si tous les matchs sont terminés (2h après le premier match)
        if now < first_match_time + timedelta(hours=2):
            return

        # Pour cette version, nous simulons les résultats
        # Dans une version réelle, vous devriez appeler une API de résultats
        all_won = True
        for pred in self.current_predictions:
            # Simulation - en réalité, vérifiez les vrais résultats
            is_won = pred.odds < 1.5  # Simulation simple pour test
            pred.result = 'win' if is_won else 'lose'
            all_won = all_won and is_won

        # Mise à jour des stats
        total_odds = 1.0
        for pred in self.current_predictions:
            total_odds *= pred.odds

        self.stats.update('win' if all_won else 'lose', total_odds)
        self.save_stats()

        # Envoi notification des résultats
        self.notifier.send_result_notification(self.current_predictions, self.stats, all_won)
        
        # Réinitialisation
        self.current_predictions = []
        self.prediction_verified = True
        self.save_predictions()

    def generate_coupon(self):
        """Génère et envoie le combo du jour"""
        matches = self.fetch_odds()
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
            self.current_predictions = predictions
            self.prediction_verified = False
            self.save_predictions()
            
            self.notifier.send_combo_predictions(predictions, total_odds, self.stats)
        else:
            logger.warning("Aucune prédiction n'a été générée.")

# Route Flask pour le monitoring
@app.route('/')
def home():
    return "Bot is alive!"

def bot_routine():
    bot = BettingBot()
    logger.info("Bot démarré!")
    
    while True:
        try:
            now = datetime.now(Config.TIMEZONE)
            
            # Génération du combo à 8h
            if now.hour == 8 and now.minute == 0:
                bot.generate_coupon()
                time.sleep(60)  # Évite les doublons
            
            # Vérification des résultats toutes les 15 minutes
            if now.minute % 15 == 0:
                bot.verify_results()
            
            time.sleep(30)
        except Exception as e:
            logger.error(f"Erreur routine: {e}")
            time.sleep(60)

if __name__ == "__main__":
    # Démarrer le bot dans un thread séparé
    bot_thread = threading.Thread(target=bot_routine)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Démarrer Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
```
