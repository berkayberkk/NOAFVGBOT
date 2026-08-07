"""
FVG modülü için test iskeleti.
Gerçek mantık yazıldıkça buraya somut senaryolar eklenecek
(örn: bilinen bir FVG içeren 3 mumluk örnek veri -> doğru sonuç bekleniyor).
"""

import pytest
from strategy.fvg import detect_fvgs


def test_detect_fvgs_not_implemented_yet():
    with pytest.raises(NotImplementedError):
        detect_fvgs([])
