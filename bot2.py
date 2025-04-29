import logging
import datetime
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode # برای استفاده از Markdown

# --- توکن ربات تلگرام ---
TELEGRAM_BOT_TOKEN = "7827254685:AAF7J122tN1OhsDkX3TSN-qI1TF_eY0ohlA" # <--- توکن خود را اینجا جایگزین کنید

# --- شناسه‌های ارزها در CoinGecko ---
target_coin_ids = [
    "bitcoin", "ethereum", "dogecoin", "cardano", "solana", "ripple", "litecoin"
]

# --- تنظیمات لاگ‌گیری ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- توابع دریافت و پردازش داده ---

def fetch_coingecko_data(coin_ids, vs_currency='usd'):
    """
    داده‌های کامل‌تر ارزها را از API CoinGecko دریافت می‌کند و به صورت دیکشنری برمی‌گرداند.
    کلید دیکشنری، شناسه ارز (id) و مقدار آن، تمام داده‌های دریافتی از API برای آن ارز است.
    """
    ids_string = ",".join(coin_ids)
    api_url = f"https://api.coingecko.com/api/v3/coins/markets"
    params = {
        'vs_currency': vs_currency,
        'ids': ids_string,
        'order': 'market_cap_desc',
        'per_page': len(coin_ids),
        'page': 1,
        'sparkline': 'false',
        'price_change_percentage': '24h' # درخواست درصد تغییرات برای نمایش
        # پارامترهای دیگر مانند 'price_change_24h' به طور پیش‌فرض توسط این endpoint برگردانده می‌شوند
    }
    try:
        response = requests.get(api_url, params=params, timeout=15) # افزایش timeout
        response.raise_for_status()
        data = response.json()
        # برگرداندن دیکشنری که کلید آن id ارز و مقدار آن کل آیتم دریافتی است
        return {item['id']: item for item in data}
    except requests.exceptions.RequestException as e:
        logger.error(f"خطا در اتصال به API CoinGecko: {e}")
        return None
    except Exception as e:
        logger.error(f"خطای نامشخص هنگام پردازش داده‌های API: {e}")
        return None

def analyze_and_rank_crypto_prices(full_api_data):
    """
    داده‌های کامل API را تحلیل و برای نمایش اولیه رتبه‌بندی می‌کند.
    ورودی: دیکشنری کامل داده‌های دریافتی از fetch_coingecko_data.
    خروجی: لیست مرتب شده برای نمایش اولیه (نام، قیمت، وضعیت تغییر).
    """
    if not full_api_data:
        return []

    results = []
    for coin_id, item in full_api_data.items():
        current = item.get('current_price')
        # محاسبه قیمت دیروز بر اساس تغییر عددی 24 ساعته
        price_change_abs = item.get('price_change_24h')
        previous = None
        if current is not None and price_change_abs is not None:
            previous = current - price_change_abs

        change = None
        status = "داده نامعتبر"
        if current is not None and previous is not None:
            change = current - previous
            if change > 0: status = f"افزایش {change:,.2f}"
            elif change < 0: status = f"کاهش {abs(change):,.2f}"
            else: status = "بدون تغییر"
        elif current is not None and previous is None:
             status = "تغییرات 24 ساعته نامشخص"
        elif current is None:
             status = "قیمت فعلی موجود نیست"

        results.append({
            "id": coin_id, # اضافه کردن id برای استفاده در دکمه‌ها
            "name": item.get('name', coin_id), # استفاده از نام یا id
            "current_price": current,
            "change_status": status,
            "raw_price": current if current is not None else float('-inf')
        })

    ranked_results = sorted(results, key=lambda x: x["raw_price"], reverse=True)
    for item in ranked_results:
        if item["raw_price"] == float('-inf'):
            item["raw_price"] = None
            item["current_price"] = None
    return ranked_results

def format_telegram_message_overview(ranked_data):
    """نتایج رتبه‌بندی شده اولیه را به فرمت پیام تلگرام تبدیل می‌کند."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"📊 **قیمت ارزهای دیجیتال (منبع: CoinGecko)** ({now}):\n\n"
    if not ranked_data:
        message += "⚠️ خطا در دریافت اطلاعات قیمت‌ها یا داده‌ای برای نمایش وجود ندارد."
        return message, None # None برای کیبورد

    keyboard_buttons = []
    for i, item in enumerate(ranked_data):
        price_str = f"${item['current_price']:,.2f}" if item['current_price'] is not None else "نامشخص"
        emoji = ""
        if "افزایش" in item['change_status']: emoji = "🔼"
        elif "کاهش" in item['change_status']: emoji = "🔽"
        elif "بدون تغییر" in item['change_status']: emoji = "➖"
        else: emoji = "❓"
        message += f"{i+1}. **{item['name']}**: {price_str} ({emoji} {item['change_status']})\n"
        # اضافه کردن دکمه برای هر ارز - callback_data باید شناسه ارز باشد
        keyboard_buttons.append(
            InlineKeyboardButton(f"{item['name']}", callback_data=item['id'])
        )

    message += "\n👇 برای جزئیات بیشتر، روی نام ارز کلیک کنید:"
    # ساخت کیبورد با دکمه‌ها در ستون‌های تکی
    keyboard = InlineKeyboardMarkup([[btn] for btn in keyboard_buttons])

    return message, keyboard

def format_coin_details_message(coin_data):
    """جزئیات یک ارز خاص را برای نمایش در تلگرام فرمت‌بندی می‌کند."""
    if not coin_data:
        return "❌ اطلاعات این ارز یافت نشد."

    name = coin_data.get('name', 'N/A')
    symbol = coin_data.get('symbol', '').upper()
    price = coin_data.get('current_price')
    price_str = f"${price:,.2f}" if price is not None else "نامشخص"
    change_perc_24h = coin_data.get('price_change_percentage_24h')
    change_perc_str = f"{change_perc_24h:+.2f}%" if change_perc_24h is not None else "نامشخص"
    change_emoji = "🔼" if change_perc_24h is not None and change_perc_24h > 0 else ("🔽" if change_perc_24h is not None and change_perc_24h < 0 else "➖")

    high_24h = coin_data.get('high_24h')
    high_24h_str = f"${high_24h:,.2f}" if high_24h is not None else "نامشخص"
    low_24h = coin_data.get('low_24h')
    low_24h_str = f"${low_24h:,.2f}" if low_24h is not None else "نامشخص"

    market_cap = coin_data.get('market_cap')
    market_cap_str = f"${market_cap:,.0f}" if market_cap is not None else "نامشخص"
    market_cap_rank = coin_data.get('market_cap_rank', 'N/A')

    volume = coin_data.get('total_volume')
    volume_str = f"${volume:,.0f}" if volume is not None else "نامشخص"

    circ_supply = coin_data.get('circulating_supply')
    circ_supply_str = f"{circ_supply:,.0f} {symbol}" if circ_supply is not None else "نامشخص"
    total_supply = coin_data.get('total_supply')
    total_supply_str = f"{total_supply:,.0f} {symbol}" if total_supply is not None else "نامشخص"
    max_supply = coin_data.get('max_supply')
    max_supply_str = f"{max_supply:,.0f} {symbol}" if max_supply is not None else ("نامحدود" if total_supply is not None else "نامشخص")


    message = f"💎 **جزئیات {name} ({symbol})** 💎\n\n"
    message += f"💰 **قیمت فعلی:** {price_str}\n"
    message += f"📈 **تغییر ۲۴ ساعته:** {change_emoji} {change_perc_str}\n"
    message += f"⬆️ **بالاترین (۲۴س):** {high_24h_str}\n"
    message += f"⬇️ **پایین‌ترین (۲۴س):** {low_24h_str}\n\n"
    message += f"📊 **ارزش بازار:** {market_cap_str} (رتبه #{market_cap_rank})\n"
    message += f"🔄 **حجم معاملات (۲۴س):** {volume_str}\n\n"
    message += f"流通 **عرضه در گردش:** {circ_supply_str}\n"
    message += f"📦 **کل عرضه:** {total_supply_str}\n"
    message += f"🔒 **حداکثر عرضه:** {max_supply_str}\n\n"
    message += f"_منبع: CoinGecko | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_"

    return message

# --- توابع کنترل‌کننده ربات ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پاسخ به دستور /start"""
    user = update.effective_user
    await update.message.reply_html(
        f"سلام {user.mention_html()}!\n\nبرای دریافت آخرین قیمت ارزهای دیجیتال، دستور /price را ارسال کنید.",
    )

async def get_prices(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لیست قیمت‌ها و دکمه‌های جزئیات را ارسال می‌کند."""
    message_to_edit = await update.message.reply_text("لطفاً صبر کنید، در حال دریافت اطلاعات قیمت‌ها...")

    # ۱. دریافت داده های کامل از CoinGecko
    full_crypto_data = fetch_coingecko_data(target_coin_ids, vs_currency='usd')

    if full_crypto_data:
        # ذخیره داده‌های کامل در context برای استفاده در callback handler
        context.bot_data['crypto_data'] = full_crypto_data

        # ۲. تحلیل و رتبه بندی برای نمایش اولیه
        analysis_results = analyze_and_rank_crypto_prices(full_crypto_data)
        # ۳. قالب بندی پیام اولیه و ایجاد کیبورد
        overview_message, keyboard = format_telegram_message_overview(analysis_results)

        # ۴. ویرایش پیام اولیه و اضافه کردن کیبورد
        await message_to_edit.edit_text(
            overview_message,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN # استفاده از Markdown
        )
    else:
        # ایجاد پیام خطا اگر دریافت داده ناموفق بود
        overview_message, _ = format_telegram_message_overview([])
        await message_to_edit.edit_text(overview_message, parse_mode=ParseMode.MARKDOWN)


async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پاسخ به کلیک روی دکمه‌های Inline Keyboard."""
    query = update.callback_query
    await query.answer() # پاسخ به تلگرام که کلیک دریافت شد

    selected_coin_id = query.data # شناسه ارز از دکمه کلیک شده
    logger.info(f"دکمه برای {selected_coin_id} کلیک شد.")

    # بازیابی داده‌های ذخیره شده
    crypto_data = context.bot_data.get('crypto_data')

    if not crypto_data:
        await query.edit_message_text(text="❌ متاسفانه داده‌های قیمت منقضی شده یا یافت نشد. لطفاً دوباره /price را اجرا کنید.")
        return

    coin_details = crypto_data.get(selected_coin_id)

    if not coin_details:
        await query.edit_message_text(text=f"❌ اطلاعات برای شناسه '{selected_coin_id}' یافت نشد.")
        logger.warning(f"اطلاعات برای شناسه {selected_coin_id} در داده‌های ذخیره شده یافت نشد.")
        return

    # فرمت کردن پیام جزئیات
    details_message = format_coin_details_message(coin_details)

    # ایجاد دکمه "بازگشت به لیست"
    back_button = InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="back_to_list")
    keyboard = InlineKeyboardMarkup([[back_button]])

    # ویرایش پیام برای نمایش جزئیات و دکمه بازگشت
    try:
        await query.edit_message_text(
            text=details_message,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN # استفاده از Markdown
        )
    except Exception as e:
        logger.error(f"خطا در ویرایش پیام برای نمایش جزئیات {selected_coin_id}: {e}")
        # اگر ویرایش ممکن نبود (مثلا پیام خیلی قدیمی است)، پیام جدید بفرست
        try:
             await context.bot.send_message(chat_id=query.message.chat_id, text=details_message, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        except Exception as send_e:
             logger.error(f"خطا در ارسال پیام جدید برای جزئیات {selected_coin_id}: {send_e}")


async def back_to_list_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """بازگرداندن پیام به لیست اولیه قیمت‌ها."""
    query = update.callback_query
    await query.answer()

    # بازیابی داده‌های ذخیره شده
    crypto_data = context.bot_data.get('crypto_data')
    if not crypto_data:
        await query.edit_message_text(text="❌ متاسفانه داده‌های قیمت منقضی شده یا یافت نشد. لطفاً دوباره /price را اجرا کنید.")
        return

    # بازسازی پیام اولیه
    analysis_results = analyze_and_rank_crypto_prices(crypto_data)
    overview_message, keyboard = format_telegram_message_overview(analysis_results)

    try:
        await query.edit_message_text(
            text=overview_message,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"خطا در ویرایش پیام برای بازگشت به لیست: {e}")
        # اگر ویرایش ممکن نبود، پیام جدید بفرست
        try:
            await context.bot.send_message(chat_id=query.message.chat_id, text=overview_message, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        except Exception as send_e:
            logger.error(f"خطا در ارسال پیام جدید برای بازگشت به لیست: {send_e}")


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پاسخ به دستورات ناشناخته"""
    await update.message.reply_text("متاسفم، این دستور را متوجه نمی‌شوم. لطفاً از /price استفاده کنید.")

# --- بخش اصلی اجرای ربات ---
def main() -> None:
    """ربات را راه‌اندازی و اجرا می‌کند."""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # ثبت کنترل‌کننده‌ها
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("price", get_prices))

    # ثبت کنترل‌کننده برای کلیک روی دکمه‌های ارزها و دکمه بازگشت
    # از یک regex برای تفکیک callback_data استفاده می‌کنیم
    # اگر callback_data برابر 'back_to_list' بود، تابع back_to_list_callback_handler اجرا می‌شود
    # در غیر این صورت (که شناسه ارز است)، تابع button_callback_handler اجرا می‌شود
    application.add_handler(CallbackQueryHandler(back_to_list_callback_handler, pattern='^back_to_list$'))
    application.add_handler(CallbackQueryHandler(button_callback_handler, pattern='^(?!back_to_list$).*$')) # هر چیزی غیر از back_to_list

    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    print("ربات در حال اجرا است...")
    application.run_polling()

if __name__ == "__main__":
    main()

