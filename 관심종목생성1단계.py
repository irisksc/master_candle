# 15% 상승 , 2천억 거래대금만족하는 종목

import sqlite3
import pandas as pd


def extract_criteria_stocks(db_path):
    conn = sqlite3.connect(db_path)

    # SQL 쿼리 구성
    # 1. 거래대금 2천억(2000억 * 1억) 이상
    # 2. (종가-시가)/시가 * 100 >= 15
    # 3. KOSPI, KOSDAQ만 포함
    query = """
    SELECT 
        d.date,
        s.name,
        d.code,
        d.close,
        (d.trading_value / 100000000) AS trading_value_billion
    FROM daily_prices d
    JOIN stocks s ON d.code = s.code
    WHERE d.trading_value >= 200000000000
      AND ((CAST(d.close AS REAL) - d.open) / d.open * 100) >= 15
      AND s.market IN ('KOSPI', 'KOSDAQ')
    ORDER BY d.date DESC;
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    # 파일 저장
    if not df.empty:
        df.to_csv('15프로2천억원.csv', index=False, encoding='utf-8-sig')
        print(f"총 {len(df)}건의 데이터를 '15프로2천억원.csv'로 저장했습니다.")
    else:
        print("조건을 만족하는 데이터가 없습니다.")


# 실행
extract_criteria_stocks('Stock_data.db')