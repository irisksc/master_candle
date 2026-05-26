import sqlite3
import pandas as pd
import os
from tqdm import tqdm  # 진행률 표시 라이브러리


def extract_longten_stocks():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(current_dir, '롱텐주봉데이터.db')
    output_csv = os.path.join(current_dir, '롱텐관심종목(10년).csv')

    conn = sqlite3.connect(db_path)

    # 1. 고유 종목 코드 리스트 가져오기
    codes = pd.read_sql("SELECT DISTINCT code, name FROM weekly_prices", conn)

    results = []
    print(f"총 {len(codes)}개 종목에 대해 롱텐 기법 필터링을 시작합니다.")

    # [수정] tqdm을 사용하여 전체 루프 진행률 확인
    for _, row in tqdm(codes.iterrows(), total=len(codes), desc="종목 분석 중"):
        code, name = row['code'], row['name']

        # 종목별 데이터 로드
        df = pd.read_sql(
            f"SELECT * FROM weekly_prices WHERE code='{code}' ORDER BY weekly_start_date ASC",
            conn
        )

        if len(df) < 60:
            continue

        # [기술적 지표 계산]
        df['MA10'] = df['close'].rolling(window=10).mean()
        df['MA60'] = df['close'].rolling(window=60).mean()
        df['Max48w'] = df['high'].shift(1).rolling(window=48).max()

        # [조건 필터링]
        cond = (
                (df['trading_value'] >= 500_000_000_000) &
                (df['high'] > df['Max48w']) &
                (df['close'] > df['MA10']) &
                (df['close'] > df['MA60'])
        )

        filtered = df[cond]

        # [수정] 조건 만족 시점에 콘솔에 즉시 알림 출력
        if not filtered.empty:
            for _, f_row in filtered.iterrows():
                print(f"\n[발견!] 날짜: {f_row['weekly_start_date']} | 종목: {name}({code}) | 종가: {f_row['close']}")
                results.append({
                    '날짜': f_row['weekly_start_date'],
                    '종목코드': code,
                    '종목명': name,
                    '기준봉종가': f_row['close']
                })

    conn.close()

    # CSV 저장
    result_df = pd.DataFrame(results)
    result_df.to_csv(output_csv, index=False, encoding='utf-8-sig')
    print(f"\n분석 완료! 총 {len(result_df)}개의 신호가 발견되었습니다.")
    print(f"결과 파일: '{output_csv}'")


if __name__ == "__main__":
    extract_longten_stocks()