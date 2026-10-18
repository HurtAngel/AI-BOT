# --- ADIM ADIM ZORLAMALI ÜRETİM DÖNGÜSÜ (KİLİTLENME ÖNLEYİCİLİ) ---
async def generate_step_by_step(user_name: str, clean_prompt: str, memory: str) -> str:
    try:
        # Adım 1: Kedy hedef adım sayısını seçsin (Zaman aşımı riski için max 3 sn bekle)
        target_steps = await asyncio.wait_for(determine_step_count(clean_prompt), timeout=5.0)
    except Exception:
        target_steps = 6  # API gecikirse varsayılan 6 adım ile devam et

    accumulated_text = ""

    for step in range(1, target_steps + 1):
        system_instructions = (
            "Sen samimi bir Discord arkadaşısın. "
            "Görevin kullanıcının isteğine adım adım cevap yazmaktır. "
            "Her adımda EN FAZLA 1 İLA 3 KELİME yazabilirsin!"
        )

        user_content = (
            f"Kullanıcı: {user_name}\n"
            f"Orijinal İstek: {clean_prompt}\n"
            f"ŞU ANKİ ADIM: {step}/{target_steps}\n"
            f"ŞU ANA KADAR YAZILAN METİN: '{accumulated_text}'\n\n"
            "TALİMAT: 'Şu Ana Kadar Yazılan Metin' kısmını tam kaldığı yerden devam ettirecek MAX 3 KELİME yaz."
        )

        messages = [
            {"role": "system", "content": system_instructions},
            {"role": "user", "content": user_content}
        ]

        try:
            # Tekil istek kilitlenmesin diye 8 saniye zaman aşımı koyuyoruz
            next_words = await asyncio.wait_for(call_kedy(messages, temperature=0.5), timeout=8.0)
        except Exception as e:
            print(f"[ZAMAN AŞIMI] Adım {step} yanıt vermedi: {e}")
            break

        if not next_words or not next_words.strip():
            # Kedy boş döndüyse (filtreye takıldıysa) döngüyü zorla bitir
            print(f"[BOŞ YANIT] Adım {step} boş döndü, biriken metin gönderiliyor.")
            break

        words = next_words.strip().split()[:3]
        chunk = " ".join(words)

        accumulated_text += " " + chunk
        accumulated_text = accumulated_text.strip()

        # Erken kontrol: Eğer 4. adımdan sonra yeterliyse hakeme sormadan da bitirebiliriz
        if step >= 4 and len(accumulated_text.split()) >= 10:
            try:
                is_done = await asyncio.wait_for(judge_response(clean_prompt, accumulated_text), timeout=4.0)
                if is_done:
                    break
            except Exception:
                pass

    return accumulated_text if accumulated_text else "Hehe, takıldım galiba ne demiştin?"
