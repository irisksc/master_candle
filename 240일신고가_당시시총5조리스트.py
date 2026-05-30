import sqlite3
import pandas as pd
from pykrx import stock
from datetime import datetime, timedelta
import time
# 엑셀 서식 제어를 위한 openpyxl 모듈
from openpyxl.utils import get_column_letter


def get_high_stocks_from_db(db_path):
    # (이전과 동일한 DB 조회 로직)
    conn = sqlite3.connect(db_path)
    query = """
            WITH RankedPrices AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY code ORDER BY weekly_start_date DESC) as rn \
                                  FROM weekly_prices),
                 Last52Weeks AS (SELECT * \
                                 FROM RankedPrices \
                                 WHERE rn <= 52),
                 MaxHighPerCode AS (SELECT code, name, MAX(high) as max_high \
                                    FROM Last52Weeks \
                                    GROUP BY code)
            SELECT m.code, m.name, m.max_high, l.weekly_start_date
            FROM MaxHighPerCode m
                     JOIN Last52Weeks l ON m.code = l.code AND m.max_high = l.high
            GROUP BY m.code; \
            """
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df


def filter_and_save_to_excel():
    db_path = "롱텐주봉데이터.db"
    df_candidates = get_high_stocks_from_db(db_path)
    print(f"▶ 1차 DB 추출 (52주 신고가): {len(df_candidates)}개 종목\n")

    final_results = []

    print("▶ pykrx 과거 시가총액 검증 시작 (5조 원 이상 필터링)...")
    for idx, row in df_candidates.iterrows():
        code = row['code']
        name = row['name']
        start_date_str = str(row['weekly_start_date']).replace("-", "").replace(".", "")[:8]

        try:
            start_dt = datetime.strptime(start_date_str, "%Y%m%d")
            end_dt = start_dt + timedelta(days=6)
            end_date_str = end_dt.strftime("%Y%m%d")

            df_cap = stock.get_market_cap(start_date_str, end_date_str, code)

            if df_cap.empty:
                continue

            max_market_cap = df_cap['시가총액'].max()

            if max_market_cap >= 5_000_000_000_000:
                # 요청하신 3가지 항목(날짜, 종목명, 시총(조))에 맞춰 데이터 구성
                final_results.append({
                    "날짜": start_dt.strftime("%Y-%m-%d"),
                    "종목명": name,
                    "시총(조)": round(max_market_cap / 1_000_000_000_000, 2)
                })
                print(f"[매칭 완료] {name} - 시총: {max_market_cap / 1_000_000_000_000:.2f}조 원")

            time.sleep(0.3)

        except Exception as e:
            continue

    df_final = pd.DataFrame(final_results)

    if not df_final.empty:
        # 시가총액 기준 내림차순 정렬
        df_final = df_final.sort_values(by="시총(조)", ascending=False).reset_index(drop=True)

        # 엑셀 파일 저장 및 가독성(셀 너비) 조정 로직
        excel_filename = "52주신고가_시총5조이상.xlsx"

        with pd.ExcelWriter(excel_filename, engine='openpyxl') as writer:
            df_final.to_excel(writer, index=False, sheet_name='신고가종목')
            worksheet = writer.sheets['신고가종목']

            # 각 열의 데이터 길이를 계산하여 셀 너비 자동 조절
            for col_idx, col_cells in enumerate(worksheet.columns, start=1):
                max_length = 0
                column_letter = get_column_letter(col_idx)

                for cell in col_cells:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass

                # 한글/영문 차이와 여백을 고려하여 너비 설정 (+5 여백)
                adjusted_width = (max_length + 5)
                worksheet.column_dimensions[column_letter].width = adjusted_width

        print(f"\n✅ 엑셀 파일 저장 완료: {excel_filename} (가독성 셀 크기 조정 적용)")
    else:
        print("\n조건을 만족하는 종목이 없습니다.")


if __name__ == "__main__":
    filter_and_save_to_excel()