import sys
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget, QTabWidget, QHeaderView, QLabel, QPushButton)
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop, Qt, QTimer
from PyQt5.QtGui import QFont, QColor


class KiwoomMasterCandleGuiSystem(QMainWindow):
    def __init__(self):
        super().__init__()
        print("▶ [시스템] 프로그램 초기화 중...")
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

        # 3가지 리스트로 세분화
        self.detected_master_candles = []
        self.completed_profit_candles = []
        self.eliminated_candles = []  # [신규] 탈락 종목 보관용 리스트

        self.initUI()

        QTimer.singleShot(500, self.on_refresh_clicked)

    def initUI(self):
        self.setWindowTitle("⚡ 마스터 캔들 전략 실시간 대시보드 (탈락 사유 추적 기능 탑재)")
        self.setGeometry(100, 100, 1150, 700)
        main_layout = QVBoxLayout()

        self.refresh_btn = QPushButton("🔄 실시간 전체 새로고침 (클릭 시 수초 간 창이 멈춘 후 리프레시됩니다)")
        self.refresh_btn.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
        self.refresh_btn.setStyleSheet("background-color: #1f77b4; color: white; padding: 12px; border-radius: 5px;")
        self.refresh_btn.clicked.connect(self.on_refresh_clicked)
        main_layout.addWidget(self.refresh_btn)

        self.tabs = QTabWidget()

        # Tab 1: 공략 가능 주도주
        self.tab1 = QWidget()
        layout1 = QVBoxLayout()
        self.table1 = QTableWidget(0, 8)
        self.table1.setHorizontalHeaderLabels(
            ["종목코드", "종목명", "기준봉 형성일", "R0(종가)", "R1(75%)", "현재가", "40일 대금", "Zone 안착"])
        self.table1.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table1.setEditTriggers(QTableWidget.NoEditTriggers)
        layout1.addWidget(QLabel("▶ 현재 진입 대기 및 공략 가능 유효 주도주 (★NEW는 오늘 기준봉 발생 종목)"))
        layout1.addWidget(self.table1)
        self.tab1.setLayout(layout1)

        # Tab 2: 익절 완료 종목
        self.tab2 = QWidget()
        layout2 = QVBoxLayout()
        self.table2 = QTableWidget(0, 7)
        self.table2.setHorizontalHeaderLabels(["종목코드", "종목명", "기준봉 형성일", "R0(종가)", "R1(75%)", "최근종가", "40일 대금"])
        self.table2.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table2.setEditTriggers(QTableWidget.NoEditTriggers)
        layout2.addWidget(QLabel("✅ 최근 5영업일 이내에 이미 +4% 익절 목표를 달성한 종목 (장중 고가 기준 돌파 완료)"))
        layout2.addWidget(self.table2)
        self.tab2.setLayout(layout2)

        # [신규] Tab 3: 탈락 종목 및 사유
        self.tab3 = QWidget()
        layout3 = QVBoxLayout()
        self.table3 = QTableWidget(0, 3)
        self.table3.setHorizontalHeaderLabels(["종목코드", "종목명", "탈락 상세 사유"])
        self.table3.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # 사유 컬럼은 길어질 수 있으므로 비율 조정
        self.table3.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table3.setEditTriggers(QTableWidget.NoEditTriggers)
        layout3.addWidget(QLabel("❌ HTS 1차 검출에는 성공했으나, 시스템 정밀 필터링(파이썬)에서 걸러진 종목들"))
        layout3.addWidget(self.table3)
        self.tab3.setLayout(layout3)

        self.tabs.addTab(self.tab1, "🎯 공략 가능 주도주")
        self.tabs.addTab(self.tab2, "🎉 익절 완료 종목")
        self.tabs.addTab(self.tab3, "❌ 탈락 종목 분석")  # 탭 추가
        main_layout.addWidget(self.tabs)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)
        self.show()
        print("▶ [UI] 대시보드 프레임 시각화 완료.")

    def comm_connect(self):
        print("🔑 [로그인] 키움증권 오픈 API 서버 접속 중...")
        self.ocx.dynamicCall("CommConnect()")
        self.login_loop = QEventLoop()
        self.login_loop.exec_()

    def on_connect(self, err_code):
        print(f"✅ [로그인] 완료 (정상 코드: {err_code})")
        if self.login_loop: self.login_loop.exit()

    def load_condition_expressions(self):
        print("📁 [조건식] 서버에서 사용자 조건식 목록 받아오는 중...")
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
                print(f"🎯 [매핑 성공] 목표 조건식 발견! 이름: {c_name} (인덱스: {c_idx})")
                break
        if self.condition_loop: self.condition_loop.exit()

    def get_hts_candidates(self):
        if self.target_cond_idx is None: return []
        print(f"🔍 [HTS 조건검색] '{self.target_cond_name}'식 조건부 종목 호출...")
        self.ocx.dynamicCall("SendCondition(QString, QString, int, int)", "0150", self.target_cond_name,
                             self.target_cond_idx, 0)
        self.search_loop = QEventLoop()
        self.search_loop.exec_()
        return self.candidate_codes

    def on_receive_tr_condition(self, screen_no, code_list, cond_name, cond_idx, next_page):
        self.candidate_codes = code_list.split(";")[:-1] if code_list else []
        print(f"▶ [HTS 1차 필터링 완료] 실시간 조건식 검출 종목 수: {len(self.candidate_codes)}개")
        if self.search_loop: self.search_loop.exit()

    def request_candles_data(self, code):
        self.tr_data = []
        integrated_code = f"{code}_AL"
        self.ocx.dynamicCall("SetInputValue(QString, QString)", "종목코드", integrated_code)
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

    def on_refresh_clicked(self):
        print("\n🔄 [새로고침] 전체 전략 재계산 파이프라인 가동 시작...")
        self.detected_master_candles.clear()
        self.completed_profit_candles.clear()
        self.eliminated_candles.clear()  # 탈락 리스트 초기화

        self.table1.setRowCount(0)
        self.table2.setRowCount(0)
        self.table3.setRowCount(0)

        if self.target_cond_idx is None:
            self.comm_connect()
            self.load_condition_expressions()

        self.scan_logic()

    def scan_logic(self):
        raw_candidates = self.get_hts_candidates()

        if not raw_candidates:
            print("❌ [결과] 1차 HTS 조건식에 검출된 종목이 0개이므로 연산을 조기 종료합니다.")
            self.update_ui_tables()
            return

        for idx, code in enumerate(raw_candidates, 1):
            name = self.ocx.dynamicCall("GetMasterCodeName(QString)", code)
            print(f"   [{idx}/{len(raw_candidates)}] {name}({code}) 데이터 분석 중...")

            self.request_candles_data(code)
            time.sleep(0.35)

            if len(self.tr_data) < 250:
                print(f"      -> 데이터 부족으로 탈락 ({len(self.tr_data)}일 데이터)")
                self.eliminated_candles.append((code, name, f"데이터 부족 ({len(self.tr_data)}일 축적됨)"))
                continue

            df = list(reversed(self.tr_data))
            total_len = len(df)

            is_match = False

            # [신규] 탈락 사유 추적용 변수 세팅
            fail_priority = 0
            fail_reason = "최근 5영업일 내 유효한 기준봉(15%↑, 2000억↑) 미발생"

            for target_idx in range(total_len - 1, total_len - 6, -1):
                if target_idx < 240: continue
                date, open_p, high, close, trading_value = df[target_idx]
                if open_p == 0: continue

                body_return = ((close - open_p) / open_p) * 100

                # 1단계 관문: 상승률과 거래대금
                if body_return < 15.0 or trading_value < 200_000_000_000:
                    continue

                # 1단계를 통과했다면 최소한 기준봉은 뜬 것이므로 사유 업데이트
                if fail_priority < 1:
                    fail_reason = f"[{date}] 장대양봉 발생했으나 240일 신고가 돌파 실패"
                    fail_priority = 1

                past_240_closes = [day[3] for day in df[target_idx - 240: target_idx]]

                # 2단계 관문: 240일 신고가
                if close <= max(past_240_closes):
                    continue

                r0, r1 = close, open_p + ((close - open_p) * 0.75)
                is_bear_trap, is_already_profit, simulated_entry_price = False, False, None

                for track_idx in range(target_idx + 1, total_len):
                    t_high = df[track_idx][2]
                    t_close = df[track_idx][3]

                    # 3단계 관문: 역주행 붕괴 이탈
                    if t_close < r1:
                        is_bear_trap = True
                        break

                    if simulated_entry_price is None:
                        if t_close >= r1 and t_close <= r0:
                            simulated_entry_price = t_close
                            continue

                    if simulated_entry_price is not None:
                        if (t_high - simulated_entry_price) / simulated_entry_price >= 0.04:
                            is_already_profit = True
                            break

                if is_bear_trap:
                    if fail_priority < 2:
                        fail_reason = f"[{date}] 기준봉 성립 후 역주행 필터 탈락 (R1 이탈 붕괴)"
                        fail_priority = 2
                    continue

                past_40_days = df[target_idx - 40: target_idx]
                hot_days_count = sum(1 for day in past_40_days if day[4] >= 100_000_000_000)
                today_close = df[-1][3]

                if target_idx == total_len - 1:
                    is_in_zone = "★NEW(오늘형성)"
                else:
                    is_in_zone = "Y" if (today_close >= r1 and today_close <= r0) else "N"

                if is_already_profit:
                    print(f"      ★ [완료포착] {date}자 기준봉, 목표 수익(+4%) 달성 완료.")
                    self.completed_profit_candles.append(
                        (code, name, date, f"{r0:,}", f"{r1:.0f}", f"{today_close:,}", f"{hot_days_count}일"))
                else:
                    print(f"      ★ [대기포착] {date}자 기준봉 유효 (안착상태: {is_in_zone})")
                    self.detected_master_candles.append(
                        (code, name, date, f"{r0:,}", f"{r1:.0f}", f"{today_close:,}", f"{hot_days_count}일",
                         is_in_zone))
                is_match = True
                break

            if not is_match:
                print(f"      -> 탈락: {fail_reason}")
                self.eliminated_candles.append((code, name, fail_reason))

        # 정렬
        self.detected_master_candles.sort(key=lambda x: int(x[6].replace('일', '')), reverse=True)
        self.completed_profit_candles.sort(key=lambda x: int(x[6].replace('일', '')), reverse=True)

        self.update_ui_tables()

    def update_ui_tables(self):
        print(
            f"\n📊 [연산 종료] 공략가능: {len(self.detected_master_candles)} / 익절완료: {len(self.completed_profit_candles)} / 조건탈락: {len(self.eliminated_candles)}")

        # Table 1 렌더링
        self.table1.setRowCount(len(self.detected_master_candles))
        for r, row in enumerate(self.detected_master_candles):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                if c == 7:
                    if val == "Y":
                        item.setBackground(QColor("#FFFFCC"))
                    elif "★NEW" in val:
                        item.setBackground(QColor("#E2EFDA"))
                        item.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
                self.table1.setItem(r, c, item)

        # Table 2 렌더링
        self.table2.setRowCount(len(self.completed_profit_candles))
        for r, row in enumerate(self.completed_profit_candles):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                self.table2.setItem(r, c, item)

        # [신규] Table 3 렌더링 (탈락 종목)
        self.table3.setRowCount(len(self.eliminated_candles))
        for r, row in enumerate(self.eliminated_candles):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                # 사유 컬럼(index 2)은 좌측 정렬로 가독성 확보, 나머지는 중앙 정렬
                if c == 2:
                    item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                else:
                    item.setTextAlignment(Qt.AlignCenter)
                # 시각적으로 덜 중요함을 나타내기 위해 글씨를 회색톤으로 처리
                item.setForeground(QColor("#555555"))
                self.table3.setItem(r, c, item)

        print("✨ [화면 리프레시 완료] 대시보드 업데이트가 완료되었습니다.\n")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    system = KiwoomMasterCandleGuiSystem()
    sys.exit(app.exec_())