import requests
import asyncio
import random
import re
import string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = "8017229052:AAEb-YaMRVP7JkPiDFAufqmL1uSTEmEFxfc"

# -------------------------------
# 📌 User storage
# -------------------------------
user_data = {}

# -------------------------------
# 🌐 Known Sender Domain Mapping
# -------------------------------
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

# -------------------------------
# 📬 TempMail API Helpers
# -------------------------------
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
        print(f"Error fetching inbox for {email}: {e}")
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


# -------------------------------
# 🎯 OTP Extractor (Helper - UNCHANGED)
# -------------------------------
def extract_otp(subject, content):
    """
    Searches subject and content for a 4-8 digit OTP.
    Prioritizes the subject line.
    """
    otp_pattern = re.compile(
        r'(?:OTP|CODE|PIN|verification|one[\s_-]time).*?(\d{4,8})' 
        r'|(\b\d{4,8}\b)'
    , re.IGNORECASE | re.DOTALL)
    
    # 1. Search the Subject first
    match = otp_pattern.search(subject)
    if match:
        return match.group(1) or match.group(2)

    # 2. Search the Body if not found in Subject
    match = otp_pattern.search(content)
    if match:
        return match.group(1) or match.group(2)
        
    return None

# -------------------------------
# 📝 Bot Handlers 
# -------------------------------
def initialize_user_data(chat_id):
    """Ensures necessary keys exist for a new user."""
    if chat_id not in user_data:
        user_data[chat_id] = {"emails": [], "active": None, "last_seen_id": None, "username": None, "auto_gen_on": False}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    initialize_user_data(update.message.chat_id)
    buttons = [
        [InlineKeyboardButton(" Generate Email", callback_data="generate")],
        [InlineKeyboardButton(" My Emails", callback_data="my_emails")]
    ]
    markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(
        "Welcome to @mailnishanbot New Webmail Bot on Telegram With New Future.\n\n"
        " Use /auto_gen to get a new email automatically after receiving an Otp. Use /set for a customized address.⏰Wait 3-4 Second For The Otp",
        reply_markup=markup
    )

async def set_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /set command for custom usernames."""
    chat_id = update.message.chat_id
    initialize_user_data(chat_id)
    
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
        "Use the **Generate Email** button or **/generate** command to create a new address with this prefix.",
        parse_mode="Markdown"
    )

async def auto_gen_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggles the automatic email generation after OTP is received."""
    chat_id = update.message.chat_id
    initialize_user_data(chat_id)
    
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

async def generate_new_email_logic(chat_id: int, username_prefix: str, update: Update, context: ContextTypes.DEFAULT_TYPE, is_callback: bool):
    """Central logic for generating a new email, used by both button and command."""
    email = generate_email(username_prefix)

    # Clear existing entries and start fresh with only one email in history
    user_data[chat_id]["emails"] = [email]
    user_data[chat_id]["active"] = email
    user_data[chat_id]["last_seen_id"] = None 
    
    response_text = f"〽️New Web Mail Generated:\n`{email}`\n⏰Wait 3-4 Second For The Otp"

    if is_callback:
        await update.callback_query.edit_message_text(
            response_text,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            response_text,
            parse_mode="Markdown"
        )

async def generate_new_email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /generate command."""
    chat_id = update.message.chat_id
    initialize_user_data(chat_id)
    username_prefix = user_data[chat_id].get("username")
    
    await generate_new_email_logic(chat_id, username_prefix, update, context, is_callback=False)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    initialize_user_data(chat_id)

    if query.data == "generate":
        username_prefix = user_data[chat_id].get("username")
        await generate_new_email_logic(chat_id, username_prefix, update, context, is_callback=True)

    elif query.data == "my_emails":
        emails = user_data[chat_id]["emails"]
        
        # Recreate the main buttons for the message
        buttons = [
            [InlineKeyboardButton("📧 Generate Email", callback_data="generate")],
            [InlineKeyboardButton("📜 My Emails", callback_data="my_emails")]
        ]
        markup = InlineKeyboardMarkup(buttons)
        
        if not emails:
            text = "❌ You haven’t generated any emails yet."
        else:
            text = "📜 *Your generated emails:*\n\n"
            for e in emails:
                marker = " (active)" if e == user_data[chat_id]["active"] else ""
                text += f"• `{e}`{marker}\n"
        
        # Edit the previous message to show the updated list
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)


# -------------------------------
# 🔄 Auto-fetch task 
# -------------------------------
async def auto_fetch(app: Application):
    while True:
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
                            f"*From:* {clean_sender}\n\n"
                            f"**{display_body_msg}**"
                        )
                    else:
                        display_body = content if content.strip() else "--- Mail body was empty or only contained unreadable data ---"
                        display_body_msg = f"Full Body:\n```\n{display_body[:500]}{'...' if len(display_body) > 500 else ''}\n```"
                        msg = (
                            f"📩 *New Mail Received!*\n\n"
                            f"*From:* {clean_sender}\n\n"
                            f"*Compose Mail (Full Body):*\n{display_body_msg}"
                        )
                    
                    try:
                        await app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
                        
                    except Exception as e:
                        print(f"Error sending message to {chat_id}: {e}")
                
                # 🔥 6. AUTO-GENERATE NEW MAIL LOGIC - TRIGGERED IF ANY NEW MAIL RECEIVED 🔥
                if new_mails_received and data.get("auto_gen_on"):
                    username_prefix = data.get("username")
                    new_email = generate_email(username_prefix)
                    
                    # Update user data:
                    # 1. Clear ALL previous emails (since we only keep one active)
                    data["emails"] = []
                    # 2. Add the new email
                    data["emails"].append(new_email)
                    # 3. Set the new email as active
                    data["active"] = new_email
                    # 4. Reset last_seen_id
                    data["last_seen_id"] = None
                    
                    # ⚡️ AUTO-TRIGGER "MY EMAILS" UPDATE ⚡️
                    
                    # Recreate the buttons for the message
                    buttons = [
                        [InlineKeyboardButton("📧 Generate Email", callback_data="generate")],
                        [InlineKeyboardButton("📜 My Emails", callback_data="my_emails")]
                    ]
                    markup = InlineKeyboardMarkup(buttons)
                    
                    text = (
                        f"♻️ **Auto-Generated New Email!** ♻️\n\n"
                        f"The previous email was deleted. Here is your updated email status:\n\n"
                        f"📜 *Your generated emails:*\n\n"
                        f"• `{new_email}` (active)"
                    )
                    
                    # Send the updated list
                    await app.bot.send_message(
                        chat_id=chat_id, 
                        text=text, 
                        parse_mode="Markdown",
                        reply_markup=markup # Include buttons for easy next actions
                    )

                    # Break the outer loop to stop polling the old email immediately
                    break 

        # Sleep for 3 seconds
        await asyncio.sleep(3)

# -------------------------------
# 🚀 Main
# -------------------------------
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("generate", generate_new_email_command)) # ADDED GENERATE COMMAND HERE
    app.add_handler(CommandHandler("set", set_username)) 
    app.add_handler(CommandHandler("auto_gen", auto_gen_toggle))
    app.add_handler(CallbackQueryHandler(button_handler))

    asyncio.get_event_loop().create_task(auto_fetch(app))

    app.run_polling()
print("🤖Bot Is running")

if __name__ == "__main__":
    main()