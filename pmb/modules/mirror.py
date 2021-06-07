import requests
from telegram.ext import CommandHandler
from telegram import InlineKeyboardMarkup

from pmb import Interval, INDEX_URL,LOGGER, MEGA_KEY, BUTTON_THREE_NAME, BUTTON_THREE_URL, BUTTON_FOUR_NAME, BUTTON_FOUR_URL, BUTTON_FIVE_NAME, BUTTON_FIVE_URL, BLOCK_MEGA_LINKS, BLOCK_MEGA_FOLDER
from pmb import dispatcher, DOWNLOAD_DIR, DOWNLOAD_STATUS_UPDATE_INTERVAL, download_dict, download_dict_lock, SHORTENER, SHORTENER_API
from pmb.helper.ext_utils import fs_utils, bot_utils
from pmb.helper.ext_utils.bot_utils import setInterval
from pmb.helper.ext_utils.exceptions import DirectDownloadLinkException, NotSupportedExtractionArchive
from pmb.helper.mirror_utils.download_utils.aria2_download import AriaDownloadHelper
from pmb.helper.mirror_utils.download_utils.direct_link_generator import direct_link_generator
from pmb.helper.mirror_utils.download_utils.telegram_downloader import TelegramDownloadHelper
from pmb.helper.mirror_utils.status_utils import listeners
from pmb.helper.mirror_utils.status_utils.extract_status import ExtractStatus
from pmb.helper.mirror_utils.status_utils.tar_status import TarStatus
from pmb.helper.mirror_utils.status_utils.upload_status import UploadStatus
from pmb.helper.mirror_utils.upload_utils import gdriveTools
from pmb.helper.telegram_helper.bot_commands import BotCommands
from pmb.helper.telegram_helper.filters import CustomFilters
from pmb.helper.telegram_helper.message_utils import *
from pmb.helper.telegram_helper import button_build
from pmb.helper.mirror_utils.download_utils.mega_download import MegaDownloader
import urllib
import pathlib
import os
import subprocess
import threading
import re

ariaDlManager = AriaDownloadHelper()
ariaDlManager.start_listener()

class MirrorListener(listeners.MirrorListeners):
    def __init__(self, bot, update, pswd, isTar=False, tag=None, extract=False):
        super().__init__(bot, update)
        self.isTar = isTar
        self.tag = tag
        self.extract = extract
        self.pswd = pswd

    def onDownloadStarted(self):
        pass

    def onDownloadProgress(self):
        # We are handling this on our own!
        pass

    def clean(self):
        try:
            Interval[0].cancel()
            del Interval[0]
            delete_all_messages()
        except IndexError:
            pass

    def onDownloadComplete(self):
        with download_dict_lock:
            LOGGER.info(f"Download completed: {download_dict[self.uid].name()}")
            download = download_dict[self.uid]
            name = download.name()
            size = download.size_raw()
            m_path = f'{DOWNLOAD_DIR}{self.uid}/{download.name()}'
        if self.isTar:
            download.is_archiving = True
            try:
                with download_dict_lock:
                    download_dict[self.uid] = TarStatus(name, m_path, size)
                path = fs_utils.tar(m_path)
            except FileNotFoundError:
                LOGGER.info('File to archive not found!')
                self.onUploadError('Internal error occurred!!')
                return
        elif self.extract:
            download.is_extracting = True
            try:
                path = fs_utils.get_base_name(m_path)
                LOGGER.info(
                    f"Extracting : {name} "
                )
                with download_dict_lock:
                    download_dict[self.uid] = ExtractStatus(name, m_path, size)
                pswd = self.pswd
                if pswd is not None:
                    archive_result = subprocess.run(["pextract", m_path, pswd])
                else:
                    archive_result = subprocess.run(["extract", m_path])
                if archive_result.returncode == 0:
                    threading.Thread(target=os.remove, args=(m_path,)).start()
                    LOGGER.info(f"Deleting archive : {m_path}")
                else:
                    LOGGER.warning('Unable to extract archive! Uploading anyway')
                    path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
                LOGGER.info(
                    f'got path : {path}'
                )

            except NotSupportedExtractionArchive:
                LOGGER.info("Not any valid archive, uploading file as it is.")
                path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
        else:
            path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
        up_name = pathlib.PurePath(path).name
        up_path = f'{DOWNLOAD_DIR}{self.uid}/{up_name}'
        if up_name == "None":
            up_name = "".join(os.listdir(f'{DOWNLOAD_DIR}{self.uid}/'))
        LOGGER.info(f"Upload Name : {up_name}")
        drive = gdriveTools.GoogleDriveHelper(up_name, self)
        size = fs_utils.get_path_size(up_path)
        upload_status = UploadStatus(drive, size, self)
        with download_dict_lock:
            download_dict[self.uid] = upload_status
        update_all_messages()
        drive.upload(up_name)

    def onDownloadError(self, error):
        error = error.replace('<', ' ')
        error = error.replace('>', ' ')
        LOGGER.info(self.update.effective_chat.id)
        with download_dict_lock:
            try:
                download = download_dict[self.uid]
                del download_dict[self.uid]
                LOGGER.info(f"Deleting folder: {download.path()}")
                fs_utils.clean_download(download.path())
                LOGGER.info(str(download_dict))
            except Exception as e:
                LOGGER.error(str(e))
                pass
            count = len(download_dict)
        if self.message.from_user.username:
            uname = f"@{self.message.from_user.username}"
        else:
            uname = f'<a href="tg://user?id={self.message.from_user.id}">{self.message.from_user.first_name}</a>'
        msg = f"{uname} your download has been stopped due to: {error} @admin"
        sendMessage(msg, self.bot, self.update)
        if count == 0:
            self.clean()
        else:
            update_all_messages()

    def onUploadStarted(self):
        pass

    def onUploadProgress(self):
        pass

    def onUploadComplete(self, link: str, size):
        with download_dict_lock:
            msg = f'<b>🗂 𝗙𝗶𝗹𝗲𝗡𝗮𝗺𝗲 : </b><code>{download_dict[self.uid].name()}</code>\n<b>📦 𝐓𝐨𝐭𝐚𝐥 𝐒𝐢𝐳𝐞 : </b><code>{size}</code>\n' \
                  f' \n' \
                  f'ᴅʀᴀɢᴏɴ ᴍɪʀʀᴏʀ ᴢᴏɴᴇ\n' \
                  f' \n' \
                  f'🎴𝙂𝙧𝙤𝙪𝙥 : @DragonMirror\n'
            buttons = button_build.ButtonMaker()
            if SHORTENER is not None and SHORTENER_API is not None:
                surl = requests.get(f'https://{SHORTENER}/api?api={SHORTENER_API}&url={link}&format=text').text
                buttons.buildbutton("🗂 𝐃𝐫𝐢𝐯𝐞 𝐋𝐢𝐧𝐤 🗂", surl)
            else:
                buttons.buildbutton("🗂 𝐃𝐫𝐢𝐯𝐞 𝐋𝐢𝐧𝐤 🗂", link)
            LOGGER.info(f'Done Uploading {download_dict[self.uid].name()}')
            if INDEX_URL is not None:
                url_path = requests.utils.quote(f'{download_dict[self.uid].name()}')
                share_url = f'{INDEX_URL}/{url_path}'
                if os.path.isdir(f'{DOWNLOAD_DIR}/{self.uid}/{download_dict[self.uid].name()}'):
                    share_url += '/'
                if SHORTENER is not None and SHORTENER_API is not None:
                    siurl = requests.get(f'https://{SHORTENER}/api?api={SHORTENER_API}&url={share_url}&format=text').text
                    buttons.buildbutton("🚀 𝐈𝐧𝐝𝐞𝐱 𝐋𝐢𝐧𝐤 🚀", siurl)
                else:
                    buttons.buildbutton("🚀 𝐈𝐧𝐝𝐞𝐱 𝐋𝐢𝐧𝐤 🚀", share_url)
            if BUTTON_THREE_NAME is not None and BUTTON_THREE_URL is not None:
                buttons.buildbutton(f"{BUTTON_THREE_NAME}", f"{BUTTON_THREE_URL}")
            if BUTTON_FOUR_NAME is not None and BUTTON_FOUR_URL is not None:
                buttons.buildbutton(f"{BUTTON_FOUR_NAME}", f"{BUTTON_FOUR_URL}")
            if BUTTON_FIVE_NAME is not None and BUTTON_FIVE_URL is not None:
                buttons.buildbutton(f"{BUTTON_FIVE_NAME}", f"{BUTTON_FIVE_URL}")
            if self.message.from_user.username:
                uname = f"@{self.message.from_user.username}"
            else:
                uname = f'<a href="tg://user?id={self.message.from_user.id}">{self.message.from_user.first_name}</a>'
            if uname is not None:
                msg += f'\n\n<b>👤 𝗨𝗽𝗹𝗼𝗮𝗱𝗲𝗿 : 👉</b> {uname}\n\n▫️#Uploaded To Team Drive ✓ \n\n🚫 𝘿𝙤 𝙉𝙤𝙩 𝙎𝙝𝙖𝙧𝙚 𝙄𝙣𝙙𝙚𝙭 𝙇𝙞𝙣𝙠 \n\n✅ 𝗣𝗼𝘄𝗲𝗿𝗲𝗱 𝗕𝘆 : <b>@DragonMirror</b>'
            try:
                fs_utils.clean_download(download_dict[self.uid].path())
            except FileNotFoundError:
                pass
            del download_dict[self.uid]
            count = len(download_dict)
        sendMarkup(msg, self.bot, self.update, InlineKeyboardMarkup(buttons.build_menu(2)))
        if count == 0:
            self.clean()
        else:
            update_all_messages()

    def onUploadError(self, error):
        e_str = error.replace('<', '').replace('>', '')
        with download_dict_lock:
            try:
                fs_utils.clean_download(download_dict[self.uid].path())
            except FileNotFoundError:
                pass
            del download_dict[self.message.message_id]
            count = len(download_dict)
        sendMessage(e_str, self.bot, self.update)
        if count == 0:
            self.clean()
        else:
            update_all_messages()

def _mirror(bot, update, isTar=False, extract=False):
    mesg = update.message.text.split('\n')
    message_args = mesg[0].split(' ')
    name_args = mesg[0].split('|')
    try:
        link = message_args[1]
        print(link)
        if link.startswith("|") or link.startswith("pswd: "):
            link = ''
    except IndexError:
        link = ''
    try:
        name = name_args[1]
        name = name.strip()
        if name.startswith("pswd: "):
            name = ''
    except IndexError:
        name = ''
    try:
        ussr = urllib.parse.quote(mesg[1], safe='')
        pssw = urllib.parse.quote(mesg[2], safe='')
    except:
        ussr = ''
        pssw = ''
    if ussr != '' and pssw != '':
        link = link.split("://", maxsplit=1)
        link = f'{link[0]}://{ussr}:{pssw}@{link[1]}'
    pswd = re.search('(?<=pswd: )(.*)', update.message.text)
    if pswd is not None:
      pswd = pswd.groups()
      pswd = " ".join(pswd)
    LOGGER.info(link)
    link = link.strip()
    reply_to = update.message.reply_to_message
    if reply_to is not None:
        file = None
        tag = reply_to.from_user.username
        media_array = [reply_to.document, reply_to.video, reply_to.audio]
        for i in media_array:
            if i is not None:
                file = i
                break

        if not bot_utils.is_url(link) and not bot_utils.is_magnet(link) or len(link) == 0:
            if file is not None:
                if file.mime_type != "application/x-bittorrent":
                    listener = MirrorListener(bot, update, pswd, isTar, tag, extract)
                    tg_downloader = TelegramDownloadHelper(listener)
                    tg_downloader.add_download(reply_to, f'{DOWNLOAD_DIR}{listener.uid}/', name)
                    sendMessage(f"<b>★ Your Telegram File Has Been Added To Download Queue.\n★ Check Status By Clicking</b> /{BotCommands.StatusCommand}", bot, update)
                    if len(Interval) == 0:
                        Interval.append(setInterval(DOWNLOAD_STATUS_UPDATE_INTERVAL, update_all_messages))
                    return
                else:
                    link = file.get_file().file_path
    else:
        tag = None
    if not bot_utils.is_url(link) and not bot_utils.is_magnet(link):
        sendMessage('No download source provided 🙄😑', bot, update)
        return

    try:
        link = direct_link_generator(link)
    except DirectDownloadLinkException as e:
        LOGGER.info(f'{link}: {e}')
    listener = MirrorListener(bot, update, pswd, isTar, tag, extract)
    if bot_utils.is_mega_link(link) and MEGA_KEY is not None and not BLOCK_MEGA_LINKS:
        mega_dl = MegaDownloader(listener)
        mega_dl.add_download(link, f'{DOWNLOAD_DIR}{listener.uid}/')
        sendMessage(f"<b>★ Mega.nz Link Added To 📑 /{BotCommands.StatusCommand}\n★ Only 1 Download At A Time Otherwise Ban.\n★ Do Not Forget To Read Mega Download Rules.</b>", bot, update)

    elif bot_utils.is_mega_link(link) and BLOCK_MEGA_LINKS:
        sendMessage("Mega links are blocked. Dont try to mirror mega links.", bot, update)
    else:
        ariaDlManager.add_download(link, f'{DOWNLOAD_DIR}{listener.uid}/', listener, name)
        sendMessage(f"<b>★ Your URL Link Has Been Added To 📑 /{BotCommands.StatusCommand}\n☆ Max Mirror Size Is <u>30GB</u> In This Group.\n★ Do Not Forget To Read Group Rules.</b>", bot, update)
    if len(Interval) == 0:
        Interval.append(setInterval(DOWNLOAD_STATUS_UPDATE_INTERVAL, update_all_messages))


def mirror(update, context):
    _mirror(context.bot, update)


def tar_mirror(update, context):
    _mirror(context.bot, update, True)


def unzip_mirror(update, context):
    _mirror(context.bot, update, extract=True)


mirror_handler = CommandHandler(BotCommands.MirrorCommand, mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
tar_mirror_handler = CommandHandler(BotCommands.TarMirrorCommand, tar_mirror,
                                    filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
unzip_mirror_handler = CommandHandler(BotCommands.UnzipMirrorCommand, unzip_mirror,
                                      filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
dispatcher.add_handler(mirror_handler)
dispatcher.add_handler(tar_mirror_handler)
dispatcher.add_handler(unzip_mirror_handler)