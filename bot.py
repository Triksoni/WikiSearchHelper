from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler
from telegram.ext import filters
import wikipedia
import logging
import requests
from io import BytesIO

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Токен бота
BOT_TOKEN = "8520840494:AAGIZrOSMldm3XIdOo9dCLm6_CYbyAxft2E"

# Настройка языка Википедии
wikipedia.set_lang("ru")

# Состояния для ConversationHandler
SEARCH, CLARIFY = range(2)


def get_article_image(page_title):
    """Получаем URL главного изображения статьи"""
    try:
        # Создаем объект страницы для получения изображений
        page = wikipedia.page(page_title)

        # Возвращаем список изображений (обычно первое - главное)
        if page.images:
            # Фильтруем только изображения из Википедии
            wiki_images = [img for img in page.images if 'upload.wikimedia.org' in img]
            if wiki_images:
                return wiki_images[0]  # Возвращаем первое изображение
        return None
    except Exception as e:
        logging.error(f"Error getting image for {page_title}: {e}")
        return None


async def send_article_with_image(update, article_title, summary, page_url, image_url=None):
    """Отправляем статью с изображением"""
    try:
        # Если есть изображение, отправляем его с подписью
        if image_url:
            try:
                # Скачиваем изображение
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    photo_data = BytesIO(response.content)
                    photo_data.name = 'image.jpg'

                    # Формируем подпись к фото
                    caption = f"📖 **{article_title}**\n\n{summary}\n\n🔗 [Читать полностью]({page_url})"

                    # Отправляем фото с подписью
                    await update.message.reply_photo(
                        photo=photo_data,
                        caption=caption,
                        parse_mode='Markdown'
                    )
                    return True
            except Exception as e:
                logging.error(f"Error sending photo: {e}")
                # Если не удалось отправить фото, продолжаем без него

        # Если изображения нет или не удалось отправить, отправляем текстовое сообщение
        response = f"📖 **{article_title}**\n\n{summary}\n\n🔗 [Читать полностью]({page_url})"
        await update.message.reply_text(response, parse_mode='Markdown')
        return True

    except Exception as e:
        logging.error(f"Error sending article: {e}")
        return False


async def start(update, context):
    """Обработчик команды /start"""
    welcome_text = """
🔍 **Вики-бот с уточняющим поиском и иллюстрациями**

Просто отправь мне любое слово, и я помогу найти нужную информацию в Википедии с картинками!

Например: "Яблоко", "Python", "Москва" и т.д.
    """
    await update.message.reply_text(welcome_text)
    return SEARCH


async def start_search(update, context):
    """Начало поиска - получаем запрос пользователя"""
    user_query = update.message.text

    # Показываем, что бот печатает
    await update.message.chat.send_action(action="typing")

    # Сохраняем запрос пользователя
    context.user_data['original_query'] = user_query

    # Ищем варианты в Википедии
    try:
        search_results = wikipedia.search(user_query)

        if not search_results:
            await update.message.reply_text("❌ Ничего не найдено по вашему запросу.")
            return ConversationHandler.END

        # Сохраняем результаты поиска
        context.user_data['search_results'] = search_results

        if len(search_results) == 1:
            # Если найден только один вариант - сразу показываем
            return await show_article(update, context, search_results[0])
        else:
            # Если несколько вариантов - предлагаем уточнить
            return await ask_for_clarification(update, context, search_results)

    except Exception as e:
        await update.message.reply_text("😵 Произошла ошибка при поиске.")
        logging.error(f"Search error: {e}")
        return ConversationHandler.END


async def ask_for_clarification(update, context, search_results):
    """Спрашиваем у пользователя, что именно его интересует"""
    # Берем первые 6 вариантов
    options = search_results[:6]

    # Формируем сообщение с вариантами
    message = "🤔 Я нашел несколько вариантов. Что именно вас интересует?\n\n"

    for i, option in enumerate(options, 1):
        message += f"{i}. {option}\n"

    message += "\n📝 Или напишите свой уточняющий запрос"
    message += "\n🖼️ Я постараюсь найти иллюстрации к статьям!"
    message += "\n❌ Или отправьте /cancel для отмены"

    await update.message.reply_text(message)
    return CLARIFY


async def handle_clarification(update, context):
    """Обрабатываем уточнение от пользователя"""
    user_choice = update.message.text

    # Показываем, что бот печатает
    await update.message.chat.send_action(action="typing")

    # Получаем сохраненные результаты поиска
    search_results = context.user_data.get('search_results', [])

    try:
        # Проверяем, выбрал ли пользователь номер из списка
        if user_choice.isdigit():
            choice_index = int(user_choice) - 1
            if 0 <= choice_index < len(search_results):
                selected_article = search_results[choice_index]
                return await show_article(update, context, selected_article)
            else:
                await update.message.reply_text("❌ Неверный номер. Попробуйте еще раз.")
                return CLARIFY
        else:
            # Пользователь ввел свой запрос - ищем конкретную информацию
            return await search_specific_info(update, context, user_choice)

    except Exception as e:
        await update.message.reply_text("😵 Произошла ошибка.")
        logging.error(f"Clarification error: {e}")
        return ConversationHandler.END


async def search_specific_info(update, context, specific_query):
    """Ищем конкретную информацию в статье"""
    search_results = context.user_data.get('search_results', [])

    if not search_results:
        await update.message.reply_text("❌ Не удалось найти информацию.")
        return ConversationHandler.END

    try:
        # Берем первую (самую релевантную) статью
        main_article = search_results[0]
        page = wikipedia.page(main_article)

        # Получаем изображение для статьи
        image_url = get_article_image(main_article)

        # Ищем упоминания конкретного запроса в статье
        content_lower = page.content.lower()
        specific_query_lower = specific_query.lower()

        if specific_query_lower in content_lower:
            # Находим предложения с этим запросом
            sentences = page.content.split('.')
            relevant_sentences = []

            for sentence in sentences:
                if specific_query_lower in sentence.lower() and len(sentence.strip()) > 10:
                    relevant_sentences.append(sentence.strip())
                    if len(relevant_sentences) >= 3:  # Ограничиваем 3 предложениями
                        break

            if relevant_sentences:
                summary = f"🔍 **Информация о '{specific_query}' в статье '{main_article}':**\n\n"
                summary += '.\n'.join(relevant_sentences) + '.'
            else:
                summary = wikipedia.summary(main_article, sentences=3)
                summary += f"\n\nℹ️ Запрос '{specific_query}' встречается в статье, но я не смог выделить конкретные предложения."
        else:
            summary = wikipedia.summary(main_article, sentences=3)
            summary += f"\n\n❌ Запрос '{specific_query}' не найден в этой статье."

        # Отправляем статью с изображением
        await send_article_with_image(update, main_article, summary, page.url, image_url)
        return ConversationHandler.END

    except Exception as e:
        await update.message.reply_text("😵 Произошла ошибка при поиске информации.")
        logging.error(f"Specific search error: {e}")
        return ConversationHandler.END


async def show_article(update, context, article_title):
    """Показываем статью с изображением"""
    try:
        # Показываем, что бот печатает
        await update.message.chat.send_action(action="typing")

        page = wikipedia.page(article_title)
        summary = wikipedia.summary(article_title, sentences=4)

        # Получаем изображение для статьи
        image_url = get_article_image(article_title)

        # Отправляем статью с изображением
        await send_article_with_image(update, page.title, summary, page.url, image_url)
        return ConversationHandler.END

    except Exception as e:
        await update.message.reply_text("😵 Не удалось загрузить статью.")
        logging.error(f"Article error: {e}")
        return ConversationHandler.END


async def cancel(update, context):
    """Отмена операции"""
    await update.message.reply_text("❌ Поиск отменен.")
    return ConversationHandler.END


def main():
    """Основная функция"""
    # Создаем Application вместо Updater
    application = Application.builder().token(BOT_TOKEN).build()

    # Настраиваем ConversationHandler для управления диалогом
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, start_search)
        ],
        states={
            SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, start_search)
            ],
            CLARIFY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_clarification)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)

    # Запускаем бота
    print("🤖 Бот запущен и готов к уточняющему поиску с иллюстрациями!")
    application.run_polling()


if __name__ == '__main__':
    main()
