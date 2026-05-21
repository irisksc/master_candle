import sys
import sqlite3
from PyQt5.QtWidgets import *
from PyQt5.QAxContainer import *
from PyQt5.QtCore import QEventLoop


class KiwoomStockInitializer(QAxWidget):
    def __init__(self):
        super().__init__()
        self.setControl("KHOPENAPI.KHOpenAPICtrl.1")
        self.db_name = "stock_manager.db"

        # 이벤트 루프 변수 생성
        self.login_event_loop = QEventLoop()

        # 시그널과 슬롯 연결
        self.OnEventConnect.connect(self._login_handler)

        self._init_db()

    def _init_db(self):
        """SQLite DB 및 테이블 초기화"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
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
            conn.commit()

    def comm_connect(self):
        """로그인 실행 및 대기"""
        self.dynamicCall("CommConnect()")
        print("키움 API 연결 요청 중... (로그인 창 확인)")

        # OnEventConnect 이벤트가 발생할 때까지 여기서 멈춤
        self.login_event_loop.exec_()

    def _login_handler(self, err_code):
        """로그인 결과 수신 핸들러"""
        if err_code == 0:
            print("로그인 성공")
        else:
            print(f"로그인 실패 (에러코드: {err_code})")
            sys.exit()  # 실패 시 프로그램 종료

        # 로그인 대기 루프 종료
        self.login_event_loop.exit()

    def initialize_stock_list(self):
        """코스피, 코스닥 종목을 가져와 DB에 등록"""
        markets = {"0": "KOSPI", "10": "KOSDAQ"}
        total_count = 0

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()

            for market_code, market_name in markets.items():
                code_list_str = self.dynamicCall("GetCodeListByMarket(QString)", market_code)
                code_list = code_list_str.split(';')[:-1]

                print(f"[{market_name}] 수집 중... ({len(code_list)} 종목)")

                for code in code_list:
                    name = self.dynamicCall("GetMasterCodeName(QString)", code)
                    integrated_code = f"{code}_AL"

                    cursor.execute("""
                                   INSERT
                                   OR IGNORE INTO stock_list (code, name, market, status)
                        VALUES (?, ?, ?, ?)
                                   """, (integrated_code, name, market_name, 'PENDING'))
                    total_count += 1

            conn.commit()

        print(f"\n[초기화 완료] 총 {total_count}개 종목이 'PENDING' 상태로 등록되었습니다.")
        self._show_sample_data()

    def _show_sample_data(self):
        """DB 데이터 샘플 출력"""
        print("\n--- DB 등록 데이터 샘플 (상위 5개) ---")
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT code, name, market, status FROM stock_list LIMIT 5")
            rows = cursor.fetchall()
            print(f"{'코드':<12} | {'종목명':<15} | {'시장':<8} | {'상태'}")
            print("-" * 55)
            for row in rows:
                print(f"{row[0]:<12} | {row[1]:<15} | {row[2]:<8} | {row[3]}")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    initializer = KiwoomStockInitializer()

    # 1. 로그인 (이벤트 루프에 의해 완료될 때까지 자동으로 기다림)
    initializer.comm_connect()

    # 2. 리스트 초기화 및 DB 저장
    initializer.initialize_stock_list()

    print("\n프로그램을 종료합니다.")