#파이참
# 키움증권 로그인테스트

import sys
from PyQt5.QtWidgets import *
from PyQt5.QAxContainer import *
from PyQt5.QtCore import QEventLoop


class KiwoomLoginTest:
    def __init__(self):
        self.app = QApplication(sys.argv)

        # 1. 키움 Open API+ OCX 컨트롤 객체 생성
        self.kiwoom = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")

        # 2. 이벤트 루프 변수 생성 (로그인 완료까지 프로그램을 대기시키기 위함)
        self.login_event_loop = QEventLoop()

        # 3. 키움 로그인 이벤트 슬롯 연결
        self.kiwoom.OnEventConnect.connect(self._event_connect)

        # 4. 로그인 프로세스 시작
        self.start_login()

    def start_login(self):
        print("▶ 키움증권 서버에 연결을 시도합니다...")

        # CommConnect() 호출 시 자동로그인이 설정되어 있다면 창 없이 즉시 진행됩니다.
        res = self.kiwoom.dynamicCall("CommConnect()")

        if res == 0:
            print("▶ 로그인창 구동 성공 (자동로그인 대기 중...)")
            # 로그인이 완료될 때까지 코드 진행을 멈추고 대기
            self.login_event_loop.exec_()
        else:
            print(f"❌ 로그인창 구동 실패 (에러코드: {res})")

    def _event_connect(self, err_code):
        """
        키움 서버로부터 로그인 처리 결과를 받는 이벤트 함수
        err_code가 0이면 로그인 성공, 음수면 실패
        """
        print("-" * 40)
        if err_code == 0:
            print("🎉 [성공] 키움증권 자동로그인에 성공했습니다!")

            # 로그인 성공 후 사용자 정보 가져오기 테스트
            user_id = self.kiwoom.dynamicCall("GetLoginInfo(QString)", "USER_ID").strip()
            user_name = self.kiwoom.dynamicCall("GetLoginInfo(QString)", "USER_NAME").strip()
            account_list = self.kiwoom.dynamicCall("GetLoginInfo(QString)", "ACCNO").strip()
            # 계좌 목록은 ';'로 구분되어 들어옵니다.
            accounts = account_list.split(';')[:-1]

            print(f"👤 사용자 ID   : {user_id}")
            print(f"📛 사용자 이름 : {user_name}")
            print(f"💳 보유 계좌수 : {len(accounts)}개 (계좌번호: {', '.join(accounts)})")

        else:
            print(f"❌ [실패] 로그인에 실패했습니다. 에러코드: {err_code}")
            print("팁: 비밀번호 저장 설정이나 모의투자/실전 서버 선택을 다시 확인하세요.")
        print("-" * 40)

        # 로그인이 끝났으므로 대기 중이던 이벤트 루프를 종료하고 프로그램을 끝냅니다.
        self.login_event_loop.exit()


if __name__ == "__main__":
    # 테스트 프로그램 실행
    test = KiwoomLoginTest()