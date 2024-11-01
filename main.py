# Importation des bibliothèques nécessaires
from flask import Flask
import os
import requests
import time
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import pytz
from telegram import Bot, ParseMode
import logging
import threading
from collections import defaultdict

# Configuration du système de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class Config:
    """Configuration principale du bot"""
    # Clés API et tokens
    ODDS_API_KEY: str = 'cab8db3bfc01585fd91c6fb8630dc591'
    TELEGRAM_BOT_TOKEN: str = '7859048967:AAGtkGTwIUDN44PZB76EyvD1zogyJPCMOmw'
    TELEGRAM_CHAT_ID: str = '-1002421926748'
    
    # Configuration de l'API des cotes
    BASE_URL: str = 'https://api.the-odds-api.com/v4/sports'
    REGIONS: str = 'eu'
    MARKETS: str = 'h2h'
    ODDS_FORMAT: str = 'decimal'
    
    # Configuration du fuseau horaire
    TIMEZONE = pytz.timezone('Europe/Paris')
    
    # Paramètres pour la sélection des paris
    MAX_VICTORY_ODDS: float = 1.60  # Cote maximale pour un pari simple
    MIN_MATCHES: int = 1            # Nombre minimum de matchs par combo
    MAX_MATCHES: int = 3            # Nombre maximum de matchs par combo
    MIN_TOTAL_ODDS: float = 1.50    # Cote totale minimale pour un combo
    MAX_TOTAL_ODDS: float = 3.00    # Cote totale maximale pour un combo
    MIN_ODDS_DROP_PERCENT: float = 30.0  # Pourcentage minimum pour l'alerte de chute de cote
    
    # Liste des bookmakers à surveiller - Utilisation de default_factory pour le type mutable
    BOOKMAKERS_TO_MONITOR: List[str] = field(
        default_factory=lambda: ['1xbet', 'bet365']
    )

@dataclass
class MatchResult:
    """Stocke le résultat d'un match"""
    home_score: int
    away_score: int
    completed: bool

@dataclass
class Prediction:
    """Stocke les informations d'une prédiction"""
    match: str              # Nom du match (équipe1 vs équipe2)
    competition: str        # Nom de la compétition
    prediction: str         # Type de prédiction
    odds: float            # Cote du pari
    start_time: datetime   # Heure de début du match
    match_id: str          # Identifiant unique du match
    home_team: str         # Équipe à domicile
    away_team: str         # Équipe à l'extérieur
    bookmaker: str = "1XBET"
    result: Optional[MatchResult] = None

@dataclass
class Stats:
    """Gestion des statistiques du bot"""
    total_bets: int = 0
    won_bets: int = 0
    lost_bets: int = 0
    total_odds_won: float = 0

    def update(self, won: bool, odds: float = 1.0):
        """Mise à jour des statistiques après un pari"""
        self.total_bets += 1
        if won:
            self.won_bets += 1
            self.total_odds_won += odds
        else:
            self.lost_bets += 1

    def format_stats(self) -> str:
        """Formatage des statistiques pour l'affichage"""
        win_rate = (self.won_bets / self.total_bets * 100) if self.total_bets > 0 else 0
        return (
            f"📊 *STATISTIQUES DU BOT*\n"
            f"Total paris: {self.total_bets}\n"
            f"Gagnés: {self.won_bets} | Perdus: {self.lost_bets}\n"
            f"Taux de réussite: {win_rate:.1f}%\n"
        )

# Dictionnaire des emojis par sport
SPORT_EMOJIS = {
    'soccer': '⚽',
    'basketball': '🏀',
    'tennis': '🎾',
    'hockey': '🏒',
    'volleyball': '🏐',
    'baseball': '⚾',
    'american_football': '🏈',
    'rugby': '🏉',
}

# Message de conseil pour la gestion du capital
CAPITAL_MANAGEMENT_MESSAGE = """
➖➖➖➖➖➖➖➖➖➖➖➖
💎 *CONSEIL PROFESSIONNEL* 💎
_La gestion du capital est la clé du succès. 
Une stake fixe de 1-3% de votre bankroll maximisera 
vos chances de réussite sur le long terme._
➖➖➖➖➖➖➖➖➖➖➖➖
"""

# Classe OddsHistory pour stocker l'historique des cotes
@dataclass
class OddsHistory:
    """Stocke l'historique des cotes pour un match"""
    match_id: str
    bookmaker: str
    initial_odds: Dict[str, float] = field(default_factory=dict)
    current_odds: Dict[str, float] = field(default_factory=dict)
    last_update: datetime = field(default_factory=lambda: datetime.now(pytz.UTC))
    sport_key: str = ""
    sport_title: str = ""
    league: str = ""
    commence_time: datetime = field(default_factory=lambda: datetime.now(pytz.UTC))
    home_team: str = ""
    away_team: str = ""






class OddsAPI:
    """Gestion des appels à l'API des cotes"""
    def __init__(self, config: Config):
        self.config = config
        self.valid_sports = set()  # Cache des sports valides
        self.last_sports_update = None

    def _make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Effectue une requête à l'API"""
        try:
            url = f"{self.config.BASE_URL}/{endpoint}"
            response = requests.get(url, params=params)
            if response.status_code == 422:  # Unprocessable Entity
                return {}
            response.raise_for_status()
            return response.json()
        except Exception as e:
            if '422' not in str(e):  # Ne log que les erreurs non-422
                logger.error(f"Erreur API: {e}")
            return {}

    def get_odds_for_sport(self, sport_key: str = 'upcoming') -> List[Dict]:
        """Récupère les cotes pour un sport donné"""
        params = {
            "apiKey": self.config.ODDS_API_KEY,
            "regions": self.config.REGIONS,
            "markets": self.config.MARKETS,
            "oddsFormat": self.config.ODDS_FORMAT
        }
        matches = self._make_request(f"{sport_key}/odds", params)
        if matches:
            logger.info(f"Récupéré {len(matches)} matchs pour {sport_key}")
        return matches

    def get_active_sports(self) -> List[str]:
        """Récupère la liste des sports actifs"""
        now = datetime.now()
        # Met à jour la liste des sports toutes les 6 heures
        if (self.last_sports_update is None or 
            (now - self.last_sports_update).total_seconds() > 21600):
            
            params = {"apiKey": self.config.ODDS_API_KEY}
            response = self._make_request("", params)
            self.valid_sports.clear()
            
            for sport in response:
                if sport.get('active') and not sport.get('has_outrights', False):
                    self.valid_sports.add(sport['key'])
            
            self.last_sports_update = now
            logger.info(f"Liste des sports mise à jour: {len(self.valid_sports)} sports actifs")
        
        return list(self.valid_sports)

    def get_match_result(self, match_id: str) -> Optional[MatchResult]:
        """Récupère le résultat d'un match"""
        params = {
            "apiKey": self.config.ODDS_API_KEY,
            "daysFrom": 3
        }
        scores = self._make_request("scores", params)
        
        for score in scores:
            if score.get("id") == match_id and score.get("completed"):
                try:
                    home_score = int(score.get("scores", [{"score": 0}])[0].get("score", 0))
                    away_score = int(score.get("scores", [{"score": 0}, {"score": 0}])[1].get("score", 0))
                    
                    return MatchResult(
                        home_score=home_score,
                        away_score=away_score,
                        completed=True
                    )
                except (IndexError, ValueError) as e:
                    logger.error(f"Erreur lors de la récupération du score pour le match {match_id}: {e}")
                    return None
        return None

class OddsDropDetector:
    """Détection des chutes de cotes importantes"""
    def __init__(self, config: Config, notifier: 'TelegramNotifier'):
        self.config = config
        self.notifier = notifier
        self.api = OddsAPI(config)
        self.odds_history: Dict[str, Dict[str, float]] = {}
        self.last_check: Dict[str, datetime] = {}

    def update_odds_history(self):
        """Mise à jour et vérification des cotes"""
        now = datetime.now(self.config.TIMEZONE)
        
        # Récupère les sports actifs
        active_sports = self.api.get_active_sports()
        
        for sport_key in active_sports:
            # Vérifie seulement toutes les 5 minutes pour chaque sport
            if (sport_key in self.last_check and 
                (now - self.last_check[sport_key]).total_seconds() < 300):
                continue
                
            matches = self.api.get_odds_for_sport(sport_key)
            
            for match in matches:
                match_id = match['id']
                current_odds = self._extract_match_odds(match)
                
                if match_id not in self.odds_history:
                    self.odds_history[match_id] = current_odds
                else:
                    self._check_odds_drop(match, sport_key, current_odds)
                    
            self.last_check[sport_key] = now

    def _extract_match_odds(self, match: Dict) -> Dict[str, float]:
        """Extrait les cotes d'un match"""
        odds = {}
        for bookmaker in match.get('bookmakers', []):
            if bookmaker['key'] not in self.config.BOOKMAKERS_TO_MONITOR:
                continue
                
            for market in bookmaker.get('markets', []):
                if market['key'] == 'h2h':
                    for outcome in market['outcomes']:
                        key = f"{bookmaker['key']}_{outcome['name']}"
                        odds[key] = outcome['price']
        return odds

    def _check_odds_drop(self, match: Dict, sport_key: str, current_odds: Dict[str, float]):
        """Vérifie les chutes de cotes"""
        for key, current_odd in current_odds.items():
            if key not in self.odds_history[match['id']]:
                continue
                
            initial_odd = self.odds_history[match['id']][key]
            drop_percent = ((initial_odd - current_odd) / initial_odd) * 100
            
            if drop_percent >= self.config.MIN_ODDS_DROP_PERCENT:
                bookmaker, team = key.split('_', 1)
                self._send_odds_drop_alert(
                    sport_key, match, team,
                    initial_odd, current_odd,
                    drop_percent, bookmaker
                )

        self.odds_history[match['id']] = current_odds

    def _send_odds_drop_alert(self, sport_key: str, match: Dict, team: str,
                           initial_odd: float, current_odd: float,
                           drop_percent: float, bookmaker: str):
        """Envoie une alerte pour une chute de cote importante"""
        sport_emoji = SPORT_EMOJIS.get(sport_key.split('_')[0], '🎮')
        
        message = (
            f"🚨 *ALERTE CHUTE DE COTE* 🚨\n\n"
            f"{sport_emoji} *Sport:* {match.get('sport_title', sport_key)}\n"
            f"🏆 *Compétition:* {match.get('sport_title', 'N/A')}\n\n"
            f"📅 *Match:* {match['home_team']} vs {match['away_team']}\n"
            f"⏰ {datetime.strptime(match['commence_time'], '%Y-%m-%dT%H:%M:%SZ').strftime('%d/%m/%Y %H:%M')}\n\n"
            f"📊 *Détails de la chute:*\n"
            f"• Équipe: {team}\n"
            f"• Cote initiale: {initial_odd:.2f}\n"
            f"• Cote actuelle: {current_odd:.2f}\n"
            f"• Chute: -{drop_percent:.1f}%\n\n"
            f"📱 *Bookmaker:* {bookmaker.upper()}\n\n"
            f"⚡️ *Action recommandée:* Vérifier rapidement les opportunités de paris sur ce match!"
        )

        self.notifier.send_message(message)
        logger.info(f"Alerte chute de cote envoyée pour {match['home_team']} vs {match['away_team']}")



class TelegramNotifier:
    """Gestion des notifications Telegram"""
    def __init__(self, config: Config):
        self.config = config
        self.bot = Bot(token=config.TELEGRAM_BOT_TOKEN)

    def send_message(self, message: str):
        """Envoie un message sur le canal Telegram"""
        try:
            self.bot.send_message(
                chat_id=self.config.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Erreur envoi message Telegram: {e}")
            
    def send_combo_message(self, predictions: List[Prediction], total_odds: float, stats: Stats):
        """Envoie un message formaté pour un nouveau combo"""
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
                    f"📈 Cote ({pred.bookmaker}): *{pred.odds:.2f}*\n"
                    f"➖➖➖➖➖➖➖➖➖➖➖➖\n\n"
                )

            message += f"📈 *COTE TOTALE: {total_odds:.2f}*\n\n"
            message += f"{stats.format_stats()}\n\n"
            message += CAPITAL_MANAGEMENT_MESSAGE

            self.send_message(message)
        except Exception as e:
            logger.error(f"Erreur envoi combo: {e}")
            
    def send_result_message(self, predictions: List[Prediction], won: bool, stats: Stats, verified_predictions: Dict[str, bool]):
        """Envoie un message formaté pour les résultats"""
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
                if pred.result:
                    score_info = f"Score final: {pred.result.home_score}-{pred.result.away_score}"
                else:
                    score_info = "Score non disponible"
                    
                message += (
                    f"{i}. {pred.match}\n"
                    f"➤ {pred.prediction} @ {pred.odds:.2f}\n"
                    f"{score_info}\n"
                    f"Résultat: {'✅' if verified_predictions.get(pred.match_id, False) else '❌'}\n\n"
                )

            message += f"\n{stats.format_stats()}\n\n"
            message += CAPITAL_MANAGEMENT_MESSAGE

            self.send_message(message)
        except Exception as e:
            logger.error(f"Erreur envoi résultat: {e}")

class BettingBot:
    """Classe principale du bot de paris"""
    def __init__(self):
        self.config = Config()
        self.notifier = TelegramNotifier(self.config)
        self.api = OddsAPI(self.config)
        self.odds_detector = OddsDropDetector(self.config, self.notifier)
        self.stats = Stats()
        self.current_predictions: List[Prediction] = []
        self.verified_predictions: Dict[str, bool] = {}

    def run(self):
        """Fonction principale d'exécution du bot"""
        # Envoie un message de démarrage
        startup_message = (
            "🚀 *BOT DÉMARRÉ* 🚀\n\n"
            "Surveillance des cotes et génération de combos en cours..."
        )
        self.notifier.send_message(startup_message)

        # Lance la boucle principale
        self._run_main_loop()

    def _run_main_loop(self):
        """Boucle principale du bot"""
        while True:
            try:
                now = datetime.now(self.config.TIMEZONE)
                
                # Mise à jour des cotes et détection des chutes
                self.odds_detector.update_odds_history()
                
                # Génération de combo à 8h
                if now.hour == 8 and now.minute == 0:
                    self.generate_combo()
                    time.sleep(60)
                
                # Vérification des résultats toutes les 15 minutes
                if now.minute % 15 == 0:
                    self.verify_results()
                    
                time.sleep(30)
            except Exception as e:
                logger.error(f"Erreur dans la boucle principale: {e}")
                time.sleep(60)






class BettingBotLogic:
    """Logique métier du bot de paris"""
    
    def _evaluate_prediction(self, match: Dict) -> Optional[Prediction]:
        """Évalue un match et retourne une prédiction si valide"""
        try:
            home_team = match['home_team']
            away_team = match['away_team']
            commence_time = datetime.strptime(
                match['commence_time'], '%Y-%m-%dT%H:%M:%SZ'
            ).replace(tzinfo=pytz.UTC).astimezone(self.config.TIMEZONE)
            competition = match.get('sport_title', 'Football')

            if not match.get('bookmakers'):
                return None
                
            # Recherche du bookmaker 1XBET
            bookmaker_data = next(
                (bm for bm in match['bookmakers'] if bm['title'].lower() == '1xbet'),
                None
            )
            
            if not bookmaker_data:
                return None
                
            # Recherche des cotes pour victoire/défaite
            market = next(
                (m for m in bookmaker_data['markets'] if m['key'] == 'h2h'),
                None
            )
            
            if not market:
                return None
                
            home_odds = next(
                (outcome['price'] for outcome in market['outcomes'] 
                 if outcome['name'] == home_team),
                None
            )
            
            away_odds = next(
                (outcome['price'] for outcome in market['outcomes']
                 if outcome['name'] == away_team),
                None
            )
            
            if not home_odds or not away_odds:
                return None
                
            best_odds = None
            prediction = None
            if home_odds <= self.config.MAX_VICTORY_ODDS:
                best_odds = home_odds
                prediction = f"Victoire {home_team}"
            elif away_odds <= self.config.MAX_VICTORY_ODDS:
                best_odds = away_odds
                prediction = f"Victoire {away_team}"
                
            if not best_odds:
                return None
                
            return Prediction(
                match=f"{home_team} vs {away_team}",
                competition=competition,
                prediction=prediction,
                odds=best_odds,
                start_time=commence_time,
                match_id=match['id'],
                home_team=home_team,
                away_team=away_team
            )
            
        except Exception as e:
            logger.error(f"Erreur évaluation match: {e}")
            return None

    def generate_combo(self):
        """Génère un nouveau combo de paris"""
        matches = self.api.get_odds_for_sport('soccer')
        if not matches:
            logger.warning("Pas de matchs disponibles")
            return

        valid_predictions = []
        for match in matches:
            prediction = self._evaluate_prediction(match)
            if prediction:
                valid_predictions.append(prediction)

        valid_predictions.sort(key=lambda x: x.odds, reverse=True)
        selected_predictions = valid_predictions[:self.config.MAX_MATCHES]
        
        if len(selected_predictions) < self.config.MIN_MATCHES:
            logger.warning("Pas assez de prédictions valides")
            return

        total_odds = 1.0
        for pred in selected_predictions:
            total_odds *= pred.odds
            
        if not (self.config.MIN_TOTAL_ODDS <= total_odds <= self.config.MAX_TOTAL_ODDS):
            logger.warning(f"Cote totale {total_odds:.2f} hors limites")
            return
            
        self.current_predictions = selected_predictions
        self.notifier.send_combo_message(selected_predictions, total_odds, self.stats)
        logger.info(f"Nouveau combo généré avec {len(selected_predictions)} matchs")

    def verify_results(self):
        """Vérifie les résultats des paris en cours"""
        if not self.current_predictions:
            return
            
        now = datetime.now(self.config.TIMEZONE)
        
        # Trouve l'heure de fin du dernier match du combo
        last_match_time = max(p.start_time for p in self.current_predictions)
        # Ajoute 2h pour la durée du match et 30min pour le délai de vérification
        verification_time = last_match_time + timedelta(hours=2, minutes=30)
        
        # Vérifie seulement si le temps de vérification est atteint
        if now < verification_time:
            return
            
        all_results_available = True
        all_won = True
        match_details = []
        
        for prediction in self.current_predictions:
            if prediction.match_id in self.verified_predictions:
                continue
                
            match_result = self.api.get_match_result(prediction.match_id)
            if not match_result or not match_result.completed:
                all_results_available = False
                continue
                
            prediction.result = match_result
            won = self._check_prediction_result(prediction)
            self.verified_predictions[prediction.match_id] = won
            all_won = all_won and won
            
            # Stocke les détails du match
            match_details.append({
                'match': prediction.match,
                'prediction': prediction.prediction,
                'odds': prediction.odds,
                'score': f"{prediction.result.home_score}-{prediction.result.away_score}",
                'won': won
            })
            
        if all_results_available:
            total_odds = 1.0
            for pred in self.current_predictions:
                total_odds *= pred.odds
            
            # Met à jour les stats
            self.stats.update(all_won, total_odds)
            
            # Envoie la notification détaillée
            self._send_detailed_results(match_details, all_won, total_odds)
            
            # Réinitialise pour le prochain combo
            self.current_predictions = []
            self.verified_predictions.clear()
            logger.info("Vérification des résultats terminée")

    def _check_prediction_result(self, prediction: Prediction) -> bool:
        """Vérifie si une prédiction est gagnante"""
        if not prediction.result or "Victoire" not in prediction.prediction:
            return False
            
        team = prediction.prediction.split("Victoire ")[1]
        
        if team == prediction.home_team:
            return prediction.result.home_score > prediction.result.away_score
        else:
            return prediction.result.away_score > prediction.result.home_score

    def _send_detailed_results(self, match_details: List[Dict], all_won: bool, total_odds: float):
        """Envoie une notification détaillée des résultats"""
        try:
            if all_won:
                header = (
                    f"🏆 *COMBO GAGNANT !* 🏆\n\n"
                    f"📈 Cote totale: {total_odds:.2f}\n\n"
                )
            else:
                header = "❌ *COMBO PERDANT* ❌\n\n"

            message = header + "*Détails des Matchs:*\n\n"
            
            for i, detail in enumerate(match_details, 1):
                message += (
                    f"{i}. {detail['match']}\n"
                    f"➤ {detail['prediction']} @ {detail['odds']:.2f}\n"
                    f"📊 *Score final: {detail['score']}*\n"
                    f"Résultat: {'✅' if detail['won'] else '❌'}\n\n"
                )

            message += f"\n{self.stats.format_stats()}\n\n"
            message += CAPITAL_MANAGEMENT_MESSAGE

            self.notifier.send_message(message)
            logger.info("Notification des résultats envoyée")
        except Exception as e:
            logger.error(f"Erreur envoi résultats: {e}")

class BettingBot(BettingBotLogic):
    """Classe finale du bot combinant toutes les fonctionnalités"""
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.notifier = TelegramNotifier(self.config)
        self.api = OddsAPI(self.config)
        self.odds_detector = OddsDropDetector(self.config, self.notifier)
        self.stats = Stats()
        self.current_predictions: List[Prediction] = []
        self.verified_predictions: Dict[str, bool] = {}

    def run(self):
        """Fonction principale d'exécution du bot"""
        try:
            startup_message = (
                "🚀 *BOT DÉMARRÉ* 🚀\n\n"
                "Génération des prédictions en cours..."
            )
            self.notifier.send_message(startup_message)

            # Génère immédiatement un premier combo
            self.generate_combo()

            while True:
                try:
                    now = datetime.now(self.config.TIMEZONE)
                    
                    # Mise à jour des cotes et détection des chutes
                    self.odds_detector.update_odds_history()
                    
                    # Vérification des résultats toutes les 5 minutes
                    self.verify_results()
                    
                    # Génération du nouveau combo à 8h si les résultats précédents ont été vérifiés
                    if now.hour == 8 and now.minute == 0 and not self.current_predictions:
                        self.generate_combo()
                        time.sleep(60)
                    
                    time.sleep(300)  # Vérifie toutes les 5 minutes
                except Exception as e:
                    logger.error(f"Erreur dans la boucle principale: {e}")
                    time.sleep(60)
        except Exception as e:
            logger.error(f"Erreur fatale dans run: {e}")
            raise

def main():
    """Point d'entrée principal du programme"""
    try:
        app = Flask(__name__)
        
        @app.route('/')
        def home():
            now = datetime.now(Config.TIMEZONE).strftime("%d/%m/%Y")
            return f"Bot is alive! Date: {now}"
        
        bot = BettingBot()
        
        flask_thread = threading.Thread(
            target=lambda: app.run(host='0.0.0.0', port=5001, debug=False)
        )
        flask_thread.daemon = True
        flask_thread.start()
        
        bot.run()
        
    except Exception as e:
        logger.error(f"Erreur fatale: {e}")
        raise

if __name__ == "__main__":
    main()
