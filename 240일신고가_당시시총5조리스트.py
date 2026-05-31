from pykrx import stock
import time


def get_historical_market_cap(ticker, start_date, end_date):
    """
    ticker: 종목코드 (예: '005930')
    start_date, end_date: YYYYMMDD 형식의 문자열
    """
    print(f"[{ticker}] {start_date} ~ {end_date} 시가총액 데이터 조회 중...")

    # 해당 기간의 시가총액, 상장주식수, 거래량, 거래대금 데이터프레임 반환
    df = stock.get_market_cap_by_date(start_date, end_date, ticker)

    return df


# 사용 예시: 특정 종목의 2023년 1월 한 달간 실제 데이터 확인
ticker = "005930"  # 종목코드
start = "20230101"
end = "20230131"

df_cap = get_historical_market_cap(ticker, start, end)

# 결과 출력 (종가, 시가총액, 거래량, 거래대금, 상장주식수 포함)
print(df_cap.head())