import os
import json
import asyncio
import threading
import discord
from discord.ext import commands
import aiohttp
from flask import Flask
from waitress import serve

# --- 1. RENDER 7/24 KAPANMA ÖNLEYİCİ SUNUCU ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Sade AI Botu 7/24 Aktif!"

@app.route('/health')
def health():
    return {"status": "ok"}, 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    serve(app, host="0.0.0.0", port=port, threads=6)

# --- 2. DISCORD VE API AYARLARI ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Kişi bazlı basit hafıza deposu
user_memory = {}

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
KEDY_API_KEY = os.environ.get("KEDY_API_KEY")

# --- 3. DÜZ KEDY API ÇAĞRISI (TEK INPUT -> TEK OUTPUT) ---
async def call_kedy_ai(messages: list):
    url = "https://api.kedy.dev/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {KEDY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "novaq",
        "messages": messages,
        "temperature": 0.7
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
                else:
                    return None
    except Exception as e:
        print(f"API Hatası: {e}")
        return None

# --- 4. MESAJ DİNLEME VE SOHBET ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.content.startswith('!'):
        await bot.process_commands(message)
        return

    bot_mentioned = bot.user.mentioned_in(message) and not message.mention_everyone
    is_dm = isinstance(message.channel, discord.DMChannel)

    user_id = str(message.author.id)
    user_name = message.author.display_name

    if bot_mentioned or is_dm:
        async with message.channel.typing():
            clean_content = message.content.replace(f'<@{bot.user.id}>', '').strip()
            
            if not clean_content:
                await message.reply("Efendim?")
                return

            # Sadece hafıza bilgisini al ve prompta sabitle
            hafiza = user_memory.get(user_id, "Henüz özel bir kayıt yok.")

            messages = [
                {
                    "role": "system",
                    "content": (
                        "Sen bir Discord asistanısın. "
                        f"Kullanıcı Hakkındaki Hafıza Logun: [{hafiza}]"
                    )
                },
                {
                    "role": "user",
                    "content": clean_content
                }
            ]

            # Tek hamlede cevabı al
            cevap = await call_kedy_ai(messages)

            if cevap:
                await message.reply(cevap)
                # Hafıza logunu son sohbetle güncelle
                user_memory[user_id] = f"Kullanıcı en son '{clean_content}' dedi."
            else:
                await message.reply("Şu an cevap veremiyorum.")

# --- 5. HAFIZA KOMUTLARI ---
@bot.command(name="hafizam")
async def hafizam(ctx):
    user_id = str(ctx.author.id)
    hafiza = user_memory.get(user_id, "Henüz kayıtlı bir hafıza yok.")
    
    embed = discord.Embed(
        title=f"🧠 {ctx.author.display_name} - Hafıza Logu",
        description=hafiza,
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed)

@bot.command(name="hafizamisil")
async def hafizamisil(ctx):
    user_id = str(ctx.author.id)
    if user_id in user_memory:
        del user_memory[user_id]
    await ctx.send("🧠 Hafıza temizlendi!")

# --- 6. BAŞLATICI ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("HATA: DISCORD_TOKEN tanımlı değil!")
