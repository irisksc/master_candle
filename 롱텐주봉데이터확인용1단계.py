#주봉데이터 변환 완료 10년치

import sqlite3


def get_stock_data(db_file, code, target_date):
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()

        # 테이블명: weekly_prices, 날짜 컬럼명: weekly_start_date로 수정
        query = "SELECT * FROM weekly_prices WHERE code = ? AND weekly_start_date = ?"
        cursor.execute(query, (code, target_date))

        row = cursor.fetchone()

        if row:
            # 컬럼 정보를 바탕으로 결과 출력
            print(f"\n--- [조회 결과] ---")
            print(f"종목코드: {row[1]} | 종목명: {row[2]}")
            print(f"날짜: {row[0]}")
            print(f"시가: {row[3]} | 고가: {row[4]} | 저가: {row[5]} | 종가: {row[6]}")
            print(f"거래대금: {row[7]}")
        else:
            print("해당 조건에 맞는 데이터를 찾을 수 없습니다.")

    except sqlite3.Error as e:
        print(f"DB 오류 발생: {e}")
    finally:
        conn.close()


# 사용 예시
db_path = '롱텐주봉데이터.db'
input_code = input("종목코드를 입력하세요: ")
input_date = input("날짜를 입력하세요 (YYYY-MM-DD): ")

get_stock_data(db_path, input_code, input_date)