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
    return "AI Asistan 7/24 Aktif ve Operasyonel!"

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

user_memory = {}
temp_chat_history = {}

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
KEDY_API_KEY = os.environ.get("KEDY_API_KEY")

# --- 3. KEDY AI ASENKRON İLETİŞİM FONKSİYONU ---
async def call_kedy_ai(messages: list):
    url = "https://api.kedy.dev/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {KEDY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "novaq",
        "messages": messages,
        "temperature": 0.6
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
                else:
                    print(f"API Hatası Status Code: {resp.status}")
                    return None
    except Exception as e:
        print(f"Kedy API İletişim Hatası: {e}")
        return None

# --- 4. BASİTLEŞTİRİLMİŞ GARANTİ HAFIZA SIKIŞTIRMA ---
async def compress_memory(user_id: str, user_name: str):
    if user_id not in temp_chat_history or not temp_chat_history[user_id]:
        return

    maddeler = "\n".join(temp_chat_history[user_id])
    mevcut_hafiza = user_memory.get(user_id, "Henüz hafıza kaydı yok.")

    # Kedy'nin afallamaması için ultra net, basitleştirilmiş komut
    messages = [
        {"role": "system", "content": "Sen kullanıcılar hakkında kısa ve net hafıza logları tutan bir veritabanı asistanısın. Asla sohbet etme, sadece maddeler yaz."},
        {"role": "user", "content": f"Kullanıcı: {user_name}\nEski Bilgiler: {mevcut_hafiza}\nYeni Mesajları:\n{maddeler}\n\nYukarıdaki bilgilere göre kullanıcının kim olduğu, özellikleri veya söylediklerini 1-2 kısa maddede güncelle."}
    ]

    yeni_hafiza = await call_kedy_ai(messages)
    if yeni_hafiza and yeni_hafiza.strip():
        user_memory[user_id] = yeni_hafiza.strip()
        print(f"[HAFIZA GÜNCELLENDİ - {user_name}]: {user_memory[user_id]}")
        # Son 3 mesajı tut, gerisini temizle ki geçmiş çok uzayıp modeli bozmasın
        temp_chat_history[user_id] = temp_chat_history[user_id][-3:]

# --- 5. MESAJ DİNLEME VE SOHBET ---
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

    if user_id not in temp_chat_history:
        temp_chat_history[user_id] = []

    if bot_mentioned or is_dm:
        async with message.channel.typing():
            clean_content = message.content.replace(f'<@{bot.user.id}>', '').strip()
            
            # Anlamsız/çok kısa mesajlarda API'ye yük bindirmeyip sohbeti devam ettir
            if not clean_content:
                await message.reply("Efendim?")
                return

            temp_chat_history[user_id].append(f"{user_name}: {clean_content}")

            # Arka planda hafızayı senkronize et
            await compress_memory(user_id, user_name)

            hafiza = user_memory.get(user_id, "Henüz özel bir bilgi yok.")

            messages = [
                {
                    "role": "system", 
                    "content": (
                        "Sen bu Discord sunucusunda takılan samimi, kasmayan, eğlenceli bir arkadaşsın. "
                        "Asla yapay zeka olduğunu söyleme. Kısa, doğal ve sohbet havasında cevap ver."
                    )
                },
                {
                    "role": "user", 
                    "content": f"Senin bu kullanıcı hakkındaki hafıza logun:\n{hafiza}\n\nKullanıcının sana son mesajı: {clean_content}"
                }
            ]

            cevap = await call_kedy_ai(messages)

            if cevap:
                await message.reply(cevap)
                temp_chat_history[user_id].append(f"Sen: {cevap}")
            else:
                await message.reply("Hehe, haklısın :D") # Kedy patlarsa bile kullanıcıya hissettirmeyen esnek yanıt

# --- 6. HAFIZA KOMUTLARI ---

@bot.command(name="hafizam")
async def hafizam(ctx):
    user_id = str(ctx.author.id)
    
    if user_id not in user_memory and user_id in temp_chat_history and temp_chat_history[user_id]:
        await compress_memory(user_id, ctx.author.display_name)
        
    hafiza = user_memory.get(user_id, "Seninle ilgili henüz sıkıştırılmış bir hafıza kaydım yok, biraz sohbet edelim!")
    
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
    if user_id in temp_chat_history:
        temp_chat_history[user_id] = []
    await ctx.send("🧠 Hakkındaki tüm hafıza loglarını temizledim!")

# --- 7. BAŞLATICI ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("HATA: DISCORD_TOKEN tanımlı değil!")
