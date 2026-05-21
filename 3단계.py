import sys
import sqlite3
import time
from datetime import datetime
from PyQt5.QtWidgets import *
from PyQt5.QAxContainer import *
from PyQt5.QtCore import QEventLoop


class KiwoomTotalSystem(QAxWidget):
    def __init__(self):
        super().__init__()
        self.setControl("KHOPENAPI.KHOpenAPICtrl.1")
        self.db_name = "stock_manager.db"

        # 이벤트 루프 제어
        self.login_event_loop = QEventLoop()
        self.tr_event_loop = QEventLoop()

        # 시그널 연결
        self.OnEventConnect.connect(self._login_handler)
        self.OnReceiveTrData.connect(self._receive_tr_data)
        self.OnReceiveMsg.connect(self._receive_msg)

        # 상태 관리
        self.current_stock_code = ""
        self.current_stock_name = ""
        self.is_skip = False

        self._init_db()

    def _init_db(self):
        """종목 리스트와 거래대금 데이터를 저장할 테이블 생성"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            # 종목 관리 테이블
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
                               DATETIME
                           )
                           """)
            # 일별 거래대금 테이블
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

    def comm_connect(self):
        print("\n[시스템] 키움 Open API 접속을 시도합니다...")
        self.dynamicCall("CommConnect()")
        self.login_event_loop.exec_()

    def _login_handler(self, err_code):
        if err_code == 0:
            print("[시스템] 로그인 성공. 수집 환경이 준비되었습니다.")
        else:
            print(f"[오류] 로그인 실패 (코드: {err_code})")
            sys.exit()
        self.login_event_loop.exit()

    def sync_stock_list(self):
        """현재 상장된 모든 종목(KOSPI, KOSDAQ)을 DB에 업데이트"""
        print("[1단계] 상장 종목 리스트를 동기화합니다...")
        markets = {"0": "KOSPI", "10": "KOSDAQ"}
        total_new = 0

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            for m_code, m_name in markets.items():
                code_list = self.dynamicCall("GetCodeListByMarket(QString)", m_code).split(';')[:-1]
                for code in code_list:
                    name = self.dynamicCall("GetMasterCodeName(QString)", code)
                    # 통합시세(_AL) 코드로 저장
                    cursor.execute("""
                                   INSERT
                                   OR IGNORE INTO stock_list (code, name, market, status)
                        VALUES (?, ?, ?, ?)
                                   """, (f"{code}_AL", name, m_name, 'PENDING'))
                    if cursor.rowcount > 0:
                        total_new += 1
            conn.commit()
        print(f" -> 신규 종목 {total_new}개 추가 완료.")

    def run_full_collection(self):
        """전체 PENDING 종목을 순회하며 수집 수행"""
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT code, name FROM stock_list WHERE status = 'PENDING'")
            target_stocks = cursor.fetchall()

            total_targets = len(target_stocks)
            if total_targets == 0:
                print("\n[알림] 수집할 PENDING 종목이 없습니다. 모든 데이터가 최신입니다.")
                return

            print(f"\n[2단계] 전체 데이터 수집을 시작합니다 (대상: {total_targets} 종목)")
            print("=" * 60)

            processed_count = 0
            success_count = 0
            skip_count = 0
            start_time = time.time()

            for code, name in target_stocks:
                self.current_stock_code = code
                self.current_stock_name = name
                self.is_skip = False

                # 데이터 요청
                self._request_daily_data(code)

                # 상태 업데이트
                processed_count += 1
                final_status = 'SKIP' if self.is_skip else 'COMPLETED'
                if not self.is_skip:
                    success_count += 1
                else:
                    skip_count += 1

                cursor.execute("UPDATE stock_list SET status = ?, last_update = DATETIME('now') WHERE code = ?",
                               (final_status, code))
                conn.commit()

                if processed_count % 10 == 0 or processed_count == total_targets:
                    elapsed = time.time() - start_time
                    progress = (processed_count / total_targets) * 100
                    print(f"[{processed_count}/{total_targets}] {progress:>5.1f}% 완료 | "
                          f"성공: {success_count}, 스킵: {skip_count} | 소요시간: {elapsed:4.0f}초")

                # API 호출 속도 조절 (1초당 5회 미만)
                time.sleep(0.25)

        print("\n" + "=" * 60)
        print(f"[완료] 전 종목 수집 공정이 종료되었습니다. (총 {success_count}개 성공)")

    def _request_daily_data(self, code):
        self.dynamicCall("SetInputValue(QString, QString)", "종목코드", code)
        self.dynamicCall("SetInputValue(QString, QString)", "기준일자", "20260514")
        self.dynamicCall("SetInputValue(QString, QString)", "수정주가구분", "1")
        self.dynamicCall("CommRqData(QString, QString, int, QString)", "일봉조회", "opt10081", 0, "0101")
        self.tr_event_loop.exec_()

    def _receive_tr_data(self, screen_no, rqname, trcode, recordname, prev_next, data_len, err_code, msg1, msg2):
        if rqname == "일봉조회":
            count = self.dynamicCall("GetRepeatCnt(QString, QString)", trcode, recordname)
            if count == 0:
                self.is_skip = True
            else:
                found_march_data = False
                with sqlite3.connect(self.db_name) as conn:
                    cursor = conn.cursor()
                    for i in range(count):
                        date = self.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, recordname, i,
                                                "일자").strip()
                        if date < "20250301": break  # 2025년 3월 이전은 버림

                        found_march_data = True
                        val_raw = int(
                            self.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, recordname, i,
                                             "거래대금").strip())
                        cursor.execute("INSERT OR REPLACE INTO daily_trading_value VALUES (?, ?, ?, ?)",
                                       (date, self.current_stock_code, val_raw, val_raw / 100.0))
                    conn.commit()
                if not found_march_data: self.is_skip = True

            self.tr_event_loop.exit()

    def _receive_msg(self, screen_no, rqname, trcode, msg):
        if "조회 데이터가 없습니다" in msg:
            self.is_skip = True
            if self.tr_event_loop.isRunning(): self.tr_event_loop.exit()

    def display_top_5_summary(self):
        """수집된 데이터 중 가장 최근일 기준 거래대금 상위 5개 종목 출력"""
        print("\n" + "*" * 25 + " [최종 요약 리포트] " + "*" * 25)
        print("최근 거래대금 기준 상위 5개 종목의 최근 5일 데이터입니다.")

        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            # 1. 가장 최근 날짜 찾기
            cursor.execute("SELECT MAX(date) FROM daily_trading_value")
            latest_date = cursor.fetchone()[0]

            # 2. 해당 날짜 기준 거래대금 상위 5개 종목 코드 추출
            cursor.execute("""
                           SELECT v.code, l.name, v.value_eok
                           FROM daily_trading_value v
                                    JOIN stock_list l ON v.code = l.code
                           WHERE v.date = ?
                           ORDER BY v.value_eok DESC LIMIT 5
                           """, (latest_date,))
            top_stocks = cursor.fetchall()

            # 3. 각 종목별 최근 5일치 출력
            for code, name, last_val in top_stocks:
                print(f"\n▶ {name} ({code}) - {latest_date} 기준 {last_val:,.2f} 억원")
                cursor.execute("""
                               SELECT date, value_eok
                               FROM daily_trading_value
                               WHERE code = ?
                               ORDER BY date DESC LIMIT 5
                               """, (code,))
                history = cursor.fetchall()
                for h_date, h_val in reversed(history):
                    print(f"   [{h_date}] 거래대금: {h_val:>10.2f} 억원")
        print("\n" + "*" * 68)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    system = KiwoomTotalSystem()

    # 공정 시작
    system.comm_connect()  # 로그인
    system.sync_stock_list()  # 리스트 동기화
    system.run_full_collection()  # 전 종목 수집 및 중간 보고
    system.display_top_5_summary()  # 최종 결과 리포트

    print("\n[알림] 모든 작업이 성공적으로 종료되었습니다.")
    sys.exit(app.exec_())