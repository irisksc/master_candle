import sys
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget, QTabWidget, QHeaderView, QLabel)
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop, Qt
from PyQt5.QtGui import QFont


class KiwoomMasterCandleGuiSystem(QMainWindow):
    def __init__(self):
        super().__init__()
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
        self.completed_profit_candles = []

    def comm_connect(self):
        self.ocx.dynamicCall("CommConnect()")
        self.login_loop = QEventLoop()
        self.login_loop.exec_()

    def on_connect(self, err_code):
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

    def scan_logic(self):
        self.comm_connect()
        self.load_condition_expressions()
        raw_candidates = self.get_hts_candidates()

        for code in raw_candidates:
            name = self.ocx.dynamicCall("GetMasterCodeName(QString)", code)
            self.request_candles_data(code)
            time.sleep(0.35)

            if len(self.tr_data) < 250: continue
            df = list(reversed(self.tr_data))
            total_len = len(df)

            for target_idx in range(total_len - 5, total_len):
                if target_idx < 240: continue
                date, open_p, high, close, trading_value = df[target_idx]
                if open_p == 0: continue

                body_return = ((close - open_p) / open_p) * 100
                if body_return < 15.0 or trading_value < 200_000_000_000: continue

                past_240_closes = [day[3] for day in df[target_idx - 240: target_idx]]
                if close <= max(past_240_closes): continue

                r0, r1 = close, open_p + ((close - open_p) * 0.75)
                is_bear_trap, is_already_profit, simulated_entry_price = False, False, None

                for track_idx in range(target_idx + 1, total_len):
                    t_close = df[track_idx][3]
                    if t_close < r1:
                        is_bear_trap = True
                        break
                    if simulated_entry_price is None:
                        if t_close >= r1 and t_close <= r0: simulated_entry_price = t_close
                    else:
                        if (t_close - simulated_entry_price) / simulated_entry_price >= 0.04:
                            is_already_profit = True
                            break

                if is_bear_trap: continue

                past_40_days = df[target_idx - 40: target_idx]
                hot_days_count = sum(1 for day in past_40_days if day[4] >= 100_000_000_000)
                today_close = df[-1][3]
                is_in_zone = "Y" if (today_close >= r1 and today_close <= r0) else "N"

                if is_already_profit:
                    self.completed_profit_candles.append(
                        (code, name, date, f"{r0:,}", f"{r1:.0f}", f"{today_close:,}", f"{hot_days_count}일"))
                else:
                    self.detected_master_candles.append(
                        (code, name, date, f"{r0:,}", f"{r1:.0f}", f"{today_close:,}", f"{hot_days_count}일",
                         is_in_zone))
                break

        self.detected_master_candles.sort(key=lambda x: int(x[6].replace('일', '')), reverse=True)
        self.completed_profit_candles.sort(key=lambda x: int(x[6].replace('일', '')), reverse=True)
        self.initUI()

    def initUI(self):
        self.setWindowTitle("⚡ 마스터 캔들 전략 실시간 대시보드")
        self.setGeometry(100, 100, 1100, 650)

        tabs = QTabWidget()

        # Tab 1: 공략 가능 종목
        tab1 = QWidget()
        layout1 = QVBoxLayout()
        table1 = QTableWidget(len(self.detected_master_candles), 8)
        table1.setHorizontalHeaderLabels(["종목코드", "종목명", "기준봉 형성일", "R0(종가)", "R1(75%)", "현재가", "40일 대금", "Zone 안착"])
        for r, row in enumerate(self.detected_master_candles):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                if c == 7 and val == "Y":  # 안착 종목 강조
                    item.setBackground(Qt.yellow)
                table1.setItem(r, c, item)
        table1.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout1.addWidget(QLabel("▶ 현재 진입 대기 및 공략 가능 유효 주도주"))
        layout1.addWidget(table1)
        tab1.setLayout(layout1)

        # Tab 2: 청산 완료 종목
        tab2 = QWidget()
        layout2 = QVBoxLayout()
        table2 = QTableWidget(len(self.completed_profit_candles), 7)
        table2.setHorizontalHeaderLabels(["종목코드", "종목명", "기준봉 형성일", "R0(종가)", "R1(75%)", "최근종가", "40일 대금"])
        for r, row in enumerate(self.completed_profit_candles):
            for c, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignCenter)
                table2.setItem(r, c, item)
        table2.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout2.addWidget(QLabel("✅ 최근 5영업일 이내에 이미 +4% 익절 목표를 달성한 종목"))
        layout2.addWidget(table2)
        tab2.setLayout(layout2)

        tabs.addTab(tab1, "🎯 공략 가능 주도주")
        tabs.addTab(tab2, "🎉 익절 완료 종목")

        self.setCentralWidget(tabs)
        self.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    system = KiwoomMasterCandleGuiSystem()
    system.scan_logic()
    sys.exit(app.exec_())