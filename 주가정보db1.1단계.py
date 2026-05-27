import sys
import time
import sqlite3
import re
from datetime import datetime
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop


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

                # 부실종목 필터링
                if any(x in state for x in ["관리종목", "투자유의", "정리매매", "거래정지"]):
                    continue
                # 우선주 제외 (끝자리가 0이 아닌 것)
                if not code.endswith("0"):
                    continue
                # ETF, ETN, 스팩, 리츠 등 제외
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

    def is_market_open(self):
        """현재 시간이 평일 장중(09:00 ~ 15:30)인지 확인"""
        now = datetime.now()
        # weekday(): 0(월) ~ 4(금)
        if now.weekday() < 5 and (
                now.hour == 9 or (now.hour > 9 and now.hour < 15) or (now.hour == 15 and now.minute <= 30)):
            return True
        return False

    def start_scraping(self):
        if self.is_market_open():
            print("\n[경고] 현재 주식 장이 열려있는 시간입니다.")
            print("오늘자 데이터가 미완성 상태(현재가 기준)로 저장될 수 있습니다.")
            print("완벽한 일봉 데이터를 원하신다면 장 마감(15:30) 이후 실행을 권장합니다.\n")

        self.comm_connect()
        print("키움증권 로그인 완료. 종목 마스터 구성 중...")

        stocks = self.get_clean_stock_list()
        total_stocks = len(stocks)
        print(f"필터링 완료. 총 수집 대상 보통주: {total_stocks}개 종목\n")

        # DB 커넥션을 루프 바깥으로 빼서 속도 최적화
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            for idx, (code, name, market) in enumerate(stocks, 1):
                # 1. DB에서 가장 최근 저장 날짜 확인
                cursor.execute("SELECT MAX(date) FROM daily_prices WHERE code = ?", (code,))
                row = cursor.fetchone()
                last_saved_date = row[0] if row and row[0] else None

                print(
                    f"[{idx}/{total_stocks}] {name}({code}) 수집 중... (기존 최신일: {last_saved_date if last_saved_date else '없음'})")

                self.tr_data = []
                next_flag = "0"

                # 2. 필요한 만큼만 과거로 거슬러 올라가며 요청
                while True:
                    self.request_tr_data(
                        tr_code="opt10081",
                        rq_name="opt10081_req",
                        next_krx=next_flag,
                        screen_no="0101",
                        inputs={"종목코드": code, "기준일자": time.strftime("%Y%m%d"), "수정주가구분": "1"}
                    )
                    time.sleep(0.35)  # API 분당 100회 초과 방어

                    if not self.tr_data:
                        break

                    oldest_in_chunk = self.tr_data[-1][0]

                    # 수집된 가장 과거 날짜가 DB 최신 날짜와 겹치거나 넘어서면 추가 요청 중단
                    if last_saved_date and oldest_in_chunk <= last_saved_date:
                        break

                    # 더 이상 과거 데이터가 없거나, 최대 수집 목표치(2600일) 도달 시 탈출
                    if not self.remained_data or len(self.tr_data) >= 2600:
                        break

                    next_flag = "2"

                # 3. 신규 데이터 필터링 및 DB 저장
                if self.tr_data:
                    if last_saved_date:
                        new_data = [item for item in self.tr_data if item[0] > last_saved_date]
                    else:
                        new_data = self.tr_data

                    if new_data:
                        # 오름차순(과거 -> 최신) 정렬 후 저장
                        new_data.sort(key=lambda x: x[0])

                        cursor.execute("INSERT OR REPLACE INTO stocks VALUES (?, ?, ?)", (code, name, market))
                        cursor.executemany(
                            "INSERT OR IGNORE INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            [(code, d, o, h, l, c, v, tv) for d, o, h, l, c, v, tv in new_data]
                        )
                        # 종목 하나 끝날 때마다 커밋하여 예기치 않은 종료 시 데이터 유실 방지
                        conn.commit()

                        print(f"▶ [완료] {len(new_data)}일 치 신규 데이터 추가! (최근 업데이트: {new_data[-1][0]})\n")
                    else:
                        print(f"▶ [유지] 이미 최신 상태입니다.\n")
                else:
                    print(f"▶ [실패] 데이터를 수집하지 못했습니다.\n")

        print("모든 종목의 최신 데이터 이어받기가 완료되었습니다.")


if __name__ == "__main__":
    scraper = KiwoomStockScraper()
    scraper.start_scraping()