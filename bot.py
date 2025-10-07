import requests
import asyncio
import random
import re
import string
import datetime
import time
import logging
import pyotp
import uuid
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    filters, 
    ContextTypes, 
    CallbackContext,
    CallbackQueryHandler
    
)
from typing import Optional

# --- 1. CONFIGURATION & SETUP ---

# >>> BOT TOKEN provided by the user <<<
BOT_TOKEN = "8017229052:AAEb-YaMRVP7JkPiDFAufqmL1uSTEmEFxfc" 

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- 2. COMMON UI SETUP ---

# Define the keyboard structure for the primary bot's functions
custom_keyboard = [
    [
        KeyboardButton("🔐 2FA Authenticator"), 
        KeyboardButton("📧 Temp Mail Service")
    ],
]
REPLY_MARKUP = ReplyKeyboardMarkup(custom_keyboard, resize_keyboard=True, one_time_keyboard=False)

# ==============================================================================
# 3. CORE LOGIC FOR BOT 1 (2FA Authenticator)
# ==============================================================================

def calculate_totp(secret_key: str) -> tuple[str, int]:
    """Calculates the current TOTP code and the time until the next refresh."""
    try:
        totp = pyotp.TOTP(secret_key)
        current_code = totp.now()
        current_time_seconds = int(time.time())
        time_remaining = 30 - (current_time_seconds % 30)

        return current_code, time_remaining
    except Exception as e:
        logger.error(f"Error calculating TOTP: {e}")
        return None, 0

def get_otp_inline_markup(secret_key: str) -> InlineKeyboardMarkup:
    """Creates the inline keyboard for the OTP message."""
    # We pass the secret key in the callback data to keep it specific, although 
    # the job_queue name is enough for stopping. Here we use a generic stop signal.
    buttons = [
        [InlineKeyboardButton("CLAIMED 🧧", callback_data=f"claim_otp")]
    ]
    return InlineKeyboardMarkup(buttons)

def format_countdown_message(code: str, time_remaining: int) -> str:
    """Formats the message content for the OTP code, including live countdown."""
    timer_emoji = "🟡"
    if time_remaining <= 5:
        timer_emoji = "🔴"
    elif time_remaining <= 15:
        timer_emoji = "🟠"
        
    message = (
        "Power By None\n\n"
        f"OTP CODE >> <code>'{code}'</code>\n" 
        f"⏳ {timer_emoji} Expires in: {time_remaining:02d} seconds\n\n"
        "Power By None"
    )
    
    return message

# --- Job Scheduler Functionality (2FA) ---

# --- HELPER FUNCTION TO STOP ACTIVE JOBS ---
async def stop_active_otp_job(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Stops the currently running OTP countdown job for a chat.
    Does NOT edit the message; the calling function or the claimant handler handles that.
    """
    jobs = context.job_queue.get_jobs_by_name(f'otp_countdown_{chat_id}')
    
    if jobs:
        job = jobs[0]
        # Stop the recurring job
        job.schedule_removal()
        logger.info(f"OTP job for chat {chat_id} stopped.")
        return True
            
    return False

async def countdown_job(context: CallbackContext) -> None:
    """The recurring job that calculates remaining time and edits the message."""
    job = context.job
    chat_id = job.data['chat_id']
    message_id = job.data['message_id']
    secret_key = job.data['secret_key']
    
    code, time_remaining = calculate_totp(secret_key)

    if code is None:
        job.schedule_removal()
        logger.error(f"Job failed for chat {chat_id}. Removing job.")
        return

    if time_remaining > 0:
        message = format_countdown_message(code, time_remaining)
        
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=message,
                parse_mode='HTML',
                reply_markup=get_otp_inline_markup(secret_key) # Attach the inline button
            )
        except Exception as e:
            logger.warning(f"Failed to edit message {message_id} in chat {chat_id}: {e}")
            job.schedule_removal() 
            
    elif time_remaining == 0:
        final_message = (
            "🔴 <b>CODE EXPIRED!</b> 🔴\n\n"
            "Your previous code has refreshed. Please send the secret key again "
            "or press the '2FA Authenticator' button to request a new code."
        )
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=final_message,
                parse_mode='HTML',
                reply_markup=None
            )
        except Exception as e:
            logger.warning(f"Failed to send final expired message: {e}")

        job.schedule_removal()
        logger.info(f"Job finished and removed for chat {chat_id}.")


async def start_countdown(update: Update, context: ContextTypes.DEFAULT_TYPE, secret_key: str) -> None:
    """Initial function to send the first message and schedule the recurring job."""
    chat_id = update.effective_chat.id
    
    # Stop any existing job before starting a new one (prevents two jobs running)
    await stop_active_otp_job(chat_id, context)

    initial_code, initial_time_remaining = calculate_totp(secret_key)
    
    if initial_code is None or initial_time_remaining == 0:
        error_message = "⚠️ <b>Error:</b> Could not generate initial code. Please try again."
        await update.message.reply_text(error_message, parse_mode='HTML', reply_markup=REPLY_MARKUP)
        return

    initial_message_text = format_countdown_message(initial_code, initial_time_remaining)

    initial_message = await update.message.reply_text(
        initial_message_text,
        reply_markup=get_otp_inline_markup(secret_key), # Attach the inline button
        parse_mode='HTML'
    )
    
    job_data = {
        'chat_id': chat_id,
        'message_id': initial_message.message_id,
        'secret_key': secret_key,
    }

    context.job_queue.run_repeating(
        countdown_job,
        interval=1.0, 
        first=1.0,     
        data=job_data,
        name=f'otp_countdown_{chat_id}'
    )
    logger.info(f"Countdown job scheduled for chat {chat_id}.")

# --- NEW HANDLER FOR CLAIMED BUTTON ---
async def claim_otp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the inline 'CLAIMED 🧧' button click on the OTP message."""
    query = update.callback_query
    chat_id = query.message.chat_id
    message_id = query.message.message_id
    
    # Acknowledge the button press instantly
    await query.answer(text="Code claimed!", show_alert=False) 
    
    # 1. Stop the recurring countdown job
    await stop_active_otp_job(chat_id, context)

    # 2. Edit the message to the 'CLAIMED' state
    claimed_message = "✅ <b>OTP CLAIMED!</b> 🧧\n\nThis code has been manually marked as claimed/used."
    
    try:
        await query.edit_message_text(
            text=claimed_message,
            parse_mode='HTML',
            reply_markup=None
        )
        logger.info(f"OTP message {message_id} in chat {chat_id} marked CLAIMED.")
    except Exception as e:
        logger.warning(f"Failed to edit OTP message {message_id} to CLAIMED: {e}")


# ==============================================================================
# 4. CORE LOGIC FOR BOT 2 (Temp Mail Service)
# ==============================================================================

# --- User storage (Merged Global Data)
user_data = {}

# --- Known Sender Domain Mapping
KNOWN_SENDERS = {
    'google.com': 'Google',
    'registration@facebookmail.com': 'Facebook',
    'meta.com': 'Meta (Facebook)',
    'twitter.com': 'X (Twitter)',
    'discord.com': 'Discord',
    'amazon.com': 'Amazon',
    'microsoft.com': 'Microsoft',
    'apple.com': 'Apple',
    'noreply@telegram.org': 'Telegram',
    'instagram.com': 'Instagram',
    'tiktok.com': 'TikTok',
    'netflix.com': 'Netflix',
    'steamcommunity.com': 'Steam',
    'reddit.com': 'Reddit',
    'paypal.com': 'PayPal',
    'snapchat.com': 'Snapchat',
    'spotify.com': 'Spotify',
    'linkedin.com': 'LinkedIn',
    'uber.com': 'Uber',
    'noreply@tm.openai.com': 'Chat Gpt'
}

def generate_random_name(min_len=6, max_len=12):
    """Generates a random username with a mix of letters and numbers."""
    chars = string.ascii_letters + string.digits
    length = random.randint(6, 12) 
    return ''.join(random.choice(chars) for _ in range(length)).lower()

def generate_email(username_prefix=None):
    """Generate random or custom mailto.plus address."""
    if username_prefix and username_prefix.isalnum():
        name = username_prefix
    else:
        name = generate_random_name() 
    return f"{name}@mailto.plus"

def fetch_inbox(email):
    """Fetch inbox for given email."""
    url = f"https://tempmail.plus/api/mails?email={email}&first_id=0&epin="
    try:
        res = requests.get(url, headers={"accept": "application/json"}, timeout=10)
        res.raise_for_status() 
        return res.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching inbox for {email}: {e}")
        return {"error": str(e)}

def format_sender_name(sender_string):
    """Extracts a clean name or identifies a known service from the sender string."""
    email_match = re.search(r'<([^@]+@[^>]+)>', sender_string)
    
    if email_match:
        email_address = email_match.group(1)
        domain = email_address.split('@')[-1]
        
        # 1. Check for Known Services
        if domain in KNOWN_SENDERS:
            return KNOWN_SENDERS[domain]
        
        # 2. Extract Name if it exists
        match_name = re.match(r'^(.*?) <.*?>$', sender_string)
        if match_name:
            clean_name = match_name.group(1).strip()
            if clean_name:
                return clean_name

    # 3. Fallback to the original string
    return sender_string.replace("<", " ").replace(">", "").strip()

def extract_otp(subject, content):
    """Searches subject and content for a 4-8 digit OTP."""
    otp_pattern = re.compile(
        r'(?:OTP|CODE|PIN|verification|one[\s_-]time).*?(\d{4,8})' 
        r'|(\b\d{4,8}\b)'
    , re.IGNORECASE | re.DOTALL)
    
    match = otp_pattern.search(subject)
    if match:
        return match.group(1) or match.group(2)

    match = otp_pattern.search(content)
    if match:
        return match.group(1) or match.group(2)
        
    return None

def initialize_user_data(chat_id):
    """Ensures necessary keys exist for a new user."""
    if chat_id not in user_data:
        user_data[chat_id] = {"emails": [], "active": None, "last_seen_id": None, "username": None, "auto_gen_on": False}


async def generate_new_email_logic(chat_id: int, username_prefix: str, update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback: bool):
    """Central logic for generating a new email, used by both button and command."""
    # --- Stop 2FA Job on any Temp Mail action (using the simpler stop job) ---
    await stop_active_otp_job(chat_id, context)

    email = generate_email(username_prefix)

    # Clear existing entries and start fresh with only one email in history
    user_data[chat_id]["emails"] = [email]
    user_data[chat_id]["active"] = email
    user_data[chat_id]["last_seen_id"] = None 
    
    response_text = f"〽️New Web Mail Generated:\n`{email}`\n⏰Wait 3-4 Second For The Otp"

    if is_callback:
        # Use a try/except to handle the CallbackQuery update when the original message is too old
        try:
            await update.callback_query.edit_message_text(
                response_text,
                parse_mode="Markdown",
                reply_markup=get_tempmail_inline_markup()
            )
        except Exception as e:
             await context.bot.send_message(chat_id=chat_id, text=response_text, parse_mode="Markdown", reply_markup=get_tempmail_inline_markup())
             
    else:
        await update.message.reply_text(
            response_text,
            parse_mode="Markdown",
            reply_markup=get_tempmail_inline_markup()
        )

# --- TempMail Inline Keyboard (UPDATED) ---

def get_tempmail_inline_markup():
    """Creates the inline keyboard for the Temp Mail service with 4 buttons."""
    buttons = [
        [
            InlineKeyboardButton("📧 Generate", callback_data="generate"),
            InlineKeyboardButton("📊 Admin Stats", callback_data="admin_stats")
        ],
        [
            InlineKeyboardButton("♻️ Auto gen", callback_data="auto_gen_inline"),
            InlineKeyboardButton("✍️ Set Username", callback_data="set_username_inline")
        ]
    ]
    return InlineKeyboardMarkup(buttons)

# -------------------------------
# 🔄 Auto-fetch task (Runs in background)
# -------------------------------
async def auto_fetch(app: Application):
    """Background task to poll inboxes and notify users."""
    logger.info("Auto-fetch task started.")
    while True:
        # Create a copy of user_data keys to safely iterate while items might be updated
        for chat_id, data in list(user_data.items()):
            email = data.get("active")
            if not email:
                continue

            inbox = fetch_inbox(email)
            last_seen = data.get("last_seen_id")
            
            new_mails_received = False

            if "mail_list" in inbox and inbox["mail_list"]:
                
                new_mails = []
                for mail in inbox["mail_list"]:
                    mail_id = mail.get("mail_id")
                    if mail_id != last_seen:
                        new_mails.append(mail)
                    else:
                        break 
                
                new_mails.reverse() 

                if new_mails:
                    # Update last seen ID to the newest mail ID
                    user_data[chat_id]["last_seen_id"] = inbox["mail_list"][0].get("mail_id") 
                    new_mails_received = True

                for mail in new_mails:
                    subject = mail.get("subject", "No Subject")
                    sender = mail.get("from", "Unknown Sender")
                    
                    # 1. Get the body content
                    raw_text_body = mail.get("text", "") 
                    html_body = mail.get("html", "")
                    
                    content = raw_text_body
                    if not content and html_body:
                        # Simple HTML stripping
                        content = re.sub('<[^>]*>', ' ', html_body) 

                    # 2. Get the clean sender name
                    clean_sender = format_sender_name(sender)
                    
                    # 3. OTP EXTRACTION LOGIC
                    otp = extract_otp(subject, content)
                    is_otp_mail = bool(otp)

                    # 4. Build the final Telegram message (displaying the mail content)
                    if is_otp_mail:
                         display_body_msg = f"HEY THIS YOUR OTP CODE >> `{otp}`"
                         msg = (
                            f"🚨 *NEW OTP RECEIVED!* 🔐\n\n"
                            f"*From:* {clean_sender}\n"
                            f"*Subject:* {subject}\n\n"
                            f"**{display_body_msg}**"
                        )
                    else:
                        display_body = content if content.strip() else "--- Mail body was empty or only contained unreadable data ---"
                        # Limit displayed body content
                        display_body_preview = display_body[:500].strip()
                        display_body_msg = f"Full Body:\n```\n{display_body_preview}{'...' if len(display_body) > 500 else ''}\n```"
                        
                        msg = (
                            f"📩 *New Mail Received!*\n\n"
                            f"*From:* {clean_sender}\n"
                            f"*Subject:* {subject}\n\n"
                            f"{display_body_msg}"
                        )
                    
                    try:
                        await app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                        
                    except Exception as e:
                        logger.error(f"Error sending message to {chat_id}: {e}")
                
                # 🔥 6. AUTO-GENERATE NEW MAIL LOGIC - TRIGGERED IF ANY NEW MAIL RECEIVED 🔥
                if new_mails_received and data.get("auto_gen_on"):
                    username_prefix = data.get("username")
                    new_email = generate_email(username_prefix)
                    
                    # Update user data:
                    data["emails"] = [new_email] # Clear all previous and set new
                    data["active"] = new_email
                    data["last_seen_id"] = None
                    
                    text = (
                        f"♻️ **Auto-Generated New Email!** ♻️\n\n"
                        f"The previous address was replaced. Your new active email is:\n"
                        f"• `{new_email}`"
                    )
                    
                    # Send the updated status
                    await app.bot.send_message(
                        chat_id=chat_id, 
                        text=text, 
                        parse_mode="Markdown",
                        reply_markup=get_tempmail_inline_markup() 
                    )

        # Sleep for 3 seconds
        await asyncio.sleep(3)


# ==============================================================================
# 5. MERGED TELEGRAM HANDLERS
# ==============================================================================

# --- Handlers for Temp Mail Bot (Bot 2) ---

async def set_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /set command for custom usernames."""
    chat_id = update.message.chat_id
    initialize_user_data(chat_id)
    
    # --- Stop 2FA Job on any Temp Mail action ---
    await stop_active_otp_job(chat_id, context)

    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "Usage: **/set <name>**\n\n"
            "The `<name>` will be used as the prefix for your new email address.\n"
            "Name must be alphanumeric and 6-12 characters.",
            parse_mode="Markdown"
        )
        return

    new_username = context.args[0].lower()

    if not (new_username.isalnum() and 6 <= len(new_username) <= 12):
        await update.message.reply_text("❌ The username must be alphanumeric and between 6 and 12 characters in length.")
        return

    user_data[chat_id]["username"] = new_username
    
    await update.message.reply_text(
        f"✅ Your preferred email prefix is now set to: `{new_username}`.\n"
        "Use **/generate** command or the button to create a new address with this prefix.",
        parse_mode="Markdown"
    )

async def auto_gen_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggles the automatic email generation after OTP is received."""
    chat_id = update.message.chat_id
    initialize_user_data(chat_id)

    # --- Stop 2FA Job on any Temp Mail action ---
    await stop_active_otp_job(chat_id, context)
    
    current_state = user_data[chat_id]["auto_gen_on"]
    new_state = not current_state
    user_data[chat_id]["auto_gen_on"] = new_state
    
    status_text = "ON" if new_state else "OFF"
    emoji = "✅" if new_state else "❌"
    
    await update.message.reply_text(
        f"{emoji} Auto-Generate New Mail is now **{status_text}**.\n\n"
        "When ON, receiving **any** new email will replace your current address with a new one.",
        parse_mode="Markdown"
    )

async def generate_new_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /generate command."""
    chat_id = update.message.chat_id
    initialize_user_data(chat_id)
    username_prefix = user_data[chat_id].get("username")
    
    # --- Stop 2FA Job on any Temp Mail action ---
    await stop_active_otp_job(chat_id, context)

    await generate_new_email_logic(chat_id, username_prefix, update, context, is_callback=False)


async def tempmail_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    initialize_user_data(chat_id)
    await query.answer() # Acknowledge the button press

    # --- Stop 2FA Job on any Temp Mail action ---
    await stop_active_otp_job(chat_id, context)

    if query.data == "generate":
        username_prefix = user_data[chat_id].get("username")
        await generate_new_email_logic(chat_id, username_prefix, update, context, is_callback=True)

    elif query.data == "admin_stats":
        # Placeholder for Admin Stats logic
        text = "📊 Admin Stats:\nThis button is a placeholder. To get stats, you would implement the data retrieval logic here."
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_tempmail_inline_markup())
        except Exception:
             await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=get_tempmail_inline_markup())

    elif query.data == "auto_gen_inline":
        # Toggle auto-generation directly via inline button
        current_state = user_data[chat_id]["auto_gen_on"]
        new_state = not current_state
        user_data[chat_id]["auto_gen_on"] = new_state
        
        status_text = "ON" if new_state else "OFF"
        emoji = "✅" if new_state else "❌"
        
        text = (
            f"{emoji} Auto-Generate New Mail is now **{status_text}**.\n\n"
            "When ON, receiving **any** new email will replace your current address with a new one."
        )
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_tempmail_inline_markup())
        except Exception:
             await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=get_tempmail_inline_markup())

    elif query.data == "set_username_inline":
        # Instruct user to use the command since inline setting is complex
        text = (
            "✍️ **Set Username**\n\n"
            "To set a custom prefix, please use the command directly in the chat:\n"
            "Usage: `/set <name>`\n"
            "Name must be alphanumeric and 6-12 characters."
        )
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=get_tempmail_inline_markup())
        except Exception:
             await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=get_tempmail_inline_markup())

    elif query.data == "my_emails":
        # (This is a fallback for the old 'my_emails' button, though not on the new markup)
        emails = user_data[chat_id]["emails"]
        markup = get_tempmail_inline_markup()
        if not emails:
            text = "❌ You haven’t generated any emails yet."
        else:
            text = "📜 *Your active email:*\n\n"
            text += f"• `{user_data[chat_id]['active']}`"
        try:
            await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=markup)


async def send_tempmail_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the '📧 Temp Mail Service' button click. 
    It displays the welcome message and the updated inline buttons.
    """
    chat_id = update.effective_chat.id
    initialize_user_data(chat_id)
    
    # --- Stop 2FA Job on any Temp Mail action ---
    await stop_active_otp_job(chat_id, context)

    markup = get_tempmail_inline_markup()

    await update.message.reply_text(
        "Welcome to the **Temp Mail Service**! 📧\n\n"
        "Use the inline buttons below to manage your temporary email account and settings.",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    logger.info(f"User {update.effective_user.id} requested Temp Mail instructions.")


# --- Handlers for 2FA Bot (Bot 1) ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The unified /start command."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    logger.info(f"Received /start from user {user_id}")
    
    # --- Stop 2FA Job on /start ---
    await stop_active_otp_job(chat_id, context)

    # Initialize data for both services
    initialize_user_data(chat_id)
    
    welcome_message = (
        "👋 **Welcome to the Unified Bot!**\n\n"
        "You have access to two powerful services:\n"
        "1. **🔐 2FA Authenticator:** Generate live TOTP codes from a secret key.\n"
        "2. **📧 Temp Mail Service:** Generate temporary emails and receive OTPs instantly.\n\n"
        "Please select a service from the keyboard menu below."
    )
    
    await update.message.reply_text(welcome_message, reply_markup=REPLY_MARKUP, parse_mode='Markdown')

async def send_2fa_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the '2FA Authenticator' button click and sends instructions in Bangla."""
    chat_id = update.effective_chat.id
    
    # --- Stop 2FA Job on button click (to clear previous one) ---
    await stop_active_otp_job(chat_id, context)

    instruction_message = (
        "🔐 <b>2FA Authenticator</b>\n\n"
        "আপনার 2FA Secret Key পাঠান।\n\n"
        "📝 <b>Format:</b>\n"
        "<pre>ABCD EFGH IGK84 LM44 NSER3 LM44</pre>\n\n"
        "⚠ <b>নিয়মাবলী:</b>\n"
        "• কমপক্ষে ১৬ অক্ষর\n"
        "• শুধুমাত্র A-Z এবং 2-7\n"
        "• Space ব্যবহার করতে হবে"
    )

    await update.message.reply_text(
        instruction_message,
        parse_mode='HTML',
        reply_markup=REPLY_MARKUP
    )
    logger.info(f"User {update.effective_user.id} requested 2FA instructions.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles incoming text messages, prioritizing menu buttons first, then 2FA keys.
    """
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    # 1. Handle Menu Button Clicks
    if text == "🔐 2FA Authenticator":
        await send_2fa_instructions(update, context)
        return
    elif text == "📧 Temp Mail Service":
        await send_tempmail_instructions(update, context)
        return

    logger.info(f"User {user_id} sent message, attempting 2FA key validation.")

    # 2. Assume the remaining message is a secret key and attempt validation
    cleaned_key = text.replace(' ', '').upper()

    code, _ = calculate_totp(cleaned_key)
    
    if code is not None:
        # Key is valid, start the live countdown sequence
        # stop_active_otp_job is called inside start_countdown
        await start_countdown(update, context, cleaned_key)
    else:
        # Failed calculation (likely an invalid key or random text)
        error_message = (
            "⚠️ <b>Invalid Input</b>\n\n"
            "এটি 2FA সিক্রেট কী বা মেনু অপশন নয়।\n"
            "অনুগ্রহ করে মেনু থেকে একটি পরিষেবা নির্বাচন করুন বা একটি বৈধ 2FA সিক্রেট কী পাঠান।"
        )
        await update.message.reply_text(error_message, parse_mode='HTML', reply_markup=REPLY_MARKUP)
        logger.warning(f"Failed to process message for user {user_id}. Not a key or menu option.")

# ==============================================================================
# 6. MAIN BOT RUNNER & HANDLER REGISTRATION
# ==============================================================================

def main() -> None:
    """Start the merged bot."""
    application = Application.builder().token(BOT_TOKEN).build()

    # --- Handlers for Bot 1 (2FA Authenticator) ---
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.Text("🔐 2FA Authenticator"), send_2fa_instructions))
    application.add_handler(MessageHandler(filters.Text("📧 Temp Mail Service"), send_tempmail_instructions))
    
    # --- Handlers for Bot 2 (Temp Mail Service) ---
    application.add_handler(CommandHandler("generate", generate_new_email_command))
    application.add_handler(CommandHandler("set", set_username)) 
    application.add_handler(CommandHandler("auto_gen", auto_gen_toggle))
    # General CallbackQueryHandler for Temp Mail buttons
    application.add_handler(CallbackQueryHandler(tempmail_button_handler, pattern='^(generate|admin_stats|auto_gen_inline|set_username_inline|my_emails)$'))
    
    # --- NEW: Handler for the CLAIMED OTP button ---
    application.add_handler(CallbackQueryHandler(claim_otp_handler, pattern='^claim_otp$'))

    # General text message handler (must be last, catches 2FA keys)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Run the auto-fetch task in the background
    asyncio.get_event_loop().create_task(auto_fetch(application))

    # Run the bot
    print("🤖 Unified Bot is running. Send /start on Telegram to begin...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

from flask import Flask
import threading
app = Flask(__name__)

@app.route('/')
def home(): return "✅ Bot is running!"

def run_flask(): app.run(host="0.0.0.0", port=10000)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    main()
