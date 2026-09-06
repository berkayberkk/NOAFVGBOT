"""
Seans / Killzone yardımcı modülü.

Kaynak: ICT (Inner Circle Trader) "killzone" kavramı -- kurumsal
işlem hacminin en yoğun olduğu saatlerin dışında oluşan sinyallerin
daha düşük kaliteli olduğu iddiası (bkz. NOA_KONSEPTI_KAYNAK_ANALIZI.md
"Win rate iyileştirme araştırması" bölümü, 2026-09-03 -- WebSearch ile
ictkillzone.com, tradingrage.com gibi kaynaklardan derlendi).

SAATLER (GMT/UTC yaklaşık -- DST ayarlanmadı, bkz. aşağıdaki kısıtlama):
- Londra Killzone: 07:00-10:00 UTC
- New York AM Killzone: 12:00-15:00 UTC
- New York PM Killzone: 18:00-20:00 UTC (Silver Bullet NY PM'in genişletilmiş hali)

KISITLAMA (açıkça belirtiliyor): `research/v2/data/acquisition.py`'nin
candle zaman damgalarını UTC'ye normalize ettiği doğrulandı, ama
yukarıdaki saatler ICT kaynaklarının GMT/EST cinsinden verdiği
değerlerden UTC'ye BASİT (DST'siz) bir çeviriyle elde edildi -- yaz
saati uygulamasına göre gerçek killzone'lardan ±1 saat kayabilir. Bu
saatler KALİBRE EDİLMEDİ, doğrudan kaynak materyalden alındı; ablation
testinin sonucuna göre (varsa) kalibre edilecek.
"""

LONDON_KILLZONE_HOURS = range(7, 10)      # 07:00-09:59 UTC
NY_AM_KILLZONE_HOURS = range(12, 15)       # 12:00-14:59 UTC
NY_PM_KILLZONE_HOURS = range(18, 20)       # 18:00-19:59 UTC


def in_killzone(hour: int) -> bool:
    """Verilen UTC saatinin (0-23) herhangi bir ICT killzone penceresinde olup olmadığını döner."""
    return hour in LONDON_KILLZONE_HOURS or hour in NY_AM_KILLZONE_HOURS or hour in NY_PM_KILLZONE_HOURS
