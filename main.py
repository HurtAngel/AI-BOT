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
    return "AI-VS-AI Kedy Savaşçısı 7/24 Aktif!"

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

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
KEDY_API_KEY = os.environ.get("KEDY_API_KEY")

# --- 3. TEMEL KEDY API ÇAĞRISI ---
async def call_kedy(messages: list, temperature: float = 0.5):
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
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
                return None
    except Exception as e:
        print(f"API Hatası: {e}")
        return None

# --- 4. HAKEM KEDY (CEVABI DENETLEYEN İKİNCİ AI) ---
async def judge_response(original_prompt: str, current_generated_text: str) -> bool:
    """İkinci Kedy API'si üretilen cevabın yeterli/mantıklı olup olmadığını denetler."""
    judge_prompt = [
        {
            "role": "system",
            "content": (
                "Sen acımasız bir edat ve mantık denetleyicisisin. "
                "Görevin verilen kullanıcının isteği ile üretilen cevabı kıyaslamak. "
                "Eğer cevap mantıklı, istek ile uyumlu ve tamamlanmış bir cümle/paragraf ise SADECE 'TAMAM' yaz. "
                "Eğer cevap yarım kalmışsa, saçmalamışsa, kendi içinde çelişiyorsa veya tamamlanmamışsa SADECE 'DEVAM' yaz."
            )
        },
        {
            "role": "user",
            "content": f"Kullanıcı İsteği: {original_prompt}\n\nÜretilen Cevap: {current_generated_text}\n\nKararın (TAMAM / DEVAM):"
        }
    ]
    
    result = await call_kedy(judge_prompt, temperature=0.1)
    if result and "TAMAM" in result.upper():
        return True
    return False

# --- 5. İŞÇİ KEDY DÖNGÜSÜ (KELİME/CÜMLE ADIMLI ZORLAMA) ---
async def generate_step_by_step(user_name: str, clean_prompt: str, memory: str) -> str:
    """Modeli adım adım sonraki kelimeleri/cümleleri üretmeye zorlayan ana döngü."""
    accumulated_response = ""
    max_steps = 8  # Maksimum döngü sayısı (Sonsuz döngüyü engellemek için)

    for step in range(max_steps):
        # Her adımda Orijinal Prompt + Hafıza + Şu ana kadar üretilen tüm metin inputa basılır
        system_instructions = (
            "Sen samimi bir Discord üyesisin. "
            "Sana verilen isteme ve şu ana kadar yazdığın metne tam bağlı kal. "
            "Şu ana kadar yazdığın metnin KALDIĞI YERDEN devam et. Asla baştan başlama veya kendini tekrarlama."
        )

        user_content = (
            f"Kullanıcı Adı: {user_name}\n"
            f"Kullanıcı Hakkındaki Hafıza: {memory}\n"
            f"Kullanıcının Orijinal İsteği: {clean_prompt}\n\n"
            f"Şu Ana Kadar Yazdığın Metin: '{accumulated_response}'\n\n"
            f"TALİMAT: Yukarıdaki 'Şu Ana Kadar Yazdığın Metin' kısmını tam olarak devam ettirecek sonraki 1-2 cümleyi yaz."
        )

        messages = [
            {"role": "system", "content": system_instructions},
            {"role": "user", "content": user_content}
        ]

        next_chunk = await call_kedy(messages, temperature=0.6)

        if not next_chunk:
            break

        # Üretilen parçayı birleştir
        accumulated_response += " " + next_chunk.strip()
        accumulated_response = accumulated_response.strip()

        # Hakem Kedy'ye soruyoruz: Cevap yeterli mi?
        is_sufficient = await judge_response(clean_prompt, accumulated_response)
        if is_sufficient:
            print(f"[HAKEM ONAYLADI] {step + 1}. adımda cevap tamamlandı.")
            break
        else:
            print(f"[HAKEM REDDETTİ] {step + 1}. adım yetersiz, devam ediliyor...")

    return accumulated_response if accumulated_response else "Bir şeyler ters gitti ya, tekrar desene."

# --- 6. MESAJ DİNLEME ---
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.content.startswith('!'):
        await bot.process_commands(message)
        return

    bot_mentioned = bot.user.mentioned_in(message) and not message.mention_everyone
    is_dm = isinstance(message.channel, discord.DMChannel)

    if bot_mentioned or is_dm:
        async with message.channel.typing():
            user_id = str(message.author.id)
            user_name = message.author.display_name
            clean_content = message.content.replace(f'<@{bot.user.id}>', '').strip()

            if not clean_content:
                await message.reply("Efendim?")
                return

            hafiza = user_memory.get(user_id, "Henüz özel bir detay yok.")

            # AI vs AI Döngüsünü başlat
            final_response = await generate_step_by_step(user_name, clean_content, hafiza)

            # Hafızayı güncelle
            user_memory[user_id] = f"Kullanıcı en son '{clean_content}' dedi."

            await message.reply(final_response)

# --- 7. KOMUTLAR ---
@bot.command(name="hafizam")
async def hafizam(ctx):
    user_id = str(ctx.author.id)
    hafiza = user_memory.get(user_id, "Hafıza henüz boş!")
    embed = discord.Embed(title=f"🧠 {ctx.author.display_name} - Hafıza Logu", description=hafiza, color=discord.Color.blue())
    await ctx.send(embed=embed)

@bot.command(name="hafizamisil")
async def hafizamisil(ctx):
    user_id = str(ctx.author.id)
    if user_id in user_memory:
        del user_memory[user_id]
    await ctx.send("🧠 Hafıza temizlendi!")

# --- 8. BAŞLATICI ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("HATA: DISCORD_TOKEN bulunamadı!")
