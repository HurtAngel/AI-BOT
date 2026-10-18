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

# RAM içi hafıza deposu
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
        "temperature": 0.5
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
                else:
                    print(f"API Hatası Status Code: {resp.status}")
                    return None
    except Exception as e:
        print(f"Kedy API İletişim Hatası: {e}")
        return None

# --- 4. HAFIZA SIKIŞTIRMA (ÖZET ÇIKARMA) ---
async def compress_memory(user_id: str, user_name: str):
    if user_id not in temp_chat_history or not temp_chat_history[user_id]:
        return

    maddeler = "\n".join(temp_chat_history[user_id])
    mevcut_hafiza = user_memory.get(user_id, "Henüz hafıza kaydı yok.")

    prompt = f"""Kullanıcı Adı: '{user_name}'
Mevcut Hafıza: {mevcut_hafiza}
Son Konuşma Metinleri:
{maddeler}

Görevin: Kullanıcının son söylediklerinden yola çıkarak kendisi hakkında verdiği kişisel bilgileri (örn: kedi olduğunu söylemesi, sevdikleri, mesleği, hobileri vb.) kısa özet maddeler halinde güncelle.

Kurallar:
- Sadece kullanıcının söylediği somut bilgileri yaz.
- Kısa, net 1-3 madde yaz.
- Yapay zeka veya açıklama metinleri ekleme, direkt özet maddeleri ver.
"""

    messages = [
        {"role": "system", "content": "Sen kullanıcılar hakkında kısa ve öz hafıza logları tutturan bir veri işleyicisisin."},
        {"role": "user", "content": prompt}
    ]

    yeni_hafiza = await call_kedy_ai(messages)
    if yeni_hafiza and yeni_hafiza.strip():
        user_memory[user_id] = yeni_hafiza.strip()
        print(f"[HAFIZA GÜNCELLENDİ - {user_name}]: {user_memory[user_id]}")
        temp_chat_history[user_id] = []

# --- 5. MESAJ DİNLEME VE SOHBET ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Komut kontrolü
    if message.content.startswith('!'):
        await bot.process_commands(message)
        return

    bot_mentioned = bot.user.mentioned_in(message) and not message.mention_everyone
    is_dm = isinstance(message.channel, discord.DMChannel)

    user_id = str(message.author.id)
    user_name = message.author.display_name

    if user_id not in temp_chat_history:
        temp_chat_history[user_id] = []

    # Bota hitap edildiyse veya DM atıldıysa cevap ver
    if bot_mentioned or is_dm:
        async with message.channel.typing():
            clean_content = message.content.replace(f'<@{bot.user.id}>', '').strip()
            
            # 1. Mesajı geçici geçmişe ekle
            temp_chat_history[user_id].append(f"{user_name}: {clean_content}")

            # 2. Önce hafızayı senkronize biçimde güncelle ki yanıtta da anında kullanabilsin
            await compress_memory(user_id, user_name)

            hafiza = user_memory.get(user_id, "Bu kullanıcı hakkında henüz kaydedilmiş bir detay yok.")

            messages = [
                {
                    "role": "system", 
                    "content": (
                        "Sen bu Discord sunucusunda takılan samimi, kasmayan ve gerçek bir üyesin. "
                        "Asla 'Ben bir yapay zekayım', 'Asistanım' deme. "
                        "Kullanıcı kedi olduğunu veya başka bir şey söylediğinde bunu hatırla ve doğal bir arkadaş gibi konuş."
                    )
                },
                {
                    "role": "user", 
                    "content": f"Kullanıcı: {user_name}\nHakkında Bildiklerin (Hafıza Logu):\n{hafiza}\n\nKullanıcının Son Mesajı: {clean_content}"
                }
            ]

            cevap = await call_kedy_ai(messages)

            if cevap:
                await message.reply(cevap)
            else:
                await message.reply("Kafam karıştı ya, ne demiştin?")

# --- 6. HAFIZA KOMUTLARI ---

@bot.command(name="hafizam")
async def hafizam(ctx):
    """Kullanıcının bot hafızasındaki sıkıştırılmış özetini gösterir."""
    user_id = str(ctx.author.id)
    
    # Hafıza boşsa geçici geçmişte işlenmemiş bir mesaj varsa hemen güncellemeyi dene
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
    """Kullanıcının kendi hafıza logunu sıfırlar."""
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
