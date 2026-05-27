import sys
import time
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop


class KiwoomMasterCandleFullTracker:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.ocx = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
        self.ocx.OnEventConnect.connect(self.on_connect)
        self.ocx.OnReceiveTrData.connect(self.on_receive_tr_data)
        self.ocx.OnReceiveConditionVer.connect(self.on_receive_condition_ver)
        self.ocx.OnReceiveTrCondition.connect(self.on_receive_tr_condition)

        self.login_loop = None
        self.tr_loop = None
        self.condition_loop = None
        self.search_loop = None

        self.tr_data = []
        self.candidate_codes = []

        self.target_cond_name = "마스터캔들API스캔용"
        self.target_cond_idx = None

    def comm_connect(self):
        self.ocx.dynamicCall("CommConnect()")
        self.login_loop = QEventLoop()
        self.login_loop.exec_()

    def on_connect(self, err_code):
        print(f"로그인 상태: {err_code}")
        if self.login_loop: self.login_loop.exit()

    def load_condition_expressions(self):
        self.ocx.dynamicCall("GetConditionLoad()")
        self.condition_loop = QEventLoop()
        self.condition_loop.exec_()

    def on_receive_condition_ver(self, ret, msg):
        cond_list_str = self.ocx.dynamicCall("GetConditionNameList()")
        cond_list = cond_list_str.split(";")[:-1]
        for cond in cond_list:
            c_idx, c_name = cond.split("^")
            if c_name == self.target_cond_name:
                self.target_cond_idx = int(c_idx)
                print(f"▶ HTS 조건식 매핑 성공: {c_name} (Index: {c_idx})")
                break
        if self.condition_loop: self.condition_loop.exit()

    def get_hts_candidates(self):
        if self.target_cond_idx is None: return []
        self.ocx.dynamicCall("SendCondition(QString, QString, int, int)", "0150", self.target_cond_name,
                             self.target_cond_idx, 0)
        self.search_loop = QEventLoop()
        self.search_loop.exec_()
        return self.candidate_codes

    def on_receive_tr_condition(self, screen_no, code_list, cond_name, cond_idx, next_page):
        self.candidate_codes = code_list.split(";")[:-1] if code_list else []
        if self.search_loop: self.search_loop.exit()

    def request_candles_data(self, code):
        self.tr_data = []
        self.ocx.dynamicCall("SetInputValue(QString, QString)", "종목코드", code)
        self.ocx.dynamicCall("SetInputValue(QString, QString)", "기준일자", time.strftime("%Y%m%d"))
        self.ocx.dynamicCall("SetInputValue(QString, QString)", "수정주가구분", "1")
        self.tr_loop = QEventLoop()
        self.ocx.dynamicCall("CommRqData(QString, QString, int, QString)", "opt10081_req", "opt10081", 0, "0101")
        self.tr_loop.exec_()

    def on_receive_tr_data(self, screen_no, rq_name, tr_code, record_name, prev_next, *args):
        if rq_name == "opt10081_req":
            count = self.ocx.dynamicCall("GetRepeatCnt(QString, QString)", tr_code, rq_name)
            for i in range(min(count, 300)):
                date = self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", tr_code, rq_name, i,
                                            "일자").strip()
                open_p = abs(
                    int(self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", tr_code, rq_name, i,
                                             "시가").strip()))
                high = abs(int(self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", tr_code, rq_name, i,
                                                    "고가").strip()))
                close = abs(int(self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", tr_code, rq_name, i,
                                                     "현재가").strip()))
                trading_value = int(
                    self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", tr_code, rq_name, i,
                                         "거래대금").strip()) * 1000000
                self.tr_data.append((date, open_p, high, close, trading_value))
        if self.tr_loop: self.tr_loop.exit()

    def scan_master_candles(self):
        self.comm_connect()
        self.load_condition_expressions()

        raw_candidates = self.get_hts_candidates()
        print(f"▶ 1차 필터링(재무/대금) 통과 종목: 총 {len(raw_candidates)}개\n")

        detected_master_candles = []  # 진입 대기 또는 현재 진행 중인 종목 리스트
        completed_profit_candles = []  # 5일 이내에 이미 익절 청산 완료된 종목 리스트

        for idx, code in enumerate(raw_candidates, 1):
            name = self.ocx.dynamicCall("GetMasterCodeName(QString)", code)
            print(f"[{idx}/{len(raw_candidates)}] {name}({code}) 시계열 검증 중...")

            self.request_candles_data(code)
            time.sleep(0.35)

            if len(self.tr_data) < 250:
                print(f"  ❌ [탈락] 데이터 부족 (보유 데이터 {len(self.tr_data)}일 / 최소 250일 필요)")
                continue

            df = list(reversed(self.tr_data))
            total_len = len(df)

            is_verified = False
            reasons_log = []

            # 최근 5영업일 구간 전수조사
            for target_idx in range(total_len - 5, total_len):
                if target_idx < 240: continue

                date, open_p, high, close, trading_value = df[target_idx]
                if open_p == 0: continue

                # 1. 몸통 길이 검증 (+15% 이상 양봉)
                body_return = ((close - open_p) / open_p) * 100
                if body_return < 15.0:
                    reasons_log.append(f"{date}: 순수 몸통 길이 미달 ({body_return:.1f}%)")
                    continue

                # 2. 거래대금 검증 (당일 2,000억 이상)
                if trading_value < 200_000_000_000:
                    reasons_log.append(f"{date}: 당일 거래대금 미달 ({trading_value // 100000000:,}억)")
                    continue

                # 3. 240일간의 종가 기준 최고가 경신 검증
                past_240_closes = [day[3] for day in df[target_idx - 240: target_idx]]
                max_close_240 = max(past_240_closes)
                if close <= max_close_240:
                    reasons_log.append(f"{date}: 240일 종가 신고가 경신 실패")
                    continue

                # --- 기준봉 확정 후 레이어 연산 ---
                r0 = close
                r1 = open_p + ((close - open_p) * 0.75)

                # 4. 사후 궤적 추적 (역주행 제외 및 익절 완료 여부 동시 검사)
                is_bear_trap = False
                is_already_profit = False
                simulated_entry_price = None

                for track_idx in range(target_idx + 1, total_len):
                    t_close = df[track_idx][3]

                    # [탈락 조건] 장중이 아닌 일봉 종가 기준으로 단 한 번이라도 R1 하향 이탈 시 역주행 탈락
                    if t_close < r1:
                        is_bear_trap = True
                        break

                    # 가상 매수 진입 시점 포착 (R0 ~ R1 존 첫 안착)
                    if simulated_entry_price is None:
                        if t_close >= r1 and t_close <= r0:
                            simulated_entry_price = t_close
                    else:
                        # 매수 단가가 확정된 이후, +4% 익절 도달 여부 체크
                        if (t_close - simulated_entry_price) / simulated_entry_price >= 0.04:
                            is_already_profit = True
                            break  # 익절 완료 시 해당 봉의 추적 종료

                if is_bear_trap:
                    reasons_log.append(f"{date}: 기준봉 이후 종가가 R1 라인을 깨고 내려갔던 역주행 봉 (탈락)")
                    continue

                # 직전 40거래일 동안 일 거래대금 1,000억 원 이상 터진 총 일수 카운트
                past_40_days = df[target_idx - 40: target_idx]
                hot_days_count = sum(1 for day in past_40_days if day[4] >= 100_000_000_000)

                # 가장 가까운 영업일(오늘 종가)이 R0와 R1 사이에 위치하는지 판정
                today_close = df[-1][3]
                is_in_zone = "Y" if (today_close >= r1 and today_close <= r0) else "N"

                # [분류 및 저장] 익절 성공 종목과 진행 중인 종목을 분리하여 리스트 업
                if is_already_profit:
                    print(f"  => 성공: {date} 기준봉 발생 후 이미 +4% 익절 완료가 확인되었습니다.")
                    completed_profit_candles.append((code, name, date, r0, r1, today_close, hot_days_count))
                else:
                    print(f"  => 적격: {date} 기준봉 유효 (현재 존 안착 여부: {is_in_zone})")
                    detected_master_candles.append((code, name, date, r0, r1, today_close, hot_days_count, is_in_zone))

                is_verified = True
                break

            if not is_verified:
                print("  ❌ [탈락 사유 요약]")
                for log in reasons_log[-2:]:
                    print(f"    - {log}")
                print("")

        # 두 리스트 모두 주도성 거래대금 일수 기준으로 정렬
        detected_master_candles.sort(key=lambda x: x[6], reverse=True)
        completed_profit_candles.sort(key=lambda x: x[6], reverse=True)

        print(
            "\n=============================================================================================================")
        print(f" 🎯 [공략 가능] 마스터 캔들 유효 종목 리스트 (총 {len(detected_master_candles)}개 / 주도성 정렬)")
        print(
            "=============================================================================================================")
        for c, n, d, r0, r1, curr, count, zone in detected_master_candles:
            print(
                f" * {n}({c}) | 기준봉일: {d} | R0(종가): {r0:,}원 | R1(75%): {r1:.0f}원 | 현재가: {curr:,}원 | [40일대금: {count}일] | [Zone안착: {zone}]")

        print(
            "\n=============================================================================================================")
        print(f" ✅ [청산 완료] 최근 5영업일 이내에 이미 +4% 익절 청산된 종목 리스트 (총 {len(completed_profit_candles)}개)")
        print(
            "=============================================================================================================")
        for c, n, d, r0, r1, curr, count in completed_profit_candles:
            print(
                f" * {n}({c}) | 기준봉일: {d} | R0(종가): {r0:,}원 | R1(75%): {r1:.0f}원 | 최근종가: {curr:,}원 | [40일대금: {count}일] -> 4% 익절 달성완료")
        print(
            "=============================================================================================================")


if __name__ == "__main__":
    scanner = KiwoomMasterCandleFullTracker()
    scanner.scan_master_candles()