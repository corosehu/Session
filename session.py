import os
import sys
import telebot
import instaloader
import logging
import asyncio
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded

# --- Configuration ---
TELEGRAM_TOKEN = "7643403624:AAFIFvF1W2FrYHfEmlPiOpJhJbEjr8dYcCA"
CHAT_ID = "6827291977"

# --- Proxy Configuration (Optional) ---
# Uncomment and set your proxy details if you want to use one.
# PROXY = {
#     "scheme": "http",  # "http", "https" "socks4", "socks5"
#     "hostname": "127.0.0.1",
#     "port": 8080,
# }
PROXY = None


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("session_bot.log"),
        logging.StreamHandler()
    ]
)

# Initialize bot and instaloader
if PROXY:
    from telebot import apihelper
    apihelper.proxy = {
        'http': f'{PROXY["scheme"]}://{PROXY["hostname"]}:{PROXY["port"]}',
        'https': f'{PROXY["scheme"]}://{PROXY["hostname"]}:{PROXY["port"]}'
    }
try:
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
except Exception as e:
    logging.exception(f"Failed to initialize Telegram Bot: {e}")
    sys.exit(f"Failed to initialize Telegram Bot: {e}")

L = instaloader.Instaloader(
    user_agent="Mozilla/5.0 (Linux; Android 13; SM-G998B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36"
)
if PROXY:
    L.context.session.proxies = {
        'http': f'{PROXY["scheme"]}://{PROXY["hostname"]}:{PROXY["port"]}',
        'https': f'{PROXY["scheme"]}://{PROXY["hostname"]}:{PROXY["port"]}'
    }


# In-memory dictionaries to store states and clients
user_states = {}
pyrogram_clients = {}

# --- Async Helper Functions for Pyrogram ---

async def telegram_send_code(client, phone_number):
    """Connects, sends the login code, and returns the phone_code_hash."""
    try:
        await client.connect()
        sent_code = await client.send_code(phone_number)
        return sent_code.phone_code_hash
    finally:
        await client.disconnect()

async def telegram_submit_code(client, phone_number, phone_code_hash, code):
    """Connects, submits the code, and returns the session string or a 2FA signal."""
    try:
        await client.connect()
        await client.sign_in(phone_number, phone_code_hash, code)
        return await client.export_session_string()
    except SessionPasswordNeeded:
        return "2FA_REQUIRED"
    finally:
        await client.disconnect()

async def telegram_submit_password(client, password):
    """Connects, submits the 2FA password, and returns the final session string."""
    try:
        await client.connect()
        await client.check_password(password)
        return await client.export_session_string()
    finally:
        await client.disconnect()

# --- UI Helper Functions ---

def gen_main_menu():
    markup = InlineKeyboardMarkup()
    markup.row_width = 2
    markup.add(InlineKeyboardButton("Instagram Session", callback_data="cb_instagram"),
               InlineKeyboardButton("Telegram Session", callback_data="cb_telegram"))
    return markup

def gen_cancel_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Cancel", callback_data="cb_cancel"))
    return markup

# --- Bot Handlers ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "Welcome! Please choose a session to generate:", reply_markup=gen_main_menu())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    chat_id = call.message.chat.id
    if call.data == "cb_instagram":
        handle_instagram_login_start(call.message)
    elif call.data == "cb_telegram":
        handle_telegram_login_start(call.message)
    elif call.data == "cb_cancel":
        user_states.pop(chat_id, None)
        pyrogram_clients.pop(chat_id, None) # Clean up client
        bot.send_message(chat_id, "Operation cancelled.", reply_markup=gen_main_menu())


# --- Instagram Session Generation ---
def handle_instagram_login_start(message):
    chat_id = message.chat.id
    msg = bot.send_message(chat_id, "Please enter your Instagram username:", reply_markup=gen_cancel_markup())
    bot.register_next_step_handler(msg, process_username_step)

def process_username_step(message):
    chat_id = message.chat.id
    username = message.text
    user_states[chat_id] = {'username': username}
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.warning(f"Could not delete username message: {e}")
    msg = bot.send_message(chat_id, f"Username `{username}` received. Now, please enter your password.", parse_mode="Markdown", reply_markup=gen_cancel_markup())
    bot.register_next_step_handler(msg, process_password_step)

def process_password_step(message):
    chat_id = message.chat.id
    password = message.text
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.warning(f"Could not delete password message: {e}")

    bot.send_message(chat_id, "Password received. Trying to log in...")
    username = user_states[chat_id]['username']

    try:
        L.login(username, password)
        complete_login(chat_id, username)
    except instaloader.exceptions.TwoFactorAuthRequiredException:
        logging.info(f"2FA required for user {username}.")
        msg = bot.send_message(chat_id, "Two-factor authentication is required. Please enter the 2FA code.", reply_markup=gen_cancel_markup())
        bot.register_next_step_handler(msg, process_2fa_step, password)
    except instaloader.exceptions.BadCredentialsException:
        logging.exception(f"Login failed for {username}: Bad credentials.")
        bot.send_message(chat_id, "Login failed: The username or password you entered is incorrect. Please try /start again.", reply_markup=gen_main_menu())
        user_states.pop(chat_id, None)
    except Exception as e:
        logging.exception(f"An unexpected error occurred during login for {username}: {e}")
        bot.send_message(chat_id, f"An unexpected error occurred: {e}. Please try /start again.", reply_markup=gen_main_menu())
        user_states.pop(chat_id, None)

def process_2fa_step(message, password):
    chat_id = message.chat.id
    two_factor_code = message.text
    username = user_states[chat_id]['username']
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.warning(f"Could not delete 2FA message: {e}")

    try:
        L.two_factor_login(two_factor_code)
        complete_login(chat_id, username)
    except Exception as e:
        logging.exception(f"Failed during 2FA login for {username}: {e}")
        bot.send_message(chat_id, "2FA login failed. The code may have been incorrect or an error occurred. Please try /start again.", reply_markup=gen_main_menu())
        user_states.pop(chat_id, None)

def complete_login(chat_id, username):
    L.save_session_to_file(username)
    logging.info(f"Session file saved for {username}.")
    session_id = L.context.session.cookies.get("sessionid")
    ds_user_id = L.context.userid
    x_ig_app_id = L.context.app_id
    response_message = f"""
Login successful for `{username}`!
Session file has been created on the server.

Here are your session details:
-----------------------------------
`Your session id`:
`{session_id}`

`Your cookie id (user id)`:
`{ds_user_id}`

`X-IG-APP ID`:
`{x_ig_app_id}`
-----------------------------------
"""
    bot.send_message(chat_id, response_message, parse_mode="Markdown", reply_markup=gen_main_menu())
    user_states.pop(chat_id, None)


# --- Telegram Session Generation ---
def handle_telegram_login_start(message):
    chat_id = message.chat.id
    msg = bot.send_message(chat_id, "Please enter your API_ID:", reply_markup=gen_cancel_markup())
    bot.register_next_step_handler(msg, process_api_id_step)

def process_api_id_step(message):
    chat_id = message.chat.id
    try:
        api_id = int(message.text.strip())
        if api_id <= 0:
            raise ValueError("API_ID must be a positive integer.")
        user_states[chat_id] = {'api_id': api_id}
        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception as e:
            logging.warning(f"Could not delete API_ID message: {e}")
        msg = bot.send_message(chat_id, "API_ID received. Now, please enter your API_HASH.", reply_markup=gen_cancel_markup())
        bot.register_next_step_handler(msg, process_api_hash_step)
    except (ValueError, TypeError):
        msg = bot.send_message(chat_id, "❌ Invalid API_ID. Please enter a valid, positive numeric ID.", reply_markup=gen_cancel_markup())
        bot.register_next_step_handler(msg, process_api_id_step)

def process_api_hash_step(message):
    chat_id = message.chat.id
    user_states[chat_id]['api_hash'] = message.text
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.warning(f"Could not delete API_HASH message: {e}")
    msg = bot.send_message(chat_id, "API_HASH received. Now, please enter your phone number (with country code).", reply_markup=gen_cancel_markup())
    bot.register_next_step_handler(msg, process_phone_number_step)

def process_phone_number_step(message):
    chat_id = message.chat.id
    phone_number = message.text.strip()
    user_states[chat_id]['phone_number'] = phone_number
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.warning(f"Could not delete phone number message: {e}")

    bot.send_message(chat_id, "Phone number received. Sending confirmation code...")
    state = user_states[chat_id]

    # Final, defensive validation of api_id
    try:
        api_id = int(state['api_id'])
        if api_id <= 0:
            raise ValueError
    except (ValueError, KeyError):
        bot.send_message(chat_id, "An internal error occurred with your API_ID. Please try again.", reply_markup=gen_main_menu())
        user_states.pop(chat_id, None)
        return

    # Event loop management must happen BEFORE client initialization
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    client = Client(
        ":memory:",
        state['api_id'],
        state['api_hash'],
        in_memory=True,
        proxy=PROXY,
        device_model="Samsung Galaxy S22 Ultra",
        app_version="10.8.0"
    )
    pyrogram_clients[chat_id] = client

    try:
        phone_code_hash = loop.run_until_complete(telegram_send_code(client, phone_number))
        user_states[chat_id]['phone_code_hash'] = phone_code_hash
        msg = bot.send_message(chat_id, "A code has been sent to your Telegram account. Please enter it.", reply_markup=gen_cancel_markup())
        bot.register_next_step_handler(msg, process_telegram_code_step)
    except Exception as e:
        logging.exception(f"An error occurred while sending Telegram code: {e}")
        bot.send_message(chat_id, f"An error occurred: {e}. Please try /start again.", reply_markup=gen_main_menu())
        user_states.pop(chat_id, None)
        pyrogram_clients.pop(chat_id, None)
    finally:
        loop.close()

def process_telegram_code_step(message):
    chat_id = message.chat.id
    code = message.text.strip()
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.warning(f"Could not delete Telegram code message: {e}")

    state = user_states[chat_id]
    client = pyrogram_clients.get(chat_id)
    if not client:
        bot.send_message(chat_id, "Session expired. Please try again.", reply_markup=gen_main_menu())
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(telegram_submit_code(client, state['phone_number'], state['phone_code_hash'], code))
        if result == "2FA_REQUIRED":
            msg = bot.send_message(chat_id, "Two-factor authentication is enabled. Please enter your password.", reply_markup=gen_cancel_markup())
            bot.register_next_step_handler(msg, process_telegram_2fa_step)
        else:
            bot.send_message(chat_id, f"Login successful! Here is your session string:\n\n`{result}`", parse_mode="Markdown", reply_markup=gen_main_menu())
            user_states.pop(chat_id, None)
            pyrogram_clients.pop(chat_id, None)
    except Exception as e:
        logging.exception(f"Failed during Telegram code verification: {e}")
        bot.send_message(chat_id, f"Login failed: {e}. Please try /start again.", reply_markup=gen_main_menu())
        user_states.pop(chat_id, None)
        pyrogram_clients.pop(chat_id, None)
    finally:
        loop.close()

def process_telegram_2fa_step(message):
    chat_id = message.chat.id
    password = message.text
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.warning(f"Could not delete 2FA password message: {e}")

    client = pyrogram_clients.get(chat_id)
    if not client:
        bot.send_message(chat_id, "Session expired. Please try again.", reply_markup=gen_main_menu())
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        session_string = loop.run_until_complete(telegram_submit_password(client, password))
        bot.send_message(chat_id, f"Login successful! Here is your session string:\n\n`{session_string}`", parse_mode="Markdown", reply_markup=gen_main_menu())
    except Exception as e:
        logging.exception(f"Failed during Telegram 2FA login: {e}")
        bot.send_message(chat_id, f"2FA login failed: {e}. Please try /start again.", reply_markup=gen_main_menu())
    finally:
        user_states.pop(chat_id, None)
        pyrogram_clients.pop(chat_id, None)
        loop.close()

if __name__ == "__main__":
    logging.info("Session generation bot started.")
    bot.polling(none_stop=True)
