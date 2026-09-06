import json

d = json.load(open("module_diagnostic_full_universe_results.json", encoding="utf-8"))
valid = {k: v for k, v in d.items() if "error" not in v}
print(f"toplam sembol: {len(d)}, gecerli (yeterli veri): {len(valid)}")

pos = []
neg = []
for sym, v in valid.items():
    exp = v["portfolio_level"]["portfolio_expectancy_r"]
    if exp > 0:
        pos.append((sym, exp))
    else:
        neg.append((sym, exp))

print(f"\npozitif expectancy: {len(pos)} sembol ({len(pos)/len(valid)*100:.1f}%)")
print(f"negatif expectancy: {len(neg)} sembol ({len(neg)/len(valid)*100:.1f}%)")

pos_sorted = sorted(pos, key=lambda x: -x[1])
neg_sorted = sorted(neg, key=lambda x: x[1])

print("\nEN GUCLU POZITIF 5:")
for s, e in pos_sorted[:5]:
    print(f"  {s}: exp={e:+.4f}")

print("\nEN GUCLU NEGATIF 5:")
for s, e in neg_sorted[:5]:
    print(f"  {s}: exp={e:+.4f}")

ob_dominant_syms = []
total_taken_all = 0
total_taken_ob = 0
ob_dominant_neg = 0
ob_dominant_pos = 0

for sym, v in valid.items():
    taken_by_mod = v["portfolio_level"]["taken_by_module"]
    exp = v["portfolio_level"]["portfolio_expectancy_r"]
    total = sum(taken_by_mod.values())
    ob_count = taken_by_mod.get("ob", 0)
    total_taken_all += total
    total_taken_ob += ob_count
    if total > 0 and ob_count > 0 and ob_count == max(taken_by_mod.values()):
        ob_dominant_syms.append(sym)
        if exp < 0:
            ob_dominant_neg += 1
        else:
            ob_dominant_pos += 1

print(f"\n=== OB-CROWDING ANALIZI (duzeltilmis motor) ===")
print(f"OB dominant modul sembol sayisi: {len(ob_dominant_syms)}/{len(valid)} ({len(ob_dominant_syms)/len(valid)*100:.1f}%)")
print(f"Toplam slot icinde OB payi: {total_taken_ob}/{total_taken_all} ({total_taken_ob/total_taken_all*100:.1f}%)")
if ob_dominant_syms:
    print(f"OB-dominant semboller icinde negatif exp={ob_dominant_neg} ({ob_dominant_neg/len(ob_dominant_syms)*100:.1f}%), pozitif exp={ob_dominant_pos} ({ob_dominant_pos/len(ob_dominant_syms)*100:.1f}%)")
