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
    return "Adım Adım Kedy Savaşçısı 7/24 Aktif!"

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

# --- 3. KEDY API ÇAĞRISI ---
async def call_kedy(messages: list, temperature: float = 0.4):
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

# --- 4. 1. AŞAMA: KEDY'NİN KENDİ ADIM SAYISINI BELİRLEMESİ ---
async def determine_step_count(clean_prompt: str) -> int:
    """Kedy'nin cevabı kaç adımda (5 ile 20 arası) bitireceğine karar vermesini sağlar."""
    prompt = [
        {
            "role": "system",
            "content": "Sen bir planlama asistanısın. Görevin sorulan soruya tam ve mantıklı bir cevap vermek için KAÇ ADIM (her adım maksimum 3 kelimedir) gerektiğini planlamaktır."
        },
        {
            "role": "user",
            "content": (
                f"Kullanıcı İsteği: '{clean_prompt}'\n\n"
                "Bu isteğe kelime kelime (her adımda en fazla 3 kelime olacak şekilde) cevap vermek için "
                "5 ile 20 arasında kaç adıma ihtiyacın var? "
                "SADECE 5 ile 20 arasında bir SAYI yaz. Başka hiçbir kelime yazma!"
            )
        }
    ]
    
    result = await call_kedy(prompt, temperature=0.2)
    try:
        # Metin içindeki sayıyı çek
        import re
        numbers = re.findall(r'\d+', result)
        if numbers:
            step_val = int(numbers[0])
            # 5 ile 20 arasında sınırla
            return max(5, min(20, step_val))
    except Exception:
        pass
    
    return 8  # Varsayılan sayı

# --- 5. 2. AŞAMA: HAKEM KEDY (DENETLEYİCİ) ---
async def judge_response(original_prompt: str, current_text: str) -> bool:
    """Hakem Kedy cümlenin/cevabın erken bitip bitmediğini denetler."""
    judge_prompt = [
        {
            "role": "system",
            "content": "Görevin üretilen cevabın kullanıcı isteğini tam ve eksiksiz karşılayıp karşılamadığını denetlemektir. SADECE 'TAMAM' veya 'DEVAM' yaz."
        },
        {
            "role": "user",
            "content": f"Kullanıcı İsteği: {original_prompt}\nŞu Anki Cevap: {current_text}\n\nEğer bu cevap mantıklı, eksiksiz ve dilbilgisine uygun bittiysa 'TAMAM', devam etmesi gerekiyorsa 'DEVAM' yaz:"
        }
    ]
    
    result = await call_kedy(judge_prompt, temperature=0.1)
    if result and "TAMAM" in result.upper():
        return True
    return False

# --- 6. ADIM ADIM ZORLAMALI ÜRETİM DÖNGÜSÜ ---
async def generate_step_by_step(user_name: str, clean_prompt: str, memory: str) -> str:
    # Adım 1: Kedy kendisi hedef adım sayısını seçsin (5 - 20)
    target_steps = await determine_step_count(clean_prompt)
    print(f"[PLANLAMA] Kedy bu cevap için {target_steps} adım hedefledi.")

    accumulated_text = ""

    for step in range(1, target_steps + 1):
        system_instructions = (
            "Sen samimi bir Discord arkadaşısın. "
            "Görevin kullanıcının isteğine adım adım cevap yazmaktır. "
            "ÇOK ÖNEMLİ KURAL: Her adımda EN FAZLA 1 İLA 3 KELİME yazabilirsin! Asla uzun cümle kurma."
        )

        user_content = (
            f"Kullanıcı: {user_name}\n"
            f"Kullanıcı Hafızası: {memory}\n"
            f"Orijinal İstek: {clean_prompt}\n"
            f"TOPLAM PLANLANAN ADIM: {target_steps}\n"
            f"ŞU ANKİ ADIM: {step}/{target_steps}\n"
            f"ŞU ANA KADAR YAZILAN METİN: '{accumulated_text}'\n\n"
            "TALİMAT: 'Şu Ana Kadar Yazılan Metin' kısmını tam kaldığı yerden devam ettirecek MAX 3 KELİME yaz. Sadece eklenecek 1-3 kelimeyi yaz!"
        )

        messages = [
            {"role": "system", "content": system_instructions},
            {"role": "user", "content": user_content}
        ]

        next_words = await call_kedy(messages, temperature=0.5)

        if not next_words:
            break

        # Sadece ilk 3 kelimeyi al (Sınırı aşarsa zorla kes)
        words = next_words.strip().split()[:3]
        chunk = " ".join(words)

        accumulated_text += " " + chunk
        accumulated_text = accumulated_text.strip()

        print(f"[ADIM {step}/{target_steps}]: + '{chunk}' -> BİRİKEN: '{accumulated_text}'")

        # 5. adımdan sonra Hakem Kedy'ye sor, erken bittiyse kes
        if step >= 5:
            is_done = await judge_response(clean_prompt, accumulated_text)
            if is_done:
                print(f"[HAKEM] Cevap {step}. adımda tam anlamıyla bittiği için erken durduruldu.")
                break

    return accumulated_text if accumulated_text else "Kafam durdu ya, tekrar desene."

# --- 7. MESAJ DİNLEME ---
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

            hafiza = user_memory.get(user_id, "Henüz özel detay yok.")

            # Savaş Alanı Çalışıyor
            final_response = await generate_step_by_step(user_name, clean_content, hafiza)

            user_memory[user_id] = f"Kullanıcı en son '{clean_content}' dedi."
            await message.reply(final_response)

# --- 8. KOMUTLAR ---
@bot.command(name="hafizam")
async def hafizam(ctx):
    user_id = str(ctx.author.id)
    hafiza = user_memory.get(user_id, "Hafıza boş!")
    embed = discord.Embed(title=f"🧠 {ctx.author.display_name} - Hafıza Logu", description=hafiza, color=discord.Color.blue())
    await ctx.send(embed=embed)

@bot.command(name="hafizamisil")
async def hafizamisil(ctx):
    user_id = str(ctx.author.id)
    if user_id in user_memory:
        del user_memory[user_id]
    await ctx.send("🧠 Hafıza temizlendi!")

# --- 9. BAŞLATICI ---
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("HATA: DISCORD_TOKEN bulunamadı!")
