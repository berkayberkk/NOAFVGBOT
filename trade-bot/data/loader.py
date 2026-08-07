"""
Geçmiş fiyat verisini (MT5'ten export edilen csv) yükleyip standart
mum sözlük formatına çeviren yardımcı modül.

Beklenen csv formatı (MT5 History Center export'u, tab-separated):
    <DATE>      <TIME>    <OPEN>  <HIGH>  <LOW>   <CLOSE> <TICKVOL> <VOL> <SPREAD>
    2026.04.01  01:00:00  4671.30 4686.54 4662.76 4674.31 5415      0     30

- Tarih formatı: YYYY.MM.DD
- Saat formatı: HH:MM:SS
- Ondalık ayracı: nokta (.)
- Ayraç: tab (\t)
"""

import csv
from datetime import datetime


def load_candles_from_csv(path: str) -> list[dict]:
    """
    MT5 export csv dosyasından mumları okuyup liste of dict formatında döner.

    Her eleman:
        {
            "time": datetime,
            "open": float,
            "high": float,
            "low": float,
            "close": float,
            "tick_volume": int,
            "spread": int,
        }

    Mumlar dosyadaki sırayla (eskiden yeniye) döner.
    """
    candles = []

    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter="\t")
        header = next(reader)  # başlık satırını atla

        for row in reader:
            if not row or len(row) < 6:
                continue  # boş/eksik satırları atla

            date_str, time_str, open_, high, low, close = row[0:6]
            tick_volume = row[6] if len(row) > 6 else "0"
            spread = row[8] if len(row) > 8 else "0"

            dt = datetime.strptime(f"{date_str} {time_str}", "%Y.%m.%d %H:%M:%S")

            candles.append({
                "time": dt,
                "open": float(open_),
                "high": float(high),
                "low": float(low),
                "close": float(close),
                "tick_volume": int(tick_volume),
                "spread": int(spread),
            })

    return candles


if __name__ == "__main__":
    # Hızlı doğrulama: dosyayı yükleyip ilk/son mumu ve toplam sayıyı yazdır
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "data/GOLD_M30.csv"
    candles = load_candles_from_csv(path)
    print(f"Toplam mum: {len(candles)}")
    print(f"İlk mum: {candles[0]}")
    print(f"Son mum: {candles[-1]}")
