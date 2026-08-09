# DART API 실호출 검증 결과 (2026-08-09)

재무 리스크 필터 구현 1단계 — 지시서 필드명을 믿지 않고 실제 응답으로 확인한 결과.
**아래 내용이 `app/services/risk_flags.py`의 계정 매칭 사양의 근거다.**

## 1. 엔드포인트 호출 결과

| 엔드포인트 | 결과 | 비고 |
|---|---|---|
| `corpCode.xml` | 정상 (ZIP → `CORPCODE.xml`) | 상장사 3,981개. `247540 → corp_code=01160363` |
| `fnlttSinglAcntAll.json` | 정상 | 에코프로비엠 2025 사업보고서 CFS 185행 |
| `list.json` | 정상 | **미사용** — 아래 참조 |
| `piicDecsn.json` | 정상 | 에코프로비엠 2026-06-30 유상증자결정 1건 |

### list.json을 쓰지 않은 이유
`piicDecsn.json`이 `corp_code` + `bgn_de`/`end_de` 기간 조회를 직접 지원하므로
"list.json으로 감지 → piicDecsn으로 상세 취득"의 2단계가 불필요하다. 호출 1회로 동일 결과.
(`list_B_24m.json`이 그 검증 기록이다.)

## 2. 재무제표 응답 구조

- 응답 행 필드: `sj_div`, `sj_nm`, `account_id`, `account_nm`, `thstrm_amount`,
  `frmtrm_amount`, `bfefrmtrm_amount`, `thstrm_nm`, `ord`, `currency` 등
- `sj_div`: `BS`(재무상태표) / `CIS`(포괄손익계산서) 또는 `IS` / `CF`(현금흐름표) / `SCE`(자본변동표)
- **사업보고서 1건에 당기·전기·전전기 3개년이 모두 담긴다.** 3개년 지표에 API 호출 1회면 충분.
- 금액은 콤마 없는 문자열. 누락 시 빈 문자열. 음수는 `-` 접두.
- 분기보고서의 `frmtrm_amount`는 "전기말"(재무상태표 기준)이라 손익·현금흐름 비교에 부적합.
  → **지표는 전부 연간(사업보고서) 기준으로 계산하고, 최근 분기는 `latest_quarter` 표기용으로만 쓴다.**

## 3. 계정 매칭에서 실제로 확인된 함정

### (1) `account_id`가 `-표준계정코드 미사용-`인 계정이 있다
- 삼성전자 `단기차입금`, 두산퓨얼셀 `유동성장기차입금`
- → `account_id` 우선 매칭 후 `account_nm` **정확일치** 폴백이 필요하다.

### (2) 같은 `account_nm`이 2행 온다
- 에코프로비엠 `리스부채` (유동/비유동), `기타금융부채` (유동/비유동)
- → 이자발생부채는 첫 행 선택이 아니라 **행 단위 합산**해야 한다.

### (3) 건설중인자산은 재무상태표 별도 계정으로 제출되지 않는다
검증한 4개 종목(에코프로비엠·삼성전자·한미반도체·두산퓨얼셀) **전부 없음**.
유형자산 총액만 제출하고 건설중인자산은 주석에 기재한다.
→ **A지표군(감가상각 절벽)은 대부분의 종목에서 `판정불가`가 된다.**
   (주석 파싱은 지시서 9장에서 범위 제외)

### (4) 현금흐름표 조정 항목을 한 줄로 뭉쳐 제출하는 기업이 많다
- 삼성전자: `조정 [ifrs-full_AdjustmentsForReconcileProfitLoss]` 한 행뿐
- 에코프로비엠·두산퓨얼셀: 조정 항목 자체가 없음
- 한미반도체: `감가상각비에 대한 조정`, `무형자산상각비에 대한 조정`, `이자비용 조정` **모두 존재**

→ **EBITDA(C2), 순차입금/EBITDA(C3), 이자보상배율(C4)은 계정을 제출한 기업에서만 계산된다.**
   나머지는 `null` + 사유 기록. 손익계산서의 `금융원가`를 이자비용으로 대체하지 않는다
   (금융원가 ≠ 이자비용, 지시서 원칙 1 "추정 금지").

## 4. 확정된 계정 매칭 사양

| 지표 입력 | sj_div | account_id | account_nm 폴백 |
|---|---|---|---|
| 유형자산 | BS | `ifrs-full_PropertyPlantAndEquipment` | 유형자산 |
| 건설중인자산 | BS | `ifrs-full_ConstructionInProgress` | 건설중인자산 |
| 현금및현금성자산 | BS | `ifrs-full_CashAndCashEquivalents` | 현금및현금성자산 |
| 영업이익 | CIS/IS | `dart_OperatingIncomeLoss` | 영업이익, 영업이익(손실) |
| 이자비용 | CIS/IS/CF | `ifrs-full_InterestExpense`, `dart_AdjustmentsForInterestExpenses` | 이자비용, 이자비용 조정 |
| 영업활동현금흐름 | CF | `ifrs-full_CashFlowsFromUsedInOperatingActivities` | 영업활동현금흐름 |
| 유형자산의 취득 | CF | `ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities` | 유형자산의 취득 |
| 무형자산의 취득 | CF | `ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities` | 무형자산의 취득 |
| 감가상각비 | CF | `ifrs-full_AdjustmentsForDepreciationExpense` | 감가상각비에 대한 조정 |
| 무형자산상각비 | CF | `ifrs-full_AdjustmentsForAmortisationExpense` | 무형자산상각비에 대한 조정 |

**이자발생부채(C1)** — BS에서 아래에 해당하는 행을 전부 합산:
`ifrs-full_ShorttermBorrowings`, `ifrs-full_CurrentPortionOfLongtermBorrowings`,
`ifrs-full_LongtermBorrowings`, `ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived`,
`ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued`, `dart_CurrentPortionOfBonds`,
`ifrs-full_CurrentLeaseLiabilities`, `ifrs-full_NoncurrentLeaseLiabilities`
(+ 표준코드 미사용 대비 계정명 폴백: 단기차입금/장기차입금/유동성장기차입금/유동성장기부채/
사채/유동성사채/리스부채/유동 리스부채/비유동 리스부채)

실제로 합산에 포함된 계정은 API 응답의 `flags.C_차입리스크.included_accounts`로 출력한다.

## 5. 유상증자 결정(piicDecsn) 필드

| 지표 | 필드 |
|---|---|
| 신주 수 (보통주) | `nstk_ostk_cnt` |
| 증자 전 발행주식총수 (보통주) | `bfic_tisstk_ostk` |
| 시설자금 | `fdpp_fclt` |
| 영업양수자금 | `fdpp_bsninh` (지시서 목록에 없었으나 API에 존재 → 포함) |
| 운영자금 | `fdpp_op` |
| 채무상환자금 | `fdpp_dtrp` |
| 타법인증권취득자금 | `fdpp_ocsa` |
| 기타 | `fdpp_etc` |
| 발행방식 | `ic_mthn` |

목적별 금액 필드가 그대로 제공되므로 공시 본문 텍스트 해석은 하지 않는다.
