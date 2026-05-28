import os
import sqlite3
import pandas as pd
from calendar import monthrange

# ==========================================
# [설정 항목] 파일 경로 고정 정의
# ==========================================
CSV_CANDIDATE_PATH = "까리존345후보종목.csv"
DB_PATH = "stock_data.db"
EXCEL_OUTPUT_PATH = "까리존345임시결과.xlsx"

UNIT_MONEY = 1000000  # 1차 진입 원금: 100만 원
END_SIMULATION_DATE = "2026-05-29"  # 최종 추적 종료일


def get_user_date_range():
    print("=" * 80)
    print(" [까리존 345 백테스트 - 하이브리드 자동 매매 익절/추매 완결판]")
    print("=" * 80)

    while True:
        start_in = input("▶ 테스트 시작 연월을 입력하세요 (예: 202001): ").replace("-", "").strip()
        if len(start_in) == 6 and start_in.isdigit():
            start_date = f"{start_in[:4]}-{start_in[4:6]}-01"
            break
        print("[입력오류] YYYYMM 형식으로 정확히 입력해 주세요.")

    while True:
        end_in = input("▶ 테스트 종료 연월을 입력하세요 (예: 202512): ").replace("-", "").strip()
        if len(end_in) == 6 and end_in.isdigit():
            year = int(end_in[:4])
            month = int(end_in[4:6])
            if 1 <= month <= 12:
                last_day = monthrange(year, month)[1]
                end_date = f"{end_in[:4]}-{end_in[4:6]}-{last_day}"
                break
        print("[입력오류] YYYYMM 형식으로 정확히 입력해 주세요.")

    return start_date, end_date


def load_target_candidates(start_date, end_date):
    if not os.path.exists(CSV_CANDIDATE_PATH):
        raise FileNotFoundError(f"후보 종목 파일이 없습니다: {CSV_CANDIDATE_PATH}")

    df = pd.read_csv(CSV_CANDIDATE_PATH, dtype={"code": str, "date": str})
    if df.empty: return df

    sample_date = str(df["date"].iloc[0])
    cmp_start = start_date.replace("-", "") if "-" not in sample_date else start_date
    cmp_end = end_date.replace("-", "") if "-" not in sample_date else end_date
    return df[(df["date"] >= cmp_start) & (df["date"] <= cmp_end)].copy()


def detect_db_date_format(conn):
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT date FROM daily_prices LIMIT 1")
        row = cursor.fetchone()
        if row and row[0]: return "HYPHEN" if "-" in str(row[0]) else "RAW"
    except:
        pass
    return "HYPHEN"


def main():
    start_candidate_date, end_candidate_date = get_user_date_range()
    print(f"\n[시스템] 시뮬레이션 하이브리드 엔진 연산을 시작합니다...")

    try:
        df_targets = load_target_candidates(start_candidate_date, end_candidate_date)
        total_event_count = len(df_targets)
        print(f"[안내] 후보 이벤트 개수: 총 {total_event_count}건 로드 완료")
        if df_targets.empty: return
    except Exception as e:
        print(f"[오류] 후보 로드 실패: {e}")
        return

    conn = sqlite3.connect(DB_PATH)
    db_date_type = detect_db_date_format(conn)

    def normalize_to_db_format(x):
        pure_date = str(x).replace("-", "").strip()
        return f"{pure_date[:4]}-{pure_date[4:6]}-{pure_date[6:8]}" if db_date_type == "HYPHEN" else pure_date

    df_targets["date"] = df_targets["date"].apply(normalize_to_db_format)
    db_start_date = normalize_to_db_format(start_candidate_date)
    db_end_date = normalize_to_db_format(END_SIMULATION_DATE)

    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT date FROM daily_prices WHERE date >= ? AND date <= ? ORDER BY date ASC",
                   (db_start_date, db_end_date))
    timeline = [r[0] for r in cursor.fetchall()]

    portfolio = {}
    pending_signals = {}
    all_target_audit_logs = {}

    for _, row in df_targets.iterrows():
        code_str = str(row["code"]).zfill(6)
        cursor.execute("SELECT high FROM daily_prices WHERE code = ? AND date = ?", (code_str, row["date"]))
        res = cursor.fetchone()
        if res:
            base_high = res[0]
            p_33_price = int(base_high * 0.67)

            cursor.execute("SELECT COUNT(*) FROM daily_prices WHERE code = ? AND date <= ?", (code_str, row["date"]))
            history_count = cursor.fetchone()[0]

            if history_count < 240:
                all_target_audit_logs[(code_str, row["date"])] = {
                    "후보등록일": row["date"], "종목명": row["name"], "종목코드": code_str, "기준봉고가": base_high,
                    "타점가격(-33%)": p_33_price,
                    "최종상태": "매수제외(상장기간부족)", "최초매수일": "-", "최종매도일": "-", "총투자금액": 0, "수익금": 0
                }
                continue

            pending_signals[(code_str, row["date"])] = {
                "name": row["name"], "base_high": base_high, "active": True, "wait_days": 0
            }

            cursor.execute("SELECT low FROM daily_prices WHERE code = ? AND date > ? ORDER BY date ASC LIMIT 20",
                           (code_str, row["date"]))
            low_rows = cursor.fetchall()

            base_audit = {
                "후보등록일": row["date"], "종목명": row["name"], "종목코드": code_str, "기준봉고가": base_high,
                "타점가격(-33%)": p_33_price,
                "최종상태": "미체결(감시중)", "최초매수일": "-", "최종매도일": "-", "총투자금액": 0, "수익금": 0
            }
            for d_idx in range(1, 21):
                base_audit[f"D+{d_idx}_저가"] = low_rows[d_idx - 1][0] if d_idx <= len(low_rows) else "-"

            all_target_audit_logs[(code_str, row["date"])] = base_audit

    peak_capital = 0
    trade_logs = []

    # 시계열 타임라인 마스터 연산
    for current_date in timeline:
        cleared_codes = []

        # --- A. 보유 종목 장중 자동 매수/매도 감시 (기계의 영역) ---
        for code, stock in portfolio.items():
            cursor.execute("SELECT open, high, low, close FROM daily_prices WHERE code = ? AND date = ?",
                           (code, current_date))
            day_data = cursor.fetchone()
            if not day_data: continue

            s_open, s_high, s_low, s_close = day_data
            stock["holding_days"] += 1
            base_high = stock["base_high"]
            holding_days = stock["holding_days"]
            signal_date = stock["signal_date"]

            # [1단계] 장중 저가 우선 판정 (Worst-case 및 연쇄 자동추매 배팅)
            pyramided_today = False
            p_43_price = base_high * 0.57
            p_50_price = base_high * 0.50
            p_66_price = base_high * 0.34

            if "43" not in stock["triggered_phases"] and s_low <= p_43_price:
                add_spent = int(UNIT_MONEY * 1.1)
                stock["total_spent"] += add_spent
                stock["total_qty"] += (add_spent / p_43_price)
                stock["triggered_phases"].append("43")
                stock["history_logs"].append(f"[-43%추매]:{current_date}")
                pyramided_today = True

            if "50" not in stock["triggered_phases"] and s_low <= p_50_price:
                add_spent = int(UNIT_MONEY * 4.3)
                stock["total_spent"] += add_spent
                stock["total_qty"] += (add_spent / p_50_price)
                stock["triggered_phases"].append("50")
                stock["history_logs"].append(f"[-50%추매]:{current_date}")
                pyramided_today = True

            if "66" not in stock["triggered_phases"] and s_low <= p_66_price:
                add_spent = int(UNIT_MONEY * 7.0)
                stock["total_spent"] += add_spent
                stock["total_qty"] += (add_spent / p_66_price)
                stock["triggered_phases"].append("66")
                stock["history_logs"].append(f"[-66%추매]:{current_date}")
                pyramided_today = True

            if pyramided_today:
                stock["avg_price"] = stock["total_spent"] / stock["total_qty"]

            # [2단계] 자동 익절/본절 판정 (장중 실시간 매도 작동)
            avg_price = stock["avg_price"]

            # 추매 내역이 있거나 10일 장기 횡보(WAIT) 상태이면 목표가는 본절(0%수익), 그 외 평시는 +6% 익절
            if len(stock["triggered_phases"]) > 1 or stock["status"] == "WAIT":
                target_exit_price = avg_price
                exit_type = "본절마감(0%)"
                profit = 0
            else:
                target_exit_price = avg_price * 1.06
                exit_type = "익절청산(+6%)"
                profit = int(stock["total_spent"] * 0.06)

            # 당일 고가가 실시간 변경된 목표가 이상으로 치솟으면 당일 즉시 탈출 허용!
            if s_high >= target_exit_price:
                trade_logs.append({
                    "종목명": stock["name"], "종목코드": code, "청산유형": exit_type,
                    "최종투자금": stock["total_spent"], "익절수익": profit, "보유일수": holding_days,
                    "매수일자": stock["buy_date"], "매도일자": current_date, "추매경로기록": ", ".join(stock["history_logs"])
                })
                all_target_audit_logs[(code, signal_date)].update({
                    "최종상태": f"매매완료({exit_type.split('(')[0]})", "최초매수일": stock["buy_date"], "최종매도일": current_date,
                    "총투자금액": stock["total_spent"], "수익금": profit
                })
                cleared_codes.append(code)
                continue

            # 10일 차 장마감 시점 횡보 전환 룰 적용
            if holding_days == 10 and stock["status"] == "HOLD" and code not in cleared_codes:
                stock["status"] = "WAIT"

            # 미청산 시 리얼타임 데이터 백업
            all_target_audit_logs[(code, signal_date)].update({
                "최종상태": f"보유중({stock['status']})", "최초매수일": stock["buy_date"], "총투자금액": stock["total_spent"]
            })

        for c_code in cleared_codes: del portfolio[c_code]

        # --- B. 신규 종목 진입 감시 (인간의 영역 - 100% 장마감 종가 기준 배팅) ---
        for (code, s_date), signal in pending_signals.items():
            if not signal["active"] or code in portfolio: continue
            if current_date <= s_date: continue

            signal["wait_days"] += 1
            if signal["wait_days"] > 120:
                signal["active"] = False
                if all_target_audit_logs[(code, s_date)]["최종상태"] == "미체결(감시중)":
                    all_target_audit_logs[(code, s_date)].update({"최종상태": "미체결(6개월기간만료)"})
                continue

            cursor.execute("SELECT open, high, low, close FROM daily_prices WHERE code = ? AND date = ?",
                           (code, current_date))
            d_data = cursor.fetchone()
            if not d_data: continue
            d_open, d_high, d_low, d_close = d_data

            base_high = signal["base_high"]
            p_33_price = base_high * 0.67
            p_43_price = base_high * 0.57
            p_50_price = base_high * 0.50

            # [수정] 종가가 -50% 이하로 추락하면 장마감 때 보고 무조건 진입 차단 (진입 전 관삭)
            if d_close <= p_50_price:
                signal["active"] = False
                all_target_audit_logs[(code, s_date)].update({"최종상태": "미체결(진입전관삭)"})
                continue

            # [수정] 종가가 -33% 이하 영역에 정착했을 때만 종가 가격으로 안전 진입
            if d_close <= p_33_price:
                phases = ["33"]
                total_spent = UNIT_MONEY
                history_list = [f"[-33%종가진입]:{current_date}"]

                # 만약 종가가 -43% 이하 영역까지 뚫린 채 마감했다면 2차 자금까지 종가 단가로 한 번에 탑승!
                if d_close <= p_43_price:
                    total_spent += int(UNIT_MONEY * 1.1)
                    phases.append("43")
                    history_list.append(f"[-43%동시종가]:{current_date}")

                portfolio[code] = {
                    "name": signal["name"], "base_high": base_high, "holding_days": 1,
                    "total_spent": total_spent, "total_qty": total_spent / d_close, "avg_price": d_close,
                    "status": "HOLD", "triggered_phases": phases, "buy_date": current_date,
                    "history_logs": history_list,
                    "signal_date": s_date
                }

                all_target_audit_logs[(code, s_date)].update({
                    "최종상태": "보유중(HOLD)", "최초매수일": current_date, "총투자금액": total_spent
                })

        # --- C. 실시간 계좌 총액 가동 한도 계산 ---
        current_total_invested = sum(s["total_spent"] for s in portfolio.values())
        if current_total_invested > peak_capital: peak_capital = current_total_invested

    conn.close()

    # --- 엑셀 통합 저장 마샬링 ---
    df_summary = pd.DataFrame({
        "지표명": [f"선택 기간 총 후보 건수", "매매 완료 청산 건수", "현재 미청산 보유 건수", "역대 최고 자금 요구치 (Peak Capital)"],
        "수치 데이터": [f"{total_event_count} 건", f"{len(trade_logs)} 건", f"{len(portfolio)} 건", f"{peak_capital:,} 원"]
    })
    df_trade_logs = pd.DataFrame(trade_logs) if trade_logs else pd.DataFrame(
        columns=["종목명", "종목코드", "청산유형", "최종투자금", "익절수익", "보유일수", "매수일자", "매도일자", "추매경로기록"])

    df_audit_sheet = pd.DataFrame(all_target_audit_logs.values())
    if not df_audit_sheet.empty:
        df_audit_sheet = df_audit_sheet.sort_values(by=["후보등록일", "종목명"]).reset_index(drop=True)

    with pd.ExcelWriter(EXCEL_OUTPUT_PATH, engine="openpyxl") as writer:
        df_summary.to_excel(writer, sheet_name="종합요약통계", index=False)
        df_trade_logs.to_excel(writer, sheet_name="매매완료상세내역", index=False)
        df_audit_sheet.to_excel(writer, sheet_name="전수조사종목현황", index=False)

    print("\n" + "=" * 115)
    print(f" [하이브리드 자동 매도/매수 시뮬레이션 완결]")
    print(f" ▶ 파일 저장 완료 : {EXCEL_OUTPUT_PATH}")
    print(f" ▶ 종가 배팅과 실시간 기계 추매/익절의 정교한 조합 결과 리포트가 도출되었습니다.")
    print("=" * 115)


if __name__ == "__main__":
    main()