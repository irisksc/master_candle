import os
import sqlite3
import pandas as pd

# ==========================================
# [설정 항목] 파일 경로 정의
# ==========================================
CSV_INPUT_PATH = "15프로2천억원.csv"
CSV_OUTPUT_PATH = "까리존345후보종목.csv"
DB_PATH = "stock_data.db"


def detect_db_date_format(conn):
    """DB에서 샘플 데이터를 읽어 날짜 포맷에 하이픈(-)이 있는지 자동으로 감지합니다."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT date FROM daily_prices LIMIT 1")
        row = cursor.fetchone()
        if row and row[0]:
            db_date_sample = str(row[0])
            if "-" in db_date_sample:
                print(f"[시스템 감지] DB 날짜 규격: 하이픈 포함 형태 (예: {db_date_sample})")
                return "HYPHEN"
            else:
                print(f"[시스템 감지] DB 날짜 규격: 하이픈 없는 형태 (예: {db_date_sample})")
                return "RAW"
    except Exception as e:
        print(f"[경고] DB 날짜 포맷 감지 중 오류 발생(기본값 하이픈 규격 적용): {e}")
    return "HYPHEN"


def preprocess_csv(path, date_format_type):
    """CSV 파일을 로드하고 감지된 DB 규격에 맞춰 날짜와 종목코드를 정규화합니다."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"입력 파일이 존재하지 않습니다: {path}")

    # CSV 로드 (숫자 깨짐 방지를 위해 일단 문자로 읽음)
    df = pd.read_csv(path, dtype={"code": str, "date": str})

    # 1. 종목코드 6자리 패딩 (예: 1820 -> 001820)
    df["code"] = df["code"].str.zfill(6)

    # 2. 날짜 포맷 동적 변환
    def convert_date(x):
        x = str(x).replace("-", "").strip()  # 먼저 모든 하이픈 제거 후 순수 숫자만 추출
        if len(x) == 8:
            if date_format_type == "HYPHEN":
                return f"{x[:4]}-{x[4:6]}-{x[6:8]}"  # YYYY-MM-DD
            else:
                return x  # YYYYMMDD
        return x

    df["date"] = df["date"].apply(convert_date)
    return df


def check_new_high_and_calc_return(conn, code, target_date):
    """
    DB를 조회하여 고가 기준 240일 신고가(신규상장주 예외 포함) 여부를 판정하고,
    시가 대비 종가 상승률을 계산합니다.
    """
    cursor = conn.cursor()

    # 대상 날짜를 포함하여 과거 데이터들을 역순으로 호출 (최대 240개)
    query = """
            SELECT date, open, high, low, close
            FROM daily_prices
            WHERE code = ? AND date <= ?
            ORDER BY date DESC
                LIMIT 240 \
            """
    cursor.execute(query, (code, target_date))
    rows = cursor.fetchall()

    # [디버깅 로그 1] DB에 해당 날짜 및 종목 데이터 자체가 없는 경우
    if not rows:
        return False, 0.0, "N", "DB 데이터 부재(매칭 실패)"

    # [디버깅 로그 2] 가져온 가장 최신 데이터가 조회 요청한 날짜와 매칭되지 않는 경우
    if rows[0][0] != target_date:
        return False, 0.0, "N", f"날짜 불일치(가장 가까운 날짜: {rows[0][0]})"

    # 당일 데이터 추출
    _, t_open, t_high, _, t_close = rows[0]

    # 데이터 개수 파악 (상장 기간 및 신규상장주 여부 판별)
    available_days = len(rows)
    is_new_listing = "Y" if available_days < 240 else "N"

    # 고가 기준 최고가(신고가) 검증 (rows 안의 모든 high 중 최고치 탐색)
    max_high_in_period = max(row[2] for row in rows)

    # 당일 고가가 해당 기간 최고가와 같다면 신고가 달성으로 판정
    if t_high >= max_high_in_period:
        # 시가 대비 종가 상승률 계산 (소수점 둘째자리 반올림)
        if t_open > 0:
            daily_return_pct = round(((t_close - t_open) / t_open) * 100, 2)
        else:
            daily_return_pct = 0.0

        return True, daily_return_pct, is_new_listing, "조건 만족"

    # [디버깅 로그 3] 데이터는 있으나 고가 기준 240일 최고가를 깨지 못한 경우
    return False, 0.0, "N", f"신고가 미달 (당일고가: {t_high} / 기간최고가: {max_high_in_period})"


def main():
    print("[시스템] '까리존 345 후보 종목 추출 프로세스 v2'를 시작합니다.")

    # 1. DB 연결 및 날짜 포맷 자동 감지
    if not os.path.exists(DB_PATH):
        print(f"[오류] 데이터베이스 파일({DB_PATH})을 찾을 수 없습니다.")
        return
    conn = sqlite3.connect(DB_PATH)

    date_format_type = detect_db_date_format(conn)

    # 2. 데이터 전처리 (감지된 규격 반영)
    try:
        df_input = preprocess_csv(CSV_INPUT_PATH, date_format_type)
        print(f"[안내] 원본 파일 로드 완료. 총 {len(df_input)}개의 이벤트를 검증합니다.")
    except Exception as e:
        print(f"[오류] CSV 파일 처리 중 실패: {e}")
        conn.close()
        return

    candidates = []
    total_count = len(df_input)

    print("-" * 95)
    print("  진행률  |   종목명 (코드)   |    날짜    | 결과 및 탈락 원인 추적")
    print("-" * 95)

    # 3. 루프를 돌며 실시간 필터링 및 진행 상황 출력
    for idx, row in df_input.iterrows():
        code = row["code"]
        date = row["date"]
        name = row["name"]
        trading_value_billion = row["trading_value_billion"]

        # 조건 검증 함수 호출 (탈락 사유인 reason 추가 수령)
        is_qualified, daily_return, is_new_listing, reason = check_new_high_and_calc_return(conn, code, date)

        progress_pct = ((idx + 1) / total_count) * 100

        if is_qualified:
            status_msg = "★ 관종 합류"
            if is_new_listing == "Y":
                status_msg += " (신규상장주)"
            print(f"[{progress_pct:5.1f}%] | {name[:7]:<7}({code}) | {date} | {status_msg} (시가대비 {daily_return}%)")

            # 후보 목록에 저장할 데이터 구성
            candidates.append({
                "date": date,
                "name": name,
                "code": code,
                "close": row["close"],
                "trading_value_billion": trading_value_billion,
                "daily_return_pct": f"{daily_return}%",
                "is_new_listing": is_new_listing
            })
        else:
            # 실시간 탈락 원인을 보고 싶거나 상위 일부 종목에서 매칭이 터지는지 콘솔로 즉각 확인
            # 매번 찍으면 너무 느려지므로 초기 10개 및 이후 300건마다 진행 상황과 함께 원인 표기
            if idx < 10 or (idx + 1) % 300 == 0:
                print(f"[{progress_pct:5.1f}%] | {name[:7]:<7}({code}) | {date} | 탈락: {reason}")

    # 4. 결과 저장 및 종료
    conn.close()
    print("-" * 95)

    if candidates:
        df_output = pd.DataFrame(candidates)
        df_output.to_csv(CSV_OUTPUT_PATH, index=False, encoding="utf-8-sig")
        print(f"[완료] 필터링이 최종 종료되었습니다.")
        print(f"[결과] 총 {len(df_output)}개의 정예 후보 종목이 '{CSV_OUTPUT_PATH}' 파일로 성공적으로 저장되었습니다.")
    else:
        print("[경고] 조건을 만족하는 후보 종목이 단 한 개도 없습니다.")
        print("[조치 제안] 상위 로그에서 'DB 데이터 부재'가 뜨는지 '신고가 미달'이 뜨는지 확인해 주세요.")


if __name__ == "__main__":
    main()