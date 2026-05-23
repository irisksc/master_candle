import sqlite3
import pandas as pd


def extract_master_candle_stocks(db_path):
    conn = sqlite3.connect(db_path)

    # SQL 쿼리 로직
    # 1. BaseData: 각 종목별/날짜별 데이터에 윈도우 함수 적용
    # 2. 신고가: 당일 고가가 과거 240거래일(당일 제외) 최고가보다 큼
    # 3. 거래대금 조건: 과거 40거래일 중 1,000억 이상인 날이 6일 이상
    query = """
    WITH BaseData AS (
        SELECT 
            d.date, d.code, s.name, d.open, d.high, d.close, d.trading_value,
            MAX(d.high) OVER (PARTITION BY d.code ORDER BY d.date ROWS BETWEEN 240 PRECEDING AND 1 PRECEDING) as prev_240_max,
            COUNT(*) FILTER (WHERE d.trading_value >= 100000000000) OVER (PARTITION BY d.code ORDER BY d.date ROWS BETWEEN 40 PRECEDING AND 1 PRECEDING) as count_40_1000b
        FROM daily_prices d
        JOIN stocks s ON d.code = s.code
        WHERE s.market IN ('KOSPI', 'KOSDAQ')
    )
    SELECT 
        date, 
        name, 
        code, 
        close, 
        (trading_value / 100000000) as trading_value_billion
    FROM BaseData
    WHERE trading_value >= 200000000000
      AND ((CAST(close AS REAL) - open) / open * 100) >= 15
      AND high > prev_240_max
      AND count_40_1000b >= 6
    ORDER BY date DESC;
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    # 파일 저장
    if not df.empty:
        filename = "마스터캔들 관심종목.csv"
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"총 {len(df)}건의 데이터를 '{filename}'으로 저장했습니다.")
    else:
        print("조건을 모두 만족하는 종목이 없습니다.")


# 실행
extract_master_candle_stocks('Stock_data.db')