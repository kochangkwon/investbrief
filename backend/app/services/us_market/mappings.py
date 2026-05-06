"""미국 시장 데이터 → 한국 종목/테마 매핑 정의 (지시서 v1.1).

3가지 카테고리:
- ETF_MAPPING: 섹터 평균 (5개)
- BIG_NAMES: 한국 직격 영향 빅네임 (7개)
- MACRO_INDICATORS: 매크로 지표 (4개)
- SP500_FUTURES: 한국 갭 직접 예측 시그널 (1개)

운영하면서 학습된 결과로 매핑은 주기적으로 다듬을 것.
relation 필드는 매핑 변경 시 사실 검증된 정보로 동기화 필수.
"""
from __future__ import annotations

# ============================================================
# 1. 섹터 ETF 매핑
# ============================================================
ETF_MAPPING = {
    "SOXX": {
        "name": "필라델피아 반도체",
        "category": "반도체",
        "kr_stocks": ["삼성전자", "SK하이닉스", "한미반도체", "HPSP", "이오테크닉스"],
        "kr_themes": ["AI 반도체", "HBM 후공정"],
        "note": "미국 반도체 30개 종목 평균 — 국내 반도체 섹터 전반과 동조",
    },
    "XLK": {
        "name": "기술주",
        "category": "빅테크",
        "kr_stocks": ["네이버", "카카오"],
        "kr_themes": ["인터넷 플랫폼"],
        "note": "AAPL/MSFT 비중 높음 — 직접 영향 약함, 시장 분위기 시그널",
    },
    "XBI": {
        "name": "바이오 (소형주 중심)",
        "category": "바이오",
        "kr_stocks": ["셀트리온", "알테오젠", "한미약품", "유한양행"],
        "kr_themes": ["K-바이오"],
        "note": "임상/FDA 이벤트 동조 — 국내 바이오 위험선호 시그널",
    },
    "LIT": {
        "name": "리튬/배터리",
        "category": "2차전지",
        "kr_stocks": ["LG에너지솔루션", "삼성SDI", "에코프로비엠"],
        "kr_themes": ["2차전지"],
        "note": "전기차 수요 + 리튬 가격 종합 → 2차전지 셀/소재 동조",
    },
    "XLE": {
        "name": "에너지/정유",
        "category": "정유/에너지",
        "kr_stocks": ["SK이노베이션", "S-Oil", "GS"],
        "kr_themes": [],
        "note": "WTI 유가와 함께 봐야 정확 — 단독으로는 약한 시그널",
    },
}

# ============================================================
# 2. 빅네임 매핑 (한국 직격 영향)
# ============================================================
BIG_NAMES = {
    "NVDA": {
        "name": "엔비디아",
        "kr_stocks": ["한미반도체", "이수페타시스", "SK하이닉스"],
        "relation": "HBM 후공정 장비 / AI 가속기용 PCB / HBM 메모리 직접 공급",
        "kr_themes": ["AI 반도체", "HBM 후공정"],
        "alert_threshold": 5.0,
    },
    "TSM": {
        "name": "TSMC",
        "kr_stocks": ["삼성전자", "동진쎄미켐", "솔브레인"],
        "relation": "삼성 파운드리 직접 경쟁사 / 반도체 공정소재 공급",
        "kr_themes": ["반도체", "파운드리"],
        "alert_threshold": 5.0,
    },
    "TSLA": {
        "name": "테슬라",
        "kr_stocks": ["LG에너지솔루션", "삼성SDI", "에코프로비엠"],
        "relation": "테슬라 배터리 셀 공급사 / 양극재 공급사",
        "kr_themes": ["2차전지", "전기차"],
        "alert_threshold": 5.0,
    },
    "AAPL": {
        "name": "애플",
        "kr_stocks": ["LG이노텍", "삼성전기"],
        "relation": "아이폰 카메라 모듈 / MLCC·기판 직접 공급",
        "kr_themes": ["애플 부품"],
        "alert_threshold": 4.0,
    },
    "META": {
        "name": "메타",
        "kr_stocks": ["네이버", "카카오"],
        "relation": "광고/플랫폼 동조 흐름 (직접 거래 X, 시장 분위기 동조)",
        "kr_themes": ["인터넷 플랫폼", "AI 광고"],
        "alert_threshold": 5.0,
    },
    "AMD": {
        "name": "AMD",
        "kr_stocks": ["SK하이닉스", "한미반도체"],
        "relation": "MI300 시리즈 HBM 메모리 채택 / 후공정 장비 동조",
        "kr_themes": ["HBM 후공정"],
        "alert_threshold": 5.0,
    },
    "MU": {
        "name": "마이크론",
        "kr_stocks": ["삼성전자", "SK하이닉스"],
        "relation": "메모리 직접 경쟁사 — 가격/수요 시그널 동조 (실적 가이던스 영향 큼)",
        "kr_themes": ["메모리 반도체"],
        "alert_threshold": 5.0,
    },
}

# ============================================================
# 3. 매크로 지표
# ============================================================
MACRO_INDICATORS = {
    "DX-Y.NYB": {
        "name": "달러 인덱스 (DXY)",
        "category": "환율",
        "implication_up": "달러 강세 → 외인 코스피 매도 압력, 환율 1400원대 진입 시 수출주 부담",
        "implication_down": "달러 약세 → 외인 매수 우호, 신흥국 자금 유입",
        "alert_threshold": 0.5,
        "format": "{value:.2f}",
    },
    "^TNX": {
        "name": "미국 10년물 금리",
        "category": "금리",
        "implication_up": "성장주(반도체/바이오/플랫폼) 부담 — 4.5% 이상 시 약세 가속",
        "implication_down": "성장주 호재 — 4.0% 이하 진입 시 반등 모멘텀",
        "alert_threshold": 0.05,
        "format": "{value:.2f}%",
        "is_yield": True,
    },
    "^VIX": {
        "name": "VIX 변동성 지수",
        "category": "위험도",
        "implication_up": "위험 회피 강화 → 외인 매도 증가, 성장주 약세, 안전자산 선호",
        "implication_down": "위험 자산 선호 → 외인 매수 회복, 시클리컬·반도체 강세",
        "alert_threshold": 2.0,
        "format": "{value:.2f}",
        "is_yield": True,
        "warning_levels": {
            20: "주의 구간 진입",
            25: "패닉 임계 — 매수 자제 권고",
        },
    },
    "CL=F": {
        "name": "WTI 유가",
        "category": "원자재",
        "implication_up": "정유주(SK이노/S-Oil/GS) 호재, 인플레 부담 → 금리 상승 압력",
        "implication_down": "정유주 부담, 인플레 완화 → 성장주 우호적",
        "alert_threshold": 2.0,
        "format": "${value:.2f}",
        "kr_related": ["SK이노베이션", "S-Oil", "GS"],
    },
}

# ============================================================
# 4. S&P500 선물 (한국 갭 직접 예측)
# ============================================================
SP500_FUTURES = {
    "ES=F": {
        "name": "S&P500 선물",
        "category": "선물",
        "implication": "한국 09:00 갭 방향성 직접 시그널",
    },
}
