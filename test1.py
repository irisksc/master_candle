import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop


class Kiwoom(QAxWidget):
    def __init__(self):
        super().__init__()
        self._create_kiwoom_instance()
        self._set_signal_slots()

        self.login_event_loop = QEventLoop()
        self.tr_event_loop = QEventLoop()
        self.target_trading_value_100m = 0.0

    def _create_kiwoom_instance(self):
        self.setControl("KHOPENAPI.KHOpenAPICtrl.1")

    def _set_signal_slots(self):
        self.OnEventConnect.connect(self._login_handler)
        self.OnReceiveTrData.connect(self._receive_tr_data)

    def comm_connect(self):
        self.dynamicCall("CommConnect()")
        self.login_event_loop.exec_()

    def _login_handler(self, err_code):
        if err_code == 0:
            print("키움증권 로그인 성공")
        else:
            print(f"로그인 실패 (에러코드: {err_code})")
        self.login_event_loop.exit()

    def get_daily_chart_data(self, item_code, target_date):
        # opt10081: 주식일봉차트조회요청
        # item_code에 '005930_AL' 입력 시 통합시세 요청
        self.dynamicCall("SetInputValue(QString, QString)", "종목코드", item_code)
        self.dynamicCall("SetInputValue(QString, QString)", "기준일자", target_date)
        self.dynamicCall("SetInputValue(QString, QString)", "수정주가구분", "1")  # 1: 수정주가 적용

        self.dynamicCall("CommRqData(QString, QString, int, QString)", "일봉조회_통합", "opt10081", 0, "0101")
        self.tr_event_loop.exec_()

    def _receive_tr_data(self, screen_no, rqname, trcode, recordname, prev_next, data_len, err_code, msg1, msg2):
        if rqname == "일봉조회_통합":
            # 데이터 개수 확인 (통상적으로 600일치 데이터 반환)
            count = self.dynamicCall("GetRepeatCnt(QString, QString)", trcode, recordname)

            for i in range(count):
                date = self.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, recordname, i,
                                        "일자").strip()

                # 목표 일자(20260513)를 찾으면 데이터 추출
                if date == "20260512":
                    amount_str = self.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, recordname, i,
                                                  "거래대금").strip()

                    if amount_str:
                        amount_millions = int(amount_str)
                        # opt10081의 거래대금 단위는 '백만 원' -> 100으로 나누어 '억 원' 환산
                        self.target_trading_value_100m = amount_millions / 100.0
                    break

            self.tr_event_loop.exit()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    kiwoom = Kiwoom()
    kiwoom.comm_connect()

    target_date = "20260513"
    # 삼성전자 종목코드 뒤에 '_AL'을 붙여 통합시세(KRX + NXT) 요청
    item_code_integrated = "005930_AL"

    print(f"\n데이터를 조회 중입니다... (종목코드: {item_code_integrated}, 기준일: {target_date})")
    kiwoom.get_daily_chart_data(item_code_integrated, target_date)

    print("\n========== [최종 조회 결과] ==========")
    print(f"기준일자: {target_date[:4]}년 {target_date[4:6]}월 {target_date[6:8]}일")
    if kiwoom.target_trading_value_100m > 0:
        print(f"삼성전자 통합(KRX+NXT) 거래대금: {kiwoom.target_trading_value_100m:,.2f} 억원")
    else:
        print("해당 일자의 거래 데이터가 없습니다. (휴장일이거나 상장 전일 수 있습니다.)")
    print("======================================")