import sqlite3
import pandas as pd
import os


def run_friday_close_backtest():
    current_dir = os.path.dirname(os.path.abspath('%s' % __file__)) if '__file__' in locals() else os.getcwd()
    csv_path = os.path.join(current_dir, '롱텐관심종목(10년).csv')
    db_path = os.path.join(current_dir, '롱텐주봉데이터.db')

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"'{csv_path}' 파일이 없습니다.")

    target_name = input("테스트할 종목명을 입력하세요 (예: 삼성전자): ").strip()

    signal_df = pd.read_csv(csv_path)
    signal_df['날짜'] = pd.to_datetime(signal_df['날짜'])
    df_signals = signal_df[signal_df['종목명'] == target_name].sort_values(by='날짜')

    if df_signals.empty:
        print(f"\n[안내] '{target_name}' 종목은 신호가 존재하지 않습니다.")
        return

    target_code = str(df_signals['종목코드'].iloc[0]).zfill(6)

    print(f"\n" + "=" * 75)
    print(f"▶ [{target_name} ({target_code})] 롱텐 엔젤백테스팅 (금요일 오후 종가 추매 버전)")
    print("=" * 75)

    conn = sqlite3.connect(db_path)
    df_prices = pd.read_sql(
        f"SELECT weekly_start_date, open, high, low, close FROM weekly_prices WHERE code='{target_code}' ORDER BY weekly_start_date ASC",
        conn
    )
    conn.close()

    df_prices['weekly_start_date'] = pd.to_datetime(df_prices['weekly_start_date'])
    df_prices.set_index('weekly_start_date', inplace=True)

    df_prices['MA10'] = df_prices['close'].rolling(window=10).mean()
    df_prices['env_low'] = df_prices['MA10'] * 0.90

    is_holding = False
    has_averaged_down = False
    base_price = 0
    total_cash = 0
    total_qty = 0
    buy_stage = 0

    total_entries = 0
    clean_exits = 0
    env_profit_exits = 0
    env_loss_exits = 0

    for current_date, price_row in df_prices.iterrows():
        date_str = current_date.strftime('%Y-%m-%d')

        # --- CASE 1: 무포지션 상태 ---
        if not is_holding:
            if current_date in df_signals['날짜'].values:
                total_entries += 1
                base_price = price_row['close']
                total_cash = 10_000_000
                total_qty = total_cash / base_price
                buy_stage = 0
                has_averaged_down = False
                is_holding = True
                print(f"\n[{date_str}] ★ [{total_entries}회차] 롱텐 기준봉 신규 진입 -> 진입가: {base_price:,}원")
            continue

        # --- CASE 2: 보유 중인 상태 ---
        if is_holding:
            high_p = price_row['high']
            curr_close = price_row['close']
            env_low_p = price_row['env_low']

            avg_price = total_cash / total_qty
            triggered_action = False

            # ① 장중(월~금) 본절 청산 감시 (우선순위 1 - 보유 평단가 기준 탈출)
            # 추매 이력이 있고, 이번 주 고가가 평단가에 닿았다면 장중에 탈출한 것으로 간주
            if has_averaged_down and high_p >= avg_price:
                print(
                    f"[{date_str}] ♣ [본절 청산] 장중 고가({high_p:,}원)가 평단가({int(avg_price):,}원) 터치! (투자금 {total_cash:,}원 회수)")
                is_holding, has_averaged_down = False, False
                base_price, total_cash, total_qty, buy_stage = 0, 0, 0, 0
                clean_exits += 1
                continue  # 당주 청산 완료했으므로 금요일 오후 추매 확인 패스

            # ② 금요일 오후(종가 마감) 엔젤 추매 감시 (우선순위 2)
            # [핵심] low_p(저가) 대신 curr_close(종가)로만 체결 판단. (연쇄 체결 가능하도록 순차 if문 구성)
            if buy_stage == 0 and curr_close <= base_price * 0.90:
                total_qty += (10_000_000 * 1.5) / (base_price * 0.90)
                total_cash += (10_000_000 * 1.5)
                buy_stage, has_averaged_down, triggered_action = 1, True, True
                print(f"[{date_str}]  └─ [추매 1차 체결] 금요일 종가({curr_close:,}원) 기준 -10% 도달!")

            if buy_stage == 1 and curr_close <= base_price * 0.80:
                total_qty += (10_000_000 * 2.0) / (base_price * 0.80)
                total_cash += (10_000_000 * 2.0)
                buy_stage, has_averaged_down, triggered_action = 2, True, True
                print(f"[{date_str}]  └─ [추매 2차 체결] 금요일 종가({curr_close:,}원) 기준 -20% 도달!")

            if buy_stage == 2 and curr_close <= base_price * 0.70:
                total_qty += (10_000_000 * 2.5) / (base_price * 0.70)
                total_cash += (10_000_000 * 2.5)
                buy_stage, has_averaged_down, triggered_action = 3, True, True
                print(f"[{date_str}]  └─ [추매 3차 체결] 금요일 종가({curr_close:,}원) 기준 -30% 도달!")

            if buy_stage == 3 and curr_close <= base_price * 0.60:
                total_qty += (10_000_000 * 3.0) / (base_price * 0.60)
                total_cash += (10_000_000 * 3.0)
                buy_stage, has_averaged_down, triggered_action = 4, True, True
                print(f"[{date_str}]  └─ [추매 4차 체결] 금요일 종가({curr_close:,}원) 기준 -40% 도달!")

            # 새로 갱신된 평단가 (금요일 오후 기준)
            if triggered_action:
                avg_price = total_cash / total_qty

            # ③ 금요일 오후(종가 마감) 엔벨로프 청산 감시 (우선순위 3)
            # 당주에 추매가 일어나지 않았고(미추매 상태 유지), 종가가 하한선을 이탈했을 때만 발동
            if not has_averaged_down and not triggered_action and pd.notna(env_low_p):
                if curr_close < env_low_p:
                    return_pct = ((curr_close - base_price) / base_price) * 100
                    if curr_close >= base_price:
                        print(f"[{date_str}] 🍊 [엔벨 익절] 종가({curr_close:,}원)가 하한선 이탈! (수익률: +{return_pct:.2f}%)")
                        env_profit_exits += 1
                    else:
                        print(f"[{date_str}] ⚡ [엔벨 손절] 종가({curr_close:,}원)가 하한선 이탈! (수익률: {return_pct:.2f}%)")
                        env_loss_exits += 1

                    is_holding, has_averaged_down = False, False
                    base_price, total_cash, total_qty, buy_stage = 0, 0, 0, 0
                    continue

            # 일반 보유 로그 (아무 일도 없었을 때)
            if not triggered_action:
                current_yield = ((curr_close - avg_price) / avg_price) * 100
                status_str = f"추매 {buy_stage}차 완료(대기)" if has_averaged_down else "미추매(엔벨감시)"
                print(
                    f"[{date_str}]    (보유중) 종가: {curr_close:,}원 | 평단: {int(avg_price):,}원 | 수익률: {current_yield:.2f}% | {status_str}")

    # 최종 요약 리포트
    print("\n" + "=" * 75)
    print(f"■■■ [{target_name}] 10년 종합 성적표 (마감 종가 추매 기준) ■■■")
    print(f" - 총 매매 진입(회차) 횟수     : {total_entries}회")
    print(f" - [1] 추매 후 본절 탈출 성공  : {clean_exits}회")
    print(f" - [2] 미추매 상태 엔벨로프 익절: {env_profit_exits}회")
    print(f" - [3] 미추매 상태 엔벨로프 손절: {env_loss_exits}회")
    if is_holding:
        print(f" - 현재 상태                    : {total_entries}회차 매매 포지션 미청산 (보유 중)")
    print("=" * 75)


if __name__ == "__main__":
    run_friday_close_backtest()