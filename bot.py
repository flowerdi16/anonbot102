import asyncio
import os

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    InputMediaPhoto,
    InputMediaVideo,
)
from aiogram.filters import Command
from dotenv import load_dotenv

from db import (
    init_db,
    add_user,
    is_banned,
    ban,
    unban,
    get_banned,
    save_message,
    get_user
)
from collections import defaultdict

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_IDS_RAW = os.getenv("GROUP_IDS")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is empty")
if not GROUP_IDS_RAW:
    raise ValueError("GROUP_IDS is empty")

GROUP_IDS = list(map(int, GROUP_IDS_RAW.split(",")))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
albums = defaultdict(list)
album_tasks = {}

async def delete_after_5_seconds(message: Message):
    await asyncio.sleep(5)
    try:
        await message.delete()
    except Exception as e:
        print(f"DELETE CONFIRMATION ERROR: {e}")

# ================= START =================
@dp.message(Command("start"))
async def start(message: Message):
    await add_user(message.from_user)
    await message.answer("Напишите анонимное сообщение.")


# ================= USER -> GROUPS =================
@dp.message(F.chat.type == "private")
async def user_to_groups(message: Message):
    try:
        user = message.from_user
        await add_user(user)

        if await is_banned(user.id):
            await message.answer("Вы заблокированы.")
            return

        if message.text and message.text.startswith("/"):
            return

        # ======== АЛЬБОМ ========
        if message.media_group_id:
            media_group_id = message.media_group_id
            albums[media_group_id].append(message)

            if media_group_id in album_tasks:
                return

            async def send_album():
                await asyncio.sleep(1)

                media_messages = albums.pop(media_group_id, [])
                album_tasks.pop(media_group_id, None)

                media_messages.sort(key=lambda x: x.message_id)

                media = []

                for i, msg in enumerate(media_messages):

                    caption = msg.caption if i == 0 else None

                    if msg.photo:
                        media.append(
                            InputMediaPhoto(
                                media=msg.photo[-1].file_id,
                                caption=caption
                            )
                        )

                    elif msg.video:
                        media.append(
                            InputMediaVideo(
                                media=msg.video.file_id,
                                caption=caption
                            )
                        )

                if not media:
                    return

                for group_id in GROUP_IDS:
                    sent_messages = await bot.send_media_group(
                        chat_id=group_id,
                        media=media
                    )

                    for sent in sent_messages:
                        await save_message(sent.message_id, user.id)

                await message.answer("Ваше сообщение успешно доставлено ✅")
                asyncio.create_task(delete_after_5_seconds(sent))

            album_tasks[media_group_id] = asyncio.create_task(send_album())
            return

        # ======== ОБЫЧНОЕ СООБЩЕНИЕ ========
        for group_id in GROUP_IDS:
            sent = await bot.copy_message(
                chat_id=group_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )

            await save_message(sent.message_id, user.id)

        sent = await message.answer("Ваше сообщение успешно доставлено ✅")
        asyncio.create_task(delete_after_5_seconds(sent))

    except Exception as e:
        print(f"USER_TO_GROUPS ERROR: {e}")


# ================= GROUP REPLY HANDLER =================
@dp.message(
    F.chat.id.in_(GROUP_IDS),
    F.reply_to_message
)
async def group_handler(message: Message):
    try:
        user_id = await get_user(message.reply_to_message.message_id)

        if not user_id:
            return

        text = message.text or ""

        if text == "/ban":
            await ban(user_id)
            await message.reply("Пользователь забанен.")
            return

        if text == "/unban":
            await unban(user_id)
            await message.reply("Пользователь разбанен.")
            return

        if text == "/link":
            user_id = await get_user(message.reply_to_message.message_id)

            if not user_id:
                await message.reply("Пользователь не найден.")
                return

            await message.reply(
                f"tg://user?id={user_id}\n"
                f"tg://openmessage?user_id={user_id}"
            )
            return

        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id
        )

    except Exception as e:
        print(f"GROUP_HANDLER ERROR: {e}")


# ================= BANLIST (ДОСТУП ВО ВСЕХ GROUP_IDS) =================
@dp.message(Command("banlist"))
async def ban_list(message: Message):
    try:
        print("BANLIST TRIGGERED")
        print("CHAT ID:", message.chat.id)
        print("ALLOWED:", GROUP_IDS)

        if message.chat.id not in GROUP_IDS:
            await message.answer("Нет доступа к этой команде")
            return

        rows = await get_banned()

        if not rows:
            await message.answer("Список банов пуст.")
            return

        text = "Забаненные пользователи:\n\n"

        for i, row in enumerate(rows, 1):
            uid, username, name, ban_date = row

            text += (
                f"{i}. {name}\n"
                f"@{username or 'no_username'}\n"
                f"ID: {uid}\n"
                f"{ban_date}\n\n"
            )

        await message.answer(text)

    except Exception as e:
        print("BANLIST ERROR:", e)
        await message.answer(f"Ошибка: {e}")


# ================= MAIN =================
async def main():
    await init_db()
    print("BOT STARTED")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())