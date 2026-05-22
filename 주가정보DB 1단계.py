import sys
import time
import sqlite3
import re
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget


class KiwoomStockScraper:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.ocx = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
        self.ocx.OnEventConnect.connect(self.on_connect)
        self.ocx.OnReceiveTrData.connect(self.on_receive_tr_data)

        self.login_loop = None
        self.tr_loop = None
        self.tr_data = []
        self.remained_data = False
        self.tr_req_count = 0  # API 호출 횟수 카운터

        self.db_path = "stock_data.db"
        self.init_database()

    def init_database(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                           CREATE TABLE IF NOT EXISTS stocks
                           (
                               code
                               TEXT
                               PRIMARY
                               KEY,
                               name
                               TEXT,
                               market
                               TEXT
                           )
                           """)
            cursor.execute("""
                           CREATE TABLE IF NOT EXISTS daily_prices
                           (
                               code
                               TEXT,
                               date
                               TEXT,
                               open
                               INTEGER,
                               high
                               INTEGER,
                               low
                               INTEGER,
                               close
                               INTEGER,
                               volume
                               INTEGER,
                               trading_value
                               INTEGER,
                               PRIMARY
                               KEY
                           (
                               code,
                               date
                           )
                               )
                           """)
            conn.commit()

    def comm_connect(self):
        self.ocx.dynamicCall("CommConnect()")
        from PyQt5.QtCore import QEventLoop
        self.login_loop = QEventLoop()
        self.login_loop.exec_()

    def on_connect(self, err_code):
        print(f"로그인 상태 변경: {err_code}")
        if self.login_loop:
            self.login_loop.exit()

    def get_clean_stock_list(self):
        valid_stocks = []
        for market_code, market_name in [("0", "KOSPI"), ("10", "KOSDAQ")]:
            code_list_str = self.ocx.dynamicCall("GetCodeListByMarket(QString)", market_code)
            raw_codes = code_list_str.split(";")[:-1]

            for code in raw_codes:
                name = self.ocx.dynamicCall("GetMasterCodeName(QString)", code)
                state = self.ocx.dynamicCall("GetMasterStockState(QString)", code)

                if any(x in state for x in ["관리종목", "투자유의", "정리매매", "거래정지"]):
                    continue

                if not code.endswith("0"):
                    continue

                if any(re.search(p, name, re.IGNORECASE) for p in [
                    r"스팩", r"리츠", r"호\d$", r"KODEX", r"TIGER", r"HANARO", r"KBSTAR",
                    r"ACE", r"SOL", r"인프라", r"펀드", r"ETN", r"신한", r"대신"
                ]):
                    continue

                valid_stocks.append((code, name, market_name))
        return valid_stocks

    def request_tr_data(self, tr_code, rq_name, next_krx, screen_no, inputs):
        # 1분에 100회 제한 방어 로직: 90회 요청마다 60초 휴식
        self.tr_req_count += 1
        if self.tr_req_count % 90 == 0:
            print("\n[안내] API 분당 호출 제한 방지를 위해 60초간 대기합니다...\n")
            time.sleep(60)

        for key, val in inputs.items():
            self.ocx.dynamicCall("SetInputValue(QString, QString)", key, val)

        from PyQt5.QtCore import QEventLoop
        self.tr_loop = QEventLoop()
        self.ocx.dynamicCall("CommRqData(QString, QString, int, QString)", rq_name, tr_code, next_krx, screen_no)
        self.tr_loop.exec_()

    def on_receive_tr_data(self, screen_no, rq_name, tr_code, record_name, prev_next, *args):
        self.remained_data = True if prev_next == "2" else False

        if rq_name == "opt10081_req":
            count = self.ocx.dynamicCall("GetRepeatCnt(QString, QString)", tr_code, rq_name)
            for i in range(count):
                date = self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", tr_code, rq_name, i,
                                            "일자").strip()
                open_p = abs(
                    int(self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", tr_code, rq_name, i,
                                             "시가").strip()))
                high = abs(int(self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", tr_code, rq_name, i,
                                                    "고가").strip()))
                low = abs(int(self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", tr_code, rq_name, i,
                                                   "저가").strip()))
                close = abs(int(self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", tr_code, rq_name, i,
                                                     "현재가").strip()))
                volume = int(self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", tr_code, rq_name, i,
                                                  "거래량").strip())
                trading_value = int(
                    self.ocx.dynamicCall("GetCommData(QString, QString, int, QString)", tr_code, rq_name, i,
                                         "거래대금").strip()) * 1000000

                self.tr_data.append((date, open_p, high, low, close, volume, trading_value))

        if self.tr_loop:
            self.tr_loop.exit()

    def start_scraping(self):
        self.comm_connect()
        print("키움증권 로그인 완료. 종목 마스터 구성 중...")

        stocks = self.get_clean_stock_list()
        total_stocks = len(stocks)
        print(f"필터링 완료. 총 수집 대상 보통주: {total_stocks}개 종목")

        # 기존에 수집 완료된 종목 코드 확인 (최소 2000일 이상 데이터가 있는 경우만 완료로 간주)
        existing_codes = set()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT code, count(*) FROM daily_prices GROUP BY code HAVING count(*) > 2000")
            existing_codes = {row[0] for row in cursor.fetchall()}

        for idx, (code, name, market) in enumerate(stocks, 1):
            if code in existing_codes:
                continue

            print(f"[{idx}/{total_stocks}] {name}({code}) 수집 시작...")

            # 수집 시작 전 해당 종목의 기존 데이터 삭제 (불완전 수집 데이터 초기화)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM daily_prices WHERE code = ?", (code,))
                conn.commit()

            self.tr_data = []
            next_flag = "0"
            al_code = f"{code}_AL"

            while len(self.tr_data) < 2600:
                self.request_tr_data(
                    tr_code="opt10081",
                    rq_name="opt10081_req",
                    next_krx=next_flag,
                    screen_no="0101",
                    inputs={"종목코드": al_code, "기준일자": time.strftime("%Y%m%d"), "수정주가구분": "1"}
                )
                time.sleep(0.3)

                if self.remained_data:
                    next_flag = "2"
                else:
                    break

            if self.tr_data:
                self.tr_data.sort(key=lambda x: x[0])

                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("INSERT OR REPLACE INTO stocks VALUES (?, ?, ?)", (code, name, market))
                    cursor.executemany(
                        "INSERT OR IGNORE INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [(code, d, o, h, l, c, v, tv) for d, o, h, l, c, v, tv in self.tr_data]
                    )
                    conn.commit()

                first_day = self.tr_data[0]
                print(
                    f"▶ [완료] {name}({code}) | 최초일자: {first_day[0]} | 시가: {first_day[1]:,} | 종가: {first_day[4]:,} | 고가: {first_day[2]:,} | 저가: {first_day[3]:,} | 거래량: {first_day[5]:,} | 거래대금: {first_day[6]:,}\n")

            time.sleep(0.5)

        print("\n모든 종목의 데이터 수집이 완료되었습니다.")


if __name__ == "__main__":
    scraper = KiwoomStockScraper()
    scraper.start_scraping()