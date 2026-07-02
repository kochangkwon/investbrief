"""투자자 수급 요약 — 브리프용 가공."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from app.collectors import investor_flow_collector

logger = logging.getLogger(__name__)


# 간이 종목 → 섹터 매핑 (운영하며 확장)
SECTOR_HINTS = {
    # 반도체
    "삼성전자": "반도체", "SK하이닉스": "반도체", "한미반도체": "반도체",
    "이오테크닉스": "반도체", "HPSP": "반도체", "리노공업": "반도체",
    "동진쎄미켐": "반도체소재", "솔브레인": "반도체소재", "원익IPS": "반도체장비",
    "이수페타시스": "반도체PCB", "심텍": "반도체PCB",
    # 2차전지
    "삼성SDI": "2차전지", "LG에너지솔루션": "2차전지", "SK이노베이션": "2차전지",
    "에코프로비엠": "2차전지소재", "엘앤에프": "2차전지소재", "포스코퓨처엠": "2차전지소재",
    # 바이오/제약
    "셀트리온": "바이오", "유한양행": "바이오", "한미약품": "바이오",
    "알테오젠": "바이오", "삼성바이오로직스": "바이오", "SK바이오팜": "바이오",
    "리가켐바이오": "바이오",
    # IT/플랫폼
    "네이버": "플랫폼", "카카오": "플랫폼", "크래프톤": "게임",
    "엔씨소프트": "게임", "넷마블": "게임", "펄어비스": "게임",
    # 자동차
    "현대차": "자동차", "기아": "자동차", "현대모비스": "자동차",
    "한온시스템": "자동차부품", "HL만도": "자동차부품",
    # 철강/소재
    "POSCO홀딩스": "철강", "고려아연": "비철금속", "현대제철": "철강",
    # 조선
    "HD현대중공업": "조선", "삼성중공업": "조선", "한화오션": "조선",
    "HD한국조선해양": "조선",
    # 방산
    "한화에어로스페이스": "방산", "LIG넥스원": "방산", "현대로템": "방산",
    "한화시스템": "방산",
    # 금융
    "KB금융": "금융", "신한지주": "금융", "하나금융지주": "금융",
    "메리츠금융지주": "금융", "우리금융지주": "금융", "기업은행": "금융",
    # 기타 대형주
    "LG화학": "화학", "LG전자": "가전", "삼성전기": "전자부품",
    "LG이노텍": "전자부품", "SK스퀘어": "지주", "두산에너빌리티": "에너지",
}


def _classify_sector(stock_name: str) -> str:
    return SECTOR_HINTS.get(stock_name, "기타")


async def get_today_flow_summary(
    target_date: Optional[date] = None,
) -> dict[str, Any]:
    """브리프용 수급 요약. 실패 시 빈 dict."""
    trade_date = (
        target_date if target_date else investor_flow_collector.latest_trading_date()
    )

    market_flow = await investor_flow_collector.get_market_flow(trade_date)
    if market_flow is None:
        logger.warning("수급 데이터 조회 실패 (%s)", trade_date)
        return {}

    top_traders = await investor_flow_collector.get_top_foreign_traders(
        trade_date, limit_buy=10, limit_sell=5
    )

    # 섹터별 net 집계 (매수 종목 기준)
    buyers = [t for t in top_traders if t["net_billion"] > 0]
    sector_net: dict[str, float] = {}
    for b in buyers:
        sector = _classify_sector(b["stock_name"])
        sector_net[sector] = sector_net.get(sector, 0) + b["net_billion"]

    sorted_sectors = sorted(sector_net.items(), key=lambda x: x[1], reverse=True)
    buy_sectors = [s for s, v in sorted_sectors if v > 0 and s != "기타"][:5]

    # 매도 섹터
    sellers = [t for t in top_traders if t["net_billion"] < 0]
    sell_sector_net: dict[str, float] = {}
    for s in sellers:
        sector = _classify_sector(s["stock_name"])
        sell_sector_net[sector] = sell_sector_net.get(sector, 0) + s["net_billion"]
    sorted_sell = sorted(sell_sector_net.items(), key=lambda x: x[1])
    sell_sectors = [s for s, v in sorted_sell if v < 0 and s != "기타"][:5]

    return {
        **market_flow,
        "top_buy_sectors": buy_sectors,
        "top_sell_sectors": sell_sectors,
        "top_foreign_traders": top_traders[:15],  # 매수 + 매도
    }
