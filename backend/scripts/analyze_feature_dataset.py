"""피처 예측력 분석 수동 실행 (스케줄러 자동분석과 동일 로직).

    python3 -u -m scripts.analyze_feature_dataset
"""
from __future__ import annotations

import asyncio

from app.services import feature_validation_service as fv


async def main() -> None:
    result = await fv.analyze()
    print(fv.format_report(result).replace("<b>", "").replace("</b>", "")
          .replace("<code>", "").replace("</code>", ""))


if __name__ == "__main__":
    asyncio.run(main())
