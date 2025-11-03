import os
import sys
import telebot
import instaloader
import logging

# --- Configuration ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# Validate that the token is present
if not TELEGRAM_TOKEN:
    logging.error("TELEGRAM_TOKEN environment variable not set.")
    sys.exit("Error: TELEGRAM_TOKEN environment variable not set.")
if not CHAT_ID:
    logging.warning("CHAT_ID environment variable not set. Some features might not work as expected.")


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

@bot.message_handler(commands=['login'])
def handle_login_start(message):
    """Starts the interactive login process."""
    chat_id = message.chat.id
    # Optional: Add user authorization check here if needed
    # if str(chat_id) != CHAT_ID:
    #     bot.send_message(chat_id, "You are not authorized to use this bot.")
    #     return

    msg = bot.send_message(chat_id, "Please enter your Instagram username:")
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

    msg = bot.send_message(chat_id, f"Username `{username}` received. Now, please enter your password.", parse_mode="Markdown")
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
        bot.send_message(chat_id, "Two-factor authentication is required. Please enter the 2FA code.")
        bot.register_next_step_handler(message, process_2fa_step, password)

    except instaloader.exceptions.BadCredentialsException:
        logging.error(f"Login failed for {username}: Bad credentials.")
        bot.send_message(chat_id, "Login failed: The username or password you entered is incorrect. Please try /login again.")
        del user_states[chat_id]

    except Exception as e:
        logging.error(f"An unexpected error occurred during login for {username}: {e}")
        bot.send_message(chat_id, f"An unexpected error occurred: {e}. Please try /login again.")
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
        bot.send_message(chat_id, "2FA login failed. The code may have been incorrect or an error occurred. Please try /login again.")
        if chat_id in user_states:
            del user_states[chat_id]

def complete_login(chat_id, username):
    """Saves the session and sends the details to the user."""
    L.save_session_to_file(username)
    logging.info(f"Session file saved for {username}.")

    session_id = L.context.session.cookies.get("sessionid")
    # The user ID is the correct value for 'ds_user_id' in this context
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
    bot.send_message(chat_id, response_message, parse_mode="Markdown")
    if chat_id in user_states:
        del user_states[chat_id]

if __name__ == "__main__":
    logging.info("Session generation bot started.")
    bot.polling(none_stop=True)