import pandas as pd
import os


def merge_and_append_sheet(verif_file, backtest_file, new_sheet_name='매칭결과_누적'):
    print("1. 데이터 불러오는 중...")
    df_verif = pd.read_excel(verif_file, sheet_name='리스트')
    df_back = pd.read_excel(backtest_file, sheet_name='매수일별정렬')

    print("2. 날짜 및 매칭 기준 정제 중...")
    df_back['1차매수일_dt'] = pd.to_datetime(df_back['1차매수일'], errors='coerce')
    df_back['연도'] = df_back['1차매수일_dt'].dt.year
    df_back['월'] = df_back['1차매수일_dt'].dt.month

    if '결과' not in df_back.columns:
        print("오류: 백테스팅 파일에 '결과' 컬럼이 존재하지 않습니다.")
        return

    res_idx = df_back.columns.get_loc('결과')
    target_columns = ['연도', '월', '종목명'] + list(df_back.columns[res_idx:-2])
    df_back_subset = df_back[target_columns].copy()

    print("3. 데이터 병합 (동일 월/종목 중복 시 자동으로 행 추가 누적)...")

    # --- 수정된 부분: '연도'와 '월'에서 텍스트 제거 및 4자리 연도 통일 ---
    # 1. '연도' 컬럼에서 숫자가 아닌 문자(년, 공백 등)를 모두 지우고 정수로 변환
    df_verif['연도'] = df_verif['연도'].astype(str).str.replace(r'\D', '', regex=True)
    df_verif['연도'] = pd.to_numeric(df_verif['연도'], errors='coerce').fillna(0).astype(int)

    # 2. 연도가 100보다 작으면(예: 15, 23 등) 2000을 더해 4자리 연도(2015, 2023)로 변환
    df_verif['연도'] = df_verif['연도'].apply(lambda x: x + 2000 if 0 < x < 100 else x)

    # 3. '월' 컬럼에서도 '5월' 같은 텍스트가 있을 것을 대비해 동일하게 숫자만 추출
    df_verif['월'] = df_verif['월'].astype(str).str.replace(r'\D', '', regex=True)
    df_verif['월'] = pd.to_numeric(df_verif['월'], errors='coerce').fillna(0).astype(int)
    # --------------------------------------------------------------------

    df_back_subset['연도'] = df_back_subset['연도'].fillna(0).astype(int)
    df_back_subset['월'] = df_back_subset['월'].fillna(0).astype(int)

    df_result = pd.merge(df_verif, df_back_subset, on=['연도', '월', '종목명'], how='left')

    print(f"4. '{verif_file}' 파일에 '{new_sheet_name}' 시트로 저장 중...")
    with pd.ExcelWriter(verif_file, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
        df_result.to_excel(writer, sheet_name=new_sheet_name, index=False)

    print(f"작업 완료! 파일 확인을 부탁드립니다.")


# 실행 (현재 사용 중인 파일명으로 맞췄습니다)
merge_and_append_sheet('롱텐1차검증.xlsx', '롱텐_종합백테스팅_최종결과.xlsx', '매칭결과_누적')