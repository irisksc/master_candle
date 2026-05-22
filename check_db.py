import sqlite3
import pandas as pd


def search_stock_price(db_path):
    print("=== 주가 및 거래대금 조회 시스템 ===")
    # 1. 사용자로부터 종목번호와 날짜 입력 받기
    stock_code = input("조회할 종목번호를 입력하세요 (예: 000120): ").strip()
    target_date = input("조회할 날짜를 입력하세요 (예: 20140303): ").strip()

    # 2. 데이터베이스 연결
    try:
        conn = sqlite3.connect(db_path)

        # 3. SQL 쿼리 작성 (동적 파라미터 바인딩)
        query = """
                SELECT
                    date AS '일자', open AS '시가', high AS '고가', low AS '저가', close AS '종가', volume AS '거래량', trading_value AS '거래대금'
                FROM daily_prices
                WHERE code = ? AND date = ?; \
                """

        # 4. 쿼리 실행 및 결과 가져오기
        df = pd.read_sql_query(query, conn, params=(stock_code, target_date))

        # 5. 결과 출력
        print("\n" + "=" * 60)
        if df.empty:
            print(f"[{stock_code}] 종목의 {target_date} 일자 데이터가 존재하지 않습니다.")
            print("👉 입력하신 종목코드와 날짜(휴장일 여부 등)를 다시 확인해 주세요.")
        else:
            print(f"■ 종목코드 [{stock_code}] - {target_date} 주가 정보 ■")

            # 가독성을 위해 천 단위 콤마(,) 포맷팅 적용
            formatted_df = df.copy()
            for col in ['시가', '고가', '저가', '종가', '거래량', '거래대금']:
                if col in formatted_df.columns:
                    formatted_df[col] = formatted_df[col].apply(lambda x: f"{x:,}")

            print(formatted_df.to_string(index=False))
        print("=" * 60 + "\n")

    except Exception as e:
        print("데이터 조회 중 오류가 발생했습니다:", e)
    finally:
        # 6. 자원 반환 및 연결 종료
        if 'conn' in locals():
            conn.close()


# 스크립트 실행
if __name__ == "__main__":
    db_file_path = 'stock_data.db'  # 데이터베이스 파일이 같은 폴더에 있어야 합니다.
    search_stock_price(db_file_path)