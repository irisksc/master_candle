import sys
import sqlite3
import time
from PyQt5.QtWidgets import *
from PyQt5.QAxContainer import *
from PyQt5.QtCore import QEventLoop


class KiwoomSystem(QAxWidget):
    def __init__(self):
        super().__init__()
        self.setControl("KHOPENAPI.KHOpenAPICtrl.1")
        self.db_name = "stock_manager.db"

        # 이벤트 루프 제어용
        self.login_event_loop = QEventLoop()
        self.tr_event_loop = QEventLoop()

        # 시그널 연결
        self.OnEventConnect.connect(self._login_handler)
        self.OnReceiveTrData.connect(self._receive_tr_data)
        self.OnReceiveMsg.connect(self._receive_msg)

        # 상태 관리 변수
        self.current_stock_code = ""
        self.current_stock_name = ""
        self.is_skip = False

        # DB 초기화
        self._init_db()

    def _init_db(self):
        """SQLite DB 및 테이블 생성"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            # 1. 종목 리스트 관리 테이블 (Step 1용)
            cursor.execute("""
                           CREATE TABLE IF NOT EXISTS stock_list
                           (
                               code
                               TEXT
                               PRIMARY
                               KEY,
                               name
                               TEXT,
                               market
                               TEXT,
                               status
                               TEXT
                               DEFAULT
                               'PENDING',
                               last_update
                               DATETIME,
                               error_msg
                               TEXT
                           )
                           """)
            # 2. 거래대금 저장 테이블 (Step 2용)
            cursor.execute("""
                           CREATE TABLE IF NOT EXISTS daily_trading_value
                           (
                               date
                               TEXT,
                               code
                               TEXT,
                               value_raw
                               INTEGER,
                               value_eok
                               REAL,
                               PRIMARY
                               KEY
                           (
                               date,
                               code
                           )
                               )
                           """)
            conn.commit()

    # ----------------------------------------------------------------
    # [로그인 관련]
    # ----------------------------------------------------------------
    def comm_connect(self):
        print("키움 API 연결 요청 중...")
        self.dynamicCall("CommConnect()")
        self.login_event_loop.exec_()

    def _login_handler(self, err_code):
        if err_code == 0:
            print("로그인 성공")
        else:
            print(f"로그인 실패 (코드: {err_code})")
            sys.exit()
        self.login_event_loop.exit()

    # ----------------------------------------------------------------
    # [Step 1: 종목 리스트 초기화]
    # ----------------------------------------------------------------
    def initialize_stock_list(self):
        print("\n[Step 1] 종목 리스트 업데이트 중...")
        markets = {"0": "KOSPI", "10": "KOSDAQ"}
        total_count = 0

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            for m_code, m_name in markets.items():
                code_list_str = self.dynamicCall("GetCodeListByMarket(QString)", m_code)
                code_list = code_list_str.split(';')[:-1]

                for code in code_list:
                    name = self.dynamicCall("GetMasterCodeName(QString)", code)
                    integrated_code = f"{code}_AL"
                    cursor.execute("""
                                   INSERT
                                   OR IGNORE INTO stock_list (code, name, market, status)
                        VALUES (?, ?, ?, ?)
                                   """, (integrated_code, name, m_name, 'PENDING'))
                    total_count += 1
            conn.commit()

    def run_collection_engine(self, target_count=2):
        print(f"\n[Step 2] 2025년 3월 데이터 수집 엔진 가동 (목표: {target_count}종목)...")

        success_count = 0
        while success_count < target_count:
            with sqlite3.connect(self.db_name) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT code, name FROM stock_list WHERE status = 'PENDING' LIMIT 1")
                row = cursor.fetchone()

                if not row:
                    print("수집할 PENDING 종목이 없습니다.")
                    break

                self.current_stock_code, self.current_stock_name = row
                self.is_skip = False

                print(
                    f"\n[{success_count + 1}/{target_count}] 수집 중: {self.current_stock_name}({self.current_stock_code})")

                # TR 요청 (기준일자를 2025년 3월 말로 설정)
                self._request_daily_data(self.current_stock_code)

                # 수집 후 상태 업데이트
                final_status = 'SKIP' if self.is_skip else 'COMPLETED'
                cursor.execute("""
                               UPDATE stock_list
                               SET status      = ?,
                                   last_update = DATETIME('now')
                               WHERE code = ?
                               """, (final_status, self.current_stock_code))
                conn.commit()

                if not self.is_skip:
                    success_count += 1
                    self._display_march_results()

        print(f"\n요청하신 {target_count}개 종목 수집 및 출력이 완료되었습니다.")

    def _request_daily_data(self, code):
        self.dynamicCall("SetInputValue(QString, QString)", "종목코드", code)
        self.dynamicCall("SetInputValue(QString, QString)", "기준일자", "20250331")  # 3월 말 기준으로 조회
        self.dynamicCall("SetInputValue(QString, QString)", "수정주가구분", "1")
        self.dynamicCall("CommRqData(QString, QString, int, QString)", "일봉조회", "opt10081", 0, "0101")
        self.tr_event_loop.exec_()
        time.sleep(0.3)

    def _receive_tr_data(self, screen_no, rqname, trcode, recordname, prev_next, data_len, err_code, msg1, msg2):
        if rqname == "일봉조회":
            count = self.dynamicCall("GetRepeatCnt(QString, QString)", trcode, recordname)

            if count == 0:
                self.is_skip = True
                self.tr_event_loop.exit()
                return

            found_march_data = False
            with sqlite3.connect(self.db_name) as conn:
                cursor = conn.cursor()
                for i in range(count):
                    date = self.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, recordname, i,
                                            "일자").strip()

                    # 2025년 3월 데이터만 필터링하여 저장
                    if date.startswith("202503"):
                        found_march_data = True
                        val_raw = int(
                            self.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, recordname, i,
                                             "거래대금").strip())
                        val_eok = val_raw / 100.0

                        cursor.execute("""
                            INSERT OR REPLACE INTO daily_trading_value (date, code, value_raw, value_eok)
                            VALUES (?, ?, ?, ?)
                        """, (date, self.current_stock_code, val_raw, val_eok))

                    elif date < "20250301":
                        # 3월 이전 데이터가 나오기 시작하면 루프 종료
                        break
                conn.commit()

            if not found_march_data:
                self.is_skip = True

            self.tr_event_loop.exit()

    def _receive_msg(self, screen_no, rqname, trcode, msg):
        """서버로부터 메시지 수신 시 호출 (조회 데이터 없음 등 예외 처리)"""
        if "조회 데이터가 없습니다" in msg or "종목을 찾을 수 없습니다" in msg:
            print(f"  [알림] {self.current_stock_code}: {msg.strip()} -> SKIP 처리 결정")
            self.is_skip = True
            # 데이터가 없으면 대기 중인 이벤트 루프를 강제로 종료하여 다음 단계로 진행
            if self.tr_event_loop.isRunning():
                self.tr_event_loop.exit()

    def _display_march_results(self):
        print(f"--- {self.current_stock_name} 2025년 3월 최근 5일 데이터 ---")
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                           SELECT date, value_eok
                           FROM daily_trading_value
                           WHERE code = ? AND date LIKE '202503%'
                           ORDER BY date DESC LIMIT 5
                           """, (self.current_stock_code,))

            rows = cursor.fetchall()
            for row in reversed(rows):  # 날짜 순으로 출력
                print(f"날짜: {row[0]} | 통합 거래대금: {row[1]:>10.2f} 억원")
        print("-" * 55)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    sys_manager = KiwoomSystem()
    sys_manager.comm_connect()
    sys_manager.initialize_stock_list()

    # 상위 2개 종목에 대해 2025년 3월 데이터 수집 실행
    sys_manager.run_collection_engine(target_count=2)

    sys.exit(app.exec_())