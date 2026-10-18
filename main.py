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

# Kişi bazlı sıkıştırılmış hafıza: { "user_id": "Özetlenmiş hafıza metni..." }
user_memory = {}

# Kullanıcının son ham mesajları (Özet çıkarmak için geçici bellek)
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
        "temperature": 0.7
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
    """Kullanıcının son konuşmalarını sıkıştırıp özet hafızaya dönüştürür."""
    if user_id not in temp_chat_history or len(temp_chat_history[user_id]) < 4:
        return

    maddeler = "\n".join(temp_chat_history[user_id])
    mevcut_hafiza = user_memory.get(user_id, "Henüz hafıza kaydı yok.")

    prompt = f"""Görevin '{user_name}' isimli kullanıcının sohbet geçmişini ve mevcut hafıza kaydını inceleyip SIKIŞTIRILMIŞ ÖZET BİR HAFIZA LOGU oluşturmaktır.

Mevcut Hafıza Logu:
{mevcut_hafiza}

Yeni Konuşmalar:
{maddeler}

Kurallar:
- Sadece kullanıcının sevdiği şeyleri, kişisel bilgilerini, takıldığı konuları ve ruh halini kısa cümlelerle logla.
- Gereksiz selamlaşmaları veya önemsiz cümleleri at.
- Maksimim 3-4 maddelik sıkıştırılmış bir özet çıkar.
- Doğrudan yeni hafıza logunu yaz.
"""

    yeni_hafiza = await call_kedy_ai([{"role": "user", "content": prompt}])
    if yeni_hafiza:
        user_memory[user_id] = yeni_hafiza.strip()
        temp_chat_history[user_id] = [] # Geçici sohbeti temizle

# --- 5. MESAJ DİNLEME VE SOHBET ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Bot etiketlendi mi veya bota komut dışı mesaj mı atıldı?
    bot_mentioned = bot.user.mentioned_in(message) and not message.mention_everyone
    is_dm = isinstance(message.channel, discord.DMChannel)

    # Geçici sohbete ekle
    user_id = str(message.author.id)
    user_name = message.author.display_name

    if user_id not in temp_chat_history:
        temp_chat_history[user_id] = []
    temp_chat_history[user_id].append(f"{user_name}: {message.content}")

    # Bota hitap edildiyse veya DM atıldıysa cevap ver
    if bot_mentioned or is_dm:
        async with message.channel.typing():
            hafiza = user_memory.get(user_id, "Bu kullanıcı hakkında henüz geçmiş bilgi yok.")

            system_prompt = f"""Sen bu Discord sunucusunda takılan, gerçek bir insan gibi samimi, sıcak, kasmayan ve zeki bir üyesin.
Yapay zeka olduğunu sürekli vurgulama, resmi konuşma. Arkadaşınla sohbet eder gibi doğal, samimi Türkçe kullan.

Karşındaki Kullanıcı: {user_name}
Kullanıcı Hakkında Bildiklerin (Sıkıştırılmış Hafıza Logu):
{hafiza}

Kullanıcının Son Mesajı: "{message.content}"

Hafızandaki bilgileri doğal bir şekilde dikkate alarak arkadaşça cevap ver."""

            cevap = await call_kedy_ai([{"role": "user", "content": system_prompt}])

            if cevap:
                await message.reply(cevap)
            else:
                await message.reply("Kafam biraz karıştı ya, ne demiştin?")

    # Her 5 mesajda bir arka planda hafızayı özetle
    if len(temp_chat_history[user_id]) >= 5:
        asyncio.create_task(compress_memory(user_id, user_name))

    await bot.process_commands(message)

# --- 6. HAFIZA KOMUTLARI ---

@bot.command(name="hafizam")
async def hafizam(ctx):
    """Kullanıcının bot hafızasındaki sıkıştırılmış özetini gösterir."""
    user_id = str(ctx.author.id)
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
