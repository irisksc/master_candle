import sys
import time
import pandas as pd
from PyQt5.QtWidgets import QApplication
from pykiwoom.kiwoom import Kiwoom


class MasterCandleScanner:
    def __init__(self):
        # 1. PyQt 이벤트 루프 초기화 (키움 API 구동 필수 환경)
        self.app = QApplication.instance()
        if not self.app:
            self.app = QApplication(sys.argv)

        # 2. 키움 객체 생성 및 로그인 완료 대기
        self.kiwoom = Kiwoom()
        self.kiwoom.CommConnect(block=True)

        print("\n" + "=" * 60)
        print("🚀 마스터 캔들 스크리닝 시스템 가동 준비 완료")
        print("=" * 60)

        # 3. [안전장치] 키움 서버 종목 데이터 로딩 대기 시간 부여
        print("▶ 서버 안정화를 위해 3초 대기합니다...")
        time.sleep(3)

    def get_clean_market_codes(self):
        """
        [필터 1] 코스피/코스닥 전 종목 중 환기, 관리, 거래정지 종목 원천 차단
        """
        print("\n▶ [STEP 1] 시장 전 종목 리스트 수신 및 불량 종목 필터링 시작...")
        kospi = self.kiwoom.GetCodeListByMarket('0')
        kosdaq = self.kiwoom.GetCodeListByMarket('10')
        all_codes = kospi + kosdaq

        clean_codes = []
        for code in all_codes:
            if not code or len(code) < 6: continue

            # [오타 수정 완료] GetMasterConnectState -> GetMasterStockState
            state = self.kiwoom.ocx.dynamicCall("GetMasterStockState(QString)", code)

            # 안전코드: 키움 서버가 순간적으로 무응답일 때의 크래시 방지
            if state is None: continue
            state = str(state).strip()

            # 환기, 관리, 정지 종목 제외
            if "환기" in state or "관리" in state or "정지" in state:
                continue

            clean_codes.append(code)

        print(f"▶ [완료] 전체 {len(all_codes)}개 종목 중 정상 종목 {len(clean_codes)}개 압축 성공.")
        return clean_codes

    def scan_a_class_master_candle(self):
        """
        [필터 2 & 3] 기준봉 탐색 및 역주행 필터링 메인 로직
        """
        target_codes = self.get_clean_market_codes()
        final_watch_pool = {}

        print("\n▶ [STEP 2] A급 마스터 캔들 조건 및 타점 정밀 분석 시작...")

        # 💡 [안정성 테스트 팁] 처음 구동 시 속도를 확인하고 싶다면 아래 주석을 해제하여 100개만 먼저 돌려보세요.
        target_codes = target_codes[:100]

        for idx, code in enumerate(target_codes):
            name = self.kiwoom.GetMasterCodeName(code)

            # 키움 API 조회 제한(초당 5회) 회피용 딜레이
            time.sleep(0.25)

            # 1. 일봉 데이터 조회 (opt10081)
            try:
                df = self.kiwoom.block_request("opt10081",
                                               종목코드=code,
                                               기준일자="",
                                               수정주가구분=1,
                                               output="주식일봉차트조회",
                                               next=0)
            except Exception:
                continue

            if df is None or df.empty or len(df) < 240:
                continue

                # 2. 데이터 타입 정제 (부호 제거 및 숫자로 변환)
            try:
                df['종가'] = df['현재가'].astype(str).str.replace('+', '').str.replace('-', '').astype(int)
                df['시가'] = df['시가'].astype(str).str.replace('+', '').str.replace('-', '').astype(int)
                df['고가'] = df['고가'].astype(str).str.replace('+', '').str.replace('-', '').astype(int)
                df['저가'] = df['저가'].astype(str).str.replace('+', '').str.replace('-', '').astype(int)
                df['거래대금'] = df['거래대금'].astype(int) * 1000
            except Exception:
                continue

            # 과거(위) -> 최신(아래) 순으로 정렬
            df = df.iloc[::-1].reset_index(drop=True)

            # 3. 최신 기준봉 우선 탐색 (오늘부터 역순으로 5일 전까지 거꾸로 검사)
            for i in range(len(df) - 1, len(df) - 6, -1):
                if i < 240: continue

                row = df.iloc[i]
                close_val = row['종가']
                open_val = row['시가']
                money = row['거래대금']

                # [기준봉 조건 검증]
                # 조건 A: 순수 몸통 15% 이상 상승
                body_ratio = ((close_val - open_val) / open_val) * 100
                if body_ratio < 15: continue

                # 조건 B: 당일 거래대금 2천억 이상
                if money < 200000000000: continue

                # 조건 C: 240일 신고가 경신
                past_240_max = df.iloc[i - 240:i]['종가'].max()
                if close_val <= past_240_max: continue

                # [A급 주도주 조건 검증]
                # 조건 D: 기준봉 당일 포함 과거 40거래일 이내 1천억 이상 일봉 6개 이상
                start_idx = max(0, i - 39)
                sub_df = df.iloc[start_idx:i + 1]
                thousand_block_count = len(sub_df[sub_df['거래대금'] >= 100000000000])

                if thousand_block_count >= 6:
                    # 타점 가격(R0 ~ R4) 세팅
                    r0 = close_val
                    body_length = close_val - open_val
                    r1 = int(open_val + (body_length * 0.75))
                    r2 = int(open_val + (body_length * 0.50))
                    r3 = int(open_val + (body_length * 0.25))
                    r4 = open_val

                    # -------------------------------------------------------------------
                    # 핵심 역주행 방어선: 기준봉 이후 종가가 R1 밑으로 이탈한 이력이 있으면 아웃
                    # -------------------------------------------------------------------
                    is_valid = True
                    after_candles = df.iloc[i + 1:]

                    for _, after_row in after_candles.iterrows():
                        if after_row['종가'] < r1:
                            is_valid = False
                            break

                    if not is_valid:
                        break  # 이미 매물대가 깨진 역주행 종목이므로 무시하고 다음 종목 탐색
                    # -------------------------------------------------------------------

                    # 최종 통과된 종목만 관심 풀(Pool)에 등록
                    days_passed = len(df) - 1 - i
                    final_watch_pool[code] = {
                        "종목명": name,
                        "기준일자": row['일자'],
                        "경과일": f"{days_passed}일전",
                        "천억봉": thousand_block_count,
                        "R0(상단)": r0,
                        "R1(타점)": r1,
                        "R2(중심)": r2,
                        "R3(하단)": r3,
                        "R4(시가)": r4
                    }
                    print(f"🔥 [A급 포착] {name}({code}) | {row['일자']} 기준 | 40일내 천억봉: {thousand_block_count}개")
                    break

                    # 진행 상태 모니터링 (100개 단위 출력)
            if idx % 100 == 0 and idx > 0:
                print(f"   > 현재 {idx}개 종목 차트 스캔 완료...")

        return final_watch_pool


if __name__ == "__main__":
    scanner = MasterCandleScanner()
    result_pool = scanner.scan_a_class_master_candle()

    print("\n" + "=" * 80)
    print("🎯 [최종 결과] 오늘 장중 감시 대상 A급 마스터 캔들 포트폴리오")
    print("=" * 80)

    if result_pool:
        result_df = pd.DataFrame(result_pool).T
        print(result_df[['종목명', '기준일자', '경과일', '천억봉', 'R0(상단)', 'R1(타점)', 'R2(중심)', 'R4(시가)']].to_string())
    else:
        print("⚠️ 조건을 완벽히 만족하는 A급 마스터 캔들 종목이 현재 시장에 없습니다.")
    print("=" * 80)