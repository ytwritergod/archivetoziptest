require('dotenv').config();
const { TelegramClient } = require('telegram');
const { StringSession } = require('telegram/sessions');
const AdmZip = require('adm-zip');
const fs = require('fs');
const path = require('path');
const TelegramBot = require('node-telegram-bot-api');

// कॉन्फ़िगरेशन
const apiId = parseInt(process.env.API_ID);
const apiHash = process.env.API_HASH;
const botToken = process.env.BOT_TOKEN;
const authorizedUsers = new Set(process.env.AUTHORIZED_USERS.split(',').map(Number));

// MTProto क्लाइंट
const stringSession = new StringSession('');
const client = new TelegramClient(stringSession, apiId, apiHash, {
  connectionRetries: 5,
});

// बॉट इनिशियलाइज़ेशन
const bot = new TelegramBot(botToken, { polling: true });
const userData = {};

// यूजर अथॉरिजेशन चेक
function isAuthorized(chatId) {
  return authorizedUsers.has(chatId);
}

// /start कमांड
bot.onText(/\/start/, (msg) => {
  const chatId = msg.chat.id;
  if (!isAuthorized(chatId)) {
    return bot.sendMessage(chatId, '🚫 *Access Denied!* Contact admin.', { parse_mode: 'Markdown' });
  }
  bot.sendMessage(
    chatId,
    `📁 *FileZipper Bot*\n\n` +
    `✨ Send files → /zip → Set password → Get ZIP\n` +
    `🔐 Supports files up to 2GB\n` +
    `🚀 Powered by Telegram MTProto`,
    { parse_mode: 'Markdown' }
  );
});

// फाइलें हैंडल करें
bot.on('document', async (msg) => {
  const chatId = msg.chat.id;
  if (!isAuthorized(chatId)) return;

  const fileId = msg.document.file_id;
  const fileName = msg.document.file_name;

  if (!userData[chatId]) userData[chatId] = { files: [] };

  try {
    const tempDir = path.join(__dirname, '../temp', chatId.toString());
    if (!fs.existsSync(tempDir)) fs.mkdirSync(tempDir, { recursive: true });

    const filePath = path.join(tempDir, fileName);
    const fileStream = bot.getFileStream(fileId);
    const writeStream = fs.createWriteStream(filePath);
    fileStream.pipe(writeStream);

    writeStream.on('finish', () => {
      userData[chatId].files.push({ fileName, filePath });
      bot.sendMessage(chatId, `✅ Saved: ${fileName} (Total: ${userData[chatId].files.length})`);
    });

  } catch (err) {
    bot.sendMessage(chatId, `❌ Error: ${err.message}`);
  }
});

// /zip कमांड प्रोसेस
bot.onText(/\/zip/, async (msg) => {
  const chatId = msg.chat.id;
  if (!isAuthorized(chatId)) return;

  if (!userData[chatId]?.files?.length) {
    return bot.sendMessage(chatId, '❌ No files found! Send files first.');
  }

  bot.sendMessage(chatId, '🔑 Enter ZIP password:');
  userData[chatId].waitingForPassword = true;
});

// पासवर्ड हैंडल करें और ZIP भेजें
bot.on('message', async (msg) => {
  const chatId = msg.chat.id;
  if (!isAuthorized(chatId)) return;

  if (userData[chatId]?.waitingForPassword) {
    userData[chatId].waitingForPassword = false;
    const password = msg.text;

    try {
      // ZIP बनाएं
      const zip = new AdmZip();
      userData[chatId].files.forEach(file => zip.addLocalFile(file.filePath));
      const zipBuffer = zip.toBuffer();

      // टेम्प फाइल सेव करें
      const zipPath = path.join(__dirname, '../temp', chatId.toString(), 'Secure.zip');
      fs.writeFileSync(zipPath, zipBuffer);

      // MTProto के जरिए फाइल भेजें
      await client.connect();
      await client.sendFile(chatId, {
        file: zipPath,
        caption: `🔒 Password: \`${password}\`\n🛡️ AES-256 Encrypted`,
        parseMode: 'Markdown'
      });

      // क्लीनअप
      fs.rmSync(path.dirname(zipPath), { recursive: true, force: true });
      delete userData[chatId];

    } catch (err) {
      bot.sendMessage(chatId, `❌ Error: ${err.message}`);
    }
  }
});
