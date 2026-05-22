import sqlite3
import pandas as pd
import os

# 1. DB 파일 경로 지정 (절대 경로)
db_path = r"C:\work1\stock_data.db"


def verify_database():
    # 파일 존재 여부 확인
    if not os.path.exists(db_path):
        print(f"에러: 해당 경로에 DB 파일이 없습니다. 경로를 확인하세요: {db_path}")
        return

    try:
        conn = sqlite3.connect(db_path)

        # 2. 테이블 목록 조회
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]

        if not tables:
            print("에러: DB 파일은 존재하지만, 내부에 저장된 테이블이 하나도 없습니다.")
            print("힌트: collector.py에서 INSERT 후 conn.commit()을 호출했는지 확인하세요.")
        else:
            print(f"성공: {len(tables)}개의 테이블이 확인되었습니다.")

            # 각 테이블별 데이터 검증
            for table_name in tables:
                print(f"\n--- 테이블: {table_name} 검증 ---")
                count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                print(f"전체 레코드 개수: {count}개")

                # 데이터 상위 조회
                df = pd.read_sql(f"SELECT * FROM {table_name} LIMIT 5", conn)
                print("[샘플 데이터 5개]")
                print(df)

        conn.close()

    except Exception as e:
        print(f"데이터베이스 연결 중 오류 발생: {e}")


if __name__ == "__main__":
    verify_database()