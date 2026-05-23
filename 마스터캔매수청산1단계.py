import sqlite3
import pandas as pd
import os
from collections import defaultdict


def run_backtest(db_path, csv_path):
    df_triggers = pd.read_csv(csv_path)
    conn = sqlite3.connect(db_path)
    results = []

    # 자금 및 통계 추적 변수
    capital_changes = defaultdict(int)
    outcome_counts = {'익절': 0, '추매후본절': 0, '보유중': 0, '매수미발생': 0}

    # 투입 비중 (1.0 = 1차 진입금액)
    weights = [1.0, 1.5, 2.0, 2.5, 3.0]
    BASE_AMT = 1000000  # 1차 진입 금액 100만 원

    for _, row in df_triggers.iterrows():
        code = row['code']
        name = row['name']
        trigger_date = row['date']

        query_trigger = f"SELECT open, close FROM daily_prices WHERE code='{code}' AND date='{trigger_date}'"
        trigger_df = pd.read_sql(query_trigger, conn)

        if trigger_df.empty:
            continue

        r0 = trigger_df.iloc[0]['close']
        r1 = int(trigger_df.iloc[0]['open'] + (r0 - trigger_df.iloc[0]['open']) * 0.75)

        query_prices = f"SELECT date, open, high, low, close FROM daily_prices WHERE code='{code}' AND date > '{trigger_date}' ORDER BY date ASC LIMIT 200"
        prices = pd.read_sql(query_prices, conn)

        status = "매수미발생"
        buy_date = None
        buy_price = 0
        buys = []
        trading_day_count = 0

        for i, p_row in prices.iterrows():
            curr_date = p_row['date']
            curr_high = p_row['high']
            curr_low = p_row['low']
            curr_close = p_row['close']
            trading_day_count += 1

            # 5거래일 경과 및 R1 이탈 폐기 조건
            if trading_day_count > 5 and len(buys) == 0:
                status = "매수미발생"
                break

            if len(buys) == 0 and curr_close < r1:
                status = "매수미발생"
                break

            # 1차 매수
            if len(buys) == 0 and r1 <= curr_close <= r0:
                buys.append({'price': curr_close, 'date': curr_date})
                buy_date = curr_date
                buy_price = curr_close
                status = "보유중"

                invested_now = int(BASE_AMT * weights[0])
                capital_changes[curr_date] += invested_now
                continue

            # 추매 및 청산 로직
            if len(buys) > 0:
                if len(buys) == 1:
                    exit_target = buy_price * 1.04
                    status_label = "익절"
                else:
                    total_weight = sum(weights[:len(buys)])
                    total_shares = sum(weights[j] / buys[j]['price'] for j in range(len(buys)))
                    exit_target = total_weight / total_shares
                    status_label = "추매후본절"

                thresholds = [0.9, 0.8, 0.7, 0.6]
                chumae_target = None
                if len(buys) <= 4:
                    chumae_target = buy_price * thresholds[len(buys) - 1]

                chumae_executed_today = False
                if chumae_target is not None and curr_low <= chumae_target:
                    buys.append({'price': chumae_target, 'date': curr_date})
                    chumae_executed_today = True

                    invested_now = int(BASE_AMT * weights[len(buys) - 1])
                    capital_changes[curr_date] += invested_now

                if chumae_executed_today:
                    continue

                if curr_high >= exit_target:
                    holding_days = (pd.to_datetime(curr_date) - pd.to_datetime(buy_date)).days
                    total_invested = sum(BASE_AMT * weights[j] for j in range(len(buys)))
                    total_shares = sum((BASE_AMT * weights[j]) / buys[j]['price'] for j in range(len(buys)))
                    profit = (exit_target * total_shares) - total_invested

                    capital_changes[curr_date] -= int(total_invested)

                    details = []
                    for j in range(1, len(buys)):
                        d_obj = pd.to_datetime(buys[j]['date'])
                        details.append(f"{j}차({d_obj.month}/{d_obj.day}){int(buys[j]['price'])}")
                    chumae_detail = ", ".join(details)

                    results.append([
                        name, code, status_label, trigger_date, int(r0), int(r1),
                        buy_date, int(buy_price), len(buys) - 1, chumae_detail,
                        curr_date, holding_days, int(exit_target), int(total_invested), int(profit)
                    ])
                    status = status_label
                    break

        if status == "보유중":
            total_invested = sum(BASE_AMT * weights[j] for j in range(len(buys)))
            details = []
            for j in range(1, len(buys)):
                d_obj = pd.to_datetime(buys[j]['date'])
                details.append(f"{j}차({d_obj.month}/{d_obj.day}){int(buys[j]['price'])}")
            chumae_detail = ", ".join(details)
            results.append([
                name, code, "보유중", trigger_date, int(r0), int(r1),
                buy_date, int(buy_price), len(buys) - 1, chumae_detail,
                "", "", "", int(total_invested), ""
            ])

        # 개별 종목 시뮬레이션 종료 후 통계 업데이트
        if status in outcome_counts:
            outcome_counts[status] += 1

    conn.close()

    # ---------------------------
    # 1. 매매 결과 정리
    # ---------------------------
    columns = [
        '종목명', '종목번호', '결과', '기준봉 발생일', '기준봉종가', 'R1값',
        '매수일', '1차매수가', '추매횟수', '추매상세가(1차~4차)',
        '청산일', '보유일수', '청산가', '총투입금(원)', '수익금(원)'
    ]
    res_df = pd.DataFrame(results, columns=columns)

    # ---------------------------
    # 2. 일별 누적 자금 흐름 정리
    # ---------------------------
    daily_logs = []
    running_sum = 0
    for d in sorted(capital_changes.keys()):
        change = capital_changes[d]
        running_sum += change
        daily_logs.append([d, change, running_sum])
    capital_df = pd.DataFrame(daily_logs, columns=['날짜', '당일 변동금액', '누적 묶인돈(원)'])

    # ---------------------------
    # 3. 요약 통계 정리 및 출력
    # ---------------------------
    total_cases = sum(outcome_counts.values())
    summary_data = []

    print("\n" + "=" * 40)
    print("         백테스트 요약 통계         ")
    print("=" * 40)
    print(f"총 기준봉 포착 건수: {total_cases} 건\n")

    for key in ['익절', '추매후본절', '보유중', '매수미발생']:
        count = outcome_counts[key]
        ratio = (count / total_cases * 100) if total_cases > 0 else 0
        summary_data.append([key, count, f"{ratio:.2f}%"])
        print(f"- {key}: {count} 건 ({ratio:.2f}%)")
    print("=" * 40 + "\n")

    summary_df = pd.DataFrame(summary_data, columns=['분류', '발생 건수', '비율(%)'])

    # ---------------------------
    # 엑셀 파일 3개 시트로 저장
    # ---------------------------
    writer = pd.ExcelWriter("마스터캔들 결과.xlsx", engine='xlsxwriter')
    res_df.to_excel(writer, index=False, sheet_name='매매결과')
    capital_df.to_excel(writer, index=False, sheet_name='일별 자금현황')
    summary_df.to_excel(writer, index=False, sheet_name='요약 통계')

    workbook = writer.book
    money_format = workbook.add_format({'num_format': '#,##0'})

    # 시트1 포맷팅
    worksheet1 = writer.sheets['매매결과']
    money_columns1 = ['기준봉종가', 'R1값', '1차매수가', '청산가', '총투입금(원)', '수익금(원)']
    for idx, col in enumerate(res_df.columns):
        series = res_df[col]
        max_len = max(series.astype(str).map(len).max(), len(str(col))) + 3
        if col in money_columns1:
            worksheet1.set_column(idx, idx, max_len, money_format)
        else:
            worksheet1.set_column(idx, idx, max_len)

    # 시트2 포맷팅
    worksheet2 = writer.sheets['일별 자금현황']
    money_columns2 = ['당일 변동금액', '누적 묶인돈(원)']
    for idx, col in enumerate(capital_df.columns):
        series = capital_df[col]
        max_len = max(series.astype(str).map(len).max(), len(str(col))) + 5
        if col in money_columns2:
            worksheet2.set_column(idx, idx, max_len, money_format)
        else:
            worksheet2.set_column(idx, idx, max_len)

    # 시트3 포맷팅
    worksheet3 = writer.sheets['요약 통계']
    for idx, col in enumerate(summary_df.columns):
        series = summary_df[col]
        max_len = max(series.astype(str).map(len).max(), len(str(col))) + 5
        worksheet3.set_column(idx, idx, max_len)

    writer.close()
    print("백테스트 완료: 매매결과, 자금현황, 통계요약이 포함된 엑셀 파일이 저장되었습니다.")


if __name__ == "__main__":
    run_backtest('Stock_data.db', '마스터캔들 관심종목.csv')