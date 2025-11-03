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
try:
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
except Exception as e:
    logging.error(f"Failed to initialize Telegram Bot: {e}")
    sys.exit(f"Failed to initialize Telegram Bot: {e}")

L = instaloader.Instaloader(
    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Mobile/15E148 Safari/604.1"
)

# In-memory dictionary to store user login states
user_states = {}

# --- Async Helper Functions for Pyrogram ---

async def telegram_send_code(api_id, api_hash, phone_number):
    """Creates a client, connects, sends the login code, and returns necessary data."""
    async with Client(":memory:", api_id=int(api_id), api_hash=api_hash, in_memory=True) as client:
        sent_code = await client.send_code(phone_number)
        session_string = await client.export_session_string()
        return sent_code.phone_code_hash, session_string

async def telegram_finish_login(api_id, api_hash, phone_number, phone_code_hash, session_string, code, password=None):
    """Restores a client and completes the login to get the final session string."""
    async with Client(name=":memory:", session_string=session_string, api_id=int(api_id), api_hash=api_hash, in_memory=True) as client:
        try:
            await client.sign_in(phone_number, phone_code_hash, code)
        except SessionPasswordNeeded:
            if password:
                await client.check_password(password)
            else:
                return "2FA_REQUIRED"

        final_session_string = await client.export_session_string()
        return final_session_string


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

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.send_message(message.chat.id, "Welcome! Please choose a session to generate:", reply_markup=gen_main_menu())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "cb_instagram":
        handle_instagram_login_start(call.message)
    elif call.data == "cb_telegram":
        handle_telegram_login_start(call.message)
    elif call.data == "cb_cancel":
        user_states.pop(call.message.chat.id, None)
        bot.send_message(call.message.chat.id, "Operation cancelled.", reply_markup=gen_main_menu())


# --- Instagram Session Generation ---
def handle_instagram_login_start(message):
    """Starts the interactive login process for Instagram."""
    chat_id = message.chat.id
    msg = bot.send_message(chat_id, "Please enter your Instagram username:", reply_markup=gen_cancel_markup())
    bot.register_next_step_handler(msg, process_username_step)

def process_username_step(message):
    """Processes the username and asks for the password."""
    chat_id = message.chat.id
    username = message.text
    user_states[chat_id] = {'username': username}

    # Delete the message containing the username for security
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.warning(f"Could not delete username message: {e}")

    msg = bot.send_message(chat_id, f"Username `{username}` received. Now, please enter your password.", parse_mode="Markdown", reply_markup=gen_cancel_markup())
    bot.register_next_step_handler(msg, process_password_step)

def process_password_step(message):
    """Processes the password, attempts to log in, and handles 2FA."""
    chat_id = message.chat.id
    password = message.text

    # Delete the password message for security
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.warning(f"Could not delete password message: {e}")

    bot.send_message(chat_id, "Password received. Trying to log in...")

    username = user_states[chat_id]['username']

    try:
        L.login(username, password)
        # If login is successful without 2FA
        complete_login(chat_id, username)

    except instaloader.exceptions.TwoFactorAuthRequiredException:
        logging.info(f"2FA required for user {username}.")
        msg = bot.send_message(chat_id, "Two-factor authentication is required. Please enter the 2FA code.", reply_markup=gen_cancel_markup())
        bot.register_next_step_handler(msg, process_2fa_step, password)

    except instaloader.exceptions.BadCredentialsException:
        logging.error(f"Login failed for {username}: Bad credentials.")
        bot.send_message(chat_id, "Login failed: The username or password you entered is incorrect. Please try /start again.", reply_markup=gen_main_menu())
        del user_states[chat_id]

    except Exception as e:
        logging.error(f"An unexpected error occurred during login for {username}: {e}")
        bot.send_message(chat_id, f"An unexpected error occurred: {e}. Please try /start again.", reply_markup=gen_main_menu())
        if chat_id in user_states:
            del user_states[chat_id]

def process_2fa_step(message, password):
    """Processes the 2FA code and completes the login."""
    chat_id = message.chat.id
    two_factor_code = message.text
    username = user_states[chat_id]['username']

    # Delete the 2FA code message for security
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logging.warning(f"Could not delete 2FA message: {e}")

    try:
        # The password is not needed here as instaloader handles the state
        L.two_factor_login(two_factor_code)
        complete_login(chat_id, username)
    except Exception as e:
        logging.error(f"Failed during 2FA login for {username}: {e}")
        bot.send_message(chat_id, "2FA login failed. The code may have been incorrect or an error occurred. Please try /start again.", reply_markup=gen_main_menu())
        if chat_id in user_states:
            del user_states[chat_id]

def complete_login(chat_id, username):
    """Saves the session and sends the details to the user."""
    L.save_session_to_file(username)
    logging.info(f"Session file saved for {username}.")

    session_id = L.context.session.cookies.get("sessionid")
    ds_user_id = L.context.userid
    x_ig_app_id = L.context.app_id

    response_message = f"""
Login successful for `{username}`!
Session file has been created on the server.
...
"""
    bot.send_message(chat_id, response_message, parse_mode="Markdown", reply_markup=gen_main_menu())
    if chat_id in user_states:
        del user_states[chat_id]


# --- Telegram Session Generation ---
def handle_telegram_login_start(message):
    chat_id = message.chat.id
    msg = bot.send_message(chat_id, "Please enter your API_ID:", reply_markup=gen_cancel_markup())
    bot.register_next_step_handler(msg, process_api_id_step)

def process_api_id_step(message):
    chat_id = message.chat.id
    try:
        api_id = int(message.text)
        user_states[chat_id] = {'api_id': api_id}
        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception as e:
            logging.warning(f"Could not delete API_ID message: {e}")
        msg = bot.send_message(chat_id, "API_ID received. Now, please enter your API_HASH.", reply_markup=gen_cancel_markup())
        bot.register_next_step_handler(msg, process_api_hash_step)
    except ValueError:
        msg = bot.send_message(chat_id, "Invalid API_ID. Please enter a numeric ID.", reply_markup=gen_cancel_markup())
        bot.register_next_step_handler(msg, process_api_id_step)

def process_api_hash_step(message):
    chat_id = message.chat.id
    user_states[chat_id]['api_hash'] = message.text
    try: bot.delete_message(chat_id, message.message_id)
    except Exception as e: logging.warning(f"Could not delete API_HASH message: {e}")
    msg = bot.send_message(chat_id, "API_HASH received. Now, please enter your phone number (with country code).", reply_markup=gen_cancel_markup())
    bot.register_next_step_handler(msg, process_phone_number_step)

def process_phone_number_step(message):
    chat_id = message.chat.id
    user_states[chat_id]['phone_number'] = message.text
    try: bot.delete_message(chat_id, message.message_id)
    except Exception as e: logging.warning(f"Could not delete phone number message: {e}")
    bot.send_message(chat_id, "Phone number received. Sending confirmation code...")

    api_id = user_states[chat_id]['api_id']
    api_hash = user_states[chat_id]['api_hash']
    phone_number = user_states[chat_id]['phone_number']

    # Event loop management
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        phone_code_hash, session_string = loop.run_until_complete(
            telegram_send_code(api_id, api_hash, phone_number)
        )
        user_states[chat_id]['phone_code_hash'] = phone_code_hash
        user_states[chat_id]['session_string'] = session_string
        msg = bot.send_message(chat_id, "A code has been sent to your Telegram account. Please enter it.", reply_markup=gen_cancel_markup())
        bot.register_next_step_handler(msg, process_telegram_code_step)
    except Exception as e:
        logging.error(f"An unexpected error occurred during Telegram login: {e}")
        bot.send_message(chat_id, f"An error occurred: {e}. Please try /start again.", reply_markup=gen_main_menu())
        user_states.pop(chat_id, None)
    finally:
        loop.close()

def process_telegram_code_step(message):
    chat_id = message.chat.id
    code = message.text
    try: bot.delete_message(chat_id, message.message_id)
    except Exception as e: logging.warning(f"Could not delete Telegram code message: {e}")

    state = user_states[chat_id]

    # Event loop management
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        session_string = loop.run_until_complete(
            telegram_finish_login(
                state['api_id'], state['api_hash'], state['phone_number'],
                state['phone_code_hash'], state['session_string'], code
            )
        )
        if session_string == "2FA_REQUIRED":
            msg = bot.send_message(chat_id, "Two-factor authentication is enabled. Please enter your password.", reply_markup=gen_cancel_markup())
            bot.register_next_step_handler(msg, process_telegram_2fa_step)
        else:
            bot.send_message(chat_id, f"Login successful! Here is your session string:\n\n`{session_string}`", parse_mode="Markdown", reply_markup=gen_main_menu())
            user_states.pop(chat_id, None)
    except Exception as e:
        logging.error(f"Failed during Telegram code verification: {e}")
        bot.send_message(chat_id, f"Login failed: {e}. Please try /start again.", reply_markup=gen_main_menu())
        user_states.pop(chat_id, None)
    finally:
        loop.close()

def process_telegram_2fa_step(message):
    chat_id = message.chat.id
    password = message.text
    try: bot.delete_message(chat_id, message.message_id)
    except Exception as e: logging.warning(f"Could not delete 2FA password message: {e}")

    state = user_states[chat_id]

    # Event loop management
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        session_string = loop.run_until_complete(
            telegram_finish_login(
                state['api_id'], state['api_hash'], state['phone_number'],
                state['phone_code_hash'], state['session_string'], state.get('code'), password=password
            )
        )
        bot.send_message(chat_id, f"Login successful! Here is your session string:\n\n`{session_string}`", parse_mode="Markdown", reply_markup=gen_main_menu())
    except Exception as e:
        logging.error(f"Failed during Telegram 2FA login: {e}")
        bot.send_message(chat_id, f"2FA login failed: {e}. Please try /start again.", reply_markup=gen_main_menu())
    finally:
        user_states.pop(chat_id, None)
        loop.close()

if __name__ == "__main__":
    logging.info("Session generation bot started.")
    bot.polling(none_stop=True)
