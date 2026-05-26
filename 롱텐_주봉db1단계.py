import sqlite3
import pandas as pd
from tqdm import tqdm
import os


def create_weekly_database():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    src_db_path = os.path.join(current_dir, 'stock_data.db')
    tgt_db_path = os.path.join(current_dir, '롱텐주봉데이터.db')

    # 1. 연결 및 타깃 DB 스키마 생성
    tgt_conn = sqlite3.connect(tgt_db_path)
    tgt_cur = tgt_conn.cursor()

    tgt_cur.execute("DROP TABLE IF EXISTS weekly_prices")
    tgt_cur.execute("""
                    CREATE TABLE weekly_prices
                    (
                        weekly_start_date TEXT,
                        code              TEXT,
                        name              TEXT,
                        open              INTEGER,
                        high              INTEGER,
                        low               INTEGER,
                        close             INTEGER,
                        trading_value     BIGINT,
                        PRIMARY KEY (weekly_start_date, code)
                    )
                    """)
    tgt_cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_weekly_search
                        ON weekly_prices (weekly_start_date, trading_value)
                    """)
    tgt_conn.commit()

    if not os.path.exists(src_db_path):
        raise FileNotFoundError(f"\n[오류] '{src_db_path}' 파일이 존재하지 않습니다.")

    # 2. 소스 DB 데이터 로드
    src_conn = sqlite3.connect(src_db_path)
    stocks_df = pd.read_sql_query("SELECT code, name FROM stocks", src_conn)

    print(f"총 {len(stocks_df)}개 종목의 주봉 변환을 시작합니다.")

    for idx, row in tqdm(stocks_df.iterrows(), total=len(stocks_df), desc="주봉 변환 중"):
        code = row['code']
        name = row['name']

        query = f"SELECT date, open, high, low, close, volume, trading_value FROM daily_prices WHERE code = '{code}'"
        daily_df = pd.read_sql_query(query, src_conn)

        if daily_df.empty:
            continue

        daily_df['date'] = pd.to_datetime(daily_df['date'].astype(str), format='%Y%m%d')
        daily_df.set_index('date', inplace=True)

        # 주 단위 집계 규칙
        resample_rules = {
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'trading_value': 'sum'
        }

        # 1차 주간 데이터 집계
        weekly_resampled = daily_df.resample('W').agg(resample_rules).dropna()

        if weekly_resampled.empty:
            continue

        # [해결 지점] 에러가 발생하던 apply 대신 인덱스 시리즈의 resample.min() 사용
        weekly_start_dates = daily_df.index.to_series().resample('W').min()
        weekly_resampled['weekly_start_date'] = weekly_start_dates

        # 문자열 포맷팅 및 종목 정보 추가
        weekly_resampled['weekly_start_date'] = pd.to_datetime(weekly_resampled['weekly_start_date']).dt.strftime(
            '%Y-%m-%d')
        weekly_resampled['code'] = code
        weekly_resampled['name'] = name

        # 순서 정렬
        weekly_df = weekly_resampled[
            ['weekly_start_date', 'code', 'name', 'open', 'high', 'low', 'close', 'trading_value']]

        # DB 적재
        weekly_df.to_sql('weekly_prices', tgt_conn, if_exists='append', index=False)

    src_conn.close()
    tgt_conn.close()
    print(f"\n주봉 데이터베이스 구축이 완료되었습니다: '{tgt_db_path}'")


if __name__ == "__main__":
    create_weekly_database()