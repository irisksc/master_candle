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

        self.detected_master_candles = []
        self.eliminated_candles = []

        self.initUI()

        QTimer.singleShot(500, self.on_refresh_clicked)

    def initUI(self):
        self.setWindowTitle("⚡ 마스터 캔들 전략 실시간 대시보드 (다중 기준봉 독립 추적 & 세부 데이터)")
        self.setGeometry(100, 100, 1350, 750)
        main_layout = QVBoxLayout()

        self.refresh_btn = QPushButton("🔄 실시간 전체 새로고침 (클릭 시 수초 간 창이 멈춘 후 리프레시됩니다)")
        self.refresh_btn.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
        self.refresh_btn.setStyleSheet("background-color: #1f77b4; color: white; padding: 12px; border-radius: 5px;")
        self.refresh_btn.clicked.connect(self.on_refresh_clicked)
        main_layout.addWidget(self.refresh_btn)

        self.tabs = QTabWidget()

        # Tab 1: 공략 가능 주도주 (헤더 업데이트)
        self.tab1 = QWidget()
        layout1 = QVBoxLayout()
        self.table1 = QTableWidget(0, 11)
        self.table1.setHorizontalHeaderLabels(
            ["종목코드", "종목명", "기준봉 형성일", "R0(종가)", "R1(75%)", "현재가",
             "40일천억봉", "상승률(%)", "거래대금(억)", "오늘매수가능", "타점발생일"])
        self.table1.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        # 타점발생일과 상승률/거래대금 등 공간이 필요한 컬럼 미세 조정
        self.table1.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeToContents)
        self.table1.setEditTriggers(QTableWidget.NoEditTriggers)
        layout1.addWidget(QLabel("▶ 현재 진입 대기 및 공략 가능 유효 주도주 (파란색 배경: 해당 종목의 가장 최근 기준봉)"))
        layout1.addWidget(self.table1)
        self.tab1.setLayout(layout1)

        # Tab 2: 탈락 종목 분석
        self.tab2 = QWidget()
        layout2 = QVBoxLayout()
        self.table2 = QTableWidget(0, 3)
        self.table2.setHorizontalHeaderLabels(["종목코드", "종목명", "탈락 상세 사유 (발생일 및 기준봉 포함)"])

        self.table2.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table2.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table2.horizontalHeader().setStretchLastSection(True)
        self.table2.setColumnWidth(2, 650)
        self.table2.setEditTriggers(QTableWidget.NoEditTriggers)

        layout2.addWidget(QLabel("❌ HTS 1차 검출 성공 후, 파이썬 정밀 필터링(조건 미달, R1 이탈 등)에서 탈락한 종목들"))
        layout2.addWidget(self.table2)
        self.tab2.setLayout(layout2)

        self.tabs.addTab(self.tab1, "🎯 공략 가능 주도주")
        self.tabs.addTab(self.tab2, "❌ 탈락 종목 분석")
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
        self.eliminated_candles.clear()

        self.table1.setRowCount(0)
        self.table2.setRowCount(0)

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
                print(f"      -> 탈락: 데이터 부족")
                self.eliminated_candles.append((code, name, f"[데이터 부족] HTS에 {len(self.tr_data)}일치 데이터만 존재함"))
                continue

            df = list(reversed(self.tr_data))
            total_len = len(df)

            found_any_master_candle = False
            first_valid_candle_found = False  # 가장 최근 기준봉 여부 판독용 플래그

            # 최근 5일치 캔들을 역순으로 (최근 날짜부터 과거로) 검사
            for target_idx in range(total_len - 1, total_len - 6, -1):
                if target_idx < 240: continue
                date, open_p, high, close, trading_value = df[target_idx]
                if open_p == 0: continue

                body_return = ((close - open_p) / open_p) * 100

                # 1단계 관문 (기준봉 검증)
                if body_return < 15.0 or trading_value < 200_000_000_000:
                    continue

                found_any_master_candle = True
                past_240_closes = [day[3] for day in df[target_idx - 240: target_idx]]

                # 2단계 관문 (240일 신고가 검증)
                if close <= max(past_240_closes):
                    self.eliminated_candles.append((code, name, f"[기준봉: {date}] {date} 탈락: 장대양봉 발생했으나 240일 신고가 돌파 실패"))
                    continue

                r0, r1 = close, open_p + ((close - open_p) * 0.75)
                is_bear_trap = False
                buying_dates = []

                # 3단계 관문 (역주행 및 타점 체크)
                for track_idx in range(target_idx + 1, total_len):
                    t_date = df[track_idx][0]
                    t_close = df[track_idx][3]

                    if t_close < r1:
                        is_bear_trap = True
                        self.eliminated_candles.append((code, name, f"[기준봉: {date}] {t_date} 탈락: 역주행 필터 탈락 (R1 이탈 붕괴)"))
                        break

                    if track_idx < total_len - 1:
                        if t_close >= r1 and t_close <= r0:
                            buying_dates.append(t_date)

                if is_bear_trap:
                    continue

                # 모든 관문 통과
                past_40_days = df[target_idx - 40: target_idx]
                hot_days_count = sum(1 for day in past_40_days if day[4] >= 100_000_000_000)
                today_close = df[-1][3]

                if target_idx == total_len - 1:
                    is_in_zone = "★NEW(오늘형성)"
                else:
                    is_in_zone = "Y" if (today_close >= r1 and today_close <= r0) else "N"

                buy_dates_str = ", ".join(buying_dates) if buying_dates else "없음"

                # 추가 데이터 포매팅 (상승률 및 거래대금)
                body_return_str = f"{body_return:.2f}%"
                trade_val_str = f"{int(trading_value / 100_000_000):,}억"

                # 최근부터 과거로 탐색 중이므로, 처음으로 통과한 기준봉이 '가장 최근' 기준봉임
                is_most_recent = not first_valid_candle_found
                first_valid_candle_found = True

                print(f"      ★ [대기포착] {date} 기준봉 유효 (상승률:{body_return_str}, 대금:{trade_val_str})")
                self.detected_master_candles.append(
                    (code, name, date, f"{r0:,}", f"{r1:.0f}", f"{today_close:,}", f"{hot_days_count}일",
                     body_return_str, trade_val_str, is_in_zone, buy_dates_str, is_most_recent))

            if not found_any_master_candle:
                print(f"      -> 사유: [기준봉 미발생]")
                self.eliminated_candles.append((code, name, "[기준봉 미발생] 최근 5영업일 내 유효한 기준봉(15%↑, 2000억↑) 조건 미달"))

        # 정렬: 1순위 종목명(오름차순), 2순위 기준봉 형성일(최신순 내림차순)
        self.detected_master_candles.sort(key=lambda x: (x[1], -int(x[2])))

        self.update_ui_tables()

    def update_ui_tables(self):
        print(f"\n📊 [연산 종료] 공략가능(타겟별): {len(self.detected_master_candles)} / 조건탈락: {len(self.eliminated_candles)}")

        # Table 1 렌더링
        self.table1.setRowCount(len(self.detected_master_candles))
        for r, row in enumerate(self.detected_master_candles):
            # row[11]은 is_most_recent 플래그
            is_most_recent = row[11]

            for c, val in enumerate(row[:11]):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)

                # 기본 배경색 처리 (가장 최근 기준봉 하이라이트)
                if is_most_recent:
                    item.setBackground(QColor("#E8F0FE"))  # 연한 파란색

                # 특수 컬럼 컬러 우선 적용
                if c == 9:  # 오늘매수가능 (Zone 안착)
                    if val == "Y":
                        item.setBackground(QColor("#FFFFCC"))
                    elif "★NEW" in val:
                        item.setBackground(QColor("#E2EFDA"))
                        item.setFont(QFont("Malgun Gothic", 9, QFont.Bold))
                elif c == 10:  # 타점발생일 (과거 매수발생일)
                    if val != "없음":
                        item.setForeground(QColor("#D32F2F"))
                        item.setFont(QFont("Malgun Gothic", 9, QFont.Bold))

                self.table1.setItem(r, c, item)

        # Table 2 렌더링
        self.table2.setRowCount(len(self.eliminated_candles))
        for r, row in enumerate(self.eliminated_candles):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                if c == 2:
                    item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
                    if "[기준봉 미발생]" in str(val):
                        item.setForeground(QColor("#888888"))
                    else:
                        item.setForeground(QColor("#333333"))
                else:
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setForeground(QColor("#555555"))
                self.table2.setItem(r, c, item)

        print("✨ [화면 리프레시 완료] 대시보드 업데이트가 완료되었습니다.\n")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    system = KiwoomMasterCandleGuiSystem()
    sys.exit(app.exec_())