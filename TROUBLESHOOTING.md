# 🔧 WebSocket Bağlantı Sorunu Çözümü

## 🚨 Sorun: "WS: DISCONNECTED" ve Maçlar Yok

### Muhtemel Nedenler:

1. **Render.com servisi çalışmıyor**
2. **anim.py veri toplayıcısı çalışmıyor**
3. **Port 8777 kapalı**
4. **WebSocket URL'i yanlış**

---

## ✅ Adım Adım Çözüm

### 1️⃣ Render.com Servisini Kontrol Edin

1. https://dashboard.render.com adresine gidin
2. **animasyon** servisinizi bulun
3. **Status** kontrol edin:
   - 🟢 **Live** → Çalışıyor
   - 🔴 **Deploy Failed** → Hata var
   - ⚪ **Paused** → Uykuda (free plan)

#### Eğer "Deploy Failed" ise:
- **Logs** sekmesine gidin
- Hata mesajını okuyun
- Genelde Playwright kurulum hatası olur

#### Eğer "Paused" ise:
- Servise tıklayın
- **Manual Deploy** → **Clear build cache & deploy**
- 5-10 dakika bekleyin

---

### 2️⃣ Render.com Loglarını Kontrol Edin

Render Dashboard → Servis → **Logs**:

**Beklenen çıktı:**
```
[LOCAL] server: ws://0.0.0.0:8777
  - frontend: ws://0.0.0.0:8777/frontend
  - ingest:   ws://0.0.0.0:8777/ingest
```

**Eğer bu çıktıyı görmüyorsanız**, `server.py` çalışmıyor demektir.

---

### 3️⃣ anim.py'nin Çalıştığından Emin Olun

Render.com'da **iki** servis çalışmalı:

#### Seçenek A: Tek Servis (Önerilen)
`start.sh` ile her ikisi de başlar.

#### Seçenek B: İki Ayrı Servis
1. **animasyon-server** → `python server.py`
2. **animasyon-scraper** → `python anim.py`

---

### 4️⃣ WebSocket URL'ini Doğrulayın

`live_anim.html` dosyasında satır 771:

```javascript
// Render.com URL'inizi buraya yapıştırın
const ws = new WebSocket("wss://animasyon.onrender.com/frontend");
```

**Kendi Render URL'inizi kullanın!**
- Dashboard'dan URL'i kopyalayın
- `https://` değil `wss://` kullanın
- `/frontend` path'i ekleyin

---

### 5️⃣ Browser Console'da Hata Kontrolü

Tarayıcıda **F12** → **Console** sekmesi:

**Beklenen:**
```
[LOGO] masisbet.png loaded successfully
```

**Hata varsa:**
```
WebSocket connection to 'wss://...' failed
```

Bu, Render.com servisinin çalışmadığı anlamına gelir.

---

## 🎯 Hızlı Test

### Test 1: Render Servisi Çalışıyor mu?

Tarayıcıda açın:
```
https://animasyon.onrender.com
```

**Beklenen:** "Service is running" veya benzeri bir mesaj
**Hata:** "Service not found" → Servis deploy edilmemiş

### Test 2: WebSocket Port Açık mı?

Terminal'de (Render.com SSH):
```bash
curl https://animasyon.onrender.com/frontend
```

**Beklenen:** WebSocket upgrade response
**Hata:** Connection refused → Port kapalı

---

## 🔧 En Yaygın Sorunlar ve Çözümleri

### Sorun 1: Playwright Kurulum Hatası

**Hata:**
```
Error: Executable doesn't exist at /opt/render/project/.cache/ms-playwright/...
```

**Çözüm:**
Render.com'da **Build Command**'i değiştirin:
```
pip install playwright websockets && playwright install chromium --with-deps
```

### Sorun 2: Servis Uyuyor (Free Plan)

**Belirti:** İlk istek 30-60 saniye sürüyor

**Çözüm:**
1. https://uptimerobot.com → Ücretsiz hesap
2. **New Monitor**:
   - Type: HTTPS
   - URL: `https://animasyon.onrender.com`
   - Interval: 5 minutes
3. Servis sürekli uyanık kalır

### Sorun 3: anim.py Çalışmıyor

**Belirti:** WebSocket bağlanıyor ama maç yok

**Çözüm:**
Render.com'da ikinci bir servis oluşturun:
- Name: `animasyon-scraper`
- Build: Aynı
- Start: `python anim.py`

---

## 📋 Kontrol Listesi

- [ ] Render.com servisi **Live** durumda mı?
- [ ] Loglarda "server: ws://0.0.0.0:8777" yazıyor mu?
- [ ] anim.py çalışıyor mu? (loglarda "PW: goto" yazmalı)
- [ ] WebSocket URL'i doğru mu? (`wss://...`)
- [ ] Browser console'da hata var mı?
- [ ] Render.com URL'i tarayıcıda açılıyor mu?

---

## 🆘 Hala Çalışmıyorsa

### 1. Render Servisini Yeniden Deploy Edin

```
Dashboard → animasyon → Manual Deploy → Clear build cache & deploy
```

### 2. Environment Variables Kontrol Edin

```
PYTHONUNBUFFERED = 1
```

### 3. Start Command'i Değiştirin

```
python server.py
```

(anim.py'yi başlatmak için ayrı servis oluşturun)

---

## 💡 Basit Test: Local'de Çalıştırma

Render.com yerine önce local'de test edin:

```bash
# Terminal 1
python server.py

# Terminal 2
python anim.py

# Tarayıcıda live_anim.html aç
```

Local'de çalışıyorsa sorun Render.com'dadır.

---

## 📞 Destek

Render.com dokümanları:
https://docs.render.com/troubleshooting

WebSocket debugging:
https://developer.mozilla.org/en-US/docs/Web/API/WebSocket

---

## 🎯 Özet

**En olası neden:** Render.com servisi çalışmıyor veya uyuyor.

**Çözüm:**
1. Render Dashboard'da servisi kontrol edin
2. Logları inceleyin
3. Manual deploy yapın
4. UptimeRobot ile sürekli uyanık tutun
