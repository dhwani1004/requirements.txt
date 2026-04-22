"""Run once if Telegram stops working: python fix_config.py"""
import re, urllib.request, json

path = 'alert_config.py'
c = open(path, encoding='utf-8').read()
c = re.sub(r"'bot_token':\s*'[^']*'", "'bot_token': '8266836751:AAE9fzIWCfPJE-BK-eRdjGw_DRkcQICjGYY'", c)
c = re.sub(r"'chat_id':\s*'[^']*'", "'chat_id': '8741359827'", c)
open(path, 'w', encoding='utf-8').write(c)
print("Config updated")

data = json.dumps({'chat_id': '8741359827', 'text': 'Alert Bot - Telegram working!'}).encode()
req = urllib.request.Request(
    'https://api.telegram.org/bot8266836751:AAE9fzIWCfPJE-BK-eRdjGw_DRkcQICjGYY/sendMessage',
    data, {'Content-Type': 'application/json'})
r = urllib.request.urlopen(req, timeout=10)
print("Telegram test:", json.loads(r.read())['ok'])
print("DONE - restart dashboard.py")
