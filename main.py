from flask import Flask
import os
import requests
import time
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import pytz
from telegram import Bot, ParseMode
import logging
import threading

app = Flask(__name__)

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
    MIN_MATCHES: int = 2  # Minimum de matchs par combo
    MAX_MATCHES: int = 4  # Maximum de matchs par combo

@dataclass
class Prediction:
    match: str
    competition: str
    prediction: str
    odds: float
    start_time: datetime
    bookmaker: str = "Moyenne"
    result: Optional[str] = None

@dataclass
class Stats:
    total_bets: int = 0
    won_bets: int = 0
    lost_bets: int = 0
    total_odds_won: float = 0
    current_streak: int = 0
    best_streak: int = 0
    worst_streak: int = 0

    def update(self, won: bool, odds: float = 1.0):
        self.total_bets += 1
        if won:
            self.won_bets += 1
            self.total_odds_won += odds
            self.current_streak = max(1, self.current_streak + 1)
            self.best_streak = max(self.best_streak, self.current_streak)
        else:
            self.lost_bets += 1
            self.current_streak = min(-1, self.current_streak - 1)
            self.worst_streak = min(self.worst_streak, self.current_streak)

    def format_stats(self) -> str:
        win_rate = (self.won_bets / self.total_bets * 100) if self.total_bets > 0 else 0
        return (
            f"📊 *STATISTIQUES DU BOT*\n"
            f"Total paris: {self.total_bets}\n"
            f"Gagnés: {self.won_bets} | Perdus: {self.lost_bets}\n"
            f"Taux de réussite: {win_rate:.1f}%\n"
            f"Série actuelle: {abs(self.current_streak)} {'✅' if self.current_streak > 0 else '❌'}"
        )

CAPITAL_MANAGEMENT_MESSAGE = """
➖➖➖➖➖➖➖➖➖➖➖➖
💎 *CONSEIL PROFESSIONNEL* 💎
_La gestion du capital est la clé du succès. 
Une stake fixe de 1-3% de votre bankroll maximisera 
vos chances de réussite sur le long terme._
➖➖➖➖➖➖➖➖➖➖➖➖
"""

class TelegramNotifier:
    def __init__(self, config: Config):
        self.config = config
        self.bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

    async def send_startup_message(self):
        try:
            message = (
                "🚀 *BOT DÉMARRÉ* 🚀\n\n"
                "Génération du premier combo en cours..."
            )
            await self.bot.send_message(
                chat_id=self.config.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Erreur envoi message démarrage: {e}")

    def send_combo_predictions(self, predictions: List[Prediction], total_odds: float, stats: Stats):
        try:
            message = (
                f"🎯 *COMBO VIP DU JOUR* 🎯\n\n"
                f"📅 {datetime.now(self.config.TIMEZONE).strftime('%d/%m/%Y')}\n\n"
            )

            for i, pred in enumerate(predictions, 1):
                message += (
                    f"*Match {i}:*\n"
                    f"🏆 {pred.competition}\n"
                    f"⚽ {pred.match}\n"
                    f"💫 *{pred.prediction}*\n"
                    f"📈 Cote: *{pred.odds:.2f}*\n"
                    f"➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
                )

            message += f"📈 *COTE TOTALE: {total_odds:.2f}*\n\n"
            message += f"{stats.format_stats()}\n\n"
            message += CAPITAL_MANAGEMENT_MESSAGE

            self.bot.send_message(
                chat_id=self.config.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Combo envoyé avec succès - {len(predictions)} matchs - Cote: {total_odds:.2f}")
        except Exception as e:
            logger.error(f"Erreur envoi combo: {e}")

    def send_result_notification(self, predictions: List[Prediction], won: bool, stats: Stats):
        try:
            total_odds = 1.0
            for pred in predictions:
                total_odds *= pred.odds

            if won:
                message = (
                    f"🏆 *COMBO GAGNANT !* 🏆\n\n"
                    f"📈 Cote totale: {total_odds:.2f}\n\n"
                )
            else:
                message = "❌ *COMBO PERDANT* ❌\n\n"

            message += "*Détails des matchs:*\n"
            for i, pred in enumerate(predictions, 1):
                message += (
                    f"{i}. {pred.match}\n"
                    f"➤ {pred.prediction} @ {pred.odds:.2f}\n"
                    f"Résultat: {'✅' if pred.result == 'win' else '❌'}\n\n"
                )

            message += f"\n{stats.format_stats()}\n\n"
            message += CAPITAL_MANAGEMENT_MESSAGE

            self.bot.send_message(
                chat_id=self.config.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"Notification de résultat envoyée - Gagné: {won}")
        except Exception as e:
            logger.error(f"Erreur envoi résultat: {e}")

class BettingBot:
    def __init__(self):
        self.config = Config()
        self.notifier = TelegramNotifier(self.config)
        self.stats = Stats()
        self.current_predictions: List[Prediction] = []
        self.last_check_time = datetime.now()

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
        try:
            home_team = match['home_team']
            away_team = match['away_team']
            commence_time = datetime.strptime(
                match['commence_time'], '%Y-%m-%dT%H:%M:%SZ'
            ).replace(tzinfo=pytz.UTC).astimezone(self.config.TIMEZONE)
            competition = match.get('sport_title', 'Football')

            if not match.get('bookmakers'):
                return None

            all_predictions = []

            # Victoire Directe
            home_odds = self.get_average_odds(match['bookmakers'], home_team, 'h2h')
            away_odds = self.get_average_odds(match['bookmakers'], away_team, 'h2h')

            if home_odds and home_odds <= self.config.MAX_VICTORY_ODDS:
                all_predictions.append(("Victoire", home_team, home_odds))
            if away_odds and away_odds <= self.config.MAX_VICTORY_ODDS:
                all_predictions.append(("Victoire", away_team, away_odds))

            # Double Chance
            if home_odds and away_odds:
                dc_1X = 1 / ((1 / home_odds) + (1 / (2 * away_odds)))
                dc_X2 = 1 / ((1 / away_odds) + (1 / (2 * home_odds)))

                if self.config.MIN_DOUB_CHANCE_ODDS <= dc_1X <= self.config.MAX_DOUB_CHANCE_ODDS:
                    all_predictions.append(("Double chance 1X", home_team, dc_1X))
                if self.config.MIN_DOUB_CHANCE_ODDS <= dc_X2 <= self.config.MAX_DOUB_CHANCE_ODDS:
                    all_predictions.append(("Double chance X2", away_team, dc_X2))

            # Over/Under
            for ou_type, (min_odds, max_odds) in {
                "Over 2.5": (1.30, 1.85),
                "Under 2.5": (1.30, 1.70)
            }.items():
                ou_odds = self.get_average_odds(match['bookmakers'], ou_type, 'totals')
                if ou_odds and min_odds <= ou_odds <= max_odds:
                    all_predictions.append((ou_type, "", ou_odds))

            if not all_predictions:
                return None

            best_pred = max(all_predictions, key=lambda x: x[2])
            return Prediction(
                match=f"{home_team} vs {away_team}",
                competition=competition,
                prediction=f"{best_pred[0]} {best_pred[1]}",
                odds=best_pred[2],
                start_time=commence_time
            )
        except Exception as e:
            logger.error(f"Erreur évaluation match: {e}")
            return None

    def fetch_odds(self) -> List[Dict]:
        try:
            url = (
                f"{self.config.BASE_URL}?apiKey={self.config.ODDS_API_KEY}"
                f"&regions={self.config.REGIONS}&markets={self.config.MARKETS}"
                f"&oddsFormat={self.config.ODDS_FORMAT}"
            )
            response = requests.get(url)
            response.raise_for_status()
            return response.json() if response.ok else []
        except Exception as e:
            logger.error(f"Erreur récupération cotes: {e}")
            return []

    def generate_combo(self):
        matches = self.fetch_odds()
        predictions = []
        total_odds = 1.0

        # Tri des matchs par meilleure valeur
        valid_predictions = []
        for match in matches:
            prediction = self.evaluate_predictions(match)
            if prediction:
                valid_predictions.append(prediction)

        # Sélection des meilleurs matchs (entre MIN_MATCHES et MAX_MATCHES)
        valid_predictions.sort(key=lambda x: x.odds, reverse=True)
        predictions = valid_predictions[:self.config.MAX_MATCHES]
        
        if len(predictions) >= self.config.MIN_MATCHES:
            for pred in predictions:
                total_odds *= pred.odds
            self.current_predictions = predictions
            self.notifier.send_combo_predictions(predictions, total_odds, self.stats)
            logger.info(f"Nouveau combo généré avec {len(predictions)} prédictions")
        else:
            logger.warning(f"Pas assez de prédictions valides (minimum {self.config.MIN_MATCHES} requis)")

    def verify_results(self):
        if not self.current_predictions:
            return

        now = datetime.now(self.config.TIMEZONE)
        first_match_time = min(p.start_time for p in self.current_predictions)
        
        if now < first_match_time + timedelta(hours=2):
            return

        all_won = True
        for prediction in self.current_predictions:
            won = prediction.odds < 1.5  # Simulation
            prediction.result = 'win' if won else 'lose'
            all_won = all_won and won

        self.stats.update(all_won, sum(p.odds for p in self.current_predictions))
        self.notifier.send_result_notification(self.current_predictions, all_won, self.stats)
        self.current_predictions = []

@app.route('/')
def home():
    now = datetime.now(Config.TIMEZONE).strftime("%d/%m/%Y")
    return f"Bot is alive! Date: {now}"

def run_bot():
    bot = BettingBot()
    logger.info("Bot démarré!")
    
    # Génération immédiate au démarrage
    logger.info("Génération du premier combo...")
    bot.generate_combo()  # Génération immédiate
    time.sleep(5)  # Attente pour s'assurer de l'envoi

    while True:
        try:
            now = datetime.now(bot.config.TIMEZONE)
            
            if now.hour == 8 and now.minute == 0:
                bot.generate_combo()
                time.sleep(60)
                
            if now.minute % 15 == 0:
                bot.verify_results()
                
            time.sleep(30)
        except Exception as e:
            logger.error(f"Erreur dans la boucle principale: {e}")
            time.sleep(60)

if __name__ == "__main__":
    # Démarrage Flask dans un thread séparé
    flask_thread = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000))))
    flask_thread.daemon = True
    flask_thread.start()
    
    # Démarrage du bot
    run_bot()
