from flask import Flask, make_response
import os
import threading
from betting_bot import main as bot_main

app = Flask(__name__)

@app.route('/', methods=['GET', 'HEAD'])
def root():
    response = make_response('Service is running', 200)
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/health')
def health_check():
    return 'OK', 200

def run_bot():
    try:
        bot_main()
    except Exception as e:
        print(f"Bot error: {str(e)}")

if __name__ == "__main__":
    print("Starting Telegram Bot service...")
    
    # Start the bot in a separate thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    # Start the Flask server
    port = int(os.environ.get('PORT', 10000))
    print(f"Starting web server on port {port}")
    app.run(host='0.0.0.0', port=port)


