import os
import json
import asyncio
import threading
import discord
from discord.ext import commands
import aiohttp
import re
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
async def call_kedy_ai(messages: list, temperature: float = 0.5):
    url = "https://api.kedy.dev/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {KEDY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "novaq",
        "messages": messages,
        "temperature": temperature
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
                else:
                    print(f"API Hatası Status Code: {resp.status}")
                    return None
    except Exception as e:
        print(f"Kedy API İletişim Hatası: {e}")
        return None

# --- 4. HAKEM VE ADIM PLANLAMA MEKANİZMASI ---

async def determine_step_count(clean_prompt: str) -> int:
    """Kedy'nin kaç adımda cevap üreteceğine baştan karar vermesini sağlar."""
    prompt = [
        {
            "role": "system",
            "content": "Sen adım planlayıcısısın. Verilen isteğe cevap vermek için kaç adım gerektiğini hesapla."
        },
        {
            "role": "user",
            "content": f"İstek: '{clean_prompt}'\nBu isteğe adım adım (her adım max 3 kelime) cevap yazmak için 5 ile 20 arasında bir sayı ver. SADECE SAYI YAZ."
        }
    ]
    
    result = await call_kedy_ai(prompt, temperature=0.1)
    if result:
        numbers = re.findall(r'\d+', result)
        if numbers:
            val = int(numbers[0])
            return max(5, min(20, val))
    return 8

async def judge_response(original_prompt: str, current_text: str) -> bool:
    """Hakem Kedy üretilen metnin yeterli/mantıklı bittiğini kontrol eder."""
    judge_prompt = [
        {
            "role": "system",
            "content": "Sen cevap denetleyicisisin. Üretilen metin isteği tam karşılıyorsa SADECE 'TAMAM', yarım veya mantıksızsa SADECE 'DEVAM' yaz."
        },
        {
            "role": "user",
            "content": f"İstek: {original_prompt}\nCevap: {current_text}\nKarar (TAMAM/DEVAM):"
        }
    ]
    
    result = await call_kedy_ai(judge_prompt, temperature=0.1)
    if result and "TAMAM" in result.upper():
        return True
    return False

# --- 5. ADIM ADIM ZORLAMALI METİN ÜRETİMİ ---
async def generate_step_by_step(user_name: str, clean_prompt: str, memory: str) -> str:
    try:
        target_steps = await asyncio.wait_for(determine_step_count(clean_prompt), timeout=4.0)
    except Exception:
        target_steps = 7

    accumulated_text = ""

    for step in range(1, target_steps + 1):
        system_instructions = (
            "Sen bu Discord sunucusundaki samimi bir arkadaşsın. "
            "Kendi hakkında veya kullanıcı hakkında asla arka plan analizi yazma! "
            "Doğrudan sohbet et. Her adımda EN FAZLA 1 İLA 3 KELİME yaz."
        )

        user_content = (
            f"Kullanıcı: {user_name}\n"
            f"Hafıza Logu: {memory}\n"
            f"Kullanıcının İstegi: {clean_prompt}\n"
            f"ŞU ANA KADAR YAZILAN: '{accumulated_text}'\n\n"
            "TALİMAT: 'Şu Ana Kadar Yazılan' metnini tam kaldığı yerden devam ettirecek EN FAZLA 3 KELİME yaz. Asla başa dönme veya analiz yapma."
        )

        messages = [
            {"role": "system", "content": system_instructions},
            {"role": "user", "content": user_content}
        ]

        try:
            next_chunk = await asyncio.wait_for(call_kedy_ai(messages, temperature=0.5), timeout=6.0)
        except Exception:
            break

        if not next_chunk or not next_chunk.strip():
            break

        # Max 3 kelime al, gerisini zorla kes (Spam ve döngüyü engeller)
        words = next_chunk.strip().split()[:3]
        chunk = " ".join(words)

        accumulated_text += " " + chunk
        accumulated_text = accumulated_text.strip()

        # Erken tamamlama kontrolü
        if step >= 5:
            try:
                is_done = await asyncio.wait_for(judge_response(clean_prompt, accumulated_text), timeout=3.0)
                if is_done:
                    break
            except Exception:
                pass

    return accumulated_text if accumulated_text else "Aklıma bir şey gelmedi ya, ne diyordun?"

# --- 6. BASİTLEŞTİRİLMİŞ GARANTİ HAFIZA SIKIŞTIRMA ---
async def compress_memory(user_id: str, user_name: str):
    if user_id not in temp_chat_history or not temp_chat_history[user_id]:
        return

    maddeler = "\n".join(temp_chat_history[user_id])
    mevcut_hafiza = user_memory.get(user_id, "Henüz hafıza kaydı yok.")

    messages = [
        {"role": "system", "content": "Kullanıcı hakkındaki net bilgileri veritabanı maddesi olarak çıkar. Asla mesajlaşma."},
        {"role": "user", "content": f"Eski Hafıza: {mevcut_hafiza}\nYeni Sohbet:\n{maddeler}\n\nKullanıcı hakkında yeni bilinenleri 1 kısa maddede güncelle."}
    ]

    yeni_hafiza = await call_kedy_ai(messages, temperature=0.2)
    if yeni_hafiza and yeni_hafiza.strip():
        user_memory[user_id] = yeni_hafiza.strip()
        temp_chat_history[user_id] = temp_chat_history[user_id][-2:]

# --- 7. MESAJ DİNLEME VE SOHBET ---
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
            
            if not clean_content:
                await message.reply("Efendim?")
                return

            temp_chat_history[user_id].append(f"{user_name}: {clean_content}")

            # 'Unut beni' tarzı isteklerde hafızayı anında uçur
            if any(w in clean_content.lower() for w in ["unut beni", "hafızamı sil", "beni unut"]):
                user_memory[user_id] = "Sıfırlandı"
                temp_chat_history[user_id] = []
                await message.reply("Hafızamı temizledim, seni unuttum!")
                return

            hafiza = user_memory.get(user_id, "Özel bilgi yok.")

            # Multi-Agent Adım Adım Savaşçı Çalışıyor
            cevap = await generate_step_by_step(user_name, clean_content, hafiza)

            if cevap:
                await message.reply(cevap)
                temp_chat_history[user_id].append(f"Sen: {cevap}")
            else:
                await message.reply("Anlayamadım ya, tekrar desene?")

            # Arka planda hafızayı güncelle
            await compress_memory(user_id, user_name)

# --- 8. HAFIZA KOMUTLARI ---

@bot.command(name="hafizam")
async def hafizam(ctx):
    user_id = str(ctx.author.id)
    hafiza = user_memory.get(user_id, "Seninle ilgili henüz bir kayıt yok.")
    
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

# --- 9. BAŞLATICI ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("HATA: DISCORD_TOKEN tanımlı değil!")
