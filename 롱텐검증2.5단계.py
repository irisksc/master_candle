import pandas as pd
import os


def merge_fuzzy_months(verif_file, backtest_file, new_sheet_name='매칭결과_3개월허용'):
    print("1. 데이터 불러오는 중...")
    df_verif = pd.read_excel(verif_file, sheet_name='리스트')
    df_back = pd.read_excel(backtest_file, sheet_name='매수일별정렬')

    print("2. 1차 검증 파일 데이터 정제 및 고유 인덱스 부여...")
    # 필터링 중 원본 행 유실을 막기 위한 식별자
    df_verif['원본인덱스'] = df_verif.index

    # 텍스트(년, 월 등) 제거 및 연도 4자리 통일
    df_verif['연도'] = df_verif['연도'].astype(str).str.replace(r'\D', '', regex=True)
    df_verif['연도'] = pd.to_numeric(df_verif['연도'], errors='coerce').fillna(0).astype(int)
    df_verif['연도'] = df_verif['연도'].apply(lambda x: x + 2000 if 0 < x < 100 else x)

    df_verif['월'] = df_verif['월'].astype(str).str.replace(r'\D', '', regex=True)
    df_verif['월'] = pd.to_numeric(df_verif['월'], errors='coerce').fillna(0).astype(int)

    # 이름 충돌 방지를 위해 컬럼명 임시 변경
    df_verif.rename(columns={'연도': '검증_연도', '월': '검증_월'}, inplace=True)

    print("3. 백테스팅 파일 데이터 정제 및 컬럼 추출...")
    df_back['1차매수일_dt'] = pd.to_datetime(df_back['1차매수일'], errors='coerce')
    df_back['백테스트_연도'] = df_back['1차매수일_dt'].dt.year.fillna(0).astype(int)
    df_back['백테스트_월'] = df_back['1차매수일_dt'].dt.month.fillna(0).astype(int)

    if '결과' not in df_back.columns:
        print("오류: 백테스팅 파일에 '결과' 컬럼이 존재하지 않습니다.")
        return

    res_idx = df_back.columns.get_loc('결과')
    dt_col_idx = df_back.columns.get_loc('1차매수일_dt')  # 새로 추가한 컬럼 전까지

    # 병합할 타겟 컬럼 리스트 (백테스트 연/월, 종목명 + 결과부터 끝까지)
    target_columns = ['백테스트_연도', '백테스트_월', '종목명'] + list(df_back.columns[res_idx:dt_col_idx])
    df_back_subset = df_back[target_columns].copy()

    print("4. 종목명 기준 병합 및 ±3개월 오차범위 필터링 중...")
    # 1단계: 종목명이 같은 것은 모두 연결 (동일 종목의 모든 매수 내역 전개)
    merged = pd.merge(df_verif, df_back_subset, on='종목명', how='left')

    # 2단계: 연도와 월을 환산하여 개월 수 차이 계산
    diff_months = (merged['백테스트_연도'] - merged['검증_연도']) * 12 + (merged['백테스트_월'] - merged['검증_월'])

    # 3단계: 오차가 ±3개월 이내이거나, 아예 백테스팅에 매칭되는 종목이 없는(NaN) 경우만 필터링
    valid_mask = (diff_months.abs() <= 3) | merged['백테스트_연도'].isna()
    filtered_merged = merged[valid_mask].copy()

    # 4단계: 종목명은 같지만 ±3개월 범위 밖에 있어서 삭제되어버린 원본 행 복구
    survived_idx = filtered_merged['원본인덱스'].unique()
    lost_rows = df_verif[~df_verif['원본인덱스'].isin(survived_idx)].copy()

    # 유효 데이터와 복구 데이터를 합치고 원래 엑셀에 있던 순서대로 정렬
    final_result = pd.concat([filtered_merged, lost_rows], ignore_index=True)
    final_result.sort_values(by=['원본인덱스', '백테스트_연도', '백테스트_월'], inplace=True)

    # 필요 없는 임시 계산용 열 삭제 및 원본 열 이름 복구
    final_result.drop(columns=['원본인덱스', '백테스트_연도', '백테스트_월'], inplace=True)
    final_result.rename(columns={'검증_연도': '연도', '검증_월': '월'}, inplace=True)

    print(f"5. '{verif_file}' 파일에 '{new_sheet_name}' 시트로 저장 중...")
    with pd.ExcelWriter(verif_file, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
        final_result.to_excel(writer, sheet_name=new_sheet_name, index=False)

    print("작업 완료! 엑셀 파일을 확인해 주세요.")


# 실행 (경로 및 파일명은 그대로 유지합니다)
merge_fuzzy_months('롱텐1차검증.xlsx', '롱텐_종합백테스팅_최종결과.xlsx', '매칭결과_3개월허용')